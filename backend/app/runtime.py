import asyncio
import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select, update

from .ai_providers import AISettings
from .contracts import Graph
from .db import Approval, Artifact, Audit, Credential, Execution, Step, Version, Workflow, now, uid, view
from .graph import analyze, references, resolve
from .nodes import REGISTRY, Context
from .security import MAX_BODY, json_size, redact, safe_path

PROJECT = Path(__file__).resolve().parents[2]
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT", "REJECTED"}
COMPLETED_STEP = {"SUCCEEDED", "SKIPPED"}
UNKNOWN_EXTERNAL = "External request outcome is unknown. Review the provider before starting another run."
logger = logging.getLogger("agentforge")


@dataclass(frozen=True)
class Settings:
    root: Path
    fixtures: Path = PROJECT / "workflows" / "fixtures"
    allowed_hosts: frozenset[str] = frozenset()
    browser: str = ""
    external_post: bool = False
    database_url: str = ""
    browser_hosts: frozenset[str] = frozenset()
    ai: AISettings = field(default_factory=AISettings)
    executor: str = "local"
    redis_url: str = ""

    def __post_init__(self):
        if self.executor not in {"local", "distributed"}:
            raise ValueError("Executor must be local or distributed")
        if self.executor == "distributed":
            if not self.database_url.startswith(("postgresql+psycopg://", "postgresql://")):
                raise ValueError("Distributed execution requires a PostgreSQL database URL")
            if not self.redis_url.startswith(("redis://", "rediss://")):
                raise ValueError("Distributed execution requires a Redis broker URL")

    @classmethod
    def from_env(cls):
        return cls(
            root=Path(os.getenv("AGENTFORGE_ROOT", PROJECT / ".runtime")).resolve(),
            allowed_hosts=frozenset(host.strip().lower() for host in
                                    os.getenv("AGENTFORGE_ALLOWED_HOSTS", "").split(",") if host.strip()),
            browser=os.getenv("AGENTFORGE_BROWSER", ""),
            external_post=os.getenv("AGENTFORGE_EXTERNAL_POST") == "1",
            database_url=os.getenv("AGENTFORGE_DATABASE_URL", ""),
            browser_hosts=frozenset(host.strip().lower() for host in
                                    os.getenv("AGENTFORGE_BROWSER_HOSTS", "").split(",") if host.strip()),
            ai=AISettings.from_env(),
            executor=os.getenv("AGENTFORGE_EXECUTOR", "local"),
            redis_url=os.getenv("AGENTFORGE_REDIS_URL", ""),
        )


def audit(session, label, subject):
    session.add(Audit(event=label, subject=subject))


def secret_values():
    return tuple(value for name, value in os.environ.items()
                 if name.startswith("AGENTFORGE_SECRET_") and value)


def credential_value(session, name, kind=None):
    ref = session.get(Credential, name)
    if not ref or (kind and kind != ref.kind):
        raise ValueError("Credential reference is unavailable for this action")
    value = os.environ.get(ref.env_var)
    if not value:
        raise ValueError("Credential is not configured in the backend environment")
    return ref.kind, value


def queue(session, workflow, source, payload, key=None, pinned=None):
    # Serialize revision creation and keyed submissions on PostgreSQL.
    workflow = session.get(Workflow, workflow.id, populate_existing=True, with_for_update=True)
    if key:
        prior = session.scalar(select(Execution).where(Execution.workflow_id == workflow.id, Execution.key == key))
        if prior:
            return prior
    graph = Graph.model_validate(pinned.definition if pinned else workflow.definition)
    errors, _, _, _, _ = analyze(graph)
    if errors:
        raise ValueError("; ".join(errors[:8]))
    accept = next(REGISTRY[item.type].trigger for item in graph.nodes if REGISTRY[item.type].trigger)
    if source not in (accept, "retry", "preview"):
        raise ValueError(f"Workflow requires a {accept} trigger")
    if json_size(payload) > MAX_BODY:
        raise ValueError("Execution payload exceeds the size limit")
    version = pinned or session.scalar(select(Version).where(
        Version.workflow_id == workflow.id, Version.revision == workflow.revision))
    if version is None:
        version = Version(workflow_id=workflow.id, revision=workflow.revision, name=workflow.name,
                          definition=graph.model_dump(mode="json"))
        session.add(version)
        session.flush()
    execution = Execution(workflow_id=workflow.id, version_id=version.id, workflow_name=version.name,
                          revision=version.revision, source=source, key=key,
                          payload=redact(payload, secret_values()))
    session.add(execution)
    session.flush()
    audit(session, "execution.queued", execution.id)
    return execution


