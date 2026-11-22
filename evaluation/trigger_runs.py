import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.runtime import PROJECT, Settings
from evaluation.benchmark import json_file
from evaluation.scenarios import API, poll


def wait_sources(client, *sources):
    due = time.monotonic() + 20
    pending = set(sources)
    completed = {}
    while pending and time.monotonic() < due:
        runs = client.get(API + "/executions").json()["items"]
        for item in runs:
            if item["source"] in pending:
                result = poll(client, item["id"])
                completed[item["source"]] = {name: result[name] for name in ("status", "source", "error")}
                pending.remove(item["source"])
        if pending:
            time.sleep(.1)
    for source in pending:
        completed[source] = {"status": "NO_EXECUTION"}
    return completed


def check(client):
    work = {}
    for key in ("daily-report", "data-quality"):
        response = client.post(f"{API}/templates/{key}/import")
        response.raise_for_status()
        work[key] = response.json()["id"]
    due = (datetime.now(UTC) + timedelta(seconds=3)).isoformat()
    once = client.post(API + "/schedules", json={
        "workflow_id": work["daily-report"], "kind": "once", "expression": due, "timezone": "UTC"})
    once.raise_for_status()
    watch = client.post(API + "/schedules", json={
        "workflow_id": work["data-quality"], "kind": "file", "expression": ".csv", "timezone": "UTC"})
    watch.raise_for_status()
    target = client.app.state.runner.settings.root / "input" / "trigger-fixture.csv"
    target.write_bytes((PROJECT / "workflows/fixtures/orders.csv").read_bytes())
    evidence = wait_sources(client, "schedule", "file")
    disabled = client.patch(f"{API}/schedules/{watch.json()['id']}", json={"enabled": False})
    disabled.raise_for_status()
    evidence["file_disabled"] = disabled.json()["enabled"] is False
    return evidence


def main():
    runtime = PROJECT / ".runtime"
    runtime.mkdir(exist_ok=True)
    directory = PROJECT / "evaluation" / "results"
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=runtime, prefix="trigger-evaluation-") as temp:
        with TestClient(create_app(Settings(Path(temp)))) as client:
            results = check(client)
            json_file(directory, "trigger_results.json", results)
            print(results, flush=True)


if __name__ == "__main__":
    main()
