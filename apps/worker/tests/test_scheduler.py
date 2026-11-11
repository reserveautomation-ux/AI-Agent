"""Reminders notify (push + chat); jobs start workforce tasks; repeats move forward."""

import asyncio
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from workforce_worker.scheduler import fire_due


class FakePusher:
    def __init__(self):
        self.sent = []

    async def send(self, messages):
        self.sent.extend(messages)
        return [{"status": "ok"} for _ in messages]


def _run(database_url, fn):
    async def go():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as c:
            return await fn(c)

    return asyncio.run(go())


def _schedule(db, ws, kind, what, when, repeat="none", conv=None):
    return db.execute(
        "insert into schedules (workspace_id, user_id, conversation_id, kind, title, what, repeat,"
        " timezone, local_time, next_run_at) values (%s, %s, %s, %s, %s, %s, %s, 'Asia/Kolkata',"
        " %s, %s) returning id::text",
        (
            ws.id,
            ws.user,
            conv,
            kind,
            what[:40],
            what,
            repeat,
            when.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%H:%M"),
            when,
        ),
    ).fetchone()[0]


def test_reminder_pushes_and_posts_in_chat_once(database_url, db, workspace):
    conv = db.execute(
        "insert into conversations (workspace_id, user_id, title)"
        " values (%s, %s, 'x') returning id::text",
        (workspace.id, workspace.user),
    ).fetchone()[0]
    db.execute(
        "insert into push_devices (workspace_id, user_id, token, platform)"
        " values (%s, %s, %s, 'android')",
        (workspace.id, workspace.user, f"ExponentPushToken[r{workspace.id[:8]}]"),
    )
    now = datetime(2026, 11, 11, 12, 30, tzinfo=UTC)
    sid = _schedule(db, workspace, "reminder", "Call mom", now - timedelta(minutes=1), conv=conv)
    pusher = FakePusher()
    assert _run(database_url, lambda c: fire_due(c, pusher, now)) == 1
    assert _run(database_url, lambda c: fire_due(c, pusher, now)) == 0  # once only
    assert [m["title"] for m in pusher.sent] == ["⏰ Reminder"] and pusher.sent[0][
        "body"
    ] == "Call mom"
    msg = db.execute(
        "select content, meta->>'kind' from chat_messages where conversation_id = %s", (conv,)
    ).fetchone()
    assert msg == ("⏰ Reminder: Call mom", "reminder")
    assert db.execute("select active, runs from schedules where id = %s", (sid,)).fetchone() == (
        False,
        1,
    )


def test_repeating_job_starts_a_task_and_skips_missed_runs(database_url, db, workspace):
    first = datetime(2026, 11, 2, 3, 30, tzinfo=UTC)  # Mon 09:00 IST
    sid = _schedule(db, workspace, "task", "Summarise my unread email", first, repeat="weekdays")
    now = datetime(2026, 11, 11, 4, 0, tzinfo=UTC)  # Wed 09:30 IST: several runs were missed
    assert _run(database_url, lambda c: fire_due(c, FakePusher(), now)) == 1
    task = db.execute(
        "select title, objective, status::text from tasks where workspace_id = %s", (workspace.id,)
    ).fetchone()
    assert task[0] == "Summarise my unread email" and "runs every weekday" in task[1]
    assert task[2] == "draft"
    nxt = db.execute("select next_run_at, active from schedules where id = %s", (sid,)).fetchone()
    assert nxt[1] is True and nxt[0] == datetime(2026, 11, 12, 3, 30, tzinfo=UTC)  # Thu 09:00 IST


def test_emergency_stop_skips_jobs(database_url, db, workspace):
    db.execute("update workspaces set kill_switch = true where id = %s", (workspace.id,))
    now = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)
    _schedule(db, workspace, "task", "Do something", now - timedelta(minutes=5))
    _run(database_url, lambda c: fire_due(c, FakePusher(), now))
    assert (
        db.execute(
            "select count(*) from tasks where workspace_id = %s", (workspace.id,)
        ).fetchone()[0]
        == 0
    )
    db.execute("update workspaces set kill_switch = false where id = %s", (workspace.id,))
