from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from psycopg.types.json import Jsonb
from workforce_core.db import make_pool
from workforce_core.tools import TOOLS

from .config import Settings, get_settings
from .deps import ConnDep
from .routes import tasks, workforce, workspace


async def sync_tool_definitions(pool) -> None:
    """Upsert the code-defined tool registry into public.tool_definitions."""
    async with pool.connection() as conn, conn.transaction():
        for t in TOOLS:
            await conn.execute(
                """insert into public.tool_definitions
                       (name, category, description, risk_tier, input_schema, enabled)
                   values (%s, %s, %s, %s, %s, true)
                   on conflict (name) do update set
                       category = excluded.category, description = excluded.description,
                       risk_tier = excluded.risk_tier, input_schema = excluded.input_schema,
                       updated_at = now()""",
                (t.name, t.category, t.description, int(t.risk_tier), Jsonb(t.input_schema)),
            )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pool = make_pool(settings.database_url)
        await pool.open(wait=True)
        await sync_tool_definitions(pool)
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
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Workspace-Id"],
    )

    @app.get("/health", tags=["health"])
    async def health(conn: ConnDep) -> dict:
        await conn.execute("select 1")
        return {"status": "ok"}

    app.include_router(workspace.router)
    app.include_router(tasks.router)
    app.include_router(workforce.router)
    return app


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory workforce_api.main:app_factory``."""
    return create_app()
