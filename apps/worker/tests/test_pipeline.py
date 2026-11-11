"""End-to-end tests of the task pipeline with a scripted stand-in for Claude."""

import asyncio
import contextlib
import json
from types import SimpleNamespace

import anthropic
import httpx
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from workforce_core.db import sync_tool_definitions
from workforce_core.workforce import AGENTS, MODEL_PROFILES
from workforce_worker.pipeline import advance
from workforce_worker.runner import claim, process_one

# --- fake model -----------------------------------------------------------------


def usage(inp=1000, out=200):
    return SimpleNamespace(
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=0,
        server_tool_use=None,
    )


def text_resp(data, stop="end_turn"):
    text = data if isinstance(data, str) else json.dumps(data)
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop,
        usage=usage(),
        model="claude-opus-5-5",
        stop_details=None,
    )


def tool_resp(*calls):
    blocks = [
        SimpleNamespace(type="tool_use", id=f"tu_{i}_{name}", name=name, input=args)
        for i, (name, args) in enumerate(calls)
    ]
    return SimpleNamespace(
        content=blocks,
        stop_reason="tool_use",
        usage=usage(),
        model="claude-opus-5-5",
        stop_details=None,
    )


def step_result(summary="done", **kw):
    return {
        "summary": summary,
        "result": kw.get("result", summary),
        "files_saved": kw.get("files", []),
        "waiting_for_approval": kw.get("approvals", []),
        "limitations": [],
    }


def plan(agent="rs_web", deliverable="file", steps=None, question=""):
    return {
        "understanding": "Find creators",
        "reply_language": "English",
        "assumptions": [],
        "clarification_needed": question,
        "success_criteria": ["CSV with at least 2 creators"],
        "deliverable": deliverable,
        "steps": steps
        if steps is not None
        else [
            {
                "title": "Research creators",
                "agent": agent,
                "instructions": "Find fitness creators",
                "expected_output": "CSV file",
            }
        ],
    }


def verdict(passed=True, issues=()):
    return {
        "passed": passed,
        "score": 0.9 if passed else 0.3,
        "criteria": [],
        "issues": list(issues),
        "summary_for_owner": "Here are your creators." if passed else "Missing file.",
    }


class FakeLLM:
    """Routes by system prompt; each role has a handler(params, n) -> response."""

    def __init__(self, plan_fn, step_fn, verify_fn):
        self.handlers = {"plan": plan_fn, "step": step_fn, "verify": verify_fn}
        self.calls: list[tuple[str, dict]] = []

    async def create(self, **p):
        system = p["system"]
        role = (
            "plan"
            if system.startswith("You are the Chief")
            else "verify"
            if system.startswith("You are the QA")
            else "step"
        )
        n = sum(1 for r, _ in self.calls if r == role)
        self.calls.append((role, p))
        result = self.handlers[role](p, n)
        if asyncio.iscoroutine(result):
            result = await result
        if isinstance(result, Exception):
            raise result
        return result


def tool_turns(p):
    """Number of tool-result rounds already in this agent conversation."""
    return sum(1 for m in p["messages"] if m["role"] == "user" and isinstance(m["content"], list))


CSV = "name,handle,followers\nRiya,@fitwithriya,120000\nArjun,@mumbaimuscle,45000\n"

# --- fixtures -------------------------------------------------------------------


def run(database_url, fn):
    async def main():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as conn:
            return await fn(conn)

    return asyncio.run(main())


@pytest.fixture
def workspace(database_url, db, make_user):
    """A workspace with its workforce hired from the real templates."""
    uid = make_user()
    ws = db.execute(
        "select workspace_id::text from workspace_members where user_id = %s", (uid,)
    ).fetchone()[0]
    run(database_url, sync_tool_definitions)
    ids = {}
    for t in sorted(AGENTS, key=lambda a: a.role != "chief"):
        cfg = {"description": t.description, **MODEL_PROFILES[t.model_profile]}
        ids[t.key] = db.execute(
            "insert into agents (workspace_id, name, role, status, template_key, allowed_tools,"
            " config_json) values (%s, %s, %s, 'active', %s, %s, %s) returning id::text",
            (ws, t.name, t.role, t.key, list(t.tools), Jsonb(cfg)),
        ).fetchone()[0]
    return SimpleNamespace(id=ws, user=uid, agents=ids)


