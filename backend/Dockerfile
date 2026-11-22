FROM python:3.12-slim
WORKDIR /opt/agentforge
ARG AGENTFORGE_DISTRIBUTED=0
ARG AGENTFORGE_WITH_BROWSER=1
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENTFORGE_ROOT=/opt/runtime PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
COPY backend/requirements*.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && if [ "$AGENTFORGE_DISTRIBUTED" = 1 ]; then pip install --no-cache-dir -r backend/requirements-distributed.txt; fi \
    && if [ "$AGENTFORGE_WITH_BROWSER" = 1 ]; then playwright install --with-deps chromium; fi \
    && useradd --system --create-home agentforge \
    && install -d -o agentforge -g agentforge /opt/runtime
COPY backend backend
COPY workflows workflows
USER agentforge
CMD ["python", "-m", "uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
