import asyncio
import json
import sqlite3
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event

from conftest import API, create, run, wait
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.app import nodes
from backend.app.db import Approval, Artifact
from backend.app.main import create_app
from backend.app.nodes import REGISTRY
from backend.app.runtime import PROJECT, Runner, decide
from backend.app.templates import chain

START = ("manual", "Load input data", {})
TRANSFORM = ("values", "Transform data", {"values": {"receipt": "{{ nodes.n0.output.receipt }}"}})
WRITE = ("write_json", "Write output record", {"filename": "output-record"})
APPROVAL = ("approval", "Human approval", {"action": "Approve release of the report"})
REPORT = ("report", "Generate final report", {"filename": "final-report"})
FINISH = ("datetime", "Complete workflow", {})
PREFIX = ("n0", "n1", "n2")


def workflow_graph():
    return json.loads((PROJECT / "workflows/fixtures/approval-resumption.json").read_text(encoding="utf-8"))


def instrument(monkeypatch, *kinds):
    calls = Counter()

    def wrap(kind, action):
        async def counted(context, config):
            calls[kind] += 1
            return await action(context, config)

        return counted

    for kind in kinds:
        spec = REGISTRY[kind]
        monkeypatch.setitem(REGISTRY, kind, replace(spec, action=wrap(kind, spec.action)))
    return calls


def steps(snapshot):
    return {step["node_id"]: step for step in snapshot["nodes"]}


def decision_route(snapshot, node_id="n3"):
    approval = next(item for item in snapshot["approvals"] if item["node_id"] == node_id)
    return f"{API}/approvals/{approval['id']}/decision"


def approve(client, snapshot, node_id="n3"):
    return client.post(decision_route(snapshot, node_id), json={"decision": "APPROVE"})


def start_paused(client, graph=None):
    identifier = run(client, create(client, graph or workflow_graph(), "Workflow resumption audit"),
                     {"receipt": "synthetic-001"})
    return identifier, wait(client, identifier, {"WAITING_APPROVAL"})


def artifact_count(client, identifier, node_id):
    with client.app.state.sessions() as session:
        return session.scalar(select(func.count()).select_from(Artifact).where(
            Artifact.execution_id == identifier, Artifact.node_id == node_id
        ))


def test_resume_preserves_completed_actions_and_output(client, settings, monkeypatch, record_property):
    calls = instrument(monkeypatch, "manual", "values", "write_json", "report", "datetime")
    identifier, paused = start_paused(client)
    assert paused["id"] == identifier
    assert {key: step["status"] for key, step in steps(paused).items()} == {
        "n0": "SUCCEEDED", "n1": "SUCCEEDED", "n2": "SUCCEEDED", "n3": "WAITING_APPROVAL",
    }
    assert calls == {"manual": 1, "values": 1, "write_json": 1}
    assert artifact_count(client, identifier, "n2") == 1
    folder = settings.root / "artifacts" / identifier
    assert {file.name for file in folder.iterdir()} == {"n2"}
    original = paused["artifacts"][0]
    assert client.get(f"{API}/artifacts/{original['id']}").json() == {"receipt": "synthetic-001"}
    assert approve(client, paused).status_code == 200
    final = wait(client, identifier)
    assert final["id"] == identifier
    assert final["status"] == "SUCCEEDED"
    assert list(steps(final)) == [f"n{index}" for index in range(6)]
    assert all(step["status"] == "SUCCEEDED" and step["attempts"] == 1 for step in final["nodes"])
    assert all(steps(final)[key] == steps(paused)[key] for key in PREFIX)
    assert calls == {"manual": 1, "values": 1, "write_json": 1, "report": 1, "datetime": 1}
    assert artifact_count(client, identifier, "n2") == 1
    assert artifact_count(client, identifier, "n4") == 1
    assert {file.name for file in folder.iterdir()} == {"n2", "n4"}
    assert (folder / "n4").read_bytes().startswith(b"%PDF")
    assert original in final["artifacts"]
    assert final["approvals"][0]["decision"] == "APPROVE"
    observe(record_property, final)


