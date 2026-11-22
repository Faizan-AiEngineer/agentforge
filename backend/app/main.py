import hashlib
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager, nullcontext
from typing import Literal

from alembic import command
from alembic.config import Config
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field, ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from starlette.datastructures import Headers
from starlette.staticfiles import StaticFiles

from .ai_providers import PROVIDERS, model_list
from .contracts import Contract, Graph, RunInput, WorkflowInput
from .db import (
    Approval,
    Artifact,
    Audit,
    Credential,
    Execution,
    Schedule,
    Step,
    Version,
    Webhook,
    Worker,
    Workflow,
    connect,
    now,
    uid,
    view,
)
from .executors import DistributedExecutor, LocalExecutor
from .graph import analyze
from .nodes import REGISTRY
from .runtime import (
    PROJECT,
    TERMINAL,
    JSONLog,
    Runner,
    Settings,
    WorkerLock,
    artifact_path,
    audit,
    credential_value,
    decide,
    prepare_root,
    queue,
    secret_values,
)
from .security import MAX_BODY, json_size, redact
from .templates import TEMPLATES, template
from .triggers import ScheduleInput, next_fire, tick

logger = logging.getLogger("agentforge")


class LocalBoundary:
    hosts = frozenset({"127.0.0.1", "localhost", "testserver"})
    origins = frozenset({"http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8000",
               "http://localhost:8000", "http://127.0.0.1:4173", "http://localhost:4173",
               "http://127.0.0.1:8080", "http://localhost:8080"})

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        host = headers.get("host", "").split(":", 1)[0]
        origin = headers.get("origin")
        request_id = uid()
        scope.setdefault("state", {})["request_id"] = request_id
        if host not in self.hosts or (origin and origin not in self.origins):
            await JSONResponse({"detail": "Local origin required"}, status_code=403)(scope, receive, send)
            return
        if scope["method"] in {"POST", "PATCH", "PUT"}:
            body = bytearray()
            while True:
                event = await receive()
                if event["type"] == "http.disconnect":
                    return
                body.extend(event.get("body", b""))
                if len(body) > MAX_BODY:
                    await JSONResponse({"detail": "Request body exceeds 1 MiB"}, status_code=413)(
                        scope, receive, send)
                    return
                if not event.get("more_body"):
                    break

            original_receive = receive
            sent = False

            async def replay():
                nonlocal sent
                if sent:
                    return await original_receive()
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            receive = replay

        async def correlate(message):
            if message["type"] == "http.response.start":
                message["headers"] += [(b"x-request-id", request_id.encode()),
                                       (b"x-content-type-options", b"nosniff")]
                if scope["path"].startswith("/api/"):
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, correlate)


class CredentialInput(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    kind: Literal["bearer", "basic", "api_key", "webhook", "ai"]
    env_var: str = Field(pattern=r"^AGENTFORGE_SECRET_[A-Z0-9_]{1,100}$")


class Decision(Contract):
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]


class WebhookInput(Contract):
    workflow_id: str
    credential: str


class WebhookEvent(Contract):
    event_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    payload: dict = Field(default_factory=dict)


class Enabled(Contract):
    enabled: bool


def model_or_404(session, model, key):
    result = session.get(model, key)
    if result is None:
        raise HTTPException(404, "Record not found")
    return result


def workflow_data(workflow):
    return view(workflow)


def clean_graph(data):
    definition = data.definition.model_dump(mode="json")
    # Round-trip validation rejects stored credentials instead of silently changing workflow behavior.
    secrets = secret_values()
    if any(redact(value, secrets) != value for value in
           [definition, data.name, data.description]):
        raise HTTPException(422, "Workflow contains sensitive fields or values. Use credential references.")
    return definition


def create_workflow(session, data):
    graph = clean_graph(data)
    workflow = Workflow(name=data.name, description=data.description, definition=graph)
    session.add(workflow)
    session.flush()
    audit(session, "workflow.created", workflow.id)
    return workflow


def paged(session, model, *, offset, limit, order=None, conditions=(), exclude=()):
    rows = select(model).where(*conditions)
    total = session.scalar(select(func.count()).select_from(model).where(*conditions))
    if order is not None:
        rows = rows.order_by(order)
    return {"items": [view(row, *exclude) for row in session.scalars(rows.offset(offset).limit(limit))],
            "total": total, "offset": offset, "limit": limit}


