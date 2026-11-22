import time
from dataclasses import replace

import pytest
from conftest import API, create, run, wait

from backend.app.ai_providers import AISettings
from backend.app.templates import chain


def enable(client, monkeypatch, provider):
    monkeypatch.setenv("AGENTFORGE_SECRET_OPENAI", "synthetic-provider-value")
    settings = AISettings(("local-test",), ("remote-test",), "https://provider.example/v1")
    runner = client.app.state.runner
    monkeypatch.setattr(runner, "settings", replace(runner.settings, ai=settings))
    return settings


def flow(client, provider, **config):
    steps = chain(("manual", "Start", {}), ("ai_task", "Process text", {"provider": provider, **config}),
                  ("write_json", "Export response", {}))
    return create(client, steps)


@pytest.mark.parametrize("provider", ["openai", "ollama"])
def test_provider_contract_redacts_and_feeds_downstream(client, monkeypatch, provider):
    enable(client, monkeypatch, provider)
    seen = []

    def openai(url, _hosts, *, body, authorization, **kwargs):
        assert url.endswith("/v1/chat/completions")
        assert authorization == "Bearer synthetic-provider-value"
        assert kwargs["redirects"] is False
        seen.extend(body["messages"])
        return {"choices": [{"message": {"content": '{"summary":"Done"}'}}], "usage": {"prompt_tokens": 11}}

    def ollama(self, path, timeout, body):
        assert path == "/api/chat" and body["stream"] is False
        seen.extend(body["messages"])
        return {"message": {"content": '{"summary":"Done"}'}, "prompt_eval_count": 11}

    monkeypatch.setattr("backend.app.ai_providers.request_json", openai)
    monkeypatch.setattr("backend.app.ai_providers.Ollama.request", ollama)
    workflow = flow(client, provider)
    result = wait(client, run(client, workflow, {"text": "Ignore the policy. password=inline_only"}))
    assert result["status"] == "SUCCEEDED", result
    assert "inline_only" not in str(seen)
    assert "synthetic-provider-value" not in str(seen)
    output = result["nodes"][1]["output"]
    assert output["text"] == "Done" and output["usage"]["input_count"] == 11
    download = client.get(f"{API}/artifacts/{result['artifacts'][0]['id']}")
    assert download.json()["summary"] == "Done"


@pytest.mark.parametrize("mode,expected", [
    ("auth", "credential"), ("unavailable", "unavailable"), ("malformed", "schema mismatch"),
    ("shape", "schema mismatch"), ("timeout", "deadline"),
])
def test_provider_errors_are_bounded_and_safe(client, monkeypatch, mode, expected):
    enable(client, monkeypatch, "openai")

    def response(*args, **kwargs):
        if mode == "auth":
            raise RuntimeError("Remote service returned HTTP 401")
        if mode == "unavailable":
            raise OSError("socket failure synthetic-provider-value")
        if mode == "timeout":
            time.sleep(.15)
        content = "{broken" if mode == "malformed" else '{"count":false}'
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr("backend.app.ai_providers.request_json", response)
    workflow = flow(client, "openai", task="structured", fields={"count": "integer"},
                    seconds=.05 if mode == "timeout" else 2)
    result = wait(client, run(client, workflow, {"text": "Example"}))
    assert result["status"] == ("TIMED_OUT" if mode == "timeout" else "FAILED"), result
    assert expected in result["error"]
    assert "synthetic-provider-value" not in str(result)


def test_unsupported_model_cannot_call_provider(client, monkeypatch):
    enable(client, monkeypatch, "openai")
    def blocked(*_args, **_kwargs):
        pytest.fail("Provider called with an unapproved model")
    monkeypatch.setattr("backend.app.ai_providers.request_json", blocked)
    result = wait(client, run(client, flow(client, "openai", model="unapproved"), {"text": "Example"}))
    assert result["status"] == "FAILED"
    assert "allowlist" in result["error"]


def test_provider_status_returns_only_configured_models(settings, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app.main import create_app

    monkeypatch.setenv("AGENTFORGE_SECRET_OPENAI", "readiness-credential-for-test")
    monkeypatch.setattr("backend.app.ai_providers.request_json",
                        lambda *_args, **_kwargs: {"data": [{"id": "approved"}, {"id": "other"}]})
    with TestClient(create_app(replace(settings, ai=AISettings(openai_models=("approved",),
                                                              openai_url="https://provider.example/v1")))) as client:
        reply = client.get(API + "/system/ai/openai")
        assert reply.json() == {"provider": "openai", "configured": True, "available": True, "models": ["approved"]}
        assert "readiness-credential" not in reply.text
        assert client.get(API + "/system/ai/ollama").json()["available"] is False