def observe(record_property, snapshot, external_effects=0):
    record_property("result", snapshot["status"])
    record_property("logical_completions", sum(step["status"] == "SUCCEEDED" for step in snapshot["nodes"]))
    record_property("node_attempts", sum(step["attempts"] for step in snapshot["nodes"]))
    record_property("local_artifacts", len(snapshot["artifacts"]))
    record_property("external_effects", external_effects)


def assert_successful_resume(client, identifier, paused):
    final = wait(client, identifier, {"SUCCEEDED", "FAILED", "REJECTED"})
    assert final["status"] == "SUCCEEDED"
    assert final["id"] == identifier
    assert all(steps(final)[key] == steps(paused)[key] for key in PREFIX)
    assert artifact_count(client, identifier, "n2") == 1
    assert len(final["artifacts"]) == 2
    return final


def test_duplicate_approval_requests_conflict(client, monkeypatch, record_property):
    calls = instrument(monkeypatch, "write_json", "report")
    identifier, paused = start_paused(client)
    assert [approve(client, paused).status_code for _ in range(3)] == [200, 409, 409]
    final = assert_successful_resume(client, identifier, paused)
    assert calls == {"write_json": 1, "report": 1}
    assert len(final["approvals"]) == 1
    observe(record_property, final)


def test_restart_at_approval_reuses_persisted_checkpoints(settings, monkeypatch, record_property):
    calls = instrument(monkeypatch, "write_json", "report")
    with TestClient(create_app(settings)) as client:
        identifier, paused = start_paused(client)
    with TestClient(create_app(settings)) as restarted:
        recovered = wait(restarted, identifier, {"WAITING_APPROVAL"})
        assert recovered == paused
        assert approve(restarted, recovered).status_code == 200
        final = assert_successful_resume(restarted, identifier, paused)
    observe(record_property, final)
    assert calls == {"write_json": 1, "report": 1}


def test_concurrent_decisions_claim_one_transition(client, monkeypatch, record_property):
    calls = instrument(monkeypatch, "write_json", "report")
    identifier, paused = start_paused(client)
    approval_id = paused["approvals"][0]["id"]
    barrier = Barrier(2)

    def submit():
        with client.app.state.sessions.begin() as session:
            approval = session.get(Approval, approval_id)
            assert approval.decision is None
            barrier.wait(timeout=5)
            return decide(session, approval, "APPROVE")

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [pool.submit(submit) for _ in range(2)]
        assert sorted(result.result(timeout=10) for result in outcomes) == [False, True]
    assert approve(client, paused).status_code == 409
    final = assert_successful_resume(client, identifier, paused)
    observe(record_property, final)
    assert calls == {"write_json": 1, "report": 1}


def test_resume_after_failed_downstream_attempts(client, monkeypatch, record_property):
    calls = instrument(monkeypatch, "write_json")
    spec = REGISTRY["report"]
    attempts = []

    async def fail_then_recover(context, config):
        attempts.append(context.run_id)
        if len(attempts) <= 2:
            raise RuntimeError("Synthetic transient report failure")
        return await spec.action(context, config)

    monkeypatch.setitem(REGISTRY, "report", replace(spec, action=fail_then_recover))
    graph = workflow_graph()
    graph["nodes"][4]["retries"] = 1
    identifier, paused = start_paused(client, graph)
    route = f"{API}/executions/{identifier}/resume"
    assert approve(client, paused).status_code == 200
    failed = wait(client, identifier)
    assert failed["status"] == "FAILED" and steps(failed)["n4"]["attempts"] == 2
    assert failed["approvals"][0]["decision"] == "APPROVE"
    assert len(failed["artifacts"]) == 1
    assert failed["can_resume"]
    response = client.post(route)
    assert response.status_code == 202, response.text
    assert response.json()["id"] == identifier
    assert client.post(route).status_code == 409
    final = assert_successful_resume(client, identifier, paused)
    assert steps(final)["n4"]["attempts"] == 3
    assert attempts == [identifier] * 3 and calls == {"write_json": 1}
    observe(record_property, final)


