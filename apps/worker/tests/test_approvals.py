"""Approved actions run at most once, exactly as approved, and never pretend to succeed."""

from datetime import UTC, datetime, timedelta

from test_browser import FIELDS, LOCAL, Handler
from test_pipeline import (
    FakeLLM,
    new_task,
    plan,
    run,
    step_result,
    text_resp,
    tool_resp,
    tool_turns,
    verdict,
)
from workforce_core.approvals import binding_for
from workforce_worker.browser import BrowserService
from workforce_worker.pipeline import advance


def _prepared_email_task(database_url, db, workspace):
    task = new_task(db, workspace, "Email Rahul the meeting moved")

    def step(p, n):
        if tool_turns(p) == 0:
            return tool_resp(
                (
                    "send_email",
                    {"to": "rahul@example.com", "subject": "Moved", "body": "Friday 4pm"},
                )
            )
        return text_resp(step_result("ready"))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(agent="pe_email", deliverable="prepared_action")),
        step,
        lambda p, n: text_resp(verdict()),
    )
    assert run(database_url, lambda c: advance(c, llm, task)) == "waiting_for_approval"
    return task


def _decide(db, task, decision):
    """What the approval API does, then what expire_approvals() does for the worker."""
    db.execute(
        "update approval_requests set status = %s, decided_at = now() where task_id = %s",
        (decision, task),
    )
    db.execute("select public.expire_approvals()")
    assert (
        db.execute("select status::text from tasks where id = %s", (task,)).fetchone()[0]
        == "running"
    )


def _summary(db, task):
    return db.execute(
        "select status::text, result_summary from tasks where id = %s", (task,)
    ).fetchone()


def test_approved_but_not_connected_is_reported_honestly(database_url, db, workspace):
    task = _prepared_email_task(database_url, db, workspace)
    _decide(db, task, "approved")
    llm = FakeLLM(None, None, None)  # no model calls needed to carry out approvals
    assert run(database_url, lambda c: advance(c, llm, task)) == "failed"
    status, summary = _summary(db, task)
    assert "isn't connected yet" in summary and "Nothing was sent" in summary
    appr = db.execute(
        "select status::text from approval_requests where task_id = %s", (task,)
    ).fetchone()[0]
    assert appr == "consumed" and llm.calls == []


def test_declined_action_completes_without_doing_it(database_url, db, workspace):
    task = _prepared_email_task(database_url, db, workspace)
    _decide(db, task, "rejected")
    assert run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task)) == "completed"
    assert "you declined" in _summary(db, task)[1]


def test_crash_during_action_is_never_repeated(database_url, db, workspace):
    task = _prepared_email_task(database_url, db, workspace)
    # Simulate: approval consumed and action started, then the worker died.
    db.execute("update approval_requests set status = 'consumed' where task_id = %s", (task,))
    db.execute(
        "update tool_invocations set status = 'running' where task_id = %s"
        " and tool_name = 'send_email'",
        (task,),
    )
    db.execute("update tasks set status = 'running' where id = %s", (task,))
    assert run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task)) == "failed"
    assert "Outcome unknown" in _summary(db, task)[1]


def test_tampered_approval_is_not_executed(database_url, db, workspace):
    task = _prepared_email_task(database_url, db, workspace)
    db.execute(
        "update approval_requests set action_payload = action_payload ||"
        ' \'{"to": "attacker@evil.example"}\' where task_id = %s',
        (task,),
    )
    _decide(db, task, "approved")
    assert run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task)) == "failed"
    appr = db.execute(
        "select status::text from approval_requests where task_id = %s", (task,)
    ).fetchone()[0]
    assert appr == "invalidated"
    assert "differs from what was approved" in _summary(db, task)[1]


def test_approved_form_is_really_submitted_once(database_url, db, workspace, site):
    Handler.submissions.clear()
    task = new_task(db, workspace, "Register me for the event")
    args = {"url": site + "/form", "fields": FIELDS}

    def step(p, n):
        if tool_turns(p) == 0:
            return tool_resp(("browser_submit_form", args))
        return text_resp(step_result("form ready"))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(agent="op_forms", deliverable="prepared_action")),
        step,
        lambda p, n: text_resp(verdict()),
    )

    async def go(conn):
        async with BrowserService(LOCAL) as browser:
            first = await advance(conn, llm, task, browser)
            assert Handler.submissions == []  # nothing submitted before approval
            await conn.execute(
                "update approval_requests set status = 'approved' where task_id = %s", (task,)
            )
            await conn.execute("select public.expire_approvals()")
            second = await advance(conn, llm, task, browser)
            third = await advance(conn, llm, task, browser)  # e.g. a duplicate wake-up
            return first, second, third

    assert run(database_url, go) == ("waiting_for_approval", "completed", "completed")
    assert len(Handler.submissions) == 1  # at most once
    assert Handler.submissions[0]["name"] == "Asha Rao"
    assert "registered" in _summary(db, task)[1]


def test_expired_approval_wakes_task_and_is_reported(database_url, db, workspace):
    task = _prepared_email_task(database_url, db, workspace)
    db.execute(
        "update approval_requests set expires_at = now() - interval '1 second' where task_id = %s",
        (task,),
    )
    db.execute("select public.expire_approvals()")
    assert run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task)) == "completed"
    assert "expired" in _summary(db, task)[1]


def test_binding_helper_matches_gateway(database_url, db, workspace):
    """Approvals created by agents verify with the shared helper (no drift)."""
    task = _prepared_email_task(database_url, db, workspace)
    row = db.execute(
        "select task_id::text, action, action_payload, expires_at, policy_version, action_hash"
        " from approval_requests where task_id = %s",
        (task,),
    ).fetchone()
    b = binding_for(
        task_id=row[0], action=row[1], args=row[2], expires_at=row[3], policy_version=row[4]
    )
    assert b.action_hash() == row[5]
    assert row[3] > datetime.now(UTC) + timedelta(hours=23)  # default 24h to decide
