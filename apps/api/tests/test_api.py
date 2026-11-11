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
    assert all(a["parent_agent_id"] in heads for a in by_role["specialist"])
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
