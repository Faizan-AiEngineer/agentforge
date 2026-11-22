# Technology decisions

- SQLite and a single-process worker keep offline Windows setup small. SQLAlchemy and Alembic provide schema management.
- FastAPI and Pydantic define public contracts and publish OpenAPI.
- A topological traversal is sufficient for the bounded graph. No graph library is needed.
- React Flow supplies the interactive graph surface. React, TypeScript and Vite host the workspace.
- Theme tokens and responsive styles live in custom CSS. The local preview can serve the Vite build through FastAPI.
- Node output references use a constrained lookup grammar. Conditions use typed operators.
- HTTP requests use a bounded HTTPS transport. Browser fixtures use network-isolated contexts.
- The HTTP transport uses Python's HTTPSConnection to pin the checked destination address and validate the original TLS hostname. HTTPX is used by the test and verification clients.
- Offline text operations are explicitly deterministic. Integration endpoints require administrative configuration.
- The verified Windows environment uses Python 3.13.2 and Node.js 20.20.2. Python dependencies have direct pins and the frontend has an npm lockfile.
