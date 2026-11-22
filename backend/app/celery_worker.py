import asyncio
import os
from contextlib import closing
from functools import partial

from celery import Celery
from celery.signals import heartbeat_sent, worker_ready

from .db import connect
from .executors import TASK, postgres_ownership, process_delivery, register_worker
from .runtime import Runner, Settings, logger, prepare_root


def broker(url):
    return Celery("agentforge", broker=url, task_serializer="json", accept_content=["json"],
                  task_ignore_result=True, task_acks_late=True, task_reject_on_worker_lost=True,
                  worker_prefetch_multiplier=1, task_time_limit=3_660, broker_connection_timeout=4,
                  broker_transport_options={"visibility_timeout": 3_720, "socket_connect_timeout": 3,
                                            "socket_timeout": 3, "retry_on_timeout": False})


app = broker(os.getenv("AGENTFORGE_REDIS_URL", "redis://127.0.0.1:6379/0"))
active_worker = ""


@worker_ready.connect
def worker_connected(sender, **_):
    global active_worker
    active_worker = sender.hostname
    refresh_registration()


@heartbeat_sent.connect
def refresh_registration(**_):
    if not active_worker:
        return
    try:
        settings = Settings.from_env()
        engine, sessions = connect(settings.root, settings.database_url)
        with closing_engine(engine):
            register_worker(sessions, active_worker)
    except Exception:
        logger.warning("Worker registration could not be updated", extra={"event": "executor.registration"})


class closing_engine(closing):
    def __exit__(self, *_):
        self.thing.dispose()


@app.task(name=TASK)
def execute(identifier):
    settings = Settings.from_env()
    if settings.executor != "distributed":
        raise RuntimeError("Celery requires distributed executor settings")
    prepare_root(settings)
    engine, sessions = connect(settings.root, settings.database_url)
    with closing_engine(engine):
        asyncio.run(process_delivery(Runner(sessions, settings), partial(postgres_ownership, engine), identifier))


def publisher(url):
    client = broker(url)
    return lambda identifier: client.send_task(TASK, args=[identifier], retry=False)
