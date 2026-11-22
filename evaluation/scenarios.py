import argparse
import hashlib
import hmac
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.nodes import REGISTRY
from backend.app.runtime import PROJECT, Settings
from backend.app.security import MAX_BODY, resolve_target, safe_path
from backend.app.templates import chain
from evaluation.benchmark import json_file, new_capture

API = "/api/v1"
START = ("manual", "Start", {})


def poll(client, identifier, statuses=None, timeout=25):
    statuses = statuses or {"SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELLED", "WAITING_APPROVAL"}
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        response = client.get(f"{API}/executions/{identifier}")
        response.raise_for_status()
        result = response.json()
        if result["status"] in statuses:
            return result
        time.sleep(.04)
    raise TimeoutError(f"Execution {identifier} did not settle")


def draft(client, graph):
    response = client.post(API + "/workflows", json={"name": "Evaluation workflow", "definition": graph})
    response.raise_for_status()
    return response.json()


def enqueue(client, workflow, key=None):
    headers = {"Idempotency-Key": key} if key else None
    response = client.post(f"{API}/workflows/{workflow['id']}/run", json={}, headers=headers)
    response.raise_for_status()
    return response.json()["id"]


def reliability(settings):
    output = {}
    with TestClient(create_app(settings)) as client:
        spec = REGISTRY["values"]
        count = 0

        async def inject(context, config):
            nonlocal count
            count += 1
            if count < 3:
                raise RuntimeError("Synthetic transient condition")
            return await spec.action(context, config)

        graph = chain(START, ("values", "Retry operation", {"values": {"completed": True}}),
                      ("write_json", "Persist output", {}))
        graph["nodes"][1]["retries"] = 2
        with patch.dict(REGISTRY, {"values": replace(spec, action=inject)}):
            workflow = draft(client, graph)
            beginning = time.perf_counter()
            key = enqueue(client, workflow, "synthetic-retry-v1")
            duplicate = enqueue(client, workflow, "synthetic-retry-v1")
            result = poll(client, key)
            output["retry"] = {
                "status": result["status"], "attempts": count, "artifacts": len(result["artifacts"]),
                "duplicate_submission_reused_run": key == duplicate,
                "elapsed_ms": round(1000 * (time.perf_counter() - beginning), 3),
                "passed": result["status"] == "SUCCEEDED" and count == 3 and key == duplicate
                and len(result["artifacts"]) == 1,
            }
        bad = chain(START, ("filter", "Needs records", {"rules": [{"op": "truthy"}]}),
                    ("write_csv", "Never persists", {}))
        result = poll(client, enqueue(client, draft(client, bad)))
        output["failure_propagation"] = {"status": result["status"], "artifacts": len(result["artifacts"]),
                                         "passed": result["status"] == "FAILED" and not result["artifacts"]}
        pause = chain(START, ("delay", "Running gate", {"seconds": 2}))
        identifier = enqueue(client, draft(client, pause))
        poll(client, identifier, {"RUNNING"})
        response = client.post(f"{API}/executions/{identifier}/cancel")
        output["cancellation"] = {
            "status": response.json()["status"], "passed": response.json()["status"] == "CANCELLED",
        }
        identifier = enqueue(client, draft(client, pause))
        initial = poll(client, identifier, {"RUNNING"})
        checkpoint = initial["nodes"][0]["started"]
    beginning = time.perf_counter()
    with TestClient(create_app(settings)) as client:
        result = poll(client, identifier)
        restored = result["nodes"][0]["started"] == checkpoint
        output["restart"] = {"preserved_checkpoint": restored, "status": result["status"],
                              "elapsed_ms": round(1000 * (time.perf_counter() - beginning), 3),
                              "passed": restored and result["status"] == "SUCCEEDED"}
    return output


