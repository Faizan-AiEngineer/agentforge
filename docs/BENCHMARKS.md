# Benchmarks

Run from the project root:

```powershell
python -m evaluation.benchmark --repeat 3 --output .runtime/benchmark-local
```

The script uses a fresh temporary SQLite database, one local worker, and a fixed random seed. Workflow latency covers persisted execution for graphs of 5, 10, 25, 50, and 100 nodes. Submission bursts of 1, 5, 10, and 25 measure queue wait, throughput, and latency under a single worker. Direct transform timings exercise 1,000, 10,000, and 100,000 seeded records outside the 1 MiB workflow checkpoint limit. The AI evaluation checks only supported deterministic tasks and rejection of unsupported input.

The output path keeps new measurements separate from the published raw data. Pair timings with the recorded environment. The test suite covers injected retries, restart, approvals, and security boundaries. [Measured report](../evaluation/reports/BENCHMARK_REPORT.md) · [Methodology](../evaluation/reports/METHODOLOGY.md)
