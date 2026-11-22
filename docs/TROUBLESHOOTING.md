# Troubleshooting

- **Backend disconnected.** Check `http://127.0.0.1:8000/ready`. Build the frontend before launching the single-server preview. If you use the Vite development server on port 5173, keep Uvicorn running on port 8000 for the API proxy.
- **Local worker lock.** Stop the other AgentForge process for this runtime, or set a different absolute `AGENTFORGE_ROOT`. The OS releases the lock when the owner exits.
- **Browser executable missing.** Set `AGENTFORGE_BROWSER=chrome` if Chrome is installed, or run `python -m playwright install chromium` and start the backend with the variable unset.
- **A node did not run.** Inspect the execution's active port and step state. Unselected branch paths are marked skipped.
- **Workflow saved but cannot run.** Drafts can contain incomplete nodes or disconnected edges. Use Validate and apply the reported fixes.
- **Scheduler missed a run while stopped.** A local restart coalesces due interval or cron activity into one occurrence per schedule check.
- **An artifact was removed manually.** The execution metadata remains and the download will return a missing file response.