def decide(session, approval, decision):
    execution = session.get(Execution, approval.execution_id, populate_existing=True, with_for_update=True)
    if execution.status != "WAITING_APPROVAL" or approval.decision is not None:
        return False
    if decision != "EXPIRED" and approval.expires <= now():
        return False
    stamp = now()
    changed = session.execute(update(Approval).where(Approval.id == approval.id, Approval.decision.is_(None))
                              .values(decision=decision, decided=stamp)).rowcount
    if not changed:
        return False
    execution.status = "QUEUED"
    execution.dispatch_after = None
    execution.deadline += stamp - approval.created
    audit(session, f"approval.{decision.lower()}", approval.id)
    return True


def resumable_step(execution, definition, steps):
    if execution.status != "FAILED":
        return None
    failed = [step for step in steps if step.status == "FAILED"]
    if len(failed) != 1 or any(step.status in {"RUNNING", "WAITING_APPROVAL", "RETRYING"} for step in steps):
        return None
    node = next((item for item in definition["nodes"] if item["id"] == failed[0].node_id), None)
    spec = REGISTRY.get(node["type"]) if node else None
    return failed[0] if spec and spec.replay else None


def resume_failed(session, execution, definition, steps):
    step = resumable_step(execution, definition, steps)
    if step is None:
        return False
    claimed = session.execute(update(Execution).where(
        Execution.id == execution.id, Execution.status == "FAILED", Execution.ended == execution.ended,
    ).values(status="QUEUED", ended=None, error=None, dispatch_after=None,
             deadline=now() + definition.get("timeout", Graph.model_fields["timeout"].default))).rowcount
    if not claimed:
        return False
    step.status, step.ended, step.retry_at = "RETRYING", None, None
    audit(session, "execution.resume_requested", execution.id)
    return True


def prepare_root(settings):
    settings.root.mkdir(parents=True, exist_ok=True)
    for name in ("input", "artifacts"):
        directory = settings.root / name
        if directory.resolve() != directory:
            raise RuntimeError("Runtime directories must not be links")
        directory.mkdir(exist_ok=True)


def artifact_path(settings, execution_id, node_id):
    root = settings.root / "artifacts"
    directory = safe_path(root, execution_id)
    directory.mkdir(exist_ok=True)
    return safe_path(directory, node_id)


