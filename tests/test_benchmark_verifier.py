from scripts.verify_benchmark import evaluate


def test_acceptance_gate_requires_volume_latency_and_zero_failures():
    passing = [{"Name": "Aggregated", "Request Count": "60000", "Failure Count": "0", "99%": "49"}]
    failing = [{"Name": "Aggregated", "Request Count": "60000", "Failure Count": "1", "99%": "49"}]

    assert evaluate(passing, duration_seconds=60, target_rps=1000, max_p99_ms=50).passed
    assert not evaluate(failing, duration_seconds=60, target_rps=1000, max_p99_ms=50).passed
