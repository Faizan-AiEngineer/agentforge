# Portfolio materials

## Project summary

AgentForge is a local visual workflow studio for data processing, reporting, and human review. A React Flow editor produces versioned DAGs that FastAPI runs through a persistent SQLite worker. The studio exposes node checkpoints, signed triggers, approval decisions, and generated files.

## CV bullets

- Built a React Flow and TypeScript builder for composing, validating, and executing configurable DAGs with typed node settings and branch ports.
- Implemented a FastAPI and SQLite orchestration engine with pinned revisions, persisted checkpoints, scheduling, signed webhooks, bounded retries, and human approval routing.
- Added automated security and recovery tests and measured single-worker execution across 15 successful chain trials. The latest comparison averaged 737 ms at five nodes and 10.75 s at 100 nodes on the documented Windows host.

## LinkedIn project description

AgentForge is a visual workflow studio for composing, executing, and monitoring recurring business and data-processing tasks. It combines a React Flow editor with a FastAPI DAG engine, SQLite checkpoints, scheduled and signed webhook triggers, and approval routing. Example workflows clean spreadsheet data, route purchasing requests, and produce downloadable reports.

## LinkedIn announcement draft

I built AgentForge to make recurring spreadsheet cleanup, reporting, and review work easier to repeat and inspect. Each workflow runs against a saved revision. You can see which nodes ran, which branch was selected, and what each run produced.

The editor uses React Flow and TypeScript. FastAPI validates the graph and a background worker persists its progress in SQLite. One design challenge was deciding what to redo after an interruption. Checkpoints let a run resume after a review or restart, while an external write with an uncertain outcome requires inspection before another attempt.

The repository includes a purchase approval workflow, generated reports, backend tests for retries and recovery, and raw benchmark data. On the latest measured Windows run, the five-node chain averaged 737 ms and the 100-node chain averaged 10.75 s across three successful trials per size.

[GitHub repository](https://github.com/Faizan-AiEngineer/agentforge)

## Two-minute project explanation

Open CSV Cleaning. Explain how a recurring manual cleanup becomes a reusable graph with a trigger, validation rules, and separate output branches. Run the workflow, inspect a node checkpoint, and open the generated CSV. Switch to Purchase Approval and show how the workflow returns to the execution queue after the reviewer decides.

## Five-minute architecture walkthrough

1. Show the graph contract, input bindings, node configuration schemas, and port validation.
2. Explain why queueing pins an immutable revision. Follow the execution record to a persisted checkpoint.
3. Trace a conditional branch and review the retry policy for transient failures and external writes.
4. Trigger a run from a signed webhook or interval schedule. Pause at an approval and resume through the selected port.
5. Show the artifact and monitoring page. Explain the single-operator trust model and the tests and benchmarks that apply to the local worker.

## Interview questions

| Question | Answer |
| --- | --- |
| Why use a DAG? | Acyclic dependencies give a finite execution order. The validator uses a topological traversal to reject cycles. |
| How do settings and ports get validated? | The node registry supplies typed configuration models and port definitions. Graph validation checks configuration, endpoints, and port compatibility. |
| What happens when you edit a workflow during a run? | The run holds its saved revision ID, so it continues with the same graph. |
| How does conditional routing work? | The engine records the emitted port. Edges from that port activate and inactive paths produce skipped checkpoints. |
| What survives a restart? | Run state, node checkpoints, schedules, and pending decisions are persisted. The recovery code uses those records to resume eligible work. |
| How does a human decision resume work? | A valid decision is recorded atomically and requeues the suspended run. A second decision conflicts with the recorded state. |
| Can an external write run twice? | A timeout may leave the write's outcome unknown. Recovery avoids replaying uncertain writes automatically. |
| How are webhook events authenticated? | An HMAC covers the timestamp and raw body. A signed event ID and a bounded timestamp window constrain replays. |
| How are outbound requests and secrets handled? | Exact HTTPS hosts are allowlisted, DNS addresses are checked and pinned, and credential values stay in the backend environment. |
| What do the benchmarks tell you? | They measure elapsed local fixture execution with persisted checkpoints and one worker. They include allocation tracing and three trials per size. |