import asyncio
import re
from collections.abc import Callable
from contextlib import contextmanager
from typing import Protocol

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert

from .db import Execution, Worker, now
from .runtime import logger

TASK = "agentforge.execute"
RUN_ID = re.compile(r"^[0-9a-f]{32}$")
DISPATCH_LEASE = 20


class Executor(Protocol):
    def start(self) -> None: ...
    async def close(self) -> None: ...


class LocalExecutor:
    def __init__(self, runner):
        self.runner = runner
        self.task = None

    def start(self):
        self.runner.recover()
        self.task = asyncio.create_task(self.runner.worker())

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


def lock_key(identifier):
    return int.from_bytes(bytes.fromhex(identifier)[:8], "big", signed=True)


@contextmanager
def postgres_ownership(engine, identifier):
    key = lock_key(identifier)
    sql = {"key": key}
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        pid = connection.scalar(text("SELECT pg_backend_pid()"))
        claimed = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), sql)
        try:
            if not claimed:
                yield None
            else:
                def ensure():
                    if connection.scalar(text("SELECT pg_backend_pid()")) != pid:
                        raise RuntimeError("Distributed execution ownership was lost")
                yield ensure
        finally:
            if claimed:
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), sql)
                except Exception:
                    connection.invalidate()
                    raise


def register_worker(sessions, name):
    with sessions.begin() as session:
        reservation = insert(Worker).values(name=name[:255], last_seen=now())
        session.execute(reservation.on_conflict_do_update(
            index_elements=[Worker.name], set_={"last_seen": reservation.excluded.last_seen}))


def reserve_dispatch(sessions, *, seconds=DISPATCH_LEASE, limit=20, clock=now):
    stamp = clock()
    with sessions.begin() as session:
        candidates = session.scalars(select(Execution).where(
            Execution.status.in_(("QUEUED", "RUNNING")),
            or_(Execution.dispatch_after.is_(None), Execution.dispatch_after <= stamp),
        ).order_by(Execution.created).limit(limit).with_for_update(skip_locked=True)).all()
        identifiers = []
        for run in candidates:
            run.dispatch_after = stamp + seconds
            if run.status == "RUNNING" and session.bind.dialect.name == "postgresql":
                free = session.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": lock_key(run.id)})
                if not free:
                    continue
            identifiers.append(run.id)
        return identifiers


class DistributedExecutor:
    def __init__(self, sessions, publish: Callable[[str], None]):
        self.sessions = sessions
        self.publish = publish
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.dispatch())

    async def dispatch(self):
        while True:
            try:
                identifiers = await asyncio.to_thread(reserve_dispatch, self.sessions)
                for identifier in identifiers:
                    await asyncio.to_thread(self.publish, identifier)
            except Exception:
                logger.warning("Distributed delivery will retry", extra={"event": "executor.dispatch_retry"})
            await asyncio.sleep(1)

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


async def process_delivery(runner, ownership, identifier):
    if not RUN_ID.fullmatch(identifier):
        raise ValueError("Invalid execution identifier")
    with ownership(identifier) as ensure:
        if ensure is None:
            return False
        ensure()
        runner.recover(identifier)
        await runner.run(identifier, ownership=ensure)
        return True
