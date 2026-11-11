"""Set up and upgrade the database automatically when the API starts (no terminal needed).

Applies supabase/migrations/*.sql in order, each in its own transaction, and records them
in public.workforce_migrations. Only one server migrates at a time (advisory lock). If the
database was set up earlier with the Supabase CLI, those migrations are recognised.
"""

import logging
from pathlib import Path

from psycopg import AsyncConnection

log = logging.getLogger(__name__)

LOCK = 72_011_235  # any constant; shared by every API instance


def _version(path: Path) -> str:
    return path.name.split("_", 1)[0]


async def migrate(database_url: str, directory: Path) -> list[str]:
    """Apply pending migrations; returns the versions applied now."""
    files = sorted(directory.glob("*.sql"))
    if not files:
        raise RuntimeError(f"no migrations found in {directory}")
    applied_now: list[str] = []
    async with await AsyncConnection.connect(
        database_url, autocommit=True, prepare_threshold=None
    ) as conn:
        await conn.execute("select pg_advisory_lock(%s)", (LOCK,))
        try:
            await conn.execute(
                "create table if not exists public.workforce_migrations ("
                " version text primary key, name text not null,"
                " applied_at timestamptz not null default now())"
            )
            await conn.execute("alter table public.workforce_migrations enable row level security")
            done = {
                r[0]
                for r in await (
                    await conn.execute("select version from public.workforce_migrations")
                ).fetchall()
            }
            if not done and await _table_exists(conn, "public", "workspaces"):
                done = await _adopt_cli_history(conn, files)
            for path in files:
                version = _version(path)
                if version in done:
                    continue
                log.info("applying migration %s", path.name)
                async with conn.transaction():
                    await conn.execute(path.read_text())
                    await conn.execute(
                        "insert into public.workforce_migrations (version, name) values (%s, %s)",
                        (version, path.name),
                    )
                applied_now.append(version)
        finally:
            await conn.execute("select pg_advisory_unlock(%s)", (LOCK,))
    return applied_now


async def _table_exists(conn: AsyncConnection, schema: str, table: str) -> bool:
    row = await (
        await conn.execute("select to_regclass(%s) is not null", (f"{schema}.{table}",))
    ).fetchone()
    return bool(row[0])


async def _adopt_cli_history(conn: AsyncConnection, files: list[Path]) -> set[str]:
    """The schema exists but we have no record: it was set up with `supabase db push`."""
    if not await _table_exists(conn, "supabase_migrations", "schema_migrations"):
        raise RuntimeError(
            "The database already has Workforce OS tables but no migration history. "
            "Use a fresh Supabase project, or apply migrations with `supabase db push`."
        )
    rows = await (
        await conn.execute("select version from supabase_migrations.schema_migrations")
    ).fetchall()
    cli = {r[0] for r in rows}
    known = {_version(p): p.name for p in files if _version(p) in cli}
    for version, name in known.items():
        await conn.execute(
            "insert into public.workforce_migrations (version, name) values (%s, %s)"
            " on conflict do nothing",
            (version, name),
        )
    return set(known)
