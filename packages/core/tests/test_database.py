"""Tests that run the real migrations against Postgres (see conftest.py)."""

import json

import psycopg
import pytest
from workforce_core.task_states import TRANSITIONS


def _workspace_of(db, user_id):
    return db.execute(
        "select workspace_id::text from public.workspace_members where user_id = %s", (user_id,)
    ).fetchone()[0]


def _new_task(db, user_id, ws):
    return db.execute(
        "insert into public.tasks (workspace_id, title, objective, created_by)"
        " values (%s, 't', 'o', %s) returning id::text",
        (ws, user_id),
    ).fetchone()[0]


def test_python_and_sql_transitions_match(db):
    rows = db.execute("select from_status::text, to_status::text from task_status_transitions")
    sql_pairs = set(rows.fetchall())
    py_pairs = {(f.value, t.value) for f, targets in TRANSITIONS.items() for t in targets}
    assert sql_pairs == py_pairs


def test_signup_bootstraps_workspace_owner_and_policy(db, make_user):
    uid = make_user("owner@example.com")
    row = db.execute(
        "select m.role, w.owner_user_id::text, p.rules->'tiers'->>'4'"
        " from workspace_members m join workspaces w on w.id = m.workspace_id"
        " join policies p on p.workspace_id = w.id where m.user_id = %s",
        (uid,),
    ).fetchone()
    assert row == ("owner", uid, "deny")


def test_task_transitions_are_enforced_and_logged(db, make_user):
    uid = make_user()
    ws = _workspace_of(db, uid)
    task = _new_task(db, uid, ws)

    with pytest.raises(psycopg.errors.CheckViolation, match="invalid task status transition"):
        db.execute("update tasks set status = 'completed' where id = %s", (task,))

    with db.transaction():
        db.execute(
            "select set_config('app.actor_type', 'worker', true),"
            " set_config('app.reason', 'planner done', true)"
        )
        db.execute("update tasks set status = 'planned' where id = %s", (task,))

    events = db.execute(
        "select from_status::text, to_status::text, actor_type, reason from task_events"
        " where task_id = %s order by id",
        (task,),
    ).fetchall()
    assert events == [
        (None, "draft", "system", None),
        ("draft", "planned", "worker", "planner done"),
    ]


def test_tasks_must_start_in_draft(db, make_user):
    uid = make_user()
    ws = _workspace_of(db, uid)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into tasks (workspace_id, title, objective, created_by, status)"
            " values (%s, 't', 'o', %s, 'completed')",
            (ws, uid),
        )


def test_audit_log_is_append_only(db, make_user):
    uid = make_user()
    ws = _workspace_of(db, uid)
    db.execute(
        "insert into audit_events (workspace_id, actor_type, action) values (%s, 'system', 'x')",
        (ws,),
    )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("update audit_events set action = 'y' where workspace_id = %s", (ws,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("delete from audit_events where workspace_id = %s", (ws,))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("truncate audit_events")


def test_idempotency_key_prevents_duplicate_tool_runs(db, make_user):
    uid = make_user()
    ws = _workspace_of(db, uid)
    task = _new_task(db, uid, ws)
    db.execute(
        "insert into tool_definitions (name, category, description, risk_tier, input_schema)"
        " values ('idem_tool', 'test', 'd', 0, '{}') on conflict do nothing"
    )
    insert = (
        "insert into tool_invocations (workspace_id, task_id, tool_name, risk_tier,"
        " idempotency_key, arguments_hash) values (%s, %s, 'idem_tool', 0, 'k1', 'h')"
    )
    db.execute(insert, (ws, task))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, (ws, task))


def _insert_agent(db, ws, **cols):
    cols = {"workspace_id": ws, "name": "a", "role": "specialist", **cols}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    return db.execute(
        f"insert into agents ({names}) values ({marks}) returning id::text", list(cols.values())
    ).fetchone()[0]


def test_agent_guards(db, make_user):
    uid = make_user()
    ws = _workspace_of(db, uid)
    src = _insert_agent(db, ws, status="active", allowed_tools=["web_search"])

    # Clones must start in sandbox and cannot gain tools.
    with pytest.raises(psycopg.errors.CheckViolation, match="sandbox"):
        _insert_agent(db, ws, status="active", cloned_from=src, allowed_tools=["web_search"])
    with pytest.raises(psycopg.errors.CheckViolation, match="more tools"):
        _insert_agent(
            db, ws, status="sandbox", cloned_from=src, allowed_tools=["web_search", "send_email"]
        )
    clone = _insert_agent(
        db, ws, status="sandbox", cloned_from=src, lineage_id=src, allowed_tools=["web_search"]
    )
    lineage = db.execute("select lineage_id::text from agents where id = %s", (src,)).fetchone()
    assert lineage[0] == src

    # Tools cannot be widened in place; agents cannot be deleted; retirement is final.
    with pytest.raises(psycopg.errors.CheckViolation, match="widened"):
        db.execute(
            "update agents set allowed_tools = '{web_search,send_email}' where id = %s", (src,)
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        db.execute("delete from agents where id = %s", (clone,))
    db.execute("update agents set status = 'retired' where id = %s", (clone,))
    with pytest.raises(psycopg.errors.CheckViolation, match="reactivated"):
        db.execute("update agents set status = 'active' where id = %s", (clone,))


def _as_user(db, user_id):
    """Act as a Supabase 'authenticated' user inside the current transaction."""
    db.execute("set local role authenticated")
    db.execute(
        "select set_config('request.jwt.claims', %s, true)",
        (json.dumps({"sub": user_id, "role": "authenticated"}),),
    )


def test_rls_isolates_workspaces_and_blocks_direct_writes(db, make_user):
    alice, bob = make_user(), make_user()
    ws_a, ws_b = _workspace_of(db, alice), _workspace_of(db, bob)
    _new_task(db, alice, ws_a)
    _new_task(db, bob, ws_b)

    with db.transaction():
        _as_user(db, alice)
        visible = db.execute("select workspace_id::text from tasks").fetchall()
        assert {r[0] for r in visible} == {ws_a}
        assert db.execute("select count(*) from workspaces").fetchone()[0] == 1
        # Owners can read their own audit log.
        db.execute("select count(*) from audit_events").fetchone()

    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        _as_user(db, alice)
        db.execute(
            "insert into tasks (workspace_id, title, objective, created_by)"
            " values (%s, 't', 'o', %s)",
            (ws_a, alice),
        )

    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("set local role anon")
        db.execute("select count(*) from tasks")
