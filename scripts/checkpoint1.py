#!/usr/bin/env python3
"""Run the unmodified reference, export evidence and verify analytical cases.

This is an adapter and checker, NOT the independent P28 simulator.
All times are simulated milliseconds; no GPU or model weights are loaded.
"""
import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import random
import resource
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "third_party" / "distserve"
sys.path.insert(0, str(REFERENCE))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def verify_sources():
    manifest = json.loads((REFERENCE / "UPSTREAM.json").read_text())
    for name, expected in manifest["sha256"].items():
        actual = hashlib.sha256((REFERENCE / name).read_bytes()).hexdigest()
        require(actual == expected, f"Reference file changed: {name}")
    return manifest


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_csv(path, rows):
    require(bool(rows), f"No rows for {path}")
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def analytic_single(spec, profile):
    """Direct scalar evaluation of the published coefficients, no event engine.

    PP=TP=1, no queue, one request in every batch. Upstream adds 1 ms
    to prefill and a Ray term (2 + 0.0001 * current context) to each step.
    output_lens in the reference counts decode steps after prefill.
    """
    length, steps = spec["input_tokens"], spec["decode_steps"]
    a, b, c = profile["prefill"]
    prefill = a + b * length + c * length**2 + 1 + 2 + 0.0001 * length
    key = "decoding_smallbs" if 1 < profile["decoding_large_small_bs_threshold"] else "decoding_largebs"
    a, b, c = profile[key]
    decode = sum(a + b * (length + k + 1) + c + 2 + 0.0001 * (length + k)
                 for k in range(steps))
    return {"ttft_ms": prefill, "decode_ms": decode,
            "tpot_ms": decode / steps, "total_ms": prefill + decode}


def request_metrics(request, spec, config):
    events = request.log
    times = [row[0] for row in events]
    require(all(math.isfinite(t) for t in times), "Nonfinite event time")
    require(times == sorted(times), "Nonmonotone request trace")
    event_times = lambda name: [t for t, event, _ in events if event == name]
    arrivals, exits = event_times("init"), event_times("exit_system")
    prefills, decodes = event_times("do_prefill"), event_times("do_decode")
    first_tokens = event_times("wait_decode")
    steps = spec["decode_steps"]
    require(len(arrivals) == len(exits) == len(prefills) == 1, "Request lost, duplicated or chunked")
    require(len(decodes) == steps and request.counter == steps, "Decode step conservation failed")
    require(request.should_finish() and request.remain_prefill_lens == 0, "Request not complete")
    require(math.isclose(arrivals[0], spec["arrival_ms"], abs_tol=1e-9), "Arrival changed")
    first, finish, arrival = first_tokens[0], exits[0], arrivals[0]
    ttft, decode_ms = first - arrival, finish - first
    # After each do_decode the next wait_decode marks the token completion.
    token_ends = []
    for index, (_, event, _) in enumerate(events):
        if event == "do_decode":
            require(index + 1 < len(events) and events[index + 1][1] == "wait_decode",
                    "Unexpected upstream decode log semantics")
            token_ends.append(events[index + 1][0])
    intervals = [right - left for left, right in zip([first] + token_ends[:-1], token_ends)]
    require(math.isclose(sum(intervals), decode_ms, abs_tol=1e-8), "Token latency decomposition failed")
    total, tpot = finish - arrival, decode_ms / steps
    require(ttft >= 0 and tpot > 0 and math.isclose(total, ttft + decode_ms, abs_tol=1e-8),
            "Latency decomposition failed")
    return {"request_id": spec["id"], "arrival_ms": arrival,
            "input_tokens": spec["input_tokens"], "decode_steps": steps,
            "logical_output_tokens": steps + 1, "first_token_ms": first, "finish_ms": finish,
            "prefill_wait_ms": prefills[0] - arrival, "ttft_ms": ttft,
            "decode_ms": decode_ms, "tpot_ms": tpot, "max_inter_token_ms": max(intervals),
            "total_ms": total,
            "slo_ok": ttft <= config["ttft_slo_ms"] and tpot <= config["tpot_slo_ms"]}


