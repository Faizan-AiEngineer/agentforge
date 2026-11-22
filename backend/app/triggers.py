import hashlib
from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import Field
from sqlalchemy import select

from .contracts import Contract
from .db import Approval, Schedule, Workflow, now
from .runtime import decide, queue
from .security import read_file, safe_path


class ScheduleInput(Contract):
    workflow_id: str
    kind: Literal["interval", "cron", "once", "file"] = "interval"
    expression: str = Field(min_length=1, max_length=150)
    timezone: str = Field(default="UTC", max_length=100)


def next_fire(kind, expression, zone, timestamp, *, created):
    tz = ZoneInfo(zone)
    if kind == "interval":
        interval = int(expression)
        if not 5 <= interval <= 2_592_000:
            raise ValueError("Interval must be 5 to 2,592,000 seconds")
        return timestamp + interval
    if kind == "file":
        if not expression.startswith(".") or not expression[1:].isalnum() or len(expression) > 12:
            raise ValueError("A file watch requires a simple extension such as .csv")
        return timestamp + 5
    if kind == "once":
        value = datetime.fromisoformat(expression)
        if value.tzinfo is None:
            value = value.replace(tzinfo=tz)
        if created and value.timestamp() <= timestamp:
            raise ValueError("One-time schedules must be in the future")
        return value.timestamp() if created else None
    trigger = CronTrigger.from_crontab(expression, timezone=tz)
    instant = trigger.get_next_fire_time(None, datetime.fromtimestamp(timestamp + 1, UTC))
    return instant.timestamp() if instant else None


def scan_files(session, workflow, schedule, root):
    directory = root / "input"
    if directory.resolve() != directory:
        raise ValueError("The input directory must not be a link")
    for index, file in enumerate(sorted(directory.iterdir())):
        if index >= 100:
            raise ValueError("The file watch supports at most 100 input entries")
        if file.suffix.lower() != schedule.expression.lower() or file.is_symlink() or not file.is_file():
            continue
        fingerprint = hashlib.sha256(file.name.encode() + read_file(directory, file.name)).hexdigest()
        queue(session, workflow, "file", {"filename": safe_path(directory, file.name).name},
              f"file:{schedule.id}:{fingerprint}")


def tick(sessions, settings):
    stamp = now()
    with sessions.begin() as session:
        expired = session.scalars(select(Approval).where(Approval.decision.is_(None),
                                  Approval.expires <= stamp)).all()
        for approval in expired:
            decide(session, approval, "EXPIRED")
        due = session.scalars(select(Schedule).where(Schedule.enabled.is_(True), Schedule.next_run <= stamp)
                              .order_by(Schedule.next_run).limit(25).with_for_update(skip_locked=True)).all()
        for schedule in due:
            fire = schedule.next_run
            schedule.next_run = next_fire(schedule.kind, schedule.expression, schedule.timezone,
                                         stamp, created=False)
            try:
                workflow = session.get(Workflow, schedule.workflow_id)
                with session.begin_nested():
                    if schedule.kind == "file":
                        scan_files(session, workflow, schedule, settings.root)
                    else:
                        queue(session, workflow, "schedule", {"scheduled_at": fire},
                              f"schedule:{schedule.id}:{fire:.6f}")
                schedule.last_run, schedule.error = stamp, None
            except (ValueError, OSError) as error:
                schedule.error = type(error).__name__ + ": workflow or input configuration requires review"