def new_task(db, ws, objective="Find fitness creators in Mumbai", budget=None):
    return db.execute(
        "insert into tasks (workspace_id, title, objective, created_by, budget_limit_usd)"
        " values (%s, %s, %s, %s, %s) returning id::text",
        (ws.id, objective[:50], objective, ws.user, budget),
    ).fetchone()[0]


def statuses(db, task_id):
    return [
        r[0]
        for r in db.execute(
            "select to_status::text from task_events where task_id = %s order by id", (task_id,)
        ).fetchall()
    ]


# --- tests ----------------------------------------------------------------------


def research_step(p, n):
    if tool_turns(p) == 0:
        return tool_resp(
            ("create_report", {"name": "Mumbai fitness creators", "format": "csv", "content": CSV}),
            (
                "remember",
                {
                    "content": "Instagram counts are best read via the browser",
                    "memory_type": "learning",
                    "about": "my_work",
                },
            ),
        )
    return text_resp(step_result("Found 2 creators", files=["Mumbai_fitness_creators.csv"]))


def test_research_task_end_to_end(database_url, db, workspace):
    task = new_task(db, workspace)
    llm = FakeLLM(lambda p, n: text_resp(plan()), research_step, lambda p, n: text_resp(verdict()))

    status = run(database_url, lambda c: advance(c, llm, task))

    assert status == "completed"
    assert statuses(db, task) == ["draft", "planned", "queued", "running", "verifying", "completed"]
    row = db.execute(
        "select result_summary, cost_usd, verification->>'passed' from tasks where id = %s", (task,)
    ).fetchone()
    assert row[0] == "Here are your creators." and row[1] > 0 and row[2] == "true"

    art = db.execute(
        "select name, file_type, convert_from(content, 'UTF8') from artifacts where task_id = %s",
        (task,),
    ).fetchone()
    assert art == ("Mumbai_fitness_creators.csv", "text/csv", CSV)

    # The specialist got its own tools only, plus the Claude server-side web tools.
    step_call = next(p for r, p in llm.calls if r == "step")
    tool_names = {t["name"] for t in step_call["tools"]}
    assert {"web_search", "web_fetch", "create_report", "recall"} <= tool_names
    assert "send_email" not in tool_names and "code_execution" not in tool_names
    assert step_call["output_config"]["format"]["type"] == "json_schema"

    # Agent's private learning + an episode memory were saved, both unverified.
    mems = db.execute(
        "select owner_scope, memory_type, trusted from memories"
        " where workspace_id = %s order by created_at",
        (workspace.id,),
    ).fetchall()
    assert ("agent", "learning", False) in mems and ("workspace", "episode", False) in mems

    # Costs recorded per call; evaluation produced for the agent that did the work.
    assert (
        db.execute("select count(*) from llm_calls where task_id = %s", (task,)).fetchone()[0] == 4
    )
    ev = db.execute(
        "select success_rate, sample_size from agent_evaluations where agent_id = %s",
        (workspace.agents["rs_web"],),
    ).fetchone()
    assert ev == (1, 1)


def test_external_action_waits_for_approval(database_url, db, workspace):
    task = new_task(db, workspace, "Email Rahul the meeting moved to Friday")

    def email_step(p, n):
        if tool_turns(p) == 0:
            return tool_resp(
                (
                    "send_email",
                    {
                        "to": "rahul@example.com",
                        "subject": "Meeting",
                        "body": "Moved to Friday 4pm.",
                    },
                )
            )
        assert "Held for the owner's approval" in str(p["messages"][-1]["content"])
        return text_resp(step_result("Email ready", approvals=["send_email to Rahul"]))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(agent="pe_email", deliverable="prepared_action")),
        email_step,
        lambda p, n: text_resp(verdict()),
    )
    assert run(database_url, lambda c: advance(c, llm, task)) == "waiting_for_approval"

    appr = db.execute(
        "select action, recipient, status::text, length(action_hash), risk_tier"
        " from approval_requests where task_id = %s",
        (task,),
    ).fetchone()
    assert appr == ("send_email", "rahul@example.com", "pending", 64, 2)
    inv = db.execute(
        "select status from tool_invocations where task_id = %s and tool_name = 'send_email'",
        (task,),
    ).fetchone()
    assert inv[0] == "awaiting_approval"