def test_two_approval_checkpoints_keep_each_completed_segment(client, monkeypatch, record_property):
    calls = instrument(monkeypatch, "write_json", "report")
    graph = chain(START, TRANSFORM, WRITE, APPROVAL, REPORT, APPROVAL, FINISH)
    graph["edges"][3]["port"] = graph["edges"][5]["port"] = "approve"
    identifier, paused = start_paused(client, graph)
    assert approve(client, paused).status_code == 200
    second = wait_for_checkpoint(client, identifier, "n5", "WAITING_APPROVAL")
    assert second["id"] == identifier
    assert len(second["approvals"]) == 2
    assert artifact_count(client, identifier, "n2") == artifact_count(client, identifier, "n4") == 1
    assert "n6" not in steps(second)
    assert approve(client, paused).status_code == 409
    assert approve(client, second, "n5").status_code == 200
    final = assert_successful_resume(client, identifier, paused)
    assert steps(final)["n4"] == steps(second)["n4"]
    assert all(item["decision"] == "APPROVE" for item in final["approvals"])
    observe(record_property, final)
    assert calls == {"write_json": 1, "report": 1}


def wait_for_checkpoint(client, identifier, node, status):
    deadline = time.monotonic() + 10
    while True:
        snapshot = client.get(f"{API}/executions/{identifier}").json()
        if steps(snapshot).get(node, {}).get("status") == status:
            return snapshot
        assert time.monotonic() < deadline, snapshot
        time.sleep(0.045)


def test_unrouted_rejection_is_terminal_and_skips_downstream(client, monkeypatch, record_property):
    calls = instrument(monkeypatch, "write_json", "report", "datetime")
    identifier, paused = start_paused(client)
    response = client.post(decision_route(paused), json={"decision": "REJECT"})
    assert response.status_code == 200
    final = wait(client, identifier, {"SUCCEEDED", "FAILED", "REJECTED"})
    assert final["status"] == "REJECTED"
    assert final["approvals"][0]["decision"] == "REJECT"
    assert steps(final)["n3"]["port"] == "reject"
    assert {steps(final)[node]["status"] for node in ("n4", "n5")} == {"SKIPPED"}
    assert all(steps(final)[key] == steps(paused)[key] for key in PREFIX)
    assert len(final["artifacts"]) == 1
    assert calls == {"write_json": 1}
    observe(record_property, final)


def external_graph():
    graph = chain(START, TRANSFORM, WRITE, APPROVAL,
                  ("http_post", "Deliver to the synthetic receiver", {
                      "url": "https://receiver.example/delivery",
                      "body": {"receipt": "{{ nodes.n1.output.receipt }}"},
                  }), REPORT)
    graph["edges"][3]["port"] = "approve"
    return graph


