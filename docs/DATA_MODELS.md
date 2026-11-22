# Data models

| Table | Responsibility |
| --- | --- |
| workflow | Editable name, description, graph and optimistic revision |
| workflow_version | Immutable validated graph snapshots keyed by workflow and revision |
| execution | Queue, pinned version, event source, attempt state, deadline and idempotency key |
| node_execution | Inputs, output, port, timing, retry information and current status per node |
| schedule | Interval, cron, one-time, or file watch definition with last and next timestamps |
| webhook | Registered local endpoints and credential references |
| credential_reference | Environment variable name and credential kind |
| approval | One durable decision per execution and approval node |
| artifact | Download metadata, byte size, MIME type and SHA-256 |
| audit_event | Local mutation history and timestamps |

Graph nodes and edges live in versioned JSON, with Pydantic validation and registry contracts. Execution and artifact storage paths use server-controlled IDs. Timestamps in REST responses are UTC Unix seconds.
