"""Tell the owner when a task needs them or is finished (in-app + phone push).

Push goes through Expo's push service, which delivers to both Android (FCM)
and iOS (APNs). Sending is best-effort: a failed push never fails a task.
"""

import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

NOTIFY_STATUSES = {
    "completed": "✅ Done",
    "waiting_for_approval": "🟠 Needs your approval",
    "blocked": "❓ Needs your input",
    "failed": "⚠️ Couldn't finish",
}


# Extra channels for alerts (e.g. the owner's linked Telegram chat), set up by the runner.
Forwarder = Callable[[AsyncConnection, str, str, str], Awaitable[bool]]
_forwarders: list[Forwarder] = []


def add_forwarder(fn: Forwarder) -> None:
    _forwarders.append(fn)


class Pusher(Protocol):
    async def send(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class ExpoPusher:
    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or os.environ.get("EXPO_ACCESS_TOKEN")

    async def send(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(EXPO_PUSH_URL, json=messages, headers=headers)
            resp.raise_for_status()
            return resp.json().get("data", [])


def _body(summary: str | None, status: str) -> str:
    if summary:
        text = " ".join(summary.split())
        return text if len(text) <= 160 else text[:157] + "…"
    return {
        "completed": "Your result is ready.",
        "waiting_for_approval": "Review and approve the prepared action.",
        "blocked": "The Chief has a question for you.",
        "failed": "Open the task to see what happened.",
    }[status]


async def notify_task(conn: AsyncConnection, task_id: str, pusher: Pusher | None) -> int:
    """Record and push a notification for the task's current status. Returns pushes sent."""
    task = await (
        await conn.execute(
            """select t.id::text, t.workspace_id::text, t.created_by::text, t.title,
                      t.status::text, t.result_summary,
                      (select max(id) from public.task_events e where e.task_id = t.id) as event
               from public.tasks t where t.id = %s""",
            (task_id,),
        )
    ).fetchone()
    if task is None or task["status"] not in NOTIFY_STATUSES:
        return 0

    title = f"{NOTIFY_STATUSES[task['status']]}: {task['title']}"[:120]
    body = _body(task["result_summary"], task["status"])
    return await deliver(
        conn,
        pusher,
        workspace_id=task["workspace_id"],
        user_id=task["created_by"],
        task_id=task_id,
        title=title,
        body=body,
        payload={"task_id": task_id, "status": task["status"], "title": title, "body": body},
        data={"task_id": task_id, "url": f"/tasks/{task_id}"},
        event_key=f"task_event:{task['event']}",
        channel_id="tasks",
    )


async def deliver(
    conn: AsyncConnection,
    pusher: Pusher | None,
    *,
    workspace_id: str,
    user_id: str,
    title: str,
    body: str,
    payload: dict[str, Any],
    data: dict[str, Any],
    event_key: str,
    task_id: str | None = None,
    channel_id: str = "tasks",
) -> int:
    """Record a notification once (by event_key) and push it to the person's phones."""
    row = await (
        await conn.execute(
            """insert into public.notifications
                   (workspace_id, user_id, task_id, channel, payload, event_key)
               values (%s, %s, %s, 'push', %s, %s)
               on conflict (user_id, event_key) where event_key is not null do nothing
               returning id::text""",
            (workspace_id, user_id, task_id, Jsonb(payload), event_key),
        )
    ).fetchone()
    if row is None:
        return 0  # already notified for this exact event

    for forward in _forwarders:
        try:
            await forward(conn, workspace_id, user_id, f"{title}\n{body}")
        except Exception:  # noqa: BLE001 - another channel must never block push
            log.exception("forwarding %s failed", event_key)

    devices = await (
        await conn.execute(
            "select id::text, token from public.push_devices"
            " where user_id = %s and disabled_at is null",
            (user_id,),
        )
    ).fetchall()
    if not devices or pusher is None:
        return 0

    messages = [
        {
            "to": d["token"],
            "title": title,
            "body": body,
            "sound": "default",
            "channelId": channel_id,
            "data": data,
        }
        for d in devices
    ]
    try:
        tickets = await pusher.send(messages)
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("push failed for %s: %s", event_key, exc)
        await conn.execute(
            "update public.notifications set status = 'failed' where id = %s", (row["id"],)
        )
        return 0

    sent = 0
    for device, ticket in zip(devices, tickets, strict=False):
        if ticket.get("status") == "ok":
            sent += 1
        elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
            await conn.execute(
                "update public.push_devices set disabled_at = now() where id = %s",
                (device["id"],),
            )
    await conn.execute(
        "update public.notifications set status = %s, sent_at = now() where id = %s",
        ("sent" if sent else "failed", row["id"]),
    )
    return sent
