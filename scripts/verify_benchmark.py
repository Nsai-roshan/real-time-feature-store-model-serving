"""Fail CI when a Locust CSV result does not meet the stated serving SLO."""

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BenchmarkDecision:
    passed: bool
    request_count: int
    failure_count: int
    achieved_rps: float
    p99_ms: float
    reason: str


def evaluate(rows, duration_seconds: int, target_rps: int, max_p99_ms: float) -> BenchmarkDecision:
    aggregate = next((row for row in rows if row.get("Name") == "Aggregated"), None)
    if not aggregate:
        return BenchmarkDecision(False, 0, 0, 0.0, 0.0, "Locust aggregate row not found")
    request_count = int(aggregate["Request Count"])
    failure_count = int(aggregate.get("Failure Count", 0))
    p99 = float(aggregate["99%"])
    achieved_rps = request_count / duration_seconds
    required = target_rps * duration_seconds
    failures = []
    if request_count < required:
        failures.append(f"requests={request_count} < {required}")
    if failure_count:
        failures.append(f"failures={failure_count} > 0")
    if p99 > max_p99_ms:
        failures.append(f"p99={p99}ms > {max_p99_ms}ms")
    return BenchmarkDecision(
        not failures,
        request_count,
        failure_count,
        achieved_rps,
        p99,
        "; ".join(failures) if failures else "all acceptance criteria met",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path, help="Locust *_stats.csv file")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--target-rps", type=int, default=1000)
    parser.add_argument("--max-p99-ms", type=float, default=50.0)
    args = parser.parse_args()
    with args.csv.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    decision = evaluate(rows, args.duration_seconds, args.target_rps, args.max_p99_ms)
    print("PERF_METRICS_START")
    print(
        json.dumps(
            {
                "scenarios": {
                    "score_1k_rps": {
                        "requests": decision.request_count,
                        "failures": decision.failure_count,
                        "achieved_rps": round(decision.achieved_rps, 2),
                        "p99_ms": decision.p99_ms,
                    }
                }
            }
        )
    )
    print("PERF_METRICS_END")
    print(f"{'PASS' if decision.passed else 'FAIL'}: {decision.reason}")
    return 0 if decision.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