class LocalReceiver:
    def __init__(self, root):
        self.folder = root / "test-deliveries"
        self.folder.mkdir()
        self.database = self.folder / "ledger.sqlite"
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE deliveries (kind TEXT, receipt TEXT)")

    def receive(self, url, _allowed, *, body, authorization):
        assert url == "https://receiver.example/delivery"
        assert authorization is None
        assert body == {"receipt": "synthetic-001"}
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.executemany(
                "INSERT INTO deliveries VALUES (?, ?)",
                [(kind, body["receipt"]) for kind in ("email", "database", "webhook")],
            )
        with (self.folder / "receiver-output.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(body) + "\n")
        return {"delivered": True}

    def counts(self):
        with closing(sqlite3.connect(self.database)) as connection:
            result = Counter(dict(connection.execute("SELECT kind, COUNT(*) FROM deliveries GROUP BY kind")))
        file = self.folder / "receiver-output.jsonl"
        if file.exists():
            result["file"] = len(file.read_text(encoding="utf-8").splitlines())
        return result


ONE_DELIVERY = {"email": 1, "database": 1, "webhook": 1, "file": 1}


def test_external_delivery_is_not_repeated_when_later_report_retries(settings, monkeypatch, record_property):
    receiver = LocalReceiver(settings.root)
    monkeypatch.setattr(nodes, "request_json", receiver.receive)
    spec = REGISTRY["report"]
    attempts = []

    async def intermittent(context, config):
        attempts.append(context.run_id)
        if len(attempts) == 1:
            raise RuntimeError("Synthetic transient report failure")
        return await spec.action(context, config)

    monkeypatch.setitem(REGISTRY, "report", replace(spec, action=intermittent))
    graph = external_graph()
    graph["nodes"][5]["retries"] = 1
    with TestClient(create_app(replace(settings, external_post=True))) as client:
        identifier, paused = start_paused(client, graph)
        assert not receiver.counts()
        assert approve(client, paused).status_code == 200
        assert approve(client, paused).status_code == 409
        final = assert_successful_resume(client, identifier, paused)
        assert steps(final)["n4"]["attempts"] == 1
        assert steps(final)["n5"]["attempts"] == 2
        assert attempts == [identifier, identifier]
    assert receiver.counts() == ONE_DELIVERY
    observe(record_property, final, sum(receiver.counts().values()))


def test_crash_after_external_delivery_requires_reconciliation(settings, monkeypatch, record_property):
    receiver = LocalReceiver(settings.root)
    monkeypatch.setattr(nodes, "request_json", receiver.receive)
    original = Runner.persist_result
    reached_gap = Event()

    def crash_before_checkpoint(self, execution, node, result):
        if node.type == "http_post":
            reached_gap.set()
            raise asyncio.CancelledError()
        return original(self, execution, node, result)

    monkeypatch.setattr(Runner, "persist_result", crash_before_checkpoint)
    settings = replace(settings, external_post=True)
    with TestClient(create_app(settings)) as client:
        identifier, paused = start_paused(client, external_graph())
        assert approve(client, paused).status_code == 200
        assert reached_gap.wait(timeout=10)
        interrupted = wait_for_checkpoint(client, identifier, "n4", "RUNNING")
        assert "n5" not in steps(interrupted)
        assert receiver.counts() == ONE_DELIVERY
    with TestClient(create_app(settings)) as restarted:
        failed = wait(restarted, identifier)
        assert failed["status"] == "FAILED"
        assert steps(failed)["n4"]["attempts"] == 1
        assert "outcome is unknown" in failed["error"]
        assert "n5" not in steps(failed)
        assert all(steps(failed)[key] == steps(paused)[key] for key in PREFIX)
        assert len(failed["artifacts"]) == 1
        assert restarted.post(f"{API}/executions/{identifier}/retry").status_code == 409
        assert restarted.post(f"{API}/executions/{identifier}/resume").status_code == 409
        assert not failed["can_resume"]
    assert receiver.counts() == ONE_DELIVERY
    observe(record_property, failed, sum(receiver.counts().values()))


def test_recovered_file_write_records_both_attempts_without_duplicate_artifacts(settings, monkeypatch, record_property):
    replace_file = Path.replace
    interrupted = Event()

    def crash_after_replace(path, target):
        result = replace_file(path, target)
        if target.name == "n4" and not interrupted.is_set():
            interrupted.set()
            raise asyncio.CancelledError()
        return result

    monkeypatch.setattr(Path, "replace", crash_after_replace)
    with TestClient(create_app(settings)) as client:
        identifier, paused = start_paused(client)
        assert approve(client, paused).status_code == 200
        assert interrupted.wait(timeout=10)
        assert artifact_count(client, identifier, "n4") == 0
    with TestClient(create_app(settings)) as restarted:
        final = assert_successful_resume(restarted, identifier, paused)
        assert steps(final)["n4"]["attempts"] == 2
        assert artifact_count(restarted, identifier, "n4") == 1
    assert {path.name for path in (settings.root / "artifacts" / identifier).iterdir()} == {"n2", "n4"}

    observe(record_property, final)
