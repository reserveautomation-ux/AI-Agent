from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from workforce_core.db import make_pool, sync_tool_definitions

from .config import Settings, get_settings
from .deps import ConnDep
from .routes import approvals, connections, memory, tasks, workforce, workspace


def create_app(settings: Settings | None = None, google_http=None) -> FastAPI:
    """``google_http``: optional httpx.AsyncClient for Google calls (tests inject a mock)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = make_pool(settings.database_url)
        await pool.open(wait=True)
        async with pool.connection() as conn:
            await sync_tool_definitions(conn)
        app.state.pool = pool
        app.state.google_http = google_http or httpx.AsyncClient(timeout=20)
        try:
            yield
        finally:
            await pool.close()
            if google_http is None:
                await app.state.google_http.aclose()

    app = FastAPI(title="Workforce OS API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Workspace-Id"],
    )

    @app.get("/health", tags=["health"])
    async def health(conn: ConnDep) -> dict:
        await conn.execute("select 1")
        return {"status": "ok"}

    app.include_router(workspace.router)
    app.include_router(tasks.router)
    app.include_router(tasks.artifacts_router)
    app.include_router(workforce.router)
    app.include_router(memory.router)
    app.include_router(approvals.router)
    app.include_router(connections.router)
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory workforce_api.main:app_factory``."""
    return create_app()
