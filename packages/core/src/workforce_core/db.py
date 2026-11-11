"""Database helpers shared by the API and workers."""

from typing import Any, Literal

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

ActorType = Literal["user", "agent", "worker", "system"]


def make_pool(database_url: str, *, min_size: int = 1, max_size: int = 10) -> AsyncConnectionPool:
    # prepare_threshold=None: Supabase's transaction-mode pooler (port 6543)
    # does not support server-side prepared statements.
    # autocommit=True: writers must open an explicit ``conn.transaction()`` so the
    # commit happens inside the request handler, before a response is sent.
    return AsyncConnectionPool(
        database_url,
        min_size=min_size,
        max_size=max_size,
        open=False,
        kwargs={"row_factory": dict_row, "prepare_threshold": None, "autocommit": True},
    )


async def set_actor(
    conn: AsyncConnection,
    actor_type: ActorType,
    actor_id: str | None,
    reason: str | None = None,
) -> None:
    """Attribute writes in the current transaction (read by DB triggers)."""
    await conn.execute(
        "select set_config('app.actor_type', %s, true),"
        " set_config('app.actor_id', %s, true),"
        " set_config('app.reason', %s, true)",
        (actor_type, actor_id or "", reason or ""),
    )


async def record_audit(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    actor_type: ActorType,
    actor_id: str | None,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    event: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        "insert into public.audit_events"
        " (workspace_id, actor_type, actor_id, action, target_type, target_id, event_json)"
        " values (%s, %s, %s, %s, %s, %s, %s)",
        (workspace_id, actor_type, actor_id, action, target_type, target_id, Jsonb(event or {})),
    )
