# Workforce agent worker (planner, specialists, verifier, browser). Build from repo root:
#   docker build -f apps/worker/Dockerfile -t workforce-worker .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
RUN uv sync --locked --no-dev --package workforce-worker --no-install-workspace

# Chromium for the agent browser, with its system libraries.
RUN /app/.venv/bin/playwright install --with-deps chromium

COPY packages/core packages/core
COPY apps/worker apps/worker
RUN uv sync --locked --no-dev --package workforce-worker

RUN useradd --create-home --uid 10001 app
USER app

# Exec form: the worker is PID 1 and receives SIGTERM directly, so on redeploy it
# hands its in-progress task back for another worker to resume.
CMD ["/app/.venv/bin/python", "-m", "workforce_worker"]
