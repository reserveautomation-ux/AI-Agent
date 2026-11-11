import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from workforce_core.db import make_pool, sync_tool_definitions
from workforce_core.migrate import migrate

from .chat import AnthropicChat, ChatModel
from .config import Settings, get_settings
from .deps import ConnDep
from .routes import (
    approvals,
    chat,
    connections,
    memory,
    tasks,
    telegram,
    workforce,
    workspace,
)

log = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None, google_http=None, chat_model: ChatModel | None = None
) -> FastAPI:
    """``google_http``/``chat_model``: test doubles for provider calls and the chat model."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.auto_migrate:
            applied = await migrate(settings.database_url, _migrations_dir(settings))
            if applied:
                log.info("database set up / upgraded: %s", ", ".join(applied))
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
    app.state.chat_model = chat_model or (
        AnthropicChat(settings.anthropic_api_key) if settings.anthropic_api_key else None
    )
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
    app.include_router(connections.catalog_router)
    app.include_router(chat.router)
    app.include_router(telegram.router)
    return app


def _migrations_dir(settings: Settings) -> Path:
    if settings.migrations_dir:
        return Path(settings.migrations_dir)
    for parent in Path(__file__).resolve().parents:  # repo checkout or /app in the image
        candidate = parent / "supabase" / "migrations"
        if candidate.is_dir():
            return candidate
    raise RuntimeError("AUTO_MIGRATE is on but supabase/migrations wasn't found")


def app_factory() -> FastAPI:
    """Entry point for ``uvicorn --factory workforce_api.main:app_factory``."""
    return create_app()