class Runner:
    def __init__(self, sessions, settings):
        self.sessions = sessions
        self.settings = settings

    def recover(self, run_id=None):
        with self.sessions.begin() as session:
            statement = update(Execution).where(Execution.status == "RUNNING")
            if run_id is not None:
                statement = statement.where(Execution.id == run_id)
            session.execute(statement.values(status="QUEUED"))

    def running(self, run_id):
        with self.sessions() as session:
            return session.get(Execution, run_id).status == "RUNNING"

    async def bounded(self, action, timeout, run_id):
        task = asyncio.create_task(action)
        try:
            async with asyncio.timeout(timeout):
                while True:
                    done, _ = await asyncio.wait({task}, timeout=0.2)
                    if done:
                        return task.result()
                    if not self.running(run_id):
                        return None
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    def finish(self, run_id, status, error=None):
        with self.sessions.begin() as session:
            self.fail_transaction(session, run_id, status, error)

    async def worker(self):
        while True:
            try:
                with self.sessions() as session:
                    run_id = session.scalar(select(Execution.id).where(Execution.status == "QUEUED")
                                            .order_by(Execution.created).limit(1))
                if run_id:
                    await self.run(run_id)
                    continue
            except Exception:
                logger.error("Worker iteration failed", extra={"event": "worker.error"})
            await asyncio.sleep(0.2)

    async def run(self, run_id, *, ownership=lambda: None):
        ownership()
        with self.sessions.begin() as session:
            stamp = now()
            claimed = session.execute(update(Execution).where(Execution.id == run_id,
                                     Execution.status == "QUEUED").values(status="RUNNING")).rowcount
            if not claimed:
                return
            execution = session.get(Execution, run_id)
            graph = Graph.model_validate(session.get(Version, execution.version_id).definition)
            execution.started = execution.started or stamp
            execution.deadline = execution.deadline or stamp + graph.timeout
        try:
            await self.execute_graph(execution, graph, ownership)
        except Exception as error:
            ownership()
            self.finish(run_id, "FAILED", self.error_message(error))

    @staticmethod
    def error_message(error):
        if isinstance(error, (ValueError, RuntimeError, OSError)):
            return str(redact(str(error), secret_values()))[:400]
        if isinstance(error, TimeoutError):
            return "Node exceeded its deadline"
        return f"Node failed ({type(error).__name__})"

    async def execute_graph(self, execution, graph, ownership):
        errors, ordered, nodes, incoming, _ = analyze(graph)
        if errors:
            self.finish(execution.id, "FAILED", errors[0])
            return
        for identifier in ordered:
            ownership()
            if not self.running(execution.id):
                return
            if now() >= execution.deadline:
                self.finish(execution.id, "TIMED_OUT", "Workflow exceeded its deadline")
                return
            if not await self.step(execution, nodes[identifier], incoming[identifier], ownership):
                return
        ownership()
        routed_rejections = {edge.source for edge in graph.edges if edge.port == "reject"}
        with self.sessions.begin() as session:
            rejected = session.scalar(select(Approval.id).where(
                Approval.execution_id == execution.id,
                Approval.decision == "REJECT",
                Approval.node_id.not_in(routed_rejections),
            ).limit(1))
            self.fail_transaction(session, execution.id, "REJECTED" if rejected else "SUCCEEDED", None)

    async def step(self, execution, node, edges, ownership):
        run_id = execution.id
        key = (run_id, node.id)
        spec = REGISTRY[node.type]
        with self.sessions.begin() as session:
            if session.get(Execution, run_id, with_for_update=True).status != "RUNNING":
                return False
            stored = session.get(Step, key)
            if stored and stored.status in COMPLETED_STEP:
                return True
            checkpoint_query = select(Step).where(Step.execution_id == run_id)
            if node.type != "report":
                required = {edge.source for edge in edges} | {ref[1] for ref in references(node.config)}
                previous = session.scalars(checkpoint_query.where(Step.node_id.in_(required))).all() if required else []
            else:
                previous = session.scalars(checkpoint_query).all()
            checkpoints = {step.node_id: step for step in previous if step.status == "SUCCEEDED"}
            active = [checkpoints[edge.source].output for edge in edges
                      if edge.source in checkpoints and edge.port == checkpoints[edge.source].port]
            if not stored:
                stored = Step(execution_id=run_id, node_id=node.id, status="PENDING")
                session.add(stored)
            if edges and not active:
                stored.status, stored.ended = "SKIPPED", now()
                return True
            if stored.status == "RUNNING" and not spec.replay:
                stored.status, stored.ended = "FAILED", now()
                stored.error = UNKNOWN_EXTERNAL
                self.fail_transaction(session, execution.id, "FAILED", stored.error)
                return False
            attempts = stored.attempts or 0
            retry_at = stored.retry_at
            completing_approval = stored.status == "WAITING_APPROVAL"
            manual_resume = stored.status == "RETRYING" and retry_at is None
            remaining_attempts = node.retries + 1 - attempts
            if completing_approval or manual_resume:
                remaining_attempts = 1
            elif stored.status == "RUNNING":
                remaining_attempts = max(1, remaining_attempts)
            approval = session.scalar(select(Approval).where(Approval.execution_id == run_id,
                                       Approval.node_id == node.id)) if node.type == "approval" else None
            approved = (len(edges) == 1 and edges[0].port == "approve"
                        and edges[0].source in checkpoints and checkpoints[edges[0].source].port == "approve")
            outputs = {name: step.output for name, step in checkpoints.items()}
            timeline = ([view(step, "inputs", "output") for step in sorted(previous, key=lambda step: step.started or 0)]
                        if node.type == "report" else [])
        if retry_at:
            await asyncio.sleep(max(0, min(retry_at, execution.deadline) - now()))
        for attempt in range(remaining_attempts):
            ownership()
            if not self.running(run_id):
                return False
            remaining = execution.deadline - now()
            if remaining <= 0:
                self.finish(run_id, "TIMED_OUT", "Workflow exceeded its deadline")
                return False
            with self.sessions.begin() as session:
                if session.get(Execution, run_id, with_for_update=True).status != "RUNNING":
                    return False
                stored = session.get(Step, key)
                stored.status, stored.retry_at = "RUNNING", None
                stored.attempts = (stored.attempts or 0) + int(not completing_approval)
                stored.started = stored.started or now()
                stored.inputs = redact(active, secret_values())
            committing_result = False
            try:
                config = spec.config.model_validate(resolve(node.config, outputs))
                auth = None
                if getattr(config, "credential", ""):
                    with self.sessions() as session:
                        kind, secret = credential_value(session, config.credential)
                    if kind not in ("bearer", "basic", "api_key"):
                        raise ValueError("This credential type cannot be used with HTTP nodes")
                    auth = {"bearer": "Bearer ", "basic": "Basic ", "api_key": ""}[kind] + secret
                context = Context(
                    self.settings.root, self.settings.fixtures, self.settings.allowed_hosts, run_id,
                    execution.workflow_name, execution.payload, active, approval.decision if approval else None,
                    auth, self.settings.external_post and approved, self.settings.browser, timeline,
                    self.settings.browser_hosts, self.settings.ai,
                )
                result = await self.bounded(spec.action(context, config), min(node.timeout, remaining), run_id)
                ownership()
                if result is None or not self.running(run_id):
                    return False
                committing_result = True
                return self.persist_result(execution, node, result)
            except Exception as error:
                ownership()
                timed_out = isinstance(error, TimeoutError)
                status = "TIMED_OUT" if timed_out else "FAILED"
                message = "Node exceeded its deadline" if timed_out else self.error_message(error)
                if not spec.replay and timed_out:
                    message += ". " + UNKNOWN_EXTERNAL
                elif not spec.replay and committing_result:
                    message = UNKNOWN_EXTERNAL
                retry = attempt + 1 < remaining_attempts and spec.replay and (
                    timed_out or isinstance(error, (OSError, RuntimeError)))
                when = now() + (0.25 * 2 ** (attempts + attempt)) if retry else None
                with self.sessions.begin() as session:
                    if session.get(Execution, run_id, with_for_update=True).status != "RUNNING":
                        return False
                    stored = session.get(Step, key)
                    stored.error, stored.retry_at = message, when
                    stored.status = "RETRYING" if retry else status
                    if not retry:
                        stored.ended = now()
                        self.fail_transaction(session, run_id, status, message)
                        return False
                await asyncio.sleep(max(0, min(when, execution.deadline) - now()))
        return False

    @staticmethod
    def fail_transaction(session, run_id, status, message):
        execution = session.get(Execution, run_id, with_for_update=True)
        if execution.status == "RUNNING":
            execution.status, execution.ended, execution.error = status, now(), message
            audit(session, f"execution.{status.lower()}", run_id)

    def persist_result(self, execution, node, result):
        run_id = execution.id
        with self.sessions.begin() as session:
            active = session.get(Execution, run_id, with_for_update=True)
            if active.status != "RUNNING":
                return False
            stored = session.get(Step, (run_id, node.id))
            if result.approval:
                action, lifetime = result.approval
                session.add(Approval(execution_id=run_id, workflow_name=execution.workflow_name,
                                     node_id=node.id, action=redact(action, secret_values()), context=stored.inputs,
                                     expires=now() + lifetime))
                stored.status = "WAITING_APPROVAL"
                active.status = "WAITING_APPROVAL"
                audit(session, "approval.requested", run_id)
                return False
            clean = redact(result.output, secret_values())
            if json_size(clean) > MAX_BODY:
                raise ValueError("Node output exceeds the 1 MiB checkpoint limit")
            if result.artifact:
                filename, media, data = result.artifact
                path = artifact_path(self.settings, run_id, node.id)
                tmp = safe_path(path.parent, "tmp-" + uid())
                try:
                    tmp.write_bytes(data)
                    tmp.replace(path)
                finally:
                    tmp.unlink(missing_ok=True)
                entry = Artifact(execution_id=run_id, node_id=node.id, filename=filename, media_type=media,
                                 size=len(data), sha256=hashlib.sha256(data).hexdigest())
                session.add(entry)
                session.flush()
                clean["artifact_id"] = entry.id
            stored.status, stored.port, stored.output = "SUCCEEDED", result.port, clean
            stored.error, stored.ended = None, now()
            return True


class WorkerLock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.file = self.path.open("a+b")
        try:
            self.file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.file.close()
            raise RuntimeError("The local database already has an active AgentForge worker") from error
        return self

    def __exit__(self, *_):
        self.file.close()


class JSONLog(logging.Formatter):
    def format(self, record):
        return json.dumps({"time": now(), "level": record.levelname, "message": record.getMessage(),
                           "request_id": getattr(record, "request_id", None),
                           "event": getattr(record, "event", None)})