def test_verifier_rework_then_pass(database_url, db, workspace):
    task = new_task(db, workspace)

    def step(p, n):
        # First attempt "forgets" the file; the rework attempt saves it.
        rework = "QA Verifier rejected" in p["messages"][0]["content"]
        if rework and tool_turns(p) == 0:
            return tool_resp(
                ("create_report", {"name": "creators", "format": "csv", "content": CSV})
            )
        return text_resp(step_result("ok"))

    llm = FakeLLM(lambda p, n: text_resp(plan()), step, lambda p, n: text_resp(verdict()))
    assert run(database_url, lambda c: advance(c, llm, task)) == "completed"
    assert db.execute("select rework_count from tasks where id = %s", (task,)).fetchone()[0] == 1
    assert "verifying" in statuses(db, task) and statuses(db, task).count("running") == 2


def test_agent_cannot_use_tools_outside_its_role(database_url, db, workspace):
    task = new_task(db, workspace)

    def step(p, n):
        if tool_turns(p) == 0:
            return tool_resp(
                (
                    "place_stock_order",
                    {"symbol": "INFY", "side": "buy", "quantity": 10, "order_type": "market"},
                ),
                ("create_report", {"name": "c", "format": "csv", "content": CSV}),
            )
        assert "not available to you" in str(p["messages"][-1]["content"])
        return text_resp(step_result("ok"))

    llm = FakeLLM(lambda p, n: text_resp(plan()), step, lambda p, n: text_resp(verdict()))
    run(database_url, lambda c: advance(c, llm, task))
    assert (
        db.execute(
            "select count(*) from audit_events where action = 'policy.violation.tool_not_allowed'"
        ).fetchone()[0]
        >= 1
    )
    assert (
        db.execute("select count(*) from approval_requests where task_id = %s", (task,)).fetchone()[
            0
        ]
        == 0
    )


def test_question_for_owner_blocks_task(database_url, db, workspace):
    task = new_task(db, workspace, "Book it")
    llm = FakeLLM(
        lambda p, n: text_resp(plan(steps=[], question="Book what, and when?")), None, None
    )
    assert run(database_url, lambda c: advance(c, llm, task)) == "blocked"
    assert (
        db.execute("select result_summary from tasks where id = %s", (task,)).fetchone()[0]
        == "Book what, and when?"
    )


def _process(database_url, llm, task):
    async def go(conn):
        # The test database is shared; park every other task so we claim this one.
        await conn.execute(
            "update tasks set run_after = now() + interval '1 day' where id <> %s", (task,)
        )
        claimed = await claim(conn, "test-worker")
        assert claimed and claimed[0] == task
        return await process_one(
            conn, llm, task, claimed[1], worker_id="test-worker", database_url=database_url
        )

    return run(database_url, go)


def test_crash_mid_task_resumes_without_redoing_work(database_url, db, workspace):
    task = new_task(db, workspace)
    steps2 = [
        {
            "title": "Research",
            "agent": "rs_web",
            "instructions": "STEP-ONE research",
            "expected_output": "x",
        },
        {
            "title": "Write file",
            "agent": "op_docs",
            "instructions": "STEP-TWO write the file",
            "expected_output": "y",
        },
    ]
    outage = {"left": 1}

    def step(p, n):
        if "STEP-TWO" in p["messages"][0]["content"] and outage["left"]:
            outage["left"] -= 1
            req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            return anthropic.APIConnectionError(request=req)  # network blip mid-task
        if tool_turns(p) == 0 and "STEP-TWO" in p["messages"][0]["content"]:
            return tool_resp(("create_document", {"name": "list", "format": "csv", "content": CSV}))
        return text_resp(step_result("ok"))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(steps=steps2)), step, lambda p, n: text_resp(verdict())
    )
    assert _process(database_url, llm, task) is None  # failed attempt -> released for retry
    row = db.execute(
        "select status::text, lease_owner, run_after > now(), last_error from tasks where id = %s",
        (task,),
    ).fetchone()
    assert row[0] == "running" and row[1] is None and row[2] and "APIConnectionError" in row[3]

    db.execute("update tasks set run_after = now() where id = %s", (task,))
    first_step_calls = sum(
        1 for r, p in llm.calls if r == "step" and "STEP-ONE" in p["messages"][0]["content"]
    )
    assert _process(database_url, llm, task) == "completed"
    # Step 1 was checkpointed, so it was not run again after the crash.
    assert (
        sum(1 for r, p in llm.calls if r == "step" and "STEP-ONE" in p["messages"][0]["content"])
        == first_step_calls
    )


