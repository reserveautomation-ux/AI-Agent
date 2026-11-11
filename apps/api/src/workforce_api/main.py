from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from workforce_core.db import make_pool, sync_tool_definitions

from .config import Settings, get_settings
from .deps import ConnDep
from .routes import memory, tasks, workforce, workspace


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = make_pool(settings.database_url)
        await pool.open(wait=True)
        async with pool.connection() as conn:
            await sync_tool_definitions(conn)
        app.state.pool = pool
        try:
            yield
        finally:
            await pool.close()

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
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory workforce_api.main:app_factory``."""
    return create_app()
