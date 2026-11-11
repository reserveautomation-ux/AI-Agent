# Workforce API. Build from the repository root:
#   docker build -f apps/api/Dockerfile -t workforce-api .
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN pip install --no-cache-dir uv==0.11.32

WORKDIR /app

# Dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
COPY packages/core/pyproject.toml packages/core/
COPY apps/api/pyproject.toml apps/api/
COPY apps/worker/pyproject.toml apps/worker/
RUN uv sync --locked --no-dev --package workforce-api --no-install-workspace

COPY packages/core packages/core
COPY apps/api apps/api
RUN uv sync --locked --no-dev --package workforce-api

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
# Hosts like Render set $PORT. --proxy-headers: trust X-Forwarded-* from the host's proxy.
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn --factory workforce_api.main:app_factory --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