def approvals(settings):
    cases = {}
    with TestClient(create_app(settings)) as client:
        response = client.post(API + "/templates/approval-routing/import")
        response.raise_for_status()
        workflow = response.json()
        outcomes = {}
        for decision in ("APPROVE", "REJECT", "REQUEST_CHANGES"):
            outcomes[decision] = poll(client, enqueue(client, workflow), {"WAITING_APPROVAL"})
    with TestClient(create_app(settings)) as client:
        for decision, item in outcomes.items():
            approval = item["approvals"][0]
            path = f"{API}/approvals/{approval['id']}/decision"
            stamp = time.perf_counter()
            response = client.post(path, json={"decision": decision})
            response.raise_for_status()
            dupe = client.post(path, json={"decision": decision})
            final = poll(client, item["id"])
            artifact = final["artifacts"][0]["filename"] if final["artifacts"] else None
            expected = "approved.json" if decision == "APPROVE" else "review.json"
            cases[decision] = {
                "status": final["status"], "duplicate_status": dupe.status_code,
                "artifact": artifact, "resume_ms": round(1000 * (time.perf_counter() - stamp), 3),
                "passed": final["status"] == "SUCCEEDED" and artifact == expected and dupe.status_code == 409,
            }
    return cases


def requires_error(action):
    try:
        action()
    except ValueError:
        return True
    return False


def security(settings):
    evidence = {
        "allowlist": requires_error(lambda: resolve_target("https://nonlisted.example/", {"approved.example"})),
        "private_ipv4": requires_error(lambda: resolve_target("https://127.0.0.1/", {"127.0.0.1"})),
        "file_traversal": requires_error(lambda: safe_path(settings.root, "../private.txt")),
        "windows_device": requires_error(lambda: safe_path(settings.root, "NUL.txt")),
    }
    with TestClient(create_app(settings)) as client:
        evidence["foreign_origin"] = client.get("/health", headers={"Origin": "https://untrusted.example"}
                                                ).status_code == 403
        evidence["large_payload"] = client.post(API + "/validate", content=b"x" * (MAX_BODY + 1)
                                                ).status_code == 413
        evidence["invalid_graph"] = not client.post(API + "/validate", json=chain(
            START, ("unsupported", "Unknown", {}))).json()["valid"]
        key = "local synthetic fixture used to evaluate HMAC"
        with patch.dict("os.environ", {"AGENTFORGE_SECRET_EVAL": key}):
            credential = client.post(API + "/credentials", json={
                "kind": "webhook", "name": "evaluation-hook", "env_var": "AGENTFORGE_SECRET_EVAL"})
            credential.raise_for_status()
            workflow = draft(client, chain(("webhook", "Signed trigger", {}), ("write_json", "Export", {})))
            hook = client.post(API + "/webhooks", json={
                "workflow_id": workflow["id"], "credential": "evaluation-hook"})
            hook.raise_for_status()
            path = API + "/hooks/" + hook.json()["id"]
            body = json.dumps({"event_id": "evaluation-1", "payload": {"secret": key}}).encode()
            stamp = str(int(time.time()))
            headers = {"X-AgentForge-Timestamp": stamp, "X-AgentForge-Signature": "0" * 64}
            evidence["invalid_signature"] = client.post(path, content=body, headers=headers).status_code == 401
            headers["X-AgentForge-Signature"] = hmac.digest(key.encode(), stamp.encode() + b"." + body,
                                                           hashlib.sha256).hex()
            valid = client.post(path, content=body, headers=headers)
            valid.raise_for_status()
            evidence["redacted_payload"] = key not in json.dumps(poll(client, valid.json()["id"]))
    return evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    directory = new_capture("scenarios", parser.parse_args().output)
    root = PROJECT / ".runtime"
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix="scenarios-") as temp:
        for name, evaluate in (("reliability", reliability), ("approval", approvals), ("security", security)):
            results = evaluate(Settings(Path(temp) / name))
            json_file(directory, name + "_results.json", results)
            print(name, results, flush=True)


if __name__ == "__main__":
    main()
