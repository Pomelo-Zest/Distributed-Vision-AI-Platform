# Benchmark

Suggested loop:

1. Generate a larger seed file with `python scripts/load-test/scale_cameras.py 32 > config/cameras.seed.json`.
2. Call `GET /seed` on the scheduler.
3. Observe queue depth, event rate, and latency in Prometheus/Grafana.
4. Write results into `docs/performance-report.md`.