def test_budget_limit_blocks_task(database_url, db, workspace):
    task = new_task(db, workspace, budget=0.001)  # one call costs ~0.008
    llm = FakeLLM(lambda p, n: text_resp(plan()), research_step, lambda p, n: text_resp(verdict()))
    _process(database_url, llm, task)
    status, summary = db.execute(
        "select status::text, result_summary from tasks where id = %s", (task,)
    ).fetchone()
    assert status == "blocked" and "budget" in summary


def test_kill_switch_stops_claiming(database_url, db, workspace):
    task = new_task(db, workspace)
    db.execute("update workspaces set kill_switch = true where id = %s", (workspace.id,))

    async def go(conn):
        return await claim(conn, "w")

    try:
        assert run(database_url, go) is None or run(database_url, go)[0] != task
    finally:
        db.execute("update workspaces set kill_switch = false where id = %s", (workspace.id,))


def test_cancelled_task_stops(database_url, db, workspace):
    task = new_task(db, workspace)
    db.execute("update tasks set status = 'cancelled' where id = %s", (task,))
    llm = FakeLLM(lambda p, n: text_resp(plan()), research_step, lambda p, n: text_resp(verdict()))
    assert run(database_url, lambda c: advance(c, llm, task)) == "cancelled"
    assert llm.calls == []


def test_owner_answer_replans_blocked_task(database_url, db, workspace):
    task = new_task(db, workspace, "Book it")
    asked = FakeLLM(lambda p, n: text_resp(plan(steps=[], question="Book what?")), None, None)
    assert run(database_url, lambda c: advance(c, asked, task)) == "blocked"

    # What POST /tasks/{id}/retry does with an answer:
    db.execute(
        "update tasks set objective = objective || E'\\n\\nOwner''s answer: a cab to the"
        " airport at 6am', status = 'planned' where id = %s",
        (task,),
    )
    answered = FakeLLM(
        lambda p, n: text_resp(plan(agent="tr_local", deliverable="prepared_action")),
        lambda p, n: (
            tool_resp(
                ("prepare_booking_link", {"provider": "Uber", "details": "Home to airport, 6am"})
            )
            if tool_turns(p) == 0
            else text_resp(step_result("Cab ready to confirm"))
        ),
        lambda p, n: text_resp(verdict()),
    )
    assert run(database_url, lambda c: advance(c, answered, task)) == "completed"
    assert "Owner's answer" in answered.calls[0][1]["messages"][0]["content"]
    card = db.execute(
        "select convert_from(content, 'UTF8') from artifacts where task_id = %s", (task,)
    ).fetchone()[0]
    assert "m.uber.com" in card and "Nothing has been booked or paid yet" in card


def test_worker_shutdown_hands_task_back(database_url, db, workspace):
    task = new_task(db, workspace)

    async def slow_plan(p, n):
        await asyncio.sleep(3600)  # a long model call in progress when the worker stops

    llm = FakeLLM(lambda p, n: slow_plan(p, n), research_step, lambda p, n: text_resp(verdict()))

    async def go(conn):
        await conn.execute(
            "update tasks set run_after = now() + interval '1 day' where id <> %s", (task,)
        )
        claimed = await claim(conn, "stopping-worker")
        job = asyncio.create_task(
            process_one(
                conn, llm, task, claimed[1], worker_id="stopping-worker", database_url=database_url
            )
        )
        await asyncio.sleep(0.3)
        job.cancel()  # what SIGTERM does
        with contextlib.suppress(asyncio.CancelledError):
            await job

    run(database_url, go)
    owner, error = db.execute(
        "select lease_owner, last_error from tasks where id = %s", (task,)
    ).fetchone()
    assert owner is None and "restarted" in error


def test_payments_agent_prepares_upi_link(database_url, db, workspace):
    task = new_task(db, workspace, "Pay Ramesh 500 for milk, ramesh@okhdfcbank")
    llm = FakeLLM(
        lambda p, n: text_resp(plan(agent="fi_payments", deliverable="prepared_action")),
        lambda p, n: (
            tool_resp(
                ("upi_link", {"upi_id": "ramesh@okhdfcbank", "name": "Ramesh", "amount": "500"})
            )
            if tool_turns(p) == 0
            else text_resp(step_result("UPI payment ready"))
        ),
        lambda p, n: text_resp(verdict()),
    )
    assert run(database_url, lambda c: advance(c, llm, task)) == "completed"
    sent = str([c[1]["messages"] for c in llm.calls])
    assert "upi://pay?pa=ramesh@okhdfcbank&pn=Ramesh&am=500.00&cu=INR" in sent
    assert "not paid yet" in sent
