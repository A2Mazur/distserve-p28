#!/usr/bin/env python3
"""Recompute exported metrics from raw events; check all evidence hashes.

Standard library only. Does not run or import the reference simulator.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def close(actual, expected, description):
    require(math.isclose(float(actual), expected, rel_tol=1e-10, abs_tol=1e-8),
            f"{description}: {actual} != {expected}")


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def verify(directory):
    manifest = json.loads((directory / "SHA256SUMS.json").read_text())
    for name, checksum in manifest.items():
        require(Path(name).name == name, "Unexpected evidence path")
        require(hashlib.sha256((directory / name).read_bytes()).hexdigest() == checksum,
                f"Evidence checksum mismatch: {name}")
    config = json.loads((directory / "config.json").read_text())
    report = json.loads((directory / "checks.json").read_text())
    summary = read_csv(directory / "summary.csv")
    require(report["status"] == "PASS", "Run did not pass")
    require(len(summary) == len(config["cases"]) * 2 * len(config["seeds"]), "Missing runs")
    require(len({row["run"] for row in summary}) == len(summary), "Duplicate run")
    completions = 0
    for row in summary:
        run = row["run"]
        case = next(case for case in config["cases"] if case["name"] == row["case"])
        expected = {str(r["id"]): r for r in case["requests"]}
        events = read_csv(directory / f"{run}.events.csv")
        metrics = read_csv(directory / f"{run}.requests.csv")
        require(len(metrics) == len(expected), f"{run}: Missing request")
        require({r["request_id"] for r in metrics} == set(expected), f"{run}: Changed request IDs")
        require({e["request_id"] for e in events} == set(expected), f"{run}: Unknown event ID")
        ok_count = 0
        for metric in metrics:
            req_id = metric["request_id"]
            spec = expected[req_id]
            trace = [event for event in events if event["request_id"] == req_id]
            times = [float(event["time_ms"]) for event in trace]
            require(all(math.isfinite(t) for t in times) and times == sorted(times), "Invalid event time")
            get = lambda name: [float(e["time_ms"]) for e in trace if e["event"] == name]
            arrivals, ends, prefills, decodes = get("init"), get("exit_system"), get("do_prefill"), get("do_decode")
            require(len(arrivals) == len(ends) == len(prefills) == 1, "Lost or duplicate lifecycle")
            require(len(decodes) == spec["decode_steps"], "Wrong decode count")
            first = get("wait_decode")[0]
            ttft, decode = first - arrivals[0], ends[0] - first
            close(metric["arrival_ms"], spec["arrival_ms"], "arrival")
            close(metric["first_token_ms"], first, "first token")
            close(metric["finish_ms"], ends[0], "finish")
            close(metric["prefill_wait_ms"], prefills[0] - arrivals[0], "queue wait")
            close(metric["ttft_ms"], ttft, "TTFT")
            close(metric["decode_ms"], decode, "decode time")
            close(metric["tpot_ms"], decode / spec["decode_steps"], "TPOT")
            close(metric["total_ms"], ends[0] - arrivals[0], "total latency")
            require(int(metric["logical_output_tokens"]) == spec["decode_steps"] + 1, "Wrong token convention")
            token_ends = [float(trace[i + 1]["time_ms"]) for i, event in enumerate(trace)
                          if event["event"] == "do_decode"]
            intervals = [b - a for a, b in zip([first] + token_ends[:-1], token_ends)]
            close(metric["max_inter_token_ms"], max(intervals), "maximum token interval")
            slo_ok = ttft <= config["ttft_slo_ms"] and decode / spec["decode_steps"] <= config["tpot_slo_ms"]
            require(metric["slo_ok"] == str(slo_ok), "SLO flag inconsistent")
            ok_count += slo_ok
        window = (max(float(m["finish_ms"]) for m in metrics) -
                  min(float(m["arrival_ms"]) for m in metrics)) / 1000
        close(row["measurement_window_s"], window, "measurement window")
        close(row["throughput_rps"], len(metrics) / window, "throughput")
        close(row["goodput_rps"], ok_count / window, "goodput")
        close(row["goodput_per_worker_rps"], ok_count / window / config["total_workers"], "normalized goodput")
        close(row["mean_ttft_ms"], sum(float(m["ttft_ms"]) for m in metrics) / len(metrics), "mean TTFT")
        close(row["mean_tpot_ms"], sum(float(m["tpot_ms"]) for m in metrics) / len(metrics), "mean TPOT")
        require(int(row["slo_ok"]) == ok_count, "Wrong SLO count")
        require(int(row["completed"]) == int(row["requests"]) == len(metrics), "Wrong completion count")
        completions += len(metrics)
    analytic = read_csv(directory / "analytical-checks.csv")
    require(len(analytic) == report["analytical_checks"], "Missing analytical checks")
    for row in analytic:
        close(row["actual_ms"], float(row["expected_ms"]), "analytical agreement")
        require(float(row["abs_error_ms"]) <= 1e-8, "Analytical tolerance exceeded")
    require(report["runs"] == len(summary) and report["request_completions"] == completions,
            "Inconsistent run report")
    print(f"PASS: {len(manifest)} file checksums; {len(summary)} runs; "
          f"{completions} request metrics recomputed from events; {len(analytic)} analytical checks.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    verify(parser.parse_args().directory)
