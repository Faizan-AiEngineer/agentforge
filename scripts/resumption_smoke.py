import json

from playwright.sync_api import expect

from backend.app.runtime import PROJECT
from scripts.browser_smoke import open_page

API = "/api/v1"
NAME = "Workflow resumption audit"


def capture_resumption(page, origin, client, folder):
    folder.mkdir(parents=True, exist_ok=True)

    def submit(path, payload):
        response = client.post(API + path, json=payload)
        assert response.is_success, response.text
        return response.json()

    def start(name, definition):
        workflow = submit("/workflows", {"name": name, "definition": definition})
        return submit(f"/workflows/{workflow['id']}/run", {"payload": {"receipt": "synthetic-001"}})["id"]

    def locate_approval(identifier):
        return page.locator(".approval-card").filter(
            has=page.locator(f'a[href="/executions/{identifier}"]'),
        )

    def live_status(status):
        expect(page.locator(".run-summary .badge")).to_have_text(status)

    fixture = PROJECT / "workflows/fixtures/approval-resumption.json"
    graph = json.loads(fixture.read_text(encoding="utf-8"))
    identifier = start(NAME, graph)
    run_path = "/executions/" + identifier

    open_page(page, origin, "/approvals", "Approvals")
    card = locate_approval(identifier)
    expect(card.locator(".badge")).to_have_text("Waiting Approval")
    page.screenshot(path=folder / "01-waiting-for-approval.png", animations="disabled")

    open_page(page, origin, run_path, NAME)
    live_status("Waiting Approval")
    timeline = page.locator("article.timeline")
    expect(timeline.locator(".badge-succeeded")).to_have_count(3)
    expect(timeline.locator(".badge-pending")).to_have_count(2)
    timeline.screenshot(path=folder / "02-history-before-approval.png", animations="disabled")

    open_page(page, origin, "/approvals", "Approvals")
    decision_requests = []

    def record_decision(request):
        if request.method == "POST" and "/approvals/" in request.url and request.url.endswith("/decision"):
            decision_requests.append(request.url)

    page.on("request", record_decision)
    button = locate_approval(identifier).get_by_role("button", name="Approve", exact=True)
    button.evaluate("button => { button.click(); button.click(); }")
    expect(locate_approval(identifier).locator(".badge")).to_have_text("Approve")
    assert len(decision_requests) == 1, decision_requests

    open_page(page, origin, run_path, NAME)
    live_status("Succeeded")
    expect(page.locator(".page-title p")).to_contain_text(identifier[:8])
    page.screenshot(path=folder / "03-resumed-execution.png", animations="disabled")
    expect(timeline.locator(".badge-succeeded")).to_have_count(6)
    expect(timeline.locator(".step-row small").filter(has_text="1 attempt")).to_have_count(6)
    expect(timeline.locator(".badge-pending")).to_have_count(0)
    timeline.screenshot(path=folder / "04-final-execution-history.png", animations="disabled")
    final = client.get(API + run_path).json()
    assert final["id"] == identifier and len(final["artifacts"]) == 2

    rejected_name = "Rejection state audit"
    rejected = start(rejected_name, graph)
    open_page(page, origin, "/approvals", "Approvals")
    locate_approval(rejected).get_by_role("button", name="Reject", exact=True).click()
    expect(locate_approval(rejected).locator(".badge")).to_have_text("Reject")
    open_page(page, origin, "/executions/" + rejected, rejected_name)
    live_status("Rejected")
    expect(timeline.locator(".badge-skipped")).to_have_count(2)

    failed_name = "Failure state audit"
    graph["nodes"][4].update(type="write_text", config={"filename": "requires-text"})
    failed = start(failed_name, graph)
    open_page(page, origin, "/approvals", "Approvals")
    locate_approval(failed).get_by_role("button", name="Approve", exact=True).click()
    expect(locate_approval(failed).locator(".badge")).to_have_text("Approve")
    open_page(page, origin, "/executions/" + failed, failed_name)
    live_status("Failed")
    expect(page.get_by_role("button", name="Resume failed node")).to_be_enabled()
    expect(page.get_by_role("button", name="Start new run from pinned version")).to_be_enabled()
    return {"status": "VERIFIED", "approval_requests_for_two_clicks": 1, "captures": 4,
            "approved_status": "SUCCEEDED", "rejected_status": "REJECTED", "failed_status": "FAILED"}
