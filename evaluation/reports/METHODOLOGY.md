# Benchmark methodology

Use the commands from the project root with the pinned backend environment:

```powershell
python -m evaluation.benchmark --repeat 3
python -m evaluation.scenarios
python -m evaluation.trigger_runs
python -m evaluation.plot_workflow
```

The benchmark uses a temporary SQLite runtime, the same local worker used by the app, and FastAPI TestClient. It submits deterministic chains of 5, 10, 25, 50, and 100 nodes. Persisted timestamps measure execution and checkpoint durations. Python tracemalloc measures allocation peak for the process while a chain is measured.

Burst runs submit 1, 5, 10, and 25 jobs before collecting results. The measured worker remains serial. Throughput includes client polling. Error counts include non-successful terminal executions.

Data-processing measurements exercise individual actions against fixed-seed data. Those runs deliberately bypass engine checkpoint serialization and therefore do not represent the supported graph payload size. Validation runs compare actual and expected validity. Offline text experiments check documented semantics, structured outputs, and rejection of unsupported input.

Scenario runs inject controlled failures and exercise persisted approvals, auth controls, restarts, and cancellation. See each raw result file for evidence.
