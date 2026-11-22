import argparse
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import httpx

from backend.app.runtime import PROJECT, Settings
from evaluation.benchmark import json_file
from scripts.seed_demo import generate


def start_and_verify(channel, capture_only, runtime, completion):
    origin = "http://127.0.0.1:4173"
    os.environ["AGENTFORGE_ROOT"] = str(runtime.resolve())
    os.environ["AGENTFORGE_BROWSER"] = channel
    if completion:
        os.environ["AGENTFORGE_SECRET_VERIFICATION_WEBHOOK"] = secrets.token_urlsafe(32)
    results = generate(Settings.from_env(), assets=not completion)
    json_file(runtime, "demo-results.json", results)
    print({key: value["status"] for key, value in results.items()}, flush=True)
    if any(value["status"] in {"FAILED", "TIMED_OUT", "CANCELLED"} for value in results.values()):
        print("A demo run failed. Continuing browser interface checks.", flush=True)
    if not (PROJECT / "frontend/dist/index.html").is_file():
        raise SystemExit("Build the frontend before running portfolio verification")
    with subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1",
         "--port", "4173", "--no-access-log"],
        cwd=PROJECT,
    ) as server:
        try:
            with httpx.Client(trust_env=False, timeout=1) as client:
                deadline = time.monotonic() + 75
                while time.monotonic() < deadline and server.poll() is None:
                    try:
                        if client.get(origin + "/ready").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(.2)
                else:
                    raise RuntimeError("The loopback preview did not become ready")
            args = [sys.executable, "-m", "scripts.browser_smoke", "--url", origin, "--channel", channel]
            args.append("--completion" if completion else "--screenshots")
            if capture_only:
                args.append("--capture-only")
            subprocess.run(args, cwd=PROJECT, check=True, timeout=240)
        finally:
            if server.poll() is None:
                server.terminate()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="chrome")
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--completion", action="store_true")
    parser.add_argument("--runtime", type=Path, default=PROJECT / ".runtime" / "chrome-verification")
    args = parser.parse_args()
    start_and_verify(args.channel, args.capture_only, args.runtime, args.completion)


if __name__ == "__main__":
    main()
