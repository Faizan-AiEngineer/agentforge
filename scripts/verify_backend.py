import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, default=ROOT / ".runtime" / "test-verification")
    parser.add_argument("--winloop", action="store_true", help="Use the installed Windows libuv event loop for tests")
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    runtime.mkdir(parents=True, exist_ok=True)
    xml = runtime / "pytest.xml"
    if xml.exists():
        raise SystemExit("Use a fresh runtime directory to preserve existing test evidence")
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    if args.winloop:
        env["AGENTFORGE_TEST_WINLOOP"] = "1"
    began = time.perf_counter()
    counts = {}
    try:
        result = subprocess.run(
            [sys.executable, "-u", "-m", "pytest", "-q", "--tb=short", "-o", "faulthandler_timeout=120",
             "--basetemp", str(runtime / "fixtures"), "--junitxml", str(xml)],
            cwd=ROOT, env=env, check=False, timeout=400,
        )
        code = result.returncode
        if xml.exists():
            root = ElementTree.parse(xml).getroot()
            suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
            counts = {key: sum(int(suite.get(key, 0)) for suite in suites)
                      for key in ("tests", "failures", "errors", "skipped")}
            counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
        counts.update(exit_code=code, blocked=0 if "tests" in counts else None)
    except subprocess.TimeoutExpired:
        counts.update(exit_code=124, blocked="Subprocess exceeded its deadline")
    counts["elapsed_seconds"] = round(time.perf_counter() - began, 3)
    counts["event_loop"] = "winloop" if args.winloop else "asyncio default"
    (runtime / "summary.json").write_text(json.dumps(counts, indent=2) + "\n", encoding="utf-8")
    print(counts, flush=True)
    raise SystemExit(counts["exit_code"])


if __name__ == "__main__":
    main()
