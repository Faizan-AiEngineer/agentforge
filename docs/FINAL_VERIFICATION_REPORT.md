# Release verification

AgentForge uses a single-operator local deployment model. The verification below covers the bundled workflows, local execution and persistence, and the documented network and filesystem boundaries.

## Coverage

| Area | Classification | Evidence |
| --- | --- | --- |
| SQLite, migrations, and execution | Verified | Fresh SQLite setup and historical upgrade from Alembic revision 0001 to 0002 retained all 12 workflows. Tests cover graph and input validation, pinned revisions, retries, cancellation, and checkpoint recovery. |
| Builder and workflow details | Verified | Chrome created, configured, connected, saved, reopened, executed, and duplicated a workflow, and imported the purchase approval template. |
| Scheduled and signed triggers | Verified | Tests cover persisted scheduling, signed events, rejected signatures, and event deduplication. The browser journey inspected resulting runs. |
| Approvals and artifacts | Verified | Tests exercise unauthorized and duplicate decisions, approval recovery, branch selection, download paths, artifact checksums, and missing files. |
| Offline AI | Verified | Deterministic tasks and downstream handling of their outputs were exercised. |
| Ollama and OpenAI-compatible APIs | Partially verified | Controlled responses exercise authentication, deadlines, and output validation. Live model inference was unavailable for verification. |
| Playwright browser nodes | Partially verified | Bundled HTML exercised table extraction, pagination, structured export, selectors, and PNG capture. An earlier live static HTTPS check failed local certificate trust validation. |
| PostgreSQL, Redis, and Celery | Partially verified | PostgreSQL migration SQL, simulated ownership and duplicate delivery, and Celery's memory transport were exercised. No live cluster verification. |
| Docker runtime | Implemented but unverified | Compose files are included. A Docker host is needed for builds and service startup. |
| Shared authorization | Not implemented | The API assumes a trusted local operator. A reviewer key can protect decision requests within that boundary. |

## Release checks

The release rerun collected and passed **63 backend tests** in 140.85 seconds of Pytest time on Windows with Winloop and installed Chrome. There were zero failures, skips, or blocked tests. The first attempt passed 62 tests and timed out inside the browser extraction fixture. The full rerun passed with the original node deadlines and test assertions.

A fresh Python 3.13 environment installed both requirements files and passed pip's dependency consistency check. Alembic reached revision 0002, and SQLite reported integrity OK. The frontend installed from its lock file and passed three Vitest tests, TypeScript checking, and the Vite production build. Ruff passed.

The production build ran against a fresh local FastAPI process on loopback. Chrome checked all 12 navigation pages, node insertion and removal, graph connections, validation, saving and reopening, duplication, template import, approval and rejection, trigger execution, monitoring and mobile navigation. The browser downloaded results.csv and the check read the expected bytes from the saved file. All nine demo workflows succeeded, with a separate run left waiting for approval. [Release check results](../evaluation/release-verification.json)

The release audit checked 54 resolved Python packages including transitive dependencies, with zero known findings and zero skipped packages. The npm production audit also reported zero known findings. The secret-pattern scan, sample-output review, and screenshot review found no credentials. The companion security tests cover approved destinations and redirects, input boundaries, webhook signatures and replays, approval authorization, and artifact integrity. Keep the application bound to loopback in local use.

## Historical evidence

The baseline verified 31 targeted backend tests, three frontend tests, and the Chrome workflow journey. The subsequent completion run collected and passed 63 backend tests in 141.46 seconds on Windows using Pytest 9.0.3 and Winloop 0.8.4, with zero failures or skips. All nine demos succeeded, and a separate run paused for approval. Chrome verified the expected CSV bytes over the in-process application. Its native save was canceled in that run. [Baseline browser evidence](../evaluation/results/browser_results.json) · [Completion tests](../evaluation/completion-verification/backend.json) · [Demo results](../evaluation/completion-verification/demos.json) · [Completion Chrome results](../evaluation/completion-verification/browser.json)

The previous dependency review identified Pytest and Starlette advisories and updated the affected pins. The follow-up reported zero known advisories in the direct Python pins and npm production dependencies. [Follow-up audit](../evaluation/completion-verification/dependency-audit.json)

## Benchmark verification

Recalculating the two sets of raw workflow trials confirmed all 15 chains succeeded in each capture. The latest measured means were 736.80 ms for five nodes and 10,748.93 ms for 100 nodes. The original means were 263.14 ms and 7,425.92 ms. The latest 25-job burst averaged 5.93 successful executions per second. Both captures used one local worker. The later run used Winloop with concurrent verification work and predated the final framework pins. [Raw trials, environment, and methodology](../evaluation/reports/BENCHMARK_REPORT.md)

## Reproduce

Run the installation and migration from the [quick start](QUICKSTART.md), then follow its verification commands for Pytest, Ruff, TypeScript, Vitest, the production build, and the Chrome journey. See the [security model](SECURITY.md) for the controls under test and the requirements for any shared deployment.