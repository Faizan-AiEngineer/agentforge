import argparse
import csv
import json
import os
import platform
import random
import statistics
import sys
import tempfile
import time
import tracemalloc
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from anyio.from_thread import start_blocking_portal
from fastapi.testclient import TestClient

from backend.app.contracts import WorkflowInput
from backend.app.graph import analyze
from backend.app.main import create_app, create_workflow
from backend.app.nodes import REGISTRY, Context
from backend.app.runtime import PROJECT, Settings, queue
from backend.app.templates import chain

SIZES = (5, 10, 25, 50, 100)
BURSTS = (1, 5, 10, 25)
RECORDS = (1000, 10000, 100000)


def csv_rows(directory, name, rows):
    with (directory / name).open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def wait_for(client, key, wait=90):
    stop = time.monotonic() + wait
    while time.monotonic() < stop:
        row = client.get(f"/api/v1/executions/{key}").json()
        if row["status"] not in {"QUEUED", "RUNNING"}:
            return row
        time.sleep(.03)
    raise TimeoutError(f"Execution did not complete in {wait} seconds")


def create_jobs(client, count, graph_size):
    graph = chain(("manual", "Start", {}), *[
        ("values", "Set value", {"values": {"count": i}}) for i in range(graph_size - 1)])
    with client.app.state.sessions.begin() as session:
        workflow = create_workflow(session, WorkflowInput(name=f"Benchmark {graph_size}", definition=graph))
        return [queue(session, workflow, "manual", {}).id for _ in range(count)]


def engine_bench(client, repeat):
    samples = []
    for size in SIZES:
        for trial in range(repeat):
            tracemalloc.start()
            try:
                run = wait_for(client, create_jobs(client, 1, size)[0])
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            node_seconds = sum(node["ended"] - node["started"] for node in run["nodes"]
                               if node["ended"] is not None and node["started"] is not None)
            execution_seconds = run["ended"] - run["started"]
            samples.append({"nodes": size, "trial": trial + 1, "status": run["status"],
                            "execution_ms": round(1000 * execution_seconds, 3),
                            "node_ms": round(1000 * node_seconds, 3),
                            "overhead_ms": round(1000 * (execution_seconds - node_seconds), 3),
                            "trace_peak_bytes": peak})
    return samples


def burst_bench(client, repeat):
    samples = []
    for count in BURSTS:
        for trial in range(repeat):
            mark = time.perf_counter()
            executions = [wait_for(client, key) for key in create_jobs(client, count, 5)]
            elapsed = time.perf_counter() - mark
            errors = sum(item["status"] != "SUCCEEDED" for item in executions)
            samples.append({"submitted": count, "trial": trial + 1, "errors": errors,
                            "throughput_per_second": round((count - errors) / elapsed, 3),
                            "mean_latency_ms": round(1000 * statistics.mean(
                                item["ended"] - item["created"] for item in executions), 3),
                            "mean_queue_ms": round(1000 * statistics.mean(
                                item["started"] - item["created"] for item in executions), 3)})
    return samples


