import os
import time

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.runtime import Settings

API = "/api/v1"


def pytest_configure():
    if os.getenv("AGENTFORGE_TEST_WINLOOP") == "1":
        import winloop

        winloop.install()


@pytest.fixture
def settings(tmp_path):
    return Settings(root=tmp_path)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as connection:
        yield connection


def import_template(client, key):
    response = client.post(f"{API}/templates/{key}/import")
    assert response.status_code == 201, response.text
    return response.json()


def create(client, graph, name="Test workflow"):
    response = client.post(f"{API}/workflows", json={"name": name, "definition": graph})
    assert response.status_code == 201, response.text
    return response.json()


def run(client, workflow, payload=None):
    response = client.post(f"{API}/workflows/{workflow['id']}/run", json={"payload": payload or {}})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def wait(client, identifier, desired=None, timeout=10):
    desired = desired or {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "REJECTED"}
    deadline = time.monotonic() + timeout
    while True:
        data = client.get(f"{API}/executions/{identifier}").json()
        if data["status"] in desired:
            return data
        assert time.monotonic() < deadline, data
        time.sleep(.045)
