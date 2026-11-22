import argparse
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.runtime import PROJECT, Settings
from backend.app.templates import chain
from evaluation.benchmark import json_file
from evaluation.scenarios import API, START, draft, enqueue, poll


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="chrome")
    args = parser.parse_args()
    runtime = PROJECT / ".runtime"
    runtime.mkdir(exist_ok=True)
    cases = {
        "browser_table": ({"pages": 2}, lambda details: details["nodes"][-1]["output"]["count"] == 3),
        "browser_text": ({"selector": "h1"}, lambda details: "Office catalog" in details["nodes"][-1]["output"]["text"]),
        "browser_links": ({"selector": "main"}, lambda details: details["nodes"][-1]["output"]["links"][0]["href"]
                          == "catalog2.html"),
        "browser_capture": ({}, lambda details: details["artifacts"][0]["media_type"] == "image/png"),
    }
    evidence = {}
    with tempfile.TemporaryDirectory(dir=runtime, prefix="browser-evaluation-") as tmp:
        with TestClient(create_app(Settings(Path(tmp), browser=args.channel))) as client:
            for node, (config, predicate) in cases.items():
                details = poll(client, enqueue(client, draft(client, chain(START, (node, node, config)))), timeout=70)
                ok = details["status"] == "SUCCEEDED" and predicate(details)
                if ok and node == "browser_capture":
                    image = client.get(f"{API}/artifacts/{details['artifacts'][0]['id']}")
                    ok = image.status_code == 200 and image.content.startswith(b"\x89PNG\r\n\x1a\n")
                evidence[node] = {"status": details["status"], "passed": ok, "error": details["error"]}
                print(node, evidence[node], flush=True)
            graph = chain(START, ("browser_text", "Unmatched selector", {"selector": ".does-not-exist"}))
            result = poll(client, enqueue(client, draft(client, graph)), timeout=70)
            evidence["invalid_selector"] = {"status": result["status"], "error": result["error"],
                                            "passed": result["status"] == "FAILED"
                                            and "Selector matched no elements" in (result["error"] or "")}
    output = PROJECT / "evaluation" / "results"
    output.mkdir(parents=True, exist_ok=True)
    json_file(output, "browser_results.json", evidence)
    print(evidence, flush=True)
    if not all(result["passed"] for result in evidence.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
