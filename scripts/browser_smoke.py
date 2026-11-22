import argparse
import hmac
import json
import os
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

from backend.app.templates import chain

PROJECT = Path(__file__).resolve().parents[1]


def open_page(page, base, path, heading):
    page.goto(base + path, wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name=heading, exact=True).first).to_be_visible()


def attach(page, index, port, target):
    source = page.locator(".react-flow__node").nth(index).locator(f'[data-handleid="{port}"]')
    target = page.locator(".react-flow__node").nth(target).locator('[data-handleid="input"]')
    source.scroll_into_view_if_needed()
    start, end = source.bounding_box(), target.bounding_box()
    assert start is not None and end is not None
    page.mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(end["x"] + end["width"] / 2, end["y"] + end["height"] / 2, steps=18)
    page.mouse.up()


def capture(page, base):
    output = PROJECT / "docs" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)

    def shot(name):
        page.screenshot(path=output / f"{name}.png", animations="disabled", full_page=True)

    for path, heading, name in [
        ("/", "Overview", "01-overview"), ("/executions", "Execution History", "05-history"),
        ("/nodes", "Node Library", "07-node-library"), ("/templates", "Templates", "08-templates"),
        ("/approvals", "Approvals", "09-approvals"), ("/monitoring", "Monitoring", "10-monitoring"),
        ("/integrations", "Integrations", "11-integrations"),
    ]:
        open_page(page, base, path, heading)
        expect(page.get_by_text("Loading workspace…")).to_have_count(0)
        shot(name)
    workflows = page.request.get(base + "/api/v1/workflows").json()["items"]
    for workflow_name, name in (("CSV Cleaning", "02-builder"), ("Purchase Approval", "03-branching")):
        value = next(workflow for workflow in workflows if workflow["name"] == workflow_name)
        page.goto(base + "/builder/" + value["id"])
        expect(page.get_by_role("textbox", name="Workflow name")).to_have_value(workflow_name)
        expect(page.locator(".react-flow__edge").first).to_be_visible()
        shot(name)
        if workflow_name == "CSV Cleaning":
            page.locator(".react-flow__node").filter(has_text="Clean order fields").click()
            expect(page.get_by_role("textbox", name="Node name")).to_have_value("Clean order fields")
            shot("04-node-configuration")
    runs = page.request.get(base + "/api/v1/executions?status=SUCCEEDED").json()["items"]
    run = next(row for row in runs if row["workflow_name"] == "Daily Business Report")
    open_page(page, base, "/executions/" + run["id"], run["workflow_name"])
    expect(page.get_by_text("agentforge-report.pdf", exact=True)).to_be_visible()
    shot("06-execution-details")


