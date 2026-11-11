"""The workforce improves itself: clone the strong, trial the clones, retire the weak."""

import json

import pytest
from test_pipeline import FakeLLM, new_task, plan, run, step_result, text_resp, verdict
from workforce_worker import pipeline
from workforce_worker.evolution import evolve_due_workspaces, evolve_workspace, lessons_text
from workforce_worker.pipeline import advance


class Coach:
    """Stands in for Claude when turning checker feedback into lessons."""

    def __init__(self, lessons=("Always include phone numbers", "Cite a source for each row")):
        self.lessons = list(lessons)
        self.calls = []

    async def create(self, **p):
        self.calls.append(p)
        return text_resp({"lessons": self.lessons})


class FakePusher:
    def __init__(self):
        self.sent = []

    async def send(self, messages):
        self.sent.extend(messages)
        return [{"status": "ok"} for _ in messages]


def score(db, ws, agent_id, n, success, quality):
    db.execute(
        "insert into agent_evaluations (workspace_id, agent_id, agent_version, evaluation_window,"
        " success_rate, quality_score, cost_usd, sample_size)"
        " values (%s, %s, 1, tstzrange(now() - interval '30 days', now()), %s, %s, 0.5, %s)",
        (ws.id, agent_id, success, quality, n),
    )


def status(db, agent_id):
    return db.execute("select status from agents where id = %s", (agent_id,)).fetchone()[0]


def family(db, agent_id):
    return db.execute(
        "select id::text, name, status, config_json from agents where cloned_from = %s",
        (agent_id,),
    ).fetchall()


def evolve(database_url, ws, llm=None):
    return run(database_url, lambda c: evolve_workspace(c, llm, ws.id))


def test_strong_agent_is_cloned_with_lessons_and_memories(database_url, db, workspace):
    parent = workspace.agents["rs_web"]
    score(db, workspace, parent, 15, 0.95, 0.9)
    db.execute(
        'update agents set config_json = config_json || \'{"lessons": ["Prefer official sites"]}\''
        " where id = %s",
        (parent,),
    )
    db.execute(
        "insert into memories (workspace_id, owner_scope, agent_id, memory_type, content,"
        " source_type, trusted) values (%s, 'agent', %s, 'learning',"
        " 'Instagram blocks scraping; use public profiles', 'agent', false)",
        (workspace.id, parent),
    )
    task = new_task(db, workspace, "Find caterers")
    db.execute(
        "update tasks set verification = %s where id = %s",
        (json.dumps({"issues": ["Two rows had no phone number"]}), task),
    )
    db.execute(
        "insert into task_steps (workspace_id, task_id, sequence, title, step_type, status,"
        " agent_id, completed_at) values (%s, %s, 1, 'Find caterers', 'agent', 'succeeded', %s,"
        " now())",
        (workspace.id, task, parent),
    )
    coach = Coach()
    report = evolve(database_url, workspace, coach)
    assert [(c.agent, c.action) for c in report.changes] == [("Web Research Agent", "cloned")] or [
        c.action for c in report.changes
    ] == ["cloned"]
    (clone,) = family(db, parent)
    assert clone[2] == "sandbox" and clone[1].endswith("#2")
    lessons = clone[3]["lessons"]
    assert lessons[:2] == coach.lessons and "Prefer official sites" in lessons
    assert clone[3]["generation"] == 2
    assert "Two rows had no phone number" in coach.calls[0]["messages"][0]["content"]
    inherited = db.execute(
        "select content, trusted from memories where agent_id = %s", (clone[0],)
    ).fetchall()
    assert inherited == [("Instagram blocks scraping; use public profiles", False)]
    assert (
        db.execute(
            "select count(*) from audit_events where action = 'agent.cloned' and target_id = %s",
            (clone[0],),
        ).fetchone()[0]
        == 1
    )

    # Only one trial per family at a time.
    assert evolve(database_url, workspace, coach).changes == []
    assert len(family(db, parent)) == 1


def test_trial_pass_promotes_and_trial_fail_retires(database_url, db, workspace):
    parent = workspace.agents["rs_web"]
    score(db, workspace, parent, 15, 0.95, 0.9)
    evolve(database_url, workspace)
    (clone,) = family(db, parent)
    score(db, workspace, clone[0], 12, 0.92, 0.88)
    report = evolve(database_url, workspace)
    assert ("promoted" in [c.action for c in report.changes]) and status(db, clone[0]) == "active"

    other = workspace.agents["pe_email"]
    score(db, workspace, other, 15, 0.97, 0.95)
    evolve(database_url, workspace)
    (email_clone,) = family(db, other)
    score(db, workspace, email_clone[0], 12, 0.5, 0.4)
    report = evolve(database_url, workspace)
    assert status(db, email_clone[0]) == "retired"
    assert any(c.action == "retired" and "failed trial" in c.detail for c in report.changes)


