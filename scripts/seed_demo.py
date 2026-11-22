import argparse
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.contracts import WorkflowInput
from backend.app.db import Execution, Workflow
from backend.app.main import create_app, create_workflow
from backend.app.runtime import PROJECT, Settings, queue
from backend.app.templates import TEMPLATES, template

API = "/api/v1"
SAMPLES = {
    "api-to-csv": "samples/orders.csv",
    "lead-excel": "samples/sales-leads.xlsx",
    "daily-report": "sample-agentforge-report.pdf",
}


def wait_for(client, run_id):
    limit = time.monotonic() + 80
    while time.monotonic() < limit:
        details = client.get(f"{API}/executions/{run_id}").json()
        if details["status"] not in {"QUEUED", "RUNNING"}:
            return details
        time.sleep(.1)
    raise TimeoutError(f"Demo run {run_id} did not settle in 80 seconds")


def seed(client, key, suffix="", decision=None):
    info = template(key)
    trigger = info["definition"]["nodes"][0]["type"]
    source = "file" if trigger == "file_trigger" else trigger
    payload = {"fixture": key}
    if source == "file":
        settings = client.app.state.runner.settings
        demo_path = settings.root / "input" / "agentforge-demo-orders.csv"
        if not demo_path.exists():
            with demo_path.open("xb") as target:
                target.write((settings.fixtures / "orders.csv").read_bytes())
        payload["filename"] = demo_path.name
    with client.app.state.sessions.begin() as session:
        seeded = session.scalar(select(Execution).where(Execution.key == f"demo:{key}:").limit(1))
        existing = session.get(Workflow, seeded.workflow_id) if seeded else None
        workflow = existing or create_workflow(session, WorkflowInput(
            name=info["name"], description=info["description"], definition=info["definition"]))
        execution = queue(session, workflow, source, payload, key=f"demo:{key}:{suffix}")
        identifier = execution.id
    details = wait_for(client, identifier)
    if decision and details["status"] == "WAITING_APPROVAL":
        pending = details["approvals"][0]
        response = client.post(f"{API}/approvals/{pending['id']}/decision", json={"decision": decision})
        response.raise_for_status()
        details = wait_for(client, identifier)
    return details


def generate(settings, assets=False, include_browser=True):
    summary = {}
    with TestClient(create_app(settings)) as client:
        for key in TEMPLATES:
            if key == "website-extraction" and not include_browser:
                summary[key] = {"status": "SKIPPED", "reason": "Browser skipped by request"}
                continue
            decision = "APPROVE" if key == "approval-routing" else None
            details = seed(client, key, decision=decision)
            summary[key] = {name: details[name] for name in ("id", "status", "error", "artifacts")}
            if assets and details["status"] == "SUCCEEDED" and key in SAMPLES:
                entry = details["artifacts"][0]
                response = client.get(f"{API}/artifacts/{entry['id']}")
                response.raise_for_status()
                path = PROJECT / "docs" / SAMPLES[key]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(response.content)
        pending = seed(client, "approval-routing", suffix="review-inbox")
        summary["pending-approval"] = {name: pending[name] for name in ("id", "status", "error")}
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run deterministic AgentForge examples against a local database")
    parser.add_argument("--portfolio-assets", action="store_true", help="Copy generated samples into docs")
    parser.add_argument("--skip-browser", action="store_true", help="Skip the browser fixture")
    args = parser.parse_args()
    settings = Settings.from_env()
    results = generate(settings, args.portfolio_assets, not args.skip_browser)
    output = Path(settings.root) / "demo-results.json"
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: row["status"] for name, row in results.items()}, indent=2))
    if any(result["status"] in {"FAILED", "TIMED_OUT", "CANCELLED"} for result in results.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
