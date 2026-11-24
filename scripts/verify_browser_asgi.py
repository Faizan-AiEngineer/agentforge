import argparse
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from backend.app.main import create_app
from backend.app.runtime import PROJECT, Settings
from evaluation.benchmark import json_file
from scripts.browser_smoke import completion_smoke, open_page, smoke
from scripts.resumption_smoke import capture_resumption
from scripts.seed_demo import generate

ORIGIN = "http://127.0.0.1:4173"


class BrowserReply:
    def __init__(self, response):
        self.response = response
        self.ok = response.is_success
        self.status = response.status_code

    def text(self):
        return self.response.text

    def json(self):
        return self.response.json()


class InProcessRequests:
    def __init__(self, client):
        self.client = client

    def get(self, url):
        return BrowserReply(self.client.get(url))

    def post(self, url, data, headers=None):
        body = {"content": data} if isinstance(data, bytes) else {"json": data}
        return BrowserReply(self.client.post(url, headers=headers, **body))


def verify(client, channel, downloads, resumption_screenshots=None):
    # Run the production bundle and real ASGI application without binding a TCP listener.
    def route_to_app(route):
        request = route.request
        if not request.url.startswith(ORIGIN + "/"):
            route.abort()
            return
        headers = {key: value for key, value in request.all_headers().items()
                   if key not in ("content-length", "transfer-encoding")}
        result = client.request(request.method, request.url, headers=headers,
                                content=request.post_data_buffer, follow_redirects=False)
        route.fulfill(status=result.status_code, headers=dict(result.headers), body=result.content)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=channel or None, args=["--disable-background-networking"],
                                              downloads_path=downloads)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 980},
                                          service_workers="block", accept_downloads=True)
            context.route(lambda url: not url.startswith("blob:" + ORIGIN + "/"), route_to_app)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            download = {}
            approved = smoke(page, ORIGIN, download)
            completion_smoke(page, ORIGIN, approved, InProcessRequests(client))
            page.set_viewport_size({"width": 390, "height": 820})
            open_page(page, ORIGIN, "/", "Overview")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.get_by_role("button", name="Open navigation").click()
            expect(page.get_by_role("navigation", name="Workspace navigation")).to_be_visible()
            resumption = None
            if resumption_screenshots is not None:
                page.set_viewport_size({"width": 1440, "height": 1080})
                resumption = capture_resumption(page, ORIGIN, client, resumption_screenshots)
            assert not errors, errors
            return download, resumption
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--winloop", action="store_true")
    parser.add_argument("--resumption-screenshots", type=Path)
    args = parser.parse_args()
    if args.winloop:
        import winloop

        winloop.install()
    if not (PROJECT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the production frontend before verification")
    os.environ["AGENTFORGE_SECRET_VERIFICATION_WEBHOOK"] = secrets.token_urlsafe(32)
    settings = Settings(root=args.runtime.resolve(), browser=args.channel)
    result = generate(settings)
    statuses = {key: value["status"] for key, value in result.items()}
    json_file(settings.root, "demo-status.json", statuses)
    print(statuses, flush=True)
    assert statuses.pop("pending-approval") == "WAITING_APPROVAL"
    assert all(status == "SUCCEEDED" for status in statuses.values())
    downloads = settings.root / "browser-downloads"
    downloads.mkdir(exist_ok=True)
    with TestClient(create_app(settings), base_url=ORIGIN) as client, ThreadPoolExecutor(max_workers=1) as thread:
        download, resumption = thread.submit(
            verify, client, args.channel, downloads, args.resumption_screenshots,
        ).result()
    evidence = {"transport": "ASGI", "browser": args.channel, "workflow_journey": "VERIFIED",
                "webhook_schedule_monitoring_and_rejection": "VERIFIED", "download": download}
    if resumption:
        evidence["resumption"] = resumption
    json_file(settings.root, "browser-summary.json", evidence)
    print(evidence, flush=True)


if __name__ == "__main__":
    main()
