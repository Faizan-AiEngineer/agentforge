# API reference

Open [OpenAPI](http://127.0.0.1:8000/docs) on a running backend for request models and interactive calls. The service uses JSON and returns a correlation ID in response headers. Paginated endpoints accept `offset` and `limit`.

| Routes | Purpose |
| --- | --- |
| GET /health, /ready | Process and database readiness |
| GET /api/v1/system/status, /system/capabilities | Runtime configuration |
| GET /api/v1/system/ai/{provider} | Provider availability and approved models |
| GET /api/v1/nodes | Registry configuration schemas and named ports |
| POST /api/v1/validate | Pure graph validation |
| GET or POST /api/v1/workflows | List or create draft |
| GET or PUT /api/v1/workflows/{id} | Read or update with the last known revision |
| POST /api/v1/workflows/{id}/duplicate, /run | Duplicate or enqueue a manual run |
| GET /api/v1/workflows/{id}/versions | Pinned run revisions |
| GET /api/v1/templates | Preview importable definitions |
| POST /api/v1/templates/{key}/import | Create a workflow from a template |
| GET /api/v1/executions, /executions/{id} | Run history and graph checkpoints |
| POST /api/v1/executions/{id}/cancel | Cancel an active run |
| POST /api/v1/executions/{id}/resume | Requeue the same failed run for one additional attempt at its replayable failed node. Returns HTTP 202 or 409. |
| POST /api/v1/executions/{id}/retry | Start a separate run from the pinned replayable workflow |
| GET /api/v1/approvals | Pending and previous decisions |
| POST /api/v1/approvals/{id}/decision | Record approve, reject, or request changes |
| GET or POST /api/v1/schedules, /webhooks, /credentials | List and register definitions |
| PATCH /api/v1/schedules/{id} | Enable or disable |
| POST /api/v1/hooks/{id} | Receive authenticated events |
| GET /api/v1/artifacts/{id} | Download artifact by server-issued identifier |
| GET /api/v1/monitoring, /audit | Persisted statistics and audit events |

Manual run bodies contain `{"payload":{}}`. Send an optional `Idempotency-Key` to reuse a run. For a webhook, create a **Webhook Trigger** workflow, register an environment credential of type `webhook`, then create the hook. Send a UTF-8 body such as `{"event_id":"order-21","payload":{"status":"received"}}`. Set `X-AgentForge-Timestamp` to UTC Unix seconds and `X-AgentForge-Signature` to the lowercase HMAC-SHA256 hex digest of timestamp + period + exact body bytes. The server accepts timestamps within five minutes and deduplicates signed event IDs per hook. Failed signatures return 401.

When `AGENTFORGE_SECRET_REVIEWER` is configured, approval clients send it in the `X-AgentForge-Reviewer` header. Artifact downloads return 404 for missing files and 409 for content that differs from its saved checksum. AI availability returns configuration and model names without exposing provider credentials.
