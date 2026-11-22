import hashlib
import hmac
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import API, create, import_template, run, wait
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from backend.app import nodes
from backend.app.db import Execution
from backend.app.main import create_app
from backend.app.templates import chain

MANUAL = ("manual", "Start", {})


def test_migration_health_and_catalog(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    assert client.get("/openapi.json").json()["info"]["title"] == "AgentForge"
    assert client.get("/health").headers["x-request-id"]
    catalog = client.get(API + "/nodes").json()
    assert {node["type"] for node in catalog} == set(nodes.REGISTRY)
    with client.app.state.sessions() as session:
        assert session.scalar(text("SELECT version_num FROM alembic_version")) == "0002"


@pytest.mark.parametrize("key,extension", [
    ("api-to-csv", ".csv"), ("csv-cleanup", ".csv"), ("lead-excel", ".xlsx"),
    ("ai-document", ".pdf"),
])
def test_local_templates(client, key, extension):
    workflow = import_template(client, key)
    details = wait(client, run(client, workflow))
    assert details["status"] == "SUCCEEDED", details
    assert details["revision"] == 1
    artifact = details["artifacts"][0]
    response = client.get(f"{API}/artifacts/{artifact['id']}")
    assert response.status_code == 200
    assert artifact["filename"].endswith(extension)
    assert hashlib.sha256(response.content).hexdigest() == artifact["sha256"]
    if extension == ".pdf":
        assert response.content.startswith(b"%PDF")
    if extension == ".xlsx":
        assert response.content.startswith(b"PK")


def test_immutable_versions_optimistic_saves_and_references(client):
    graph = chain(MANUAL, ("values", "Create value", {"values": {"score": 42}}),
                  ("values", "Map value", {"values": {"rating": "{{ nodes.n1.output.score }}"}}))
    flow = create(client, graph)
    initial_run = run(client, flow)
    graph["nodes"][1]["config"]["values"]["score"] = 100
    update = {"name": "New name", "definition": graph, "revision": 1}
    url = f"{API}/workflows/{flow['id']}"
    assert client.put(url, json=update).json()["revision"] == 2
    assert client.put(url, json=update).status_code == 409
    new_run = run(client, flow)
    original, modified = (wait(client, key) for key in [initial_run, new_run])
    assert original["nodes"][-1]["output"] == {"rating": 42}
    assert modified["nodes"][-1]["output"] == {"rating": 100}
    assert client.get(url + "/versions").json()["total"] == 2
    duplicate = client.post(url + "/duplicate").json()
    assert duplicate["definition"] == modified["definition"]
    assert duplicate["id"] != flow["id"]


@pytest.mark.parametrize("decision,output", [
    ("APPROVE", "approved.json"), ("REJECT", "review.json"), ("REQUEST_CHANGES", "review.json")])
def test_approval_branch_and_restart(settings, decision, output):
    with TestClient(create_app(settings)) as client:
        workflow = import_template(client, "approval-routing")
        identifier = run(client, workflow)
        first = wait(client, identifier, {"WAITING_APPROVAL"})
        last_approval = first["approvals"][0]
        trigger_start = first["nodes"][0]["started"]
    with TestClient(create_app(settings)) as client:
        path = f"{API}/approvals/{last_approval['id']}/decision"
        assert client.post(path, json={"decision": decision}).status_code == 200
        assert client.post(path, json={"decision": decision}).status_code == 409
        final = wait(client, identifier)
        assert final["status"] == "SUCCEEDED", final
        assert final["nodes"][0]["started"] == trigger_start
        assert [item["filename"] for item in final["artifacts"]] == [output]
        assert sum(step["status"] == "SKIPPED" for step in final["nodes"]) == 2


def test_interrupted_worker_resumes_committed_checkpoint(settings):
    graph = chain(MANUAL, ("delay", "Wait", {"seconds": 1}), ("values", "Finish", {}))
    with TestClient(create_app(settings)) as client:
        identifier = run(client, create(client, graph))
        first = wait(client, identifier, {"RUNNING"})
        checkpoint = first["nodes"][0]["started"]
    with TestClient(create_app(settings)) as client:
        final = wait(client, identifier)
        assert final["status"] == "SUCCEEDED", final
        assert final["nodes"][0]["started"] == checkpoint
        assert final["nodes"][-1]["node_id"] == "n2"


def test_retry_attempts_and_failed_state(client, monkeypatch):
    original = nodes.REGISTRY["values"]
    calls = 0

    async def intermittent(context, config):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("Synthetic transient failure")
        return await original.action(context, config)

    monkeypatch.setitem(nodes.REGISTRY, "values", replace(original, action=intermittent))
    graph = chain(MANUAL, ("values", "Retry test", {"values": {"processed": True}}))
    graph["nodes"][1]["retries"] = 2
    result = wait(client, run(client, create(client, graph)))
    assert result["status"] == "SUCCEEDED", result
    assert calls == result["nodes"][-1]["attempts"] == 3


def test_cancellation_and_timeout(client):
    graph = chain(MANUAL, ("delay", "Pause", {"seconds": 2}))
    identifier = run(client, create(client, graph))
    wait(client, identifier, {"RUNNING"})
    assert client.post(f"{API}/executions/{identifier}/cancel").json()["status"] == "CANCELLED"
    graph["nodes"][1]["timeout"] = .05
    result = wait(client, run(client, create(client, graph)))
    assert result["status"] == result["nodes"][-1]["status"] == "TIMED_OUT"


def test_schedule_and_disable(client):
    flow = import_template(client, "daily-report")
    response = client.post(API + "/schedules", json={
        "workflow_id": flow["id"], "kind": "interval", "expression": "5", "timezone": "UTC"})
    assert response.status_code == 201, response.text
    schedule = response.json()
    cutoff = time.monotonic() + 8
    while True:
        runs = client.get(API + "/executions").json()["items"]
        if runs:
            break
        assert time.monotonic() < cutoff
        time.sleep(.15)
    details = wait(client, runs[0]["id"])
    assert details["status"] == "SUCCEEDED", details
    assert details["source"] == "schedule"
    assert client.patch(f"{API}/schedules/{schedule['id']}", json={"enabled": False}).json()["enabled"] is False


def test_webhook_signatures_redaction_and_idempotency(client, monkeypatch):
    secret = "synthetic signing credential for tests"
    monkeypatch.setenv("AGENTFORGE_SECRET_TEST", secret)
    flow = create(client, chain(("webhook", "Receive", {}), ("write_json", "Save", {})))
    reference = {"name": "hook", "kind": "webhook", "env_var": "AGENTFORGE_SECRET_TEST"}
    assert client.post(API + "/credentials", json=reference).status_code == 201
    assert secret not in client.get(API + "/credentials").text
    response = client.post(API + "/webhooks", json={"workflow_id": flow["id"], "credential": "hook"})
    assert response.status_code == 201, response.text
    path = f"{API}/hooks/{response.json()['id']}"
    data = json.dumps({"event_id": "order-12", "payload": {"name": "Demo", "token": secret}}).encode()
    assert client.post(path, content=data).status_code == 401
    timestamp = str(int(time.time()))
    signature = hmac.digest(secret.encode(), timestamp.encode() + b"." + data, "sha256").hex()
    headers = {"X-AgentForge-Signature": signature, "X-AgentForge-Timestamp": timestamp}
    key = client.post(path, headers=headers, content=data).json()["id"]
    assert client.post(path, headers=headers, content=data).json()["id"] == key
    final = wait(client, key)
    assert final["status"] == "SUCCEEDED", final
    assert final["nodes"][0]["output"]["token"] == "[redacted]"
    assert secret not in client.get(f"{API}/executions/{key}").text
    with client.app.state.sessions() as session:
        assert len(session.scalars(select(Execution)).all()) == 1


def test_browser_fixture_when_installed(client, monkeypatch):
    channel = "chrome" if Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists() else ""
    from playwright.sync_api import sync_playwright

    if not channel:
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).exists():
                pytest.skip("Playwright Chromium or desktop Edge is required")
    runner = client.app.state.runner
    monkeypatch.setattr(runner, "settings", replace(runner.settings, browser=channel))
    workflow = import_template(client, "website-extraction")
    result = wait(client, run(client, workflow), timeout=60)
    assert result["status"] == "SUCCEEDED", result
    assert result["nodes"][1]["output"]["count"] == 3
    graph = chain(MANUAL, ("browser_capture", "Capture table", {}))
    captured = wait(client, run(client, create(client, graph)), timeout=60)
    assert captured["status"] == "SUCCEEDED", captured
    assert captured["artifacts"][0]["media_type"] == "image/png"


