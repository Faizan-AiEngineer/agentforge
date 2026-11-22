from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON, Float


def uid():
    return uuid4().hex


def now():
    return datetime.now(UTC).timestamp()


class Base(DeclarativeBase):
    pass


class Workflow(Base):
    __tablename__ = "workflow"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    definition: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(default=1)
    created: Mapped[float] = mapped_column(Float, default=now)
    updated: Mapped[float] = mapped_column(Float, default=now)


class Version(Base):
    __tablename__ = "workflow_version"
    __table_args__ = (UniqueConstraint("workflow_id", "revision"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow.id"), index=True)
    revision: Mapped[int]
    name: Mapped[str]
    definition: Mapped[dict] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(Float, default=now)


class Execution(Base):
    __tablename__ = "execution"
    __table_args__ = (UniqueConstraint("workflow_id", "key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("workflow_version.id"))
    workflow_name: Mapped[str]
    revision: Mapped[int]
    source: Mapped[str]
    key: Mapped[str | None]
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(index=True, default="QUEUED")
    created: Mapped[float] = mapped_column(Float, index=True, default=now)
    started: Mapped[float | None]
    ended: Mapped[float | None]
    deadline: Mapped[float | None]
    error: Mapped[str | None]
    dispatch_after: Mapped[float | None] = mapped_column(Float, index=True)


class Worker(Base):
    __tablename__ = "executor_worker"
    name: Mapped[str] = mapped_column(String(255), primary_key=True)
    last_seen: Mapped[float] = mapped_column(Float)


class Step(Base):
    __tablename__ = "node_execution"
    execution_id: Mapped[str] = mapped_column(ForeignKey("execution.id"), primary_key=True)
    node_id: Mapped[str] = mapped_column(primary_key=True)
    status: Mapped[str]
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    started: Mapped[float | None]
    ended: Mapped[float | None]
    inputs: Mapped[list | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    port: Mapped[str | None]
    error: Mapped[str | None]
    retry_at: Mapped[float | None]


class Approval(Base):
    __tablename__ = "approval"
    __table_args__ = (UniqueConstraint("execution_id", "node_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    execution_id: Mapped[str] = mapped_column(ForeignKey("execution.id"), index=True)
    workflow_name: Mapped[str]
    node_id: Mapped[str]
    action: Mapped[str]
    context: Mapped[list] = mapped_column(JSON)
    created: Mapped[float] = mapped_column(Float, default=now)
    expires: Mapped[float]
    decision: Mapped[str | None]
    decided: Mapped[float | None]
    reviewer: Mapped[str] = mapped_column(default="Local operator")


class Artifact(Base):
    __tablename__ = "artifact"
    __table_args__ = (UniqueConstraint("execution_id", "node_id"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    execution_id: Mapped[str] = mapped_column(ForeignKey("execution.id"), index=True)
    node_id: Mapped[str]
    filename: Mapped[str]
    media_type: Mapped[str]
    size: Mapped[int]
    sha256: Mapped[str]
    created: Mapped[float] = mapped_column(Float, default=now)


class Schedule(Base):
    __tablename__ = "schedule"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow.id"), index=True)
    kind: Mapped[str]
    expression: Mapped[str]
    timezone: Mapped[str]
    enabled: Mapped[bool] = mapped_column(default=True)
    next_run: Mapped[float | None]
    last_run: Mapped[float | None]
    error: Mapped[str | None]


class Webhook(Base):
    __tablename__ = "webhook"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow.id"), index=True)
    credential: Mapped[str]
    created: Mapped[float] = mapped_column(Float, default=now)


class Credential(Base):
    __tablename__ = "credential_reference"
    name: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str]
    env_var: Mapped[str]
    created: Mapped[float] = mapped_column(Float, default=now)


class Audit(Base):
    __tablename__ = "audit_event"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    event: Mapped[str]
    subject: Mapped[str]
    created: Mapped[float] = mapped_column(Float, index=True, default=now)


def connect(root: Path, database_url: str = ""):
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(database_url or f"sqlite:///{(root / 'agentforge.sqlite').as_posix()}")
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def configure(dbapi_connection, _):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine, sessionmaker(engine, expire_on_commit=False)


def view(row, *exclude):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns
            if column.key not in exclude}