def smoke(page, base, browser_download=None):
    if browser_download is not None:
        page.add_init_script("""
            const create = URL.createObjectURL.bind(URL);
            URL.createObjectURL = blob => {
                window.agentForgeDownloadBlob = blob;
                return create(blob);
            };
        """)
    name = "Browser verification " + uuid4().hex[:8]
    open_page(page, base, "/", "Overview")
    page.get_by_role("button", name="Switch to light theme").click()
    assert page.locator("html").get_attribute("data-theme") == "light"
    page.get_by_role("button", name="Switch to dark theme").click()
    page.get_by_role("button", name="Search workspace").click()
    page.get_by_role("textbox", name="Search pages and workflows").fill("My Workflows")
    page.get_by_role("dialog").get_by_role("link", name="My Workflows").click()
    expect(page.get_by_role("heading", name="My Workflows")).to_be_visible()
    page.get_by_role("link", name="New workflow").click()
    page.get_by_role("textbox", name="Workflow name").fill(name)
    page.get_by_role("button", name="Add manual trigger").click()
    search = page.get_by_role("textbox", name="Find a node")
    for label in ("Set Variables", "Condition", "CSV Export"):
        search.fill(label)
        page.get_by_role("button", name=label, exact=True).click()
    search.fill("Date and Time")
    page.get_by_role("button", name="Date and Time", exact=True).click()
    expect(page.locator(".react-flow__node")).to_have_count(5)
    page.locator(".react-flow__controls-fitview").click()
    page.locator(".react-flow__node").filter(has_text="Date and Time").click()
    page.get_by_role("button", name="Delete selected node").click()
    expect(page.locator(".react-flow__node")).to_have_count(4)
    page.locator(".react-flow__controls-fitview").click()
    page.wait_for_timeout(450)
    page.locator(".react-flow__node").nth(1).click()
    page.get_by_role("textbox", name="values", exact=True).fill(json.dumps({"records": [{"id": 1}], "count": 1}))
    page.get_by_role("textbox", name="values", exact=True).press("Tab")
    page.locator(".react-flow__node").nth(2).click()
    page.get_by_role("textbox", name="rules", exact=True).fill(
        json.dumps([{"field": "count", "op": "gt", "value": 0}]))
    page.get_by_role("textbox", name="rules", exact=True).press("Tab")
    attach(page, 0, "out", 1)
    attach(page, 1, "out", 2)
    attach(page, 2, "true", 3)
    expect(page.locator(".react-flow__edge")).to_have_count(3)
    page.get_by_role("button", name="Validate", exact=True).click()
    expect(page.get_by_text("Workflow is valid")).to_be_visible()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Workflow saved", exact=True)).to_be_visible()
    page.reload()
    expect(page.get_by_role("textbox", name="Workflow name")).to_have_value(name)
    expect(page.locator(".react-flow__edge")).to_have_count(3)
    page.get_by_role("button", name="Run workflow", exact=True).click()
    page.get_by_role("link", name="Inspect execution", exact=True).click()
    expect(page.get_by_text("results.csv", exact=True)).to_be_visible(timeout=20000)
    with page.expect_download() as download:
        page.get_by_role("link", name=re.compile("results.csv")).click()
    assert download.value.suggested_filename == "results.csv", download.value.suggested_filename
    failure = download.value.failure()
    if failure and browser_download is not None:
        content = page.evaluate("async () => Array.from(new Uint8Array("
                                "await window.agentForgeDownloadBlob.arrayBuffer()))")
        assert bytes(content).endswith(b"1\r\n")
        browser_download.update(browser_bytes_verified=True, native_save="BLOCKED", reason=failure)
        print(f"Chrome produced the expected CSV bytes. Native file save returned {failure}.", flush=True)
    else:
        assert not failure, failure
        assert download.value.path().read_bytes().endswith(b"1\r\n")
        if browser_download is not None:
            browser_download.update(browser_bytes_verified=True, native_save="VERIFIED")
    open_page(page, base, "/executions", "Execution History")
    expect(page.get_by_role("link", name=re.compile(name)).first).to_be_visible()
    open_page(page, base, "/workflows", "My Workflows")
    page.get_by_role("button", name="Duplicate " + name, exact=True).click()
    expect(page.get_by_role("textbox", name="Workflow name")).to_have_value(name + " (copy)")
    page.get_by_role("textbox", name="Workflow name").fill(name + " revised")
    page.get_by_role("button", name="Run workflow", exact=True).click()
    page.get_by_role("link", name="Inspect execution", exact=True).click()
    expect(page.get_by_text("results.csv", exact=True)).to_be_visible(timeout=20000)
    open_page(page, base, "/templates", "Templates")
    page.locator("article.tile").filter(has_text="Purchase Approval").get_by_role("button", name="Preview").click()
    page.get_by_role("button", name="Import template").click()
    expect(page.get_by_role("textbox", name="Workflow name")).to_have_value("Purchase Approval")
    page.get_by_role("button", name="Run workflow", exact=True).click()
    page.get_by_role("link", name="Inspect execution", exact=True).click()
    expect(page.get_by_text("Waiting Approval", exact=True).first).to_be_visible(timeout=20000)
    run_url = page.url
    open_page(page, base, "/approvals", "Approvals")
    card = page.locator("article.approval-card").filter(
        has=page.get_by_role("link", name="Inspect run").and_(page.locator(f'[href="{run_url.removeprefix(base)}"]')))
    card.get_by_role("button", name="Approve", exact=True).click()
    page.goto(run_url)
    expect(page.get_by_text("approved.json", exact=True)).to_be_visible(timeout=20000)
    return run_url