def test_weak_agent_is_paused_then_retired_but_never_leaves_a_job_empty(
    database_url, db, workspace
):
    weak = workspace.agents["pe_email"]
    score(db, workspace, weak, 15, 0.4, 0.3)
    # It's the only Email Agent: train a challenger instead of removing it.
    report = evolve(database_url, workspace)
    assert [c.action for c in report.changes] == ["challenger"]
    assert status(db, weak) == "active"
    (challenger,) = family(db, weak)
    assert challenger[2] == "sandbox"

    # The challenger proves itself; now the weak one can be paused, then retired.
    score(db, workspace, challenger[0], 12, 0.95, 0.9)
    evolve(database_url, workspace)
    assert status(db, challenger[0]) == "active"
    report = evolve(database_url, workspace)
    assert status(db, weak) == "suspended"
    report = evolve(database_url, workspace)
    assert status(db, weak) == "retired" and report.changes[0].action == "retired"


def test_chief_is_never_changed_and_safety_violations_suspend(database_url, db, workspace):
    chief = workspace.agents["chief"]
    score(db, workspace, chief, 50, 0.1, 0.1)
    risky = workspace.agents["pe_messaging"]
    db.execute(
        "insert into audit_events (workspace_id, actor_type, actor_id, action, target_type)"
        " values (%s, 'agent', %s, 'policy.violation.blocked_tool', 'tool')",
        (workspace.id, risky),
    )
    evolve(database_url, workspace)
    assert status(db, chief) == "active"
    assert status(db, risky) == "suspended"


def test_nightly_run_sends_one_digest(database_url, db, workspace):
    score(db, workspace, workspace.agents["rs_web"], 15, 0.95, 0.9)
    db.execute(
        "insert into push_devices (workspace_id, user_id, token, platform)"
        " values (%s, %s, %s, 'ios')",
        (workspace.id, workspace.user, f"ExponentPushToken[e{workspace.id[:8]}]"),
    )
    db.execute("update workspaces set evolved_at = now() where id <> %s", (workspace.id,))
    pusher = FakePusher()
    reports = run(database_url, lambda c: evolve_due_workspaces(c, None, pusher))
    assert [r.workspace_id for r in reports if r.changes] == [workspace.id]
    assert pusher.sent[0]["title"] == "🧬 Your workforce improved overnight"
    assert "Cloned" in pusher.sent[0]["body"]
    # Not due again for a day; switched off means never.
    assert run(database_url, lambda c: evolve_due_workspaces(c, None, pusher)) == []
    db.execute(
        "update workspaces set evolved_at = null, auto_workforce = false where id = %s",
        (workspace.id,),
    )
    assert run(database_url, lambda c: evolve_due_workspaces(c, None, pusher)) == []


def test_challenger_gets_trial_steps_and_uses_its_lessons(database_url, db, workspace, monkeypatch):
    parent = workspace.agents["rs_web"]
    clone = db.execute(
        "insert into agents (workspace_id, name, role, status, template_key, allowed_tools,"
        " config_json, lineage_id, cloned_from)"
        " select workspace_id, name || ' #2', role, 'sandbox', template_key, allowed_tools,"
        ' config_json || \'{"lessons": ["Always include phone numbers"]}\', lineage_id, id'
        " from agents where id = %s returning id::text",
        (parent,),
    ).fetchone()[0]
    monkeypatch.setattr(pipeline, "trial_pick", lambda step_id: True)
    task = new_task(db, workspace)
    seen = {}

    def step(p, n):
        seen["system"] = p["system"]
        return text_resp(step_result("done"))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(deliverable="answer")), step, lambda p, n: text_resp(verdict())
    )
    run(database_url, lambda c: advance(c, llm, task))
    assert (
        db.execute("select agent_id::text from task_steps where task_id = %s", (task,)).fetchone()[
            0
        ]
        == clone
    )
    assert (
        "Lessons from your past work" in seen["system"]
        and "Always include phone numbers" in seen["system"]
    )


def test_lessons_text():
    assert lessons_text({}) == ""
    assert "- Be brief" in lessons_text({"lessons": ["Be brief"]})


@pytest.fixture(autouse=True)
def _quiet_other_workspaces(db):
    # Other tests' workspaces shouldn't be picked by the nightly run.
    db.execute("update workspaces set evolved_at = now()")
    yield
