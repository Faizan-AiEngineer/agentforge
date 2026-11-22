# AgentForge local benchmark report

Windows 11 26100, Intel processor family 6 model 142, four logical processors, Python 3.13.2. Three trials per timing case. See [environment](../results/environment.json) for library versions.

## Workflow size

| Nodes | Mean execution duration | Successes |
| ---: | ---: | ---: |
| 5 | 263.14 ms | 3/3 |
| 10 | 420.30 ms | 3/3 |
| 25 | 1,204.05 ms | 3/3 |
| 50 | 2,788.82 ms | 3/3 |
| 100 | 7,425.92 ms | 3/3 |

The [raw workflow results](../results/workflow_performance.csv) include memory allocation peaks and node timing. Tracing allocations and the SQLite filesystem affect these measurements.

[Workflow duration figure](figures/workflow-duration.pdf)

## Submission bursts

| Submitted | Mean successful completions per second | Mean queue wait | Errors |
| ---: | ---: | ---: | ---: |
| 1 | 4.40 | 110.17 ms | 0 |
| 5 | 8.06 | 342.12 ms | 0 |
| 10 | 9.07 | 567.30 ms | 0 |
| 25 | 9.87 | 1,210.57 ms | 0 |

These are bursts of work for one local worker. [Raw burst results](../results/concurrency_results.csv)

## Correctness

- Retry succeeded on the third attempt with one artifact and reused the original run for a duplicate submission. Cancellation, failure propagation, and checkpoint restart passed. [Reliability data](../results/reliability_results.json)
- Approve, reject, and request changes each resumed the run after restarting the app. Duplicate decisions returned 409. Observed decision-to-completion times were 303, 280, and 272 ms. [Approval data](../results/approval_results.json)
- Graph validity matched expectations for seven cases. Four offline tasks matched their expected outputs and one unsupported task was rejected. [Graph data](../results/validation_results.json) · [Offline processing data](../results/ai_evaluation.json)
- Nine security observations passed, including private addresses, path constraints, oversized bodies, invalid signatures and secret redaction. [Security data](../results/security_results.json)
- One-time scheduling and approved file detection both generated successful runs. Disabling the file watch persisted. [Trigger data](../results/trigger_results.json)
- At 100,000 records, the mean per-action times were 600 ms for filtering, 1,286 ms for deduplication, 1,122 ms for aggregation and 608 ms for CSV export. All 36 direct data-action trials succeeded. [Record processing data](../results/data_processing_results.csv)

## Completion comparison

The original measurements above remain unchanged. The completion capture used the same Windows 11 host class, Python 3.13.2, fixture seed, test client, instrumentation, and three trials per size. It used the Winloop event loop and ran while other verification work was active. It measured the updated runner before installing the final FastAPI and Starlette pins. The baseline and completion capture are useful comparisons under those conditions, with several environment differences still uncontrolled. [Completion environment](../final-results/environment.json)

| Nodes | Baseline mean (ms) | Completion mean (ms) | Median (ms) | Minimum (ms) | Maximum (ms) | Samples |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 5 | 263.14 | 736.80 | 757.71 | 686.57 | 766.13 | 3 |
| 10 | 420.30 | 1,207.58 | 1,181.79 | 1,102.95 | 1,338.00 | 3 |
| 25 | 1,204.05 | 4,406.93 | 5,497.96 | 1,850.88 | 5,871.96 | 3 |
| 50 | 2,788.82 | 7,302.84 | 7,701.49 | 4,488.97 | 9,718.07 | 3 |
| 100 | 7,425.92 | 10,748.93 | 11,404.86 | 9,370.52 | 11,471.42 | 3 |

The measured five-node mean rose about 180%, and the 100-node mean rose about 45%. Active verification tasks, Winloop, SQLite I/O variation, and the added state checks all differ across runs. The experiment cannot isolate their individual costs. At 25 queued jobs, mean throughput fell from 9.87 to 5.93 successful runs per second and measured errors remained zero. This exercises a single local worker with several jobs queued.

The measured retry case took 1,297 ms and completed on the third attempt. Restart recovery took 2,965 ms including process setup and the resumed delay. The three approval decisions took 308.60 to 401.45 ms from decision to completion, with a 358.22 ms mean and 364.62 ms median.

Reproduce into a fresh output path. [Raw workflow trials](../final-results/workflow_performance.csv) · [Burst and data statistics](../final-results/summary.json) · [Retry, restart, and approval statistics](../final-results/scenario_summary.json)

```powershell
python -m evaluation.benchmark --winloop --repeat 3 --scenarios --output .runtime/benchmark-comparison
```

Distributed throughput and scaling remain unmeasured.
