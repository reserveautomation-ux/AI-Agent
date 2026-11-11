import time

import jwt
import pytest
from fastapi.testclient import TestClient
from workforce_api.config import Settings
from workforce_api.main import create_app
from workforce_core.workforce import AGENTS

SECRET = "test-jwt-secret-that-is-long-enough-for-hs256"
SUPABASE_URL = "https://example.supabase.co"


@pytest.fixture(scope="module")
def client(database_url):
    settings = Settings(
        database_url=database_url, supabase_url=SUPABASE_URL, supabase_jwt_secret=SECRET
    )
    with TestClient(create_app(settings)) as c:
        yield c


def token_for(user_id: str, **overrides) -> str:
    claims = {
        "sub": user_id,
        "aud": "authenticated",
        "iss": f"{SUPABASE_URL}/auth/v1",
        "exp": int(time.time()) + 3600,
        "email": "owner@example.com",
        "role": "authenticated",
        **overrides,
    }
    return jwt.encode(claims, SECRET, algorithm="HS256")


def auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {token_for(user_id)}"}


# --- auth ---------------------------------------------------------------------


def test_requires_valid_token(client, make_user):
    uid = make_user()
    assert client.get("/tasks").status_code == 401
    assert client.get("/tasks", headers={"Authorization": "Bearer junk"}).status_code == 401
    expired = token_for(uid, exp=int(time.time()) - 10)
    assert client.get("/tasks", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    wrong_iss = token_for(uid, iss="https://evil.example/auth/v1")
    assert client.get("/tasks", headers={"Authorization": f"Bearer {wrong_iss}"}).status_code == 401


def test_me_returns_workspace(client, make_user):
    uid = make_user()
    body = client.get("/me", headers=auth(uid)).json()
    assert body["user_id"] == uid
    assert body["workspace"]["role"] == "owner"
    assert body["workspace"]["kill_switch"] is False


# --- tasks --------------------------------------------------------------------


def test_create_list_get_cancel_task(client, make_user):
    uid = make_user()
    h = auth(uid)
    objective = "Find 50 fitness creators in Mumbai\nwith >10k followers"
    r = client.post("/tasks", json={"objective": objective}, headers=h)
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["status"] == "draft"
    assert task["title"] == "Find 50 fitness creators in Mumbai"

    assert [t["id"] for t in client.get("/tasks", headers=h).json()] == [task["id"]]
    assert client.get("/tasks?status=draft", headers=h).json()[0]["id"] == task["id"]
    assert client.get("/tasks?status=running", headers=h).json() == []

    detail = client.get(f"/tasks/{task['id']}", headers=h).json()
    assert [e["to_status"] for e in detail["events"]] == ["draft"]
    assert detail["events"][0]["actor_type"] == "user"

    r = client.post(f"/tasks/{task['id']}/cancel", json={"reason": "changed my mind"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/tasks/{task['id']}/cancel", headers=h).status_code == 409

    events = client.get(f"/tasks/{task['id']}", headers=h).json()["events"]
    assert events[-1]["reason"] == "changed my mind"

    actions = [a["action"] for a in client.get("/audit", headers=h).json()]
    assert actions[:2] == ["task.cancelled", "task.created"]


def test_tasks_are_isolated_between_workspaces(client, make_user):
    alice, bob = make_user(), make_user()
    task = client.post("/tasks", json={"objective": "private"}, headers=auth(alice)).json()
    assert client.get(f"/tasks/{task['id']}", headers=auth(bob)).status_code == 404
    assert client.post(f"/tasks/{task['id']}/cancel", headers=auth(bob)).status_code == 404
    assert client.get("/tasks", headers=auth(bob)).json() == []
    assert client.get("/tasks/not-a-uuid", headers=auth(alice)).status_code == 404


def test_task_validation_and_budget_policy(client, make_user):
    h = auth(make_user())
    assert client.post("/tasks", json={"objective": "   "}, headers=h).status_code == 422
    r = client.post("/tasks", json={"objective": "x", "budget_limit_usd": 500}, headers=h)
    assert r.status_code == 422 and "policy maximum" in r.text
    assert (
        client.post("/tasks", json={"objective": "x", "budget_limit_usd": 2}, headers=h).status_code
        == 201
    )


def test_kill_switch_blocks_new_tasks(client, make_user):
    h = auth(make_user())
    assert client.post("/workspace/kill-switch", json={"enabled": True}, headers=h).json()[
        "kill_switch"
    ]
    assert client.post("/tasks", json={"objective": "x"}, headers=h).status_code == 423
    client.post("/workspace/kill-switch", json={"enabled": False}, headers=h)
    assert client.post("/tasks", json={"objective": "x"}, headers=h).status_code == 201


# --- workforce ----------------------------------------------------------------


def _bootstrap(client, h):
    r = client.post("/workforce/bootstrap", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_bootstrap_builds_hierarchy_idempotently(client, make_user):
    h = auth(make_user())
    wf = _bootstrap(client, h)
    assert len(wf["agents"]) == len(AGENTS)
    assert len(_bootstrap(client, h)["agents"]) == len(AGENTS)

    by_role = {}
    for a in wf["agents"]:
        by_role.setdefault(a["role"], []).append(a)
    chief = by_role["chief"][0]
    assert all(a["parent_agent_id"] == chief["id"] for a in by_role["department_head"])
    heads = {a["id"] for a in by_role["department_head"]}
    for a in by_role["specialist"]:
        expected = heads if a["department_id"] else {chief["id"]}
        assert a["parent_agent_id"] in expected, a["name"]
    assert all(d["manager_agent_id"] in heads for d in wf["departments"])


def test_clone_promote_retire_flow(client, make_user, db):
    uid = make_user()
    h = auth(uid)
    wf = _bootstrap(client, h)
    web = next(a for a in wf["agents"] if a["template_key"] == "rs_web")
    chief = next(a for a in wf["agents"] if a["role"] == "chief")

    r = client.post(f"/agents/{web['id']}/clone", headers=h)
    assert r.status_code == 201, r.text
    clone = r.json()
    assert clone["status"] == "sandbox"
    assert clone["allowed_tools"] == web["allowed_tools"]
    assert clone["lineage_id"] == web["id"]

    # Clones only go live after passing evaluation.
    r = client.post(f"/agents/{clone['id']}/promote", headers=h)
    assert r.status_code == 409 and "evaluation" in r.text
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    db.execute(
        "insert into agent_evaluations (workspace_id, agent_id, agent_version, evaluation_window,"
        " success_rate, quality_score, sample_size)"
        " values (%s, %s, 1, tstzrange(now() - interval '1 day', now()), 0.92, 0.9, 30)",
        (ws, clone["id"]),
    )
    assert client.post(f"/agents/{clone['id']}/promote", headers=h).json()["status"] == "active"

    # Replica cap: original + 2 clones max.
    assert client.post(f"/agents/{web['id']}/clone", headers=h).status_code == 201
    assert client.post(f"/agents/{web['id']}/clone", headers=h).status_code == 409

    assert client.post(f"/agents/{clone['id']}/retire", headers=h).json()["status"] == "retired"
    assert client.post(f"/agents/{clone['id']}/retire", headers=h).status_code == 409
    assert client.post(f"/agents/{chief['id']}/retire", headers=h).status_code == 409
    assert client.post(f"/agents/{chief['id']}/clone", headers=h).status_code == 409


def test_lifecycle_review_clones_strong_and_suspends_weak(client, make_user, db):
    uid = make_user()
    h = auth(uid)
    wf = _bootstrap(client, h)
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    strong = next(a for a in wf["agents"] if a["template_key"] == "pe_email")
    weak = next(a for a in wf["agents"] if a["template_key"] == "sh_orders")
    for agent, success in ((strong, 0.97), (weak, 0.3)):
        db.execute(
            "insert into agent_evaluations (workspace_id, agent_id, agent_version,"
            " evaluation_window, success_rate, quality_score, sample_size)"
            " values (%s, %s, 1, tstzrange(now() - interval '7 days', now()), %s, 0.9, 40)",
            (ws, agent["id"], success),
        )

    preview = client.post("/workforce/lifecycle-review", headers=h).json()
    by_id = {d["agent_id"]: d for d in preview}
    assert by_id[strong["id"]]["action"] == "clone" and not by_id[strong["id"]]["applied"]
    assert by_id[weak["id"]]["action"] == "suspend"

    applied = client.post("/workforce/lifecycle-review?apply=true", headers=h).json()
    by_id = {d["agent_id"]: d for d in applied}
    assert by_id[strong["id"]]["new_agent_id"]
    assert by_id[weak["id"]]["applied"]

    agents = {a["id"]: a for a in client.get("/workforce", headers=h).json()["agents"]}
    assert agents[weak["id"]]["status"] == "suspended"
    assert agents[by_id[strong["id"]]["new_agent_id"]]["status"] == "sandbox"

    # Second review: the weak agent is still weak while suspended -> retired.
    again = client.post("/workforce/lifecycle-review?apply=true", headers=h).json()
    assert {d["agent_id"]: d for d in again}[weak["id"]]["action"] == "retire"


def test_integrations_register(client, make_user):
    body = client.get("/integrations", headers=auth(make_user())).json()
    access = {i["key"]: i["access"] for i in body}
    assert access["gmail"] == "official_api"
    assert access["deep_links"] == "deep_link"


def test_bootstrap_adds_only_missing_agents(client, make_user, db):
    uid = make_user()
    h = auth(uid)
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    # An older workspace that only ever hired the chief.
    db.execute(
        "insert into agents (workspace_id, name, role, status, template_key)"
        " values (%s, 'Chief AI Executive', 'chief', 'active', 'chief')",
        (ws,),
    )
    wf = _bootstrap(client, h)
    assert len(wf["agents"]) == len(AGENTS)
    chiefs = [a for a in wf["agents"] if a["role"] == "chief"]
    assert len(chiefs) == 1
    generalist = next(a for a in wf["agents"] if a["template_key"] == "generalist")
    assert generalist["parent_agent_id"] == chiefs[0]["id"]
    assert generalist["department_id"] is None


def test_capabilities_catalog(client, make_user):
    caps = client.get("/capabilities", headers=auth(make_user())).json()
    by_key = {c["key"]: c for c in caps}
    assert by_key["research"]["handling"] == "automatic"
    assert by_key["cab"]["handling"] == "you_confirm_in_app"
    assert by_key["stock_orders"]["handling"] == "owner_approval"


# --- memory -------------------------------------------------------------------


def test_memory_api(client, make_user):
    h = auth(make_user())
    r = client.post(
        "/memories",
        json={"content": "I prefer aisle seats", "memory_type": "preference", "pinned": True},
        headers=h,
    )
    assert r.status_code == 201, r.text
    mem = r.json()
    assert mem["trusted"] and mem["pinned"] and mem["source_type"] == "user"

    r = client.post("/memories", json={"content": "my bank OTP is 445566"}, headers=h)
    assert r.status_code == 422 and "OTP" in r.text

    assert [m["id"] for m in client.get("/memories?q=aisle", headers=h).json()] == [mem["id"]]
    assert client.get("/memories?q=zebra", headers=h).json() == []

    assert not client.post(f"/memories/{mem['id']}/pin", json={"pinned": False}, headers=h).json()[
        "pinned"
    ]
    assert client.delete(f"/memories/{mem['id']}", headers=h).status_code == 204
    assert client.get("/memories", headers=h).json() == []

    other = auth(make_user())
    assert client.delete(f"/memories/{mem['id']}", headers=other).status_code == 404


def test_confirming_agent_memory_makes_it_trusted(client, make_user, db):
    uid = make_user()
    h = auth(uid)
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    mid = db.execute(
        "insert into memories (workspace_id, owner_scope, memory_type, content, source_type)"
        " values (%s, 'workspace', 'fact', 'Office closes at 7pm', 'agent') returning id::text",
        (ws,),
    ).fetchone()[0]
    assert not client.get("/memories", headers=h).json()[0]["trusted"]
    assert client.post(f"/memories/{mid}/confirm", headers=h).json()["trusted"]


def test_task_detail_retry_and_download(client, make_user, db):
    h = auth(make_user())
    task = client.post("/tasks", json={"objective": "List creators"}, headers=h).json()
    ws = client.get("/me", headers=h).json()["workspace"]["id"]

    # Simulate a worker that got blocked on budget after saving a file.
    db.execute(
        "insert into artifacts (workspace_id, task_id, name, storage_uri, file_type,"
        " checksum_sha256, size_bytes, content, preview) values (%s, %s, 'list.csv', 'inline',"
        " 'text/csv', 'x', 7, convert_to('a,b', 'UTF8'), 'a,b')",
        (ws, task["id"]),
    )
    db.execute("update tasks set status = 'planned' where id = %s", (task["id"],))
    db.execute(
        "update tasks set status = 'blocked', result_summary = 'budget reached' where id = %s",
        (task["id"],),
    )

    detail = client.get(f"/tasks/{task['id']}", headers=h).json()
    assert detail["status"] == "blocked" and detail["artifacts"][0]["name"] == "list.csv"
    art_id = detail["artifacts"][0]["id"]
    r = client.get(f"/artifacts/{art_id}", headers=h)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "list.csv" in r.headers["content-disposition"]
    assert client.get(f"/artifacts/{art_id}", headers=auth(make_user())).status_code == 404

    r = client.post(f"/tasks/{task['id']}/retry", json={"answer": "Only Mumbai"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "planned"  # no steps yet -> re-plan
    assert "Owner's answer: Only Mumbai" in r.json()["objective"]
    assert client.post(f"/tasks/{task['id']}/retry", headers=h).status_code == 409


def test_device_registration(client, make_user, db):
    alice, bob = make_user(), make_user()
    token = "ExponentPushToken[phone-1234567]"
    body = {"token": token, "platform": "android", "device_name": "Pixel"}
    assert client.post("/devices", json=body, headers=auth(alice)).status_code == 204
    # Same phone signs in as someone else -> it now belongs to them.
    assert client.post("/devices", json=body, headers=auth(bob)).status_code == 204
    owner = db.execute(
        "select user_id::text from push_devices where token = %s", (token,)
    ).fetchone()[0]
    assert owner == bob
    assert (
        client.post("/devices", json={**body, "platform": "symbian"}, headers=auth(bob)).status_code
        == 422
    )
    assert (
        client.post("/devices/unregister", json={"token": token}, headers=auth(bob)).status_code
        == 204
    )
    assert db.execute(
        "select disabled_at is not null from push_devices where token = %s", (token,)
    ).fetchone()[0]


# --- approvals ----------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from psycopg.types.json import Jsonb  # noqa: E402
from workforce_core.approvals import binding_for, binding_from_row  # noqa: E402


def _waiting_task(client, db, h):
    task = client.post("/tasks", json={"objective": "Email Rahul"}, headers=h).json()
    for s in ("planned", "queued", "running", "verifying", "waiting_for_approval"):
        db.execute("update tasks set status = %s where id = %s", (s, task["id"]))
    return task


def _approval(db, ws, task_id, action="send_email", args=None, tier=2, expires_in=3600):
    args = args or {"to": "rahul@example.com", "subject": "Review", "body": "Moved to Friday."}
    expires = datetime.now(UTC) + timedelta(seconds=expires_in)
    policy = db.execute(
        "select id::text, version from policies where workspace_id = %s", (ws,)
    ).fetchone()
    b = binding_for(
        task_id=task_id, action=action, args=args, expires_at=expires, policy_version=policy[1]
    )
    inv = db.execute(
        "insert into tool_invocations (workspace_id, task_id, tool_name, risk_tier,"
        " idempotency_key, arguments_hash, arguments_json, status)"
        " values (%s, %s, %s, %s, gen_random_uuid()::text, %s, %s, 'awaiting_approval')"
        " returning id::text",
        (ws, task_id, action, tier, b.action_hash(), Jsonb(args)),
    ).fetchone()[0]
    return db.execute(
        "insert into approval_requests (workspace_id, task_id, tool_invocation_id, action,"
        " action_payload, action_hash, amount, currency, recipient, item, policy_id,"
        " policy_version, risk_tier, expires_at) values"
        " (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id::text",
        (
            ws,
            task_id,
            inv,
            action,
            Jsonb(args),
            b.action_hash(),
            b.amount,
            b.currency,
            b.recipient,
            b.item,
            policy[0],
            policy[1],
            tier,
            expires,
        ),
    ).fetchone()[0]


def _task_status(db, task_id):
    return db.execute("select status::text from tasks where id = %s", (task_id,)).fetchone()[0]


def test_approve_flow(client, make_user, db):
    h = auth(make_user())
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    task = _waiting_task(client, db, h)
    a1 = _approval(db, ws, task["id"])
    a2 = _approval(
        db, ws, task["id"], args={"to": "asha@example.com", "subject": "Hi", "body": "See you"}
    )

    pending = client.get("/approvals", headers=h).json()
    assert {p["id"] for p in pending} == {a1, a2}
    item = next(p for p in pending if p["id"] == a1)
    assert item["task_title"] == "Email Rahul" and not item["owner_only"]

    # Wrong hash = the owner saw something else -> refused.
    r = client.post(f"/approvals/{a1}/approve", json={"action_hash": "0" * 64}, headers=h)
    assert r.status_code == 409 and "changed" in r.text

    r = client.post(
        f"/approvals/{a1}/approve", json={"action_hash": item["action_hash"]}, headers=h
    )
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert _task_status(db, task["id"]) == "waiting_for_approval"  # a2 still pending
    assert (
        client.post(
            f"/approvals/{a1}/approve", json={"action_hash": item["action_hash"]}, headers=h
        ).status_code
        == 409
    )  # already decided

    item2 = next(p for p in pending if p["id"] == a2)
    r = client.post(
        f"/approvals/{a2}/reject",
        json={"action_hash": item2["action_hash"], "reason": "not needed"},
        headers=h,
    )
    assert r.json()["status"] == "rejected" and r.json()["execution_status"] == "denied"
    assert _task_status(db, task["id"]) == "running"  # nothing left waiting -> worker resumes

    mine = client.get(f"/approvals?state=all&task_id={task['id']}", headers=h).json()
    assert {a["id"] for a in mine} == {a1, a2}
    assert client.get("/approvals?task_id=nope", headers=h).status_code == 404
    decided = client.get("/approvals?state=decided", headers=h).json()
    assert {d["status"] for d in decided} == {"approved", "rejected"}
    events = db.execute(
        "select decision from approval_events where approval_id in (%s, %s)", (a1, a2)
    ).fetchall()
    assert sorted(e[0] for e in events) == ["approved", "rejected"]


def test_edit_then_approve_rebinds_exact_action(client, make_user, db):
    h = auth(make_user())
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    task = _waiting_task(client, db, h)
    aid = _approval(db, ws, task["id"])
    old = client.get("/approvals", headers=h).json()[0]

    r = client.post(
        f"/approvals/{aid}/approve",
        json={
            "action_hash": old["action_hash"],
            "changes": {"body": "Moved to Friday 4pm. Thanks!"},
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    new = r.json()
    assert new["action_payload"]["body"] == "Moved to Friday 4pm. Thanks!"
    assert new["action_hash"] != old["action_hash"]
    row = db.execute(
        "select task_id, action, action_payload, amount, currency, recipient, item,"
        " account_ref, expires_at, policy_version from approval_requests"
        " where id = %s",
        (aid,),
    ).fetchone()
    cols = [
        "task_id",
        "action",
        "action_payload",
        "amount",
        "currency",
        "recipient",
        "item",
        "account_ref",
        "expires_at",
        "policy_version",
    ]
    assert binding_from_row(dict(zip(cols, row, strict=True))).action_hash() == new["action_hash"]
    args = db.execute(
        "select arguments_json->>'body' from tool_invocations where task_id = %s", (task["id"],)
    ).fetchone()[0]
    assert args == "Moved to Friday 4pm. Thanks!"

    # Only existing text fields can be edited.
    aid2 = _approval(db, ws, task["id"])
    h2 = next(p for p in client.get("/approvals", headers=h).json() if p["id"] == aid2)
    r = client.post(
        f"/approvals/{aid2}/approve",
        json={"action_hash": h2["action_hash"], "changes": {"bcc": "x@y.z"}},
        headers=h,
    )
    assert r.status_code == 422


def test_tampering_and_expiry_are_caught(client, make_user, db):
    h = auth(make_user())
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    task = _waiting_task(client, db, h)
    aid = _approval(db, ws, task["id"])
    shown = client.get("/approvals", headers=h).json()[0]["action_hash"]
    # Someone changes the stored recipient without going through the system.
    db.execute(
        "update approval_requests set action_payload = action_payload ||"
        ' \'{"to": "attacker@evil.example"}\' where id = %s',
        (aid,),
    )
    r = client.post(f"/approvals/{aid}/approve", json={"action_hash": shown}, headers=h)
    assert r.status_code == 409 and "integrity" in r.text

    task2 = _waiting_task(client, db, h)
    old = _approval(db, ws, task2["id"], expires_in=-5)
    assert old not in [p["id"] for p in client.get("/approvals", headers=h).json()]
    assert (
        db.execute("select status::text from approval_requests where id = %s", (old,)).fetchone()[0]
        == "expired"
    )
    assert _task_status(db, task2["id"]) == "running"


def test_money_actions_need_the_owner(client, make_user, db):
    owner, admin = make_user(), make_user()
    h = auth(owner)
    ws = client.get("/me", headers=h).json()["workspace"]["id"]
    db.execute(
        "insert into workspace_members (workspace_id, user_id, role) values (%s, %s, 'admin')",
        (ws, admin),
    )
    task = _waiting_task(client, db, h)
    aid = _approval(
        db,
        ws,
        task["id"],
        action="book_flight",
        tier=3,
        args={"offer_id": "off_1", "amount": 4999.5, "currency": "INR"},
    )
    item = client.get("/approvals", headers=h).json()[0]
    assert item["owner_only"] and item["amount"] == "4999.5000"

    admin_h = {**auth(admin), "X-Workspace-Id": ws}
    r = client.post(
        f"/approvals/{aid}/approve", json={"action_hash": item["action_hash"]}, headers=admin_h
    )
    assert r.status_code == 403
    r = client.post(
        f"/approvals/{aid}/approve", json={"action_hash": item["action_hash"]}, headers=h
    )
    assert r.status_code == 200
    # Strangers can't see or decide it.
    assert client.get("/approvals", headers=auth(make_user())).json() == []


def test_timezone_defaults_to_india_and_can_change(client, make_user):
    h = auth(make_user())
    assert client.get("/me", headers=h).json()["workspace"]["timezone"] == "Asia/Kolkata"
    r = client.post("/workspace/timezone", json={"timezone": "Europe/London"}, headers=h)
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/London"
    assert (
        client.post("/workspace/timezone", json={"timezone": "Mars/Base"}, headers=h).status_code
        == 422
    )
