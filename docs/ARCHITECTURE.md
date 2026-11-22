# Architecture

AgentForge is a single-user automation workspace. The local React client talks to a loopback FastAPI API. SQLAlchemy stores workflow drafts, immutable runnable versions, executions and checkpoints. One local worker consumes the durable queue and releases its slot during approvals. A separate artifact root contains generated files.

```mermaid
flowchart LR
  UI[React Flow workspace] --> API[FastAPI]
  API --> DB[(SQLite)]
  API --> Worker[Local worker]
  Scheduler[Scheduler] --> DB
  Worker --> DB
  Worker --> Registry[Typed node registry]
  Registry --> Artifacts[Local artifacts]
```

```mermaid
stateDiagram-v2
  [*] --> QUEUED
  QUEUED --> RUNNING
  RUNNING --> WAITING_APPROVAL
  WAITING_APPROVAL --> QUEUED: decision
  RUNNING --> QUEUED: restart recovery
  RUNNING --> SUCCEEDED
  RUNNING --> FAILED
  RUNNING --> TIMED_OUT
  RUNNING --> CANCELLED
  QUEUED --> CANCELLED
  WAITING_APPROVAL --> CANCELLED
```

```mermaid
flowchart TD
  A[Resolve inputs] --> B[Persist start]
  B --> C[Execute with timeout]
  C -->|transient error| D[Bounded backoff]
  D --> C
  C -->|success| E[Persist output and active port]
  C -->|terminal error| F[Persist failure]
```

```mermaid
flowchart LR
  A[Condition] -->|true| B[True branch]
  A -. inactive .-> C[False branch]
  B --> D[Merge active inputs]
```

```mermaid
sequenceDiagram
  Worker->>DB: Store request and suspend execution atomically
  Reviewer->>API: Submit decision
  API->>DB: Record first decision and enqueue
  Worker->>DB: Resume pinned version and route decision
```

```mermaid
flowchart LR
  Schedule[Persisted schedules] --> Tick[Local time check]
  Tick --> Claim[Advance due time and enqueue in one transaction]
  Claim --> Worker[Worker]
```

```mermaid
erDiagram
  WORKFLOW ||--o{ VERSION : owns
  WORKFLOW ||--o{ SCHEDULE : plans
  WORKFLOW ||--o{ WEBHOOK : accepts
  VERSION ||--o{ EXECUTION : pins
  EXECUTION ||--o{ NODE_EXECUTION : checkpoints
  EXECUTION ||--o{ APPROVAL : suspends
  EXECUTION ||--o{ ARTIFACT : generates
```

Workflow nodes and edges are normalized by Pydantic and stored together inside each graph snapshot. The public API uses JSON models under /api/v1. The builder reads registry schemas and sends the same graph contract used by imports, templates and executions. Drafts can be saved before validation. An execution pins a validated revision.

```mermaid
flowchart LR
  Local[Local API lifespan] --> SQLite[(SQLite queue)]
  SQLite --> LocalWorker[Single local execution worker]
```

```mermaid
flowchart LR
  API[Single local API and scheduler] --> PG[(PostgreSQL source of truth)]
  PG --> Dispatch[Durable dispatch reservations]
  Dispatch --> Redis[(Redis run IDs only)]
  Redis --> Celery[Celery workers]
  Celery --> PG
  Celery --> Volume[Shared runtime artifact volume]
```

The two executors share the runner and workflow state transitions. The distributed dispatcher reserves eligible rows before publishing just their run IDs. A PostgreSQL advisory lock protects each run during worker execution. Worker heartbeats register availability in PostgreSQL. A lost message becomes eligible again when its reservation expires, and a failed worker releases ownership when its database session ends.

Browser nodes fetch administrator-approved pages through the pinned HTTPS transport and render the resulting static markup in an offline Playwright context. AI nodes use model allowlists and provider-specific adapters with a shared bounded task contract. The local SQLite default starts without a provider or broker.
