"""Shared pytest fixtures.

Database tests need TEST_DATABASE_URL pointing at any Postgres server you can
create databases on (``scripts/test-db.sh start`` prints one). Each test session
creates a fresh database, applies the Supabase stub and all migrations, and
drops it afterwards. Without TEST_DATABASE_URL, database tests are skipped.
"""

import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

ROOT = Path(__file__).parent
MIGRATIONS = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
STUB = ROOT / "supabase" / "tests" / "supabase_stub.sql"


def _with_db(url: str, dbname: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{dbname}"


@pytest.fixture(scope="session")
def database_url():
    server_url = os.environ.get("TEST_DATABASE_URL")
    if not server_url:
        pytest.skip("TEST_DATABASE_URL not set (run scripts/test-db.sh start)")
    dbname = f"wf_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(server_url, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(dbname)))
    url = _with_db(server_url, dbname)
    try:
        with psycopg.connect(url, autocommit=True) as conn:
            for path in [STUB, *MIGRATIONS]:
                conn.execute(path.read_text())
        yield url
    finally:
        with psycopg.connect(server_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(dbname))
            )


@pytest.fixture
def db(database_url):
    with psycopg.connect(database_url, autocommit=True) as conn:
        yield conn


def create_auth_user(conn, email: str | None = None) -> str:
    """Insert into auth.users (as Supabase Auth would); the trigger creates a workspace."""
    user_id = str(uuid.uuid4())
    conn.execute(
        "insert into auth.users (id, email) values (%s, %s)",
        (user_id, email or f"{user_id[:8]}@example.com"),
    )
    return user_id


@pytest.fixture
def make_user(db):
    return lambda email=None: create_auth_user(db, email)