async def data_bench(repeat):
    rng = random.Random(42)
    samples = []
    operations = {
        "filter": {"rules": [{"field": "amount", "op": "gt", "value": 75}]},
        "dedupe": {"keys": ["id"]},
        "aggregate": {"group_by": "region", "operation": "sum"},
        "write_csv": {},
    }
    for size in RECORDS:
        records = [{"id": index // 2, "region": index % 4, "amount": rng.randint(1, 150)}
                   for index in range(size)]
        for kind, config in operations.items():
            spec = REGISTRY[kind]
            task = spec.config.model_validate(config)
            context = Context(PROJECT, PROJECT, frozenset(), "benchmark", "Data benchmark", {},
                              [{"records": records}])
            for trial in range(repeat):
                mark = time.perf_counter()
                error = ""
                count = None
                try:
                    result = await spec.action(context, task)
                    count = result.output.get("count")
                except ValueError as exc:
                    error = str(exc)
                samples.append({"records": size, "operation": kind, "trial": trial + 1,
                                "duration_ms": round(1000 * (time.perf_counter() - mark), 3),
                                "output_records": count, "status": "FAILED" if error else "SUCCEEDED",
                                "error": error})
    return samples


def contract_validation():
    base = chain(("manual", "Start", {}), ("values", "Values", {}))
    cases = {
        "good": base,
        "missing_endpoint": {**base, "edges": [{"source": "n0", "target": "missing"}]},
        "cycle": {**base, "edges": [*base["edges"], {"source": "n1", "target": "n0"}]},
        "invalid_port": {**base, "edges": [{"source": "n0", "target": "n1", "port": "bad"}]},
        "bad_config": chain(("manual", "Start", {}), ("delay", "Delay", {"seconds": 100})),
        "bad_node": chain(("manual", "Start", {}), ("missing", "Unsupported", {})),
        "bad_reference": chain(("manual", "Start", {}), ("values", "Values", {"values": {
            "amount": "{{ nodes.missing.output.amount }}"}})),
    }
    rows = []
    for case, definition in cases.items():
        graph = WorkflowInput(name=case, definition=definition).definition
        mark = time.perf_counter()
        errors, *_ = analyze(graph)
        rows.append({"case": case, "expected_valid": case == "good",
                     "valid": not errors, "errors": errors,
                     "duration_ms": round(1000 * (time.perf_counter() - mark), 3)})
    return rows


async def offline_evaluation():
    cases = [
        ("summarize", {"text": "The order is approved. Delivery is Monday.", "sentences": 1},
         {"summary": "The order is approved."}),
        ("classify", {"text": "Please send my invoice", "categories": {"billing": ["invoice"]}},
         {"label": "billing"}),
        ("extract_info", {"text": "demo@example.org total 45"}, {"emails": ["demo@example.org"]}),
        ("structured", {"text": "status: reviewed", "fields": ["status"]}, {"fields": {"status": "reviewed"}}),
        ("structured", {"text": "Compose a novel", "fields": ["status"]}, None),
    ]
    rows = []
    for kind, config, expected in cases:
        node = REGISTRY[kind]
        ctx = Context(PROJECT, PROJECT, frozenset(), "bench", "Offline evaluation", {}, [])
        mark = time.perf_counter()
        try:
            result = await node.action(ctx, node.config.model_validate(config))
            passed = expected is not None and all(result.output.get(key) == val for key, val in expected.items())
            outcome = "structured_result"
        except ValueError:
            passed, outcome = expected is None, "unsupported_input"
        rows.append({"task": kind, "outcome": outcome, "passed": passed,
                     "duration_ms": round(1000 * (time.perf_counter() - mark), 3)})
    return rows


def json_file(directory, name, data):
    (directory / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def new_capture(label, output=None):
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    directory = output or PROJECT / ".runtime" / (label + "-" + stamp)
    directory.mkdir(parents=True)
    return directory


def describe(samples):
    return {"samples": len(samples), "mean": round(statistics.mean(samples), 3),
            "median": round(statistics.median(samples), 3), "minimum": min(samples), "maximum": max(samples)}


def summarize(chains, bursts, data):
    return {
        "workflow_ms": {str(size): describe([row["execution_ms"] for row in chains if row["nodes"] == size])
                        for size in SIZES},
        "bursts": {str(size): {
            field: describe([row[field] for row in bursts if row["submitted"] == size])
            for field in ("throughput_per_second", "mean_latency_ms", "mean_queue_ms", "errors")}
            for size in BURSTS},
        "data_ms": {f"{size}:{kind}": describe([row["duration_ms"] for row in data
                                                if row["records"] == size and row["operation"] == kind])
                    for size in RECORDS for kind in sorted({row["operation"] for row in data})},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", default=3, type=int, choices=range(1, 11))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--scenarios", action="store_true")
    parser.add_argument("--winloop", action="store_true", help="Use the installed Windows libuv event loop")
    args = parser.parse_args()
    loop_factory = None
    if args.winloop:
        import winloop

        winloop.install()
        loop_factory = winloop.new_event_loop
    directory = new_capture("measurement", args.output)
    workspace = PROJECT / ".runtime"
    workspace.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="benchmark-", dir=workspace) as temp:
        with TestClient(create_app(Settings(Path(temp)))) as client:
            chains = engine_bench(client, args.repeat)
            bursts = burst_bench(client, args.repeat)
    with start_blocking_portal(backend_options={"loop_factory": loop_factory}) as portal:
        data = portal.call(data_bench, args.repeat)
        offline = portal.call(offline_evaluation)
    csv_rows(directory, "workflow_performance.csv", chains)
    csv_rows(directory, "concurrency_results.csv", bursts)
    csv_rows(directory, "data_processing_results.csv", data)
    json_file(directory, "summary.json", summarize(chains, bursts, data))
    json_file(directory, "validation_results.json", contract_validation())
    json_file(directory, "ai_evaluation.json", offline)
    json_file(directory, "environment.json", {
        "system": platform.platform(), "architecture": platform.machine(),
        "cpu": os.getenv("PROCESSOR_IDENTIFIER") or platform.processor(), "cpu_count": os.cpu_count(),
        "python": sys.version.split()[0], "repeat": args.repeat, "seed": 42,
        "dependencies": {name: version(name) for name in ("fastapi", "sqlalchemy", "pydantic", "openpyxl")},
        "method": "SQLite queue and single local worker in FastAPI TestClient",
        "event_loop": "winloop" if args.winloop else "asyncio default",
    })
    if args.scenarios:
        from evaluation.scenarios import approvals, reliability, security

        with tempfile.TemporaryDirectory(dir=workspace, prefix="benchmark-scenarios-") as temp:
            scenario_results = {name: run(Settings(Path(temp) / name)) for name, run in
                                (("reliability", reliability), ("approval", approvals), ("security", security))}
            for name, result in scenario_results.items():
                json_file(directory, name + "_results.json", result)
            json_file(directory, "scenario_summary.json", {
                **{name + "_ms": describe([scenario_results["reliability"][name]["elapsed_ms"]])
                   for name in ("retry", "restart")},
                "approval_ms": describe([row["resume_ms"] for row in scenario_results["approval"].values()]),
            })
    print("Wrote measured results into " + str(directory))


if __name__ == "__main__":
    main()
