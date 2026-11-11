"""Fire reminders and repeating jobs when they are due.

A reminder notifies the person (phone push, plus a message in the chat it was set in).
A job starts a normal workforce task, so it gets the same planning, approvals and
verification as anything typed by hand. After downtime, missed repeats are skipped
(never a burst of catch-up runs).
"""

import logging
from datetime import UTC, datetime

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from workforce_core.db import record_audit
from workforce_core.schedules import REPEAT_TEXT, next_run

from .notify import Pusher, deliver

log = logging.getLogger(__name__)

DUE_SQL = """select id::text, workspace_id::text, user_id::text, conversation_id::text, kind,
                    title, what, repeat, timezone, local_time, next_run_at, runs
             from public.schedules
             where active and next_run_at <= %s
             order by next_run_at limit 1
             for update skip locked"""


async def fire_due(
    conn: AsyncConnection, pusher: Pusher | None, now: datetime | None = None
) -> int:
    now = now or datetime.now(UTC)
    fired = 0
    for _ in range(50):  # bounded per pass
        async with conn.transaction():
            s = await (await conn.execute(DUE_SQL, (now,))).fetchone()
            if s is None:
                break
            if s["kind"] == "reminder":
                await _remind(conn, s, pusher)
            else:
                await _start_job(conn, s)
            nxt = next_run(s["next_run_at"], s["repeat"], s["timezone"], s["local_time"])
            while nxt is not None and nxt <= now:  # skip runs missed while the worker was down
                nxt = next_run(nxt, s["repeat"], s["timezone"], s["local_time"])
            await conn.execute(
                "update public.schedules set runs = runs + 1, last_run_at = %s, next_run_at = %s,"
                " active = %s where id = %s",
                (now, nxt, nxt is not None, s["id"]),
            )
            fired += 1
    return fired


async def _remind(conn: AsyncConnection, s: dict, pusher: Pusher | None) -> None:
    text = f"⏰ Reminder: {s['what']}"
    if s["conversation_id"]:
        await conn.execute(
            "insert into public.chat_messages (conversation_id, workspace_id, role, content, meta)"
            " values (%s, %s, 'assistant', %s, %s)",
            (
                s["conversation_id"],
                s["workspace_id"],
                text,
                Jsonb({"kind": "reminder", "schedule_id": s["id"]}),
            ),
        )
        await conn.execute(
            "update public.conversations set updated_at = now() where id = %s",
            (s["conversation_id"],),
        )
    body = s["what"] if len(s["what"]) <= 160 else s["what"][:157] + "…"
    await deliver(
        conn,
        pusher,
        workspace_id=s["workspace_id"],
        user_id=s["user_id"],
        title="⏰ Reminder",
        body=body,
        payload={"kind": "reminder", "schedule_id": s["id"], "text": s["what"]},
        data={"url": "/", "kind": "reminder"},
        event_key=f"schedule:{s['id']}:{s['runs']}",
    )


async def _start_job(conn: AsyncConnection, s: dict) -> None:
    ws = await (
        await conn.execute(
            "select kill_switch, status from public.workspaces where id = %s", (s["workspace_id"],)
        )
    ).fetchone()
    if ws["kill_switch"] or ws["status"] != "active":
        log.info("schedule %s skipped: emergency stop is on", s["id"])
        return
    repeat = REPEAT_TEXT.get(s["repeat"], "")
    objective = s["what"] + (f"\n\n(Scheduled job that runs {repeat}.)" if repeat else "")
    task = await (
        await conn.execute(
            "insert into public.tasks (workspace_id, title, objective, created_by, conversation_id)"
            " values (%s, %s, %s, %s, %s) returning id::text",
            (s["workspace_id"], s["title"][:200], objective, s["user_id"], s["conversation_id"]),
        )
    ).fetchone()
    await record_audit(
        conn,
        workspace_id=s["workspace_id"],
        actor_type="system",
        actor_id=None,
        action="task.created",
        target_type="task",
        target_id=task["id"],
        event={"title": s["title"], "source": "schedule", "schedule_id": s["id"]},
    )
