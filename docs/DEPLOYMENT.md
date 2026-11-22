# Deployment

The default Compose file builds FastAPI with SQLite and a static React frontend behind Nginx. The only published port is 127.0.0.1:8080. Persistent state and artifacts go into a named runtime volume. The build includes Playwright Chromium by default. Set the backend build argument `AGENTFORGE_WITH_BROWSER=0` for an image without browser dependencies.

```powershell
docker compose config --quiet
docker compose up --build
docker compose down
```

## Optional distributed execution

Run from the project root. Set fresh, URL-safe values in the shell. Avoid saving live values in the project.

```powershell
$env:AGENTFORGE_SECRET_POSTGRES = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:AGENTFORGE_SECRET_REDIS = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:AGENTFORGE_SECRET_REVIEWER = python -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose -f docker-compose.yml -f docker-compose.distributed.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.distributed.yml up --build -d
docker compose -f docker-compose.yml -f docker-compose.distributed.yml ps
Invoke-RestMethod http://127.0.0.1:8080/api/v1/system/status
docker compose -f docker-compose.yml -f docker-compose.distributed.yml down
```

Docker starts PostgreSQL and Redis on its private network, then starts the migration and API service before the Celery worker. Verify that the status endpoint reports an active worker before queuing a manual template. Approve a paused run with the configured reviewer key if the approval form requests it. API and worker share the runtime volume. Keep the local SQLite and distributed deployments in separate Compose projects if using both.

Container runtime, real PostgreSQL locks, Redis delivery and Celery failure behavior are unverified on the completion host. Use a single API scheduler. Review [security boundaries](SECURITY.md) before considering shared deployment.