def run_case(case, backend, seed, config, output):
    import simpy
    from simdistserve.base.request import Request
    from simdistserve.base.scheduler import put_request_at_time
    from simdistserve.clusters.disagg import DisaggCluster
    from simdistserve.clusters.vllm import VLLMCluster
    from simdistserve.constants import ModelTypes

    random.seed(seed)
    env = simpy.Environment()
    worker_config = dict(model_type=ModelTypes.model_str_to_object(config["model"]),
                         TP_Prefill=1, TP_Decode=1, engine_type=config["profile_engine"],
                         prefill_max_batch_size=config["prefill_max_batch_size"],
                         prefill_max_tokens=config["prefill_max_tokens"],
                         decode_max_tokens=config["decode_max_tokens"],
                         decode_max_batch_size=10**7, enable_chunked_prefill=False)
    cluster = (DisaggCluster(env, N_prefill_instance=1, N_decode_instance=1,
                             PP_prefill=1, PP_decode=1, worker_configs=worker_config)
               if backend == "disaggregated" else
               VLLMCluster(env, N_instance=2, PP=1, worker_configs=worker_config))
    require(len(cluster.get_all_workers()) == config["total_workers"], "Unequal resource budget")
    requests = []
    for spec in case["requests"]:
        request = Request(env=env, req_id=spec["id"], prefill_length=spec["input_tokens"],
                          output_lens=spec["decode_steps"])
        requests.append(request)
        env.process(put_request_at_time(env, cluster.scheduler, spec["arrival_ms"], request))
    cluster.run()
    env.run()
    require(len({r.req_id for r in requests}) == len(requests), "Duplicate request ID")
    require(all(not w.prefill_queue and not w.decode_queue for w in cluster.get_all_workers()),
            "Undrained queue")
    metrics = [request_metrics(r, spec, config) for r, spec in zip(requests, case["requests"])]
    run_name = f"{case['name']}-{backend}-seed{seed}"
    request_events = [{"request_id": r.req_id, "time_ms": t, "event": event, "worker_id": worker}
                      for r in requests for t, event, worker in r.log]
    worker_events = [{"worker_id": w.wid, "time_ms": row[0], "event": row[1],
                      "num_tokens": row[2], "prefill_batch_size": row[3], "decode_batch_size": row[4],
                      "prefill_lengths": json.dumps(row[5]), "decode_lengths": json.dumps(row[6])}
                     for w in cluster.get_all_workers() for row in w.log]
    write_csv(output / f"{run_name}.requests.csv", metrics)
    write_csv(output / f"{run_name}.events.csv", request_events)
    write_csv(output / f"{run_name}.workers.csv", worker_events)
    checks = []
    if case["analytical"]:
        profiles = json.loads((REFERENCE / "simdistserve/estimators/profile_data/profiler-a100-80g.distserve.json").read_text())
        for metric, spec in zip(metrics, case["requests"]):
            expected = analytic_single(spec, profiles[config["model"]]["1"])
            require(abs(metric["prefill_wait_ms"]) < 1e-9, "Analytical case must have no queue")
            for name, value in expected.items():
                error = abs(metric[name] - value)
                require(error <= 1e-8, f"{run_name}: {name} disagrees with analytical result: {error}")
                checks.append({"run": run_name, "request_id": spec["id"], "metric": name,
                               "expected_ms": value, "actual_ms": metric[name], "abs_error_ms": error})
    first_arrival = min(m["arrival_ms"] for m in metrics)
    last_finish = max(m["finish_ms"] for m in metrics)
    elapsed_s = (last_finish - first_arrival) / 1000
    successes = sum(m["slo_ok"] for m in metrics)
    return {"run": run_name, "case": case["name"], "backend": backend, "seed": seed,
            "requests": len(requests), "completed": len(metrics), "slo_ok": successes,
            "measurement_window_s": elapsed_s,
            "throughput_rps": len(metrics) / elapsed_s, "goodput_rps": successes / elapsed_s,
            "goodput_per_worker_rps": successes / elapsed_s / config["total_workers"],
            "mean_ttft_ms": sum(m["ttft_ms"] for m in metrics) / len(metrics),
            "mean_tpot_ms": sum(m["tpot_ms"] for m in metrics) / len(metrics)}, checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/checkpoint-1.json")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/local/checkpoint-1")
    args = parser.parse_args()
    start = time.perf_counter()
    manifest = verify_sources()
    config = json.loads(args.config.read_text())
    require(config["tensor_parallelism"] == config["pipeline_parallelism"] == 1,
            "Checkpoint adapter supports TP=PP=1")
    require(config["profile_engine"] == "distserve", "Analytical oracle uses distserve profile")
    args.output.mkdir(parents=True, exist_ok=True)
    write_json(args.output / "config.json", config)
    rows, all_checks = [], []
    for case in config["cases"]:
        for backend in ("colocated", "disaggregated"):
            for seed in config["seeds"]:
                row, checks = run_case(case, backend, seed, config, args.output)
                rows.append(row)
                all_checks.extend(checks)
    # Seeds alter upstream chunk identifiers, not timing for these fixed inputs.
    for case in config["cases"]:
        for backend in ("colocated", "disaggregated"):
            repetitions = [r for r in rows if r["case"] == case["name"] and r["backend"] == backend]
            for name in ("mean_ttft_ms", "mean_tpot_ms", "goodput_rps"):
                require(len({r[name] for r in repetitions}) == 1, "Deterministic timing changed across seeds")
    write_csv(args.output / "summary.csv", rows)
    write_csv(args.output / "analytical-checks.csv", all_checks)
    environment = {"python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
                   "packages": {name: importlib.metadata.version(name) for name in
                                ("simpy", "numpy", "pandas", "python-dateutil", "pytz", "tzdata")},
                   "upstream_commit": manifest["commit"],
                   "command": "python scripts/checkpoint1.py --config configs/checkpoint-1.json --output OUTPUT",
                   "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   "requirements_sha256": hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest(),
                   "wall_time_s": time.perf_counter() - start,
                   "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss *
                                     (1 if sys.platform == "darwin" else 1024)}
    try:
        environment["host_memory_bytes"] = int(subprocess.check_output(
            ["sysctl", "-n", "hw.memsize"], stderr=subprocess.DEVNULL, text=True))
    except (OSError, ValueError, subprocess.CalledProcessError):
        environment["host_memory_bytes"] = None
        try:
            import os
            environment["host_memory_bytes"] = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
        except (ValueError, OSError):
            pass
    write_json(args.output / "environment.json", environment)
    report = {"status": "PASS", "reference_files_verified": len(manifest["sha256"]),
              "runs": len(rows), "request_completions": sum(row["completed"] for row in rows),
              "analytical_checks": len(all_checks),
              "max_analytical_error_ms": max(row["abs_error_ms"] for row in all_checks),
              "checks": ["upstream SHA-256", "equal worker budget", "request and decode-step conservation",
                         "event chronology", "queue drain", "latency and token-interval decomposition",
                         "closed-form no-queue reference", "deterministic repeatability"],
              "scope": "Reference feasibility and metrics only; no independent simulator or final experiment."}
    write_json(args.output / "checks.json", report)
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.output.iterdir())
              if p.is_file() and p.name != "SHA256SUMS.json"}
    write_json(args.output / "SHA256SUMS.json", hashes)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
