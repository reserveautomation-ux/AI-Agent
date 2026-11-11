"""The API can set up a fresh database by itself, and does nothing the second time."""

import asyncio
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from workforce_core.migrate import migrate

ROOT = Path(__file__).resolve().parents[3]
STUB = ROOT / "supabase" / "tests" / "supabase_stub.sql"
MIGRATIONS = ROOT / "supabase" / "migrations"


@pytest.fixture
def fresh_db(request):
    import os

    base = os.environ.get("TEST_DATABASE_URL")
    if not base:
        pytest.skip("TEST_DATABASE_URL not set")
    name = f"wf_mig_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    url = base.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(url, autocommit=True) as c:
        c.execute(STUB.read_text())  # what a Supabase project already has (auth schema, roles)
    yield url
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(name)))


def test_sets_up_a_fresh_database_once(fresh_db):
    first = asyncio.run(migrate(fresh_db, MIGRATIONS))
    assert first == [p.name.split("_", 1)[0] for p in sorted(MIGRATIONS.glob("*.sql"))]
    assert asyncio.run(migrate(fresh_db, MIGRATIONS)) == []
    with psycopg.connect(fresh_db) as c:
        assert c.execute("select to_regclass('public.chat_messages') is not null").fetchone()[0]


def test_adopts_a_database_set_up_with_the_supabase_cli(fresh_db):
    files = sorted(MIGRATIONS.glob("*.sql"))
    with psycopg.connect(fresh_db, autocommit=True) as c:
        for p in files[:-1]:  # the CLI applied all but the newest
            c.execute(p.read_text())
        c.execute("create schema supabase_migrations")
        c.execute("create table supabase_migrations.schema_migrations (version text primary key)")
        for p in files[:-1]:
            c.execute(
                "insert into supabase_migrations.schema_migrations values (%s)",
                (p.name.split("_", 1)[0],),
            )
    assert asyncio.run(migrate(fresh_db, MIGRATIONS)) == [files[-1].name.split("_", 1)[0]]