def stats(session):
    totals = dict(session.execute(select(Execution.status, func.count()).group_by(Execution.status)).all())
    workflow_count = session.scalar(select(func.count()).select_from(Workflow))
    duration = session.scalar(select(func.avg(Execution.ended - Execution.started)).where(
        Execution.status.in_(TERMINAL), Execution.started.is_not(None)))
    usage = session.execute(select(Step.node_id, func.count()).where(Step.status != "SKIPPED")
                            .group_by(Step.node_id).order_by(func.count().desc()).limit(8)).all()
    recent = session.scalars(select(Execution).order_by(Execution.created.desc()).limit(10)).all()
    final = sum(totals.get(state, 0) for state in TERMINAL)
    failures = totals.get("FAILED", 0) + totals.get("TIMED_OUT", 0)
    return {"workflows": workflow_count, "total_executions": sum(totals.values()), "statuses": totals,
            "active_workflows": session.scalar(select(func.count(func.distinct(Execution.workflow_id))).where(
                Execution.status.in_(["QUEUED", "RUNNING", "WAITING_APPROVAL"]))),
            "completed": final, "failed": failures,
            "success_rate": totals.get("SUCCEEDED", 0) / final if final else None,
            "avg_duration": duration,
            "node_usage": [{"node": label, "runs": count} for label, count in usage],
            "pending_approvals": totals.get("WAITING_APPROVAL", 0),
            "recent": [view(row, "key", "payload", "deadline") for row in recent]}


