# Quick start

Follow the [Windows install and launch](../README.md#windows-quick-start). All commands below run at the repository root.

If Windows installed Node.js for the current account and PowerShell cannot find it, add its program directory to that terminal's PATH:

```powershell
$env:Path = "$env:LOCALAPPDATA\Programs\nodejs;$env:Path"
node --version
npm.cmd --version
```

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend scripts evaluation
npm --prefix frontend run check
npm --prefix frontend test
npm --prefix frontend run build
```

With the production preview running and Chrome available on Windows:

```powershell
.\.venv\Scripts\python.exe -m scripts.browser_smoke --url http://127.0.0.1:8000 --channel chrome
```

The browser suite creates uniquely named verification workflows. Use a separate runtime if you want to keep them out of your local data. Set `AGENTFORGE_ROOT` before launching and seeding the backend. Stop the server before running the demo seed against the same runtime.

```powershell
.\.venv\Scripts\python.exe -m scripts.seed_demo --portfolio-assets
.\.venv\Scripts\python.exe -m evaluation.benchmark --repeat 3 --scenarios --output .runtime/benchmark-local
.\.venv\Scripts\python.exe -m evaluation.scenarios
.\.venv\Scripts\python.exe -m evaluation.trigger_runs
```

To schedule **Daily Business Report**, open **Schedules & Triggers**, choose the saved workflow, and enter an interval of at least five seconds or a cron expression. File watch accepts an extension such as `.csv` and watches the runtime input directory. Use freshly copied files and leave them in place until the run completes. For webhook setup see the [API reference](API_REFERENCE.md).

To capture real screenshots from a seeded runtime:

```powershell
.\.venv\Scripts\python.exe -m scripts.browser_smoke --url http://127.0.0.1:8000 --channel chrome --capture-only
```

For frontend development with live reload, run `npm.cmd --prefix frontend run dev` in a second terminal while Uvicorn runs on port 8000. Open the [Vite development server](http://127.0.0.1:5173). You can reproduce the dedicated Chrome portfolio run with `python -m scripts.verify_portfolio --channel chrome`.

The expanded browser verifier starts an isolated loopback application and uses a temporary signing secret for its signed webhook test. Select a fresh runtime for each result:

```powershell
python -m scripts.verify_backend --runtime .runtime/my-backend-verification
python -m scripts.verify_portfolio --completion --channel chrome --runtime .runtime/my-browser-verification
```

## Optional AI and browser settings

- **Offline**. Choose `offline` in the AI Task node. It runs without credentials.
- **Ollama**. Start an existing local Ollama daemon with a model you have already installed. Set `AGENTFORGE_OLLAMA_MODELS` to the approved comma-separated model names. The adapter uses 127.0.0.1:11434 and fixed API paths.
- **OpenAI-compatible**. Set `AGENTFORGE_OPENAI_BASE_URL` to your approved HTTPS API base, including `/v1` when required. Set `AGENTFORGE_OPENAI_MODELS` and `AGENTFORGE_SECRET_OPENAI` in the backend environment. Enable requests only with authorization for provider charges.
- **Availability**. Use the provider’s Check button under Integrations. It checks the model-list API without requesting a completion.
- **Browser**. Set `AGENTFORGE_BROWSER_HOSTS` to exact approved public HTTPS hostnames. Only approved HTML retrieval and static extraction are supported. Use the bundled fixtures for offline runs.

Windows asyncio can require loopback for its internal wake-up socket even though ASGI tests use HTTPX in-process. On Windows, install the optional event loop in the test environment to run ASGI verification without binding a listener:

```powershell
python -m pip install winloop==0.8.4
python -m scripts.verify_backend --winloop --runtime .runtime/my-asgi-tests
python -m scripts.verify_browser_asgi --winloop --channel chrome --runtime .runtime/my-asgi-browser
```

The Chrome command loads the actual production bundle and forwards browser requests to the running FastAPI ASGI app. The server-based verifier still requires explicit Windows loopback permission. See [deployment](DEPLOYMENT.md) for Docker and the distributed backend.
