#!/usr/bin/env python3
"""Analytical KV-size/unit checks; not a network or serving simulator."""
import argparse
import json
import math
from pathlib import Path


def kv_bytes(input_tokens):
    if input_tokens < 0:
        raise ValueError("Negative input length")
    return 2 * 40 * 5120 * 2 * input_tokens


def transfer_ms(byte_count, bandwidth_gbps, latency_ms=0):
    if byte_count < 0 or bandwidth_gbps <= 0 or latency_ms < 0:
        raise ValueError("Invalid network parameters")
    return latency_ms + 1000 * byte_count / (bandwidth_gbps * 10**9 / 8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    volume = kv_bytes(512)
    assert volume == 419430400
    assert kv_bytes(0) == 0
    assert transfer_ms(0, 10) == 0
    assert math.isclose(transfer_ms(10**9, 8), 1000)
    assert math.isclose(transfer_ms(2 * volume, 10), 2 * transfer_ms(volume, 10))
    assert math.isclose(transfer_ms(volume, 20), transfer_ms(volume, 10) / 2)
    assert math.isclose(transfer_ms(volume, 10, 1) - transfer_ms(volume, 10), 1)
    report = {"status": "PASS", "model": "OPT-13B", "input_tokens": 512,
              "layers": 40, "hidden_size": 5120, "bytes_per_element": 2,
              "kv_bytes": volume, "kv_MiB": volume / 2**20,
              "architecture_source": "https://huggingface.co/facebook/opt-13b/blob/main/config.json",
              "assumption": "K and V for input context, TP=1, FP16, no compression, no first output token",
              "transfer_ms_zero_latency": {str(b): transfer_ms(volume, b) for b in (1, 10, 25, 100)},
              "checks": ["zero payload", "GB/Gbit/second to millisecond conversion", "double size",
                         "double bandwidth", "add fixed latency"],
              "scope": "Arithmetic feasibility only; a contended network event model remains future work."}
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")


if __name__ == "__main__":
    main()
