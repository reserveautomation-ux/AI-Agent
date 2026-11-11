import httpx
from test_pipeline import (
    FakeLLM,
    new_task,
    plan,
    research_step,
    run,
    text_resp,
    verdict,
)
from workforce_worker.notify import notify_task


class FakePusher:
    def __init__(self, tickets=None, fail=False):
        self.sent: list[dict] = []
        self.tickets = tickets
        self.fail = fail

    async def send(self, messages):
        if self.fail:
            raise httpx.ConnectError("push service down")
        self.sent.extend(messages)
        return self.tickets or [{"status": "ok", "id": "t"} for _ in messages]


def _device(db, ws, token="ExponentPushToken[abc123xyz]"):
    db.execute(
        "insert into push_devices (workspace_id, user_id, token, platform)"
        " values (%s, %s, %s, 'android')",
        (ws.id, ws.user, token),
    )


def test_push_when_task_finishes(database_url, db, workspace):
    _device(db, workspace)
    task = new_task(db, workspace)
    llm = FakeLLM(lambda p, n: text_resp(plan()), research_step, lambda p, n: text_resp(verdict()))
    pusher = FakePusher()

    async def go(conn):
        await conn.execute(
            "update tasks set run_after = now() + interval '1 day' where id <> %s", (task,)
        )
        from workforce_worker.runner import claim, process_one

        claimed = await claim(conn, "w")
        return await process_one(
            conn, llm, task, claimed[1], worker_id="w", database_url=database_url, pusher=pusher
        )

    assert run(database_url, go) == "completed"
    assert len(pusher.sent) == 1
    msg = pusher.sent[0]
    assert msg["to"] == "ExponentPushToken[abc123xyz]"
    assert msg["title"].startswith("✅ Done")
    assert msg["body"] == "Here are your creators."
    assert msg["data"] == {"task_id": task, "url": f"/tasks/{task}"}

    # Same event again (e.g. worker re-checks) -> no duplicate push.
    assert run(database_url, lambda c: notify_task(c, task, pusher)) == 0
    assert len(pusher.sent) == 1
    assert (
        db.execute("select status from notifications where task_id = %s", (task,)).fetchone()[0]
        == "sent"
    )


def test_dead_tokens_are_disabled_and_push_failures_are_harmless(database_url, db, workspace):
    _device(db, workspace, "ExponentPushToken[dead-device-1]")
    task = new_task(db, workspace)
    db.execute("update tasks set status = 'planned' where id = %s", (task,))
    db.execute(
        "update tasks set status = 'blocked', result_summary = 'Which city?' where id = %s", (task,)
    )

    dead = FakePusher(tickets=[{"status": "error", "details": {"error": "DeviceNotRegistered"}}])
    assert run(database_url, lambda c: notify_task(c, task, dead)) == 0
    assert db.execute(
        "select disabled_at is not null from push_devices where token ="
        " 'ExponentPushToken[dead-device-1]'"
    ).fetchone()[0]

    db.execute("update tasks set status = 'failed' where id = %s", (task,))
    _device(db, workspace, "ExponentPushToken[live-device-2]")
    assert run(database_url, lambda c: notify_task(c, task, FakePusher(fail=True))) == 0
    assert (
        db.execute(
            "select status from notifications where task_id = %s order by created_at desc limit 1",
            (task,),
        ).fetchone()[0]
        == "failed"
    )


def test_no_push_for_in_progress_tasks(database_url, db, workspace):
    _device(db, workspace, "ExponentPushToken[quiet-device-3]")
    task = new_task(db, workspace)
    pusher = FakePusher()
    assert run(database_url, lambda c: notify_task(c, task, pusher)) == 0
    assert pusher.sent == []