def completion_smoke(page, base, approved_url, api_request=None):
    api = base + "/api/v1"
    api_request = api_request or page.request
    approved = api_request.get(api + "/executions/" + approved_url.rsplit("/", 1)[-1]).json()
    page.goto(base + "/builder/" + approved["workflow_id"])
    page.get_by_role("button", name="Run workflow", exact=True).click()
    page.get_by_role("link", name="Inspect execution", exact=True).click()
    expect(page.get_by_text("Waiting Approval", exact=True).first).to_be_visible(timeout=20000)
    rejected_url = page.url
    open_page(page, base, "/approvals", "Approvals")
    card = page.locator("article.approval-card").filter(
        has=page.locator(f'[href="{rejected_url.removeprefix(base)}"]'))
    card.get_by_role("button", name="Reject", exact=True).click()
    page.goto(rejected_url)
    expect(page.get_by_text("review.json", exact=True)).to_be_visible(timeout=20000)

    key = os.environ["AGENTFORGE_SECRET_VERIFICATION_WEBHOOK"]
    reference = api_request.post(api + "/credentials", data={
        "name": "browser-e2e-webhook", "kind": "webhook", "env_var": "AGENTFORGE_SECRET_VERIFICATION_WEBHOOK",
    })
    assert reference.ok, reference.text()
    hook_graph = chain(("webhook", "Receive event", {}), ("write_json", "Export event", {"filename": "signed"}))
    hook_flow = api_request.post(api + "/workflows", data={"name": "Browser signed webhook", "definition": hook_graph})
    assert hook_flow.ok, hook_flow.text()
    hook_id = hook_flow.json()["id"]
    open_page(page, base, "/schedules", "Schedules & Triggers")
    hook_form = page.locator("form").filter(has=page.get_by_role("heading", name="Create webhook", exact=True))
    hook_form.get_by_label("Webhook workflow").select_option(hook_id)
    hook_form.get_by_label("Webhook credential").select_option("browser-e2e-webhook")
    hook_form.get_by_role("button", name="Add webhook").click()
    expect(page.get_by_text("Webhook created")).to_be_visible()
    hook = next(item for item in api_request.get(api + "/webhooks").json()["items"]
                if item["workflow_id"] == hook_id)
    stamp = str(int(time.time()))
    body = json.dumps({"event_id": "browser-" + uuid4().hex, "payload": {"record": "signed"}}).encode()
    hook_url = api + "/hooks/" + hook["id"]
    assert api_request.post(hook_url, data=body).status == 401
    headers = {"Content-Type": "application/json", "X-AgentForge-Timestamp": stamp,
               "X-AgentForge-Signature": hmac.digest(key.encode(), stamp.encode() + b"." + body, "sha256").hex()}
    incoming = api_request.post(hook_url, headers=headers, data=body)
    assert incoming.ok, incoming.text()
    incoming_id = incoming.json()["id"]
    assert api_request.post(hook_url, headers=headers, data=body).json()["id"] == incoming_id

    schedule_data = api_request.post(api + "/workflows", data={
        "name": "Browser scheduled workflow",
        "definition": chain(("schedule", "Clock", {}), ("write_json", "Save schedule", {"filename": "scheduled"})),
    })
    assert schedule_data.ok, schedule_data.text()
    page.reload()
    schedule = page.locator("form").filter(has=page.get_by_role("heading", name="Create schedule", exact=True))
    schedule.get_by_label("Trigger type").select_option("once")
    schedule.get_by_label("Workflow").select_option(schedule_data.json()["id"])
    schedule.get_by_label("ISO date and time").fill((datetime.now(UTC) + timedelta(seconds=6)).isoformat())
    schedule.get_by_role("button", name="Add schedule").click()
    expect(page.get_by_text("Schedule created")).to_be_visible()
    open_page(page, base, "/executions/" + incoming_id, "Browser signed webhook")
    expect(page.get_by_text("signed.json", exact=True)).to_be_visible(timeout=20000)
    open_page(page, base, "/executions", "Execution History")
    page.get_by_role("link", name=re.compile("Browser scheduled workflow")).first.click(timeout=25000)
    expect(page.get_by_text("scheduled.json", exact=True)).to_be_visible(timeout=20000)

    graph = chain(("manual", "Start", {}), ("filter", "Missing records", {"rules": [{"op": "truthy"}]}))
    failure = api_request.post(api + "/workflows", data={"name": "Browser error handling", "definition": graph})
    assert failure.ok, failure.text()
    failed = api_request.post(api + "/workflows/" + failure.json()["id"] + "/run", data={})
    assert failed.ok, failed.text()
    open_page(page, base, "/executions/" + failed.json()["id"], "Browser error handling")
    expect(page.get_by_text(re.compile("Expected an array of record objects")).first).to_be_visible(timeout=20000)
    open_page(page, base, "/monitoring", "Monitoring")
    expect(page.get_by_role("heading", name="Execution outcomes")).to_be_visible()
    assert api_request.get(api + "/monitoring").json()["failed"] >= 1
    open_page(page, base, "/integrations", "Integrations")
    expect(page.get_by_role("heading", name="Ollama", exact=True)).to_be_visible()
    open_page(page, base, "/nodes", "Node Library")
    page.get_by_role("textbox", name="Search nodes").fill("CSV Export")
    expect(page.get_by_role("heading", name="CSV Export", exact=True)).to_be_visible()
    open_page(page, base, "/credentials", "Credentials")
    expect(page.get_by_role("textbox", name="Environment variable")).to_be_visible()
    open_page(page, base, "/settings", "Settings")
    expect(page.get_by_role("link", name="System status JSON")).to_be_visible()
    print("Verified signed webhook, schedule, rejection, monitoring and error handling", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:5173")
    parser.add_argument("--channel", default="")
    parser.add_argument("--screenshots", action="store_true")
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--completion", action="store_true")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=args.channel or None)
        page = browser.new_page(viewport={"width": 1440, "height": 980}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        if args.screenshots or args.capture_only:
            capture(page, args.url)
        if not args.capture_only:
            approved_url = smoke(page, args.url)
            if args.completion:
                completion_smoke(page, args.url, approved_url)
            page.set_viewport_size({"width": 390, "height": 820})
            open_page(page, args.url, "/", "Overview")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.get_by_role("button", name="Open navigation").click()
            expect(page.get_by_role("navigation", name="Workspace navigation")).to_be_visible()
        assert not errors, errors
        browser.close()
        print("Browser verification completed")


if __name__ == "__main__":
    main()