def create_app(settings=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        prepare_root(settings)
        local = settings.executor == "local"
        with (WorkerLock(settings.root / "worker.lock") if local else nullcontext()):
            engine, sessions = connect(settings.root, settings.database_url)
            config = Config(str(PROJECT / "backend" / "alembic.ini"))
            with engine.connect() as connection:
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            app.state.sessions = sessions
            runner = Runner(sessions, settings)
            app.state.runner = runner
            if local:
                executor = LocalExecutor(runner)
            else:
                from .celery_worker import publisher
                executor = DistributedExecutor(sessions, publisher(settings.redis_url))
            executor.start()
            scheduler = AsyncIOScheduler()
            async def trigger_tick():
                tick(sessions, settings)
            scheduler.add_job(trigger_tick, "interval", seconds=1, max_instances=1, coalesce=True)
            scheduler.start()
            try:
                yield
            finally:
                scheduler.shutdown(wait=False)
                await executor.close()
                engine.dispose()

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONLog())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    app = FastAPI(title="AgentForge", version="0.1.0", lifespan=lifespan)
    app.add_middleware(LocalBoundary)
    api = APIRouter(prefix="/api/v1")

    def db(request: Request):
        with request.app.state.sessions() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    # Commits occur explicitly before returning mutations. The dependency provides rollback.
    def save(session):
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise HTTPException(409, "Record already exists or a concurrent change occurred") from error

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        details = [{"location": item["loc"], "message": item["msg"].split(", ")[0]} for item in error.errors()]
        return JSONResponse({"detail": details, "request_id": request.state.request_id}, status_code=422)

    @app.exception_handler(ValueError)
    async def bad_value(request, error):
        return JSONResponse({"detail": redact(str(error), secret_values())[:500],
                             "request_id": request.state.request_id}, status_code=422)

    @app.exception_handler(Exception)
    async def unexpected(request, error):
        logger.error("Request failed (%s)", type(error).__name__,
                     extra={"event": "request.error", "request_id": request.state.request_id})
        return JSONResponse({"detail": "Unexpected local service error", "request_id": request.state.request_id},
                            status_code=500)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/ready")
    async def ready(session=Depends(db)):
        session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @api.get("/system/status")
    async def system_status(session=Depends(db)):
        local = settings.executor == "local"
        active = 1 if local else session.scalar(
            select(func.count()).select_from(Worker).where(Worker.last_seen >= now() - 15))
        return {"mode": settings.executor, "version": app.version, "database": session.bind.dialect.name,
                "worker": "single-process" if local else "celery", "active_workers": active,
                "offline": not (settings.allowed_hosts or settings.browser_hosts or settings.ai.configured("openai"))}

    @api.get("/system/capabilities")
    async def capabilities():
        setup = {name: bool(settings.ai.configured(name)) for name in PROVIDERS}
        return {"offline_text": True, "browser_fixture": True, "browser_channel": settings.browser or "chromium",
                "browser_hosts": sorted(settings.browser_hosts), "ai_setup": setup,
                "external_http": bool(settings.allowed_hosts), "approved_hosts": sorted(settings.allowed_hosts),
                "external_post": settings.external_post and bool(settings.allowed_hosts),
                "external_ai": setup["ollama"] or setup["openai"],
                "distributed_worker": settings.executor == "distributed",
                "approval_requires_key": bool(os.getenv("AGENTFORGE_SECRET_REVIEWER"))}

    @api.get("/system/ai/{provider}")
    async def ai_status(provider: Literal["offline", "ollama", "openai"]):
        return await model_list(settings.ai, provider)

    @api.get("/nodes")
    async def catalog():
        return [{"type": key, "name": spec.name, "category": spec.category,
                 "description": spec.description, "schema": spec.config.model_json_schema(),
                 "ports": spec.ports, "trigger": spec.trigger, "input_kind": spec.input_kind,
                 "output_kind": spec.output_kind,
                 "available": ((bool(settings.allowed_hosts) and (key != "http_post" or settings.external_post))
                               if key in {"http_get", "http_post", "api_pages"} else True)}
                for key, spec in REGISTRY.items()]

    @api.post("/validate")
    async def validate(graph: Graph):
        errors, ordered, _, _, _ = analyze(graph)
        return {"valid": not errors, "errors": errors, "order": ordered if not errors else []}

    @api.get("/workflows")
    async def workflows(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)):
        return paged(session, Workflow, offset=offset, limit=limit, order=Workflow.updated.desc())

    @api.post("/workflows", status_code=201)
    async def add_workflow(data: WorkflowInput, session=Depends(db)):
        workflow = create_workflow(session, data)
        save(session)
        return workflow_data(workflow)

    @api.get("/workflows/{workflow_id}")
    async def get_workflow(workflow_id: str, session=Depends(db)):
        return workflow_data(model_or_404(session, Workflow, workflow_id))

    @api.put("/workflows/{workflow_id}")
    async def save_workflow(workflow_id: str, data: WorkflowInput, session=Depends(db)):
        model_or_404(session, Workflow, workflow_id)
        graph = clean_graph(data)
        changed = session.execute(update(Workflow).where(Workflow.id == workflow_id,
                                  Workflow.revision == data.revision).values(
            name=data.name, description=data.description, definition=graph, updated=now(),
            revision=Workflow.revision + 1)).rowcount
        if not changed:
            raise HTTPException(409, "The draft has changed. Reopen it before saving.")
        audit(session, "workflow.updated", workflow_id)
        save(session)
        return workflow_data(session.get(Workflow, workflow_id))

    @api.post("/workflows/{workflow_id}/duplicate", status_code=201)
    async def duplicate(workflow_id: str, session=Depends(db)):
        source = model_or_404(session, Workflow, workflow_id)
        workflow = create_workflow(session, WorkflowInput(name=source.name[:90] + " (copy)",
                                   description=source.description, definition=Graph.model_validate(source.definition)))
        save(session)
        return workflow_data(workflow)

    @api.get("/workflows/{workflow_id}/versions")
    async def versions(workflow_id: str, offset: int = Query(0, ge=0),
                       limit: int = Query(25, ge=1, le=100), session=Depends(db)):
        model_or_404(session, Workflow, workflow_id)
        return paged(session, Version, offset=offset, limit=limit, order=Version.revision.desc(),
                     conditions=(Version.workflow_id == workflow_id,))

    @api.get("/templates")
    async def templates():
        return [template(key) for key in TEMPLATES]

    @api.post("/templates/{key}/import", status_code=201)
    async def import_template(key: str, session=Depends(db)):
        if key not in TEMPLATES:
            raise HTTPException(404, "Template not found")
        data = template(key)
        workflow = create_workflow(session, WorkflowInput.model_validate(
            {name: data[name] for name in ("name", "description", "definition")}))
        save(session)
        return workflow_data(workflow)

    @api.post("/workflows/{workflow_id}/run", status_code=202)
    async def run(workflow_id: str, data: RunInput, preview: bool = False, session=Depends(db),
                  key: str | None = Header(None, alias="Idempotency-Key", max_length=100)):
        if preview:
            raise HTTPException(422, "Use the workflow's configured event source")
        workflow = model_or_404(session, Workflow, workflow_id)
        execution = queue(session, workflow, "manual", data.payload, "manual:" + key if key else None)
        save(session)
        return view(execution, "key", "payload", "deadline")

    @api.get("/executions")
    async def executions(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                         status: str | None = Query(None, max_length=30), session=Depends(db)):
        return paged(session, Execution, offset=offset, limit=limit, order=Execution.created.desc(),
                     conditions=(Execution.status == status,) if status else (),
                     exclude=("key", "payload", "deadline"))

    @api.get("/executions/{execution_id}")
    async def execution_details(execution_id: str, session=Depends(db)):
        run = model_or_404(session, Execution, execution_id)
        steps = session.scalars(select(Step).where(Step.execution_id == execution_id)
                               .order_by(Step.started.is_(None), Step.started)).all()
        approvals = session.scalars(select(Approval).where(Approval.execution_id == execution_id)).all()
        artifacts = session.scalars(select(Artifact).where(Artifact.execution_id == execution_id)).all()
        return {**view(run, "key", "deadline"), "definition": session.get(Version, run.version_id).definition,
                "nodes": [view(step) for step in steps], "approvals": [view(approval) for approval in approvals],
                "artifacts": [view(item) for item in artifacts]}

    @api.post("/executions/{execution_id}/cancel")
    async def cancel(execution_id: str, session=Depends(db)):
        run = session.get(Execution, execution_id, with_for_update=True)
        if run is None:
            raise HTTPException(404, "Record not found")
        if run.status in TERMINAL:
            raise HTTPException(409, "Only active executions can be cancelled")
        run.status, run.ended = "CANCELLED", now()
        session.execute(update(Step).where(Step.execution_id == run.id,
                        Step.status.in_(["RUNNING", "RETRYING", "WAITING_APPROVAL"]))
                        .values(status="CANCELLED", ended=run.ended))
        session.execute(update(Approval).where(Approval.execution_id == run.id, Approval.decision.is_(None))
                        .values(decision="CANCELLED", decided=run.ended))
        audit(session, "execution.cancelled", run.id)
        save(session)
        return view(run, "key", "payload", "deadline")

    @api.post("/executions/{execution_id}/retry", status_code=202)
    async def retry(execution_id: str, session=Depends(db)):
        run = model_or_404(session, Execution, execution_id)
        if run.status not in {"FAILED", "TIMED_OUT", "CANCELLED"}:
            raise HTTPException(409, "Retry is available for failed, timed out or cancelled runs")
        version = session.get(Version, run.version_id)
        if any(not REGISTRY.get(item["type"]) or not REGISTRY[item["type"]].replay
               for item in version.definition["nodes"]):
            raise HTTPException(409, "This workflow contains an external write. Review the provider first.")
        clone = queue(session, session.get(Workflow, run.workflow_id), "retry", run.payload, pinned=version)
        save(session)
        return view(clone, "key", "payload", "deadline")

    @api.get("/artifacts/{artifact_id}")
    async def download(artifact_id: str, session=Depends(db)):
        entry = model_or_404(session, Artifact, artifact_id)
        path = artifact_path(settings, entry.execution_id, entry.node_id)
        if not path.is_file():
            raise HTTPException(404, "Artifact file is missing")
        with path.open("rb") as source:
            if path.stat().st_size != entry.size or hashlib.file_digest(source, "sha256").hexdigest() != entry.sha256:
                raise HTTPException(409, "Artifact content does not match its saved checkpoint")
        return FileResponse(path, filename=entry.filename, media_type=entry.media_type)

    @api.get("/approvals")
    async def approvals(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)):
        return paged(session, Approval, offset=offset, limit=limit, order=Approval.created.desc())

    @api.post("/approvals/{approval_id}/decision")
    async def approval_decision(approval_id: str, data: Decision, session=Depends(db),
                                reviewer_key: str = Header("", alias="X-AgentForge-Reviewer", max_length=200)):
        configured = os.getenv("AGENTFORGE_SECRET_REVIEWER")
        if configured and not hmac.compare_digest(configured.encode(), reviewer_key.encode()):
            raise HTTPException(403, "A valid reviewer key is required")
        approval = model_or_404(session, Approval, approval_id)
        if not decide(session, approval, data.decision):
            raise HTTPException(409, "Approval was already decided, expired, or cancelled")
        save(session)
        return view(approval)

    @api.get("/schedules")
    async def schedules(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)):
        return paged(session, Schedule, offset=offset, limit=limit, order=Schedule.next_run)

    @api.post("/schedules", status_code=201)
    async def schedule(data: ScheduleInput, session=Depends(db)):
        workflow = model_or_404(session, Workflow, data.workflow_id)
        expected = "file_trigger" if data.kind == "file" else "schedule"
        if not any(node["type"] == expected for node in workflow.definition["nodes"]):
            raise HTTPException(422, f"A {expected} trigger node is required")
        try:
            fire = next_fire(data.kind, data.expression, data.timezone, now(), created=True)
        except (ValueError, KeyError, OverflowError):
            raise HTTPException(422, "Invalid schedule expression or time zone") from None
        schedule = Schedule(**data.model_dump(), next_run=fire)
        session.add(schedule)
        session.flush()
        audit(session, "schedule.created", schedule.id)
        save(session)
        return view(schedule)

    @api.patch("/schedules/{schedule_id}")
    async def toggle_schedule(schedule_id: str, data: Enabled, session=Depends(db)):
        schedule = model_or_404(session, Schedule, schedule_id)
        if data.enabled and not schedule.enabled:
            try:
                schedule.next_run = next_fire(schedule.kind, schedule.expression, schedule.timezone,
                                              now(), created=True)
            except ValueError:
                raise HTTPException(422, "One-time schedule is already past") from None
        schedule.enabled = data.enabled
        audit(session, "schedule.updated", schedule.id)
        save(session)
        return view(schedule)

    @api.get("/webhooks")
    async def webhooks(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)):
        return paged(session, Webhook, offset=offset, limit=limit, order=Webhook.created.desc())

    @api.post("/webhooks", status_code=201)
    async def create_webhook(data: WebhookInput, session=Depends(db)):
        workflow = model_or_404(session, Workflow, data.workflow_id)
        if not any(node["type"] == "webhook" for node in workflow.definition["nodes"]):
            raise HTTPException(422, "A webhook trigger node is required")
        _, secret = credential_value(session, data.credential, "webhook")
        if len(secret) < 24:
            raise HTTPException(422, "Configure a webhook secret of at least 24 characters")
        webhook = Webhook(**data.model_dump())
        session.add(webhook)
        session.flush()
        audit(session, "webhook.created", webhook.id)
        save(session)
        return view(webhook)

    @api.post("/hooks/{hook_id}", status_code=202)
    async def web_event(hook_id: str, request: Request, session=Depends(db),
                        stamp: str = Header("", alias="X-AgentForge-Timestamp", max_length=16),
                        signature: str = Header("", alias="X-AgentForge-Signature", max_length=64)):
        hook = model_or_404(session, Webhook, hook_id)
        try:
            _, secret = credential_value(session, hook.credential, "webhook")
        except ValueError:
            raise HTTPException(401, "Invalid webhook authentication") from None
        raw = await request.body()
        expected = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
        if (not re.fullmatch(r"[0-9]{1,12}", stamp) or abs(now() - int(stamp)) > 300
                or not re.fullmatch(r"[0-9a-f]{64}", signature) or not hmac.compare_digest(expected, signature)):
            raise HTTPException(401, "Invalid or expired webhook signature")
        try:
            event = WebhookEvent.model_validate_json(raw)
            json_size(event.payload)
        except (ValidationError, ValueError):
            raise HTTPException(422, "Invalid event envelope") from None
        key = f"hook:{hook.id}:{event.event_id}"
        existing = session.scalar(select(Execution).where(Execution.workflow_id == hook.workflow_id,
                                  Execution.key == key))
        if existing:
            return view(existing, "key", "payload", "deadline")
        recent = session.scalar(select(func.count()).select_from(Execution).where(
            Execution.workflow_id == hook.workflow_id, Execution.key.startswith(f"hook:{hook.id}:"),
            Execution.created >= now() - 60))
        if recent >= 20:
            raise HTTPException(429, "Webhook rate limit reached")
        run = queue(session, session.get(Workflow, hook.workflow_id), "webhook", event.payload, key)
        save(session)
        return view(run, "key", "payload", "deadline")

    @api.get("/credentials")
    async def credentials(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)):
        return paged(session, Credential, offset=offset, limit=limit, order=Credential.created.desc())

    @api.post("/credentials", status_code=201)
    async def create_credential(data: CredentialInput, session=Depends(db)):
        credential = Credential(**data.model_dump())
        session.add(credential)
        audit(session, "credential.referenced", credential.name)
        save(session)
        return view(credential)

    @api.get("/credentials/{name}/status")
    async def credential_status(name: str, session=Depends(db)):
        entry = model_or_404(session, Credential, name)
        return {"configured": bool(os.environ.get(entry.env_var))}

    @api.get("/monitoring")
    async def monitoring(session=Depends(db)):
        return stats(session)

    @api.get("/audit")
    async def audit_log(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100), session=Depends(db)):
        return paged(session, Audit, offset=offset, limit=limit, order=Audit.created.desc())

    app.include_router(api)
    frontend = PROJECT / "frontend" / "dist"
    if (frontend / "index.html").is_file() and (frontend / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="frontend-assets")

        @app.get("/{route:path}", include_in_schema=False)
        async def frontend_route(route: str):
            if route.split("/", 1)[0] in {"api", "assets"}:
                raise HTTPException(404, "Route not found")
            return FileResponse(frontend / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