def test_approved_browser_pagination_exports_structured_records(client, monkeypatch):
    channel = "chrome" if Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists() else ""
    from playwright.sync_api import sync_playwright

    if not channel:
        with sync_playwright() as playwright:
            if not Path(playwright.chromium.executable_path).exists():
                pytest.skip("Playwright Chromium or desktop Chrome is required")
    runner = client.app.state.runner
    monkeypatch.setattr(runner, "settings", replace(runner.settings, browser=channel,
                                                   browser_hosts=frozenset({"fixture.example"})))
    fetched = []

    def document(url, allowed, **kwargs):
        assert allowed == {"fixture.example"} and kwargs["limit"] == 512 * 1024
        fetched.append(url)
        assert url in ("https://fixture.example/first", "https://fixture.example/second")
        value = "first" if url.endswith("/first") else "second"
        html = (f"<html><title>Fixture</title><article><h2>{value}</h2></article>"
                '<img src="file:///private/example"><script>throw new Error("disabled")</script>'
                '<a rel="next" href="/second">Next</a></html>')
        return html.encode(), "text/html", url

    monkeypatch.setattr("backend.app.browser_nodes.request_bytes", document)
    graph = chain(
        MANUAL,
        ("browser_open", "Open page", {"url": "https://fixture.example/first"}),
        ("browser_elements", "Extract", {"selector": "article", "fields": {"name": "h2"}, "pages": 4, "max_records": 2}),
        ("write_csv", "Export records", {}),
    )
    result = wait(client, run(client, create(client, graph)), timeout=100)
    assert result["status"] == "SUCCEEDED", result
    assert result["nodes"][1]["output"]["title"] == "Fixture"
    assert result["nodes"][2]["output"]["records"] == [{"name": "first"}, {"name": "second"}]
    assert fetched == ["https://fixture.example/first", "https://fixture.example/first", "https://fixture.example/second"]
    assert client.get(f"{API}/artifacts/{result['artifacts'][0]['id']}").content.endswith(b"first\r\nsecond\r\n")
