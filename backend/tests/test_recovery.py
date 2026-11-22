import asyncio
import os
import time
from contextlib import contextmanager
from dataclasses import replace

from anyio.from_thread import start_blocking_portal
from conftest import API, create, import_template, run, wait
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.contracts import WorkflowInput
from backend.app.db import Base, Execution, connect
from backend.app.executors import process_delivery, reserve_dispatch
from backend.app.main import create_app, create_workflow
from backend.app.nodes import REGISTRY
from backend.app.runtime import Runner, artifact_path, prepare_root, queue
from backend.app.templates import chain

START = ("manual", "Start", {})


def test_interrupted_nonreplayable_side_effect_is_never_repeated(settings, monkeypatch):
    calls = []

    async def external(context, _):
        calls.append(context.run_id)
        await asyncio.Event().wait()

    monkeypatch.setitem(REGISTRY, "http_post", replace(REGISTRY["http_post"], action=external))
    graph = chain(START, ("http_post", "Mock external side effect", {"url": "https://provider.example"}))
    with TestClient(create_app(settings)) as client:
        identifier = run(client, create(client, graph))
        current = wait(client, identifier, {"RUNNING"})
        assert current
        for _ in range(80):
            if calls:
                break
            time.sleep(.04)
        assert calls == [identifier]
    with TestClient(create_app(settings)) as client:
        result = wait(client, identifier)
        assert result["status"] == "FAILED"
        assert "outcome is unknown" in result["error"]
        assert calls == [identifier]
        assert client.post(f"{API}/executions/{identifier}/retry").status_code == 409


def test_reviewer_key_authorizes_approval_without_exposure(client, monkeypatch):
    monkeypatch.setenv("AGENTFORGE_SECRET_REVIEWER", "test-reviewer-only")
    execution = run(client, import_template(client, "approval-routing"))
    paused = wait(client, execution, {"WAITING_APPROVAL"})
    route = API + f"/approvals/{paused['approvals'][0]['id']}/decision"
    assert client.get(API + "/system/capabilities").json()["approval_requires_key"] is True
    assert client.post(route, json={"decision": "APPROVE"}).status_code == 403
    response = client.post(route, json={"decision": "APPROVE"}, headers={"X-AgentForge-Reviewer": "test-reviewer-only"})
    assert response.status_code == 200 and "test-reviewer-only" not in response.text
    assert wait(client, execution)["status"] == "SUCCEEDED"


def test_missing_and_changed_artifact(client):
    graph = chain(START, ("write_json", "Save file", {}))
    execution = run(client, create(client, graph))
    result = wait(client, execution)
    path = artifact_path(client.app.state.runner.settings, execution, "n1")
    route = f"{API}/artifacts/{result['artifacts'][0]['id']}"
    assert client.get(route).status_code == 200
    path.write_bytes(b"modified")
    assert client.get(route).status_code == 409
    path.unlink()
    assert client.get(route).status_code == 404


def test_distributed_delivery_recovers_and_deduplicates_with_local_database(settings):
    prepare_root(settings)
    engine, sessions = connect(settings.root)
    Base.metadata.create_all(engine)
    runner = Runner(sessions, settings)
    with sessions.begin() as session:
        workflow = create_workflow(session, WorkflowInput(
            name="Delivery simulation", definition=chain(START, ("write_json", "Save", {}))))
        execution = queue(session, workflow, "manual", {})
        execution.status = "RUNNING"
        identifier = execution.id
    reserved = reserve_dispatch(runner.sessions, clock=lambda: 100)
    assert reserved == [identifier]
    assert reserve_dispatch(runner.sessions, clock=lambda: 101) == []
    assert reserve_dispatch(runner.sessions, clock=lambda: 121) == [identifier]

    @contextmanager
    def owned(run_id):
        assert run_id == identifier
        yield lambda: None

    @contextmanager
    def busy(run_id):
        assert run_id == identifier
        yield None

    async def deliver():
        assert await process_delivery(runner, busy, identifier) is False
        assert await process_delivery(runner, owned, identifier)
        assert await process_delivery(runner, owned, identifier)

    factory = None
    if os.getenv("AGENTFORGE_TEST_WINLOOP") == "1":
        from winloop import new_event_loop

        factory = new_event_loop
    with start_blocking_portal(backend_options={"loop_factory": factory}) as portal:
        portal.call(deliver)
    from backend.app.db import Artifact
    with sessions() as session:
        assert session.get(Execution, identifier).status == "SUCCEEDED"
        assert len(session.scalars(select(Artifact)).all()) == 1
        assert len(session.scalars(select(Execution)).all()) == 1
    engine.dispose()
