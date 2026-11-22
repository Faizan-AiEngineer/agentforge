import socket

import pytest
from conftest import API, create, run, wait

from backend.app.security import MAX_BODY, request_json, resolve_target, safe_path
from backend.app.templates import chain


@pytest.mark.parametrize("url", [
    "file:///etc/hosts", "http://example.org", "https://localhost/",
    "https://169.254.169.254/", "https://username@example.org", "https://example.org:444/",
])
def test_destinations_fail_before_network(url):
    with pytest.raises(ValueError):
        resolve_target(url, {"example.org"})


def test_private_dns_resolution_rejected(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="public IP"):
        resolve_target("https://example.org/", {"example.org"})


def test_https_redirect_cannot_reach_a_private_resolution(monkeypatch):
    connected = []

    class Redirect:
        status = 302

        @staticmethod
        def getheader(_):
            return "https://approved-target.example/"

    class Transport:
        def __init__(self, host, address, timeout):
            connected.append((host, address))

        def request(self, *_args, **_kwargs):
            pass

        def getresponse(self):
            return Redirect()

        def close(self):
            pass

    def dns(host, *_args, **_kwargs):
        address = "93.184.216.34" if host == "approved-start.example" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]

    monkeypatch.setattr(socket, "getaddrinfo", dns)
    monkeypatch.setattr("backend.app.security.PinnedHTTPS", Transport)
    with pytest.raises(ValueError, match="public IP"):
        request_json("https://approved-start.example/", {"approved-start.example", "approved-target.example"})
    assert connected == [("approved-start.example", "93.184.216.34")]


@pytest.mark.parametrize("path", ["../orders.csv", "..\\orders.csv", "C:/private.txt", "/etc/passwd", "x:y"])
def test_restricted_file_paths(tmp_path, path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, path)


def test_request_boundary(client):
    assert client.get("/health", headers={"Host": "untrusted.example"}).status_code == 403
    assert client.get("/health", headers={"Origin": "https://untrusted.example"}).status_code == 403
    assert client.post(API + "/validate", content=b"x" * (MAX_BODY + 1)).status_code == 413


def test_invalid_workflows(client):
    graph = chain(("manual", "Start", {}), ("delay", "Waiting", {"seconds": 500}))
    graph["nodes"].append({"id": "orphan", "type": "shell", "label": "Unknown"})
    graph["edges"] += [{"source": "n1", "target": "n0", "port": "other"},
                       {"source": "n1", "target": "ghost"}]
    outcome = client.post(API + "/validate", json=graph).json()
    assert not outcome["valid"]
    errors = " ".join(outcome["errors"])
    for phrase in ("cycle", "Unsupported", "disconnected", "Unknown port", "missing endpoint", "configuration"):
        assert phrase in errors
    saved = create(client, graph)
    assert client.post(f"{API}/workflows/{saved['id']}/run", json={}).status_code == 422


def test_no_network_post_without_approval(client, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Outbound call should never execute")

    monkeypatch.setattr("backend.app.nodes.request_json", forbidden)
    graph = chain(("manual", "Start", {}), ("http_post", "Send", {"url": "https://example.org"}))
    flow = create(client, graph)
    result = wait(client, run(client, flow))
    assert result["status"] == "FAILED"
    assert "approval" in result["error"].lower()
