param(
    [int]$Users = 1000,
    [int]$DurationSeconds = 60
)

$ErrorActionPreference = "Stop"
docker compose up --build -d
try {
    docker compose exec -T api python scripts/seed_synthetic_features.py
    $prefix = "loadtest/results"
    $runSeconds = $DurationSeconds + 10
    locust -f loadtest/locustfile.py --host http://localhost:8000 --headless --users $Users --spawn-rate 100 --run-time "$runSeconds`s" --reset-stats --csv $prefix
    python scripts/verify_benchmark.py "$prefix`_stats.csv" --duration-seconds $DurationSeconds
}
finally {
    docker compose down
}
