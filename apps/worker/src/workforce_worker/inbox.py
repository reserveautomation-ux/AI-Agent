"""Important-email alerts: tell the owner (phone push) when important mail arrives.

Uses Gmail's own "important" signal, skips promotions and social mail, and only
alerts about mail that arrived after the inbox was connected. Each email alerts once.
"""

import logging
import time
from email.utils import parseaddr

from psycopg import AsyncConnection
from workforce_core.google import GoogleError, gmail_search

from .executor import ActionFailed, Integrations, NotConnected, _call, open_session
from .notify import Pusher, deliver

log = logging.getLogger(__name__)

ALERT_QUERY = "is:important is:unread newer_than:2d -category:promotions -category:social"


def _sender(value: str) -> str:
    name, addr = parseaddr(value)
    return name or addr or value or "Someone"


async def check_inboxes(
    conn: AsyncConnection, integ: Integrations, pusher: Pusher | None, now_ms: int | None = None
) -> int:
    """One pass over every connected inbox. Returns the number of alerts sent."""
    now_ms = now_ms or int(time.time() * 1000)
    rows = await (
        await conn.execute(
            """select c.id::text as connection_id, c.workspace_id::text, w.enabled,
                      w.last_seen_ms,
                      (select m.user_id::text from public.workspace_members m
                        where m.workspace_id = c.workspace_id and m.role = 'owner'
                        order by m.created_at limit 1) as owner
               from public.tool_connections c
               left join public.inbox_watch w on w.connection_id = c.id
               where c.provider = 'gmail_inbox' and c.connection_status = 'active'"""
        )
    ).fetchall()
    alerts = 0
    for r in rows:
        if r["last_seen_ms"] is None:
            # Newly connected: start from now, never alert about the old backlog.
            await conn.execute(
                "insert into public.inbox_watch (connection_id, workspace_id, last_seen_ms)"
                " values (%s, %s, %s) on conflict (connection_id) do nothing",
                (r["connection_id"], r["workspace_id"], now_ms),
            )
            continue
        if not r["enabled"] or not r["owner"]:
            continue
        try:
            s = await open_session(conn, r["workspace_id"], "gmail_inbox", integ)
            found = await _call(s, lambda s=s: gmail_search(s.http, s.token, ALERT_QUERY, 10))
        except (NotConnected, ActionFailed, GoogleError) as exc:
            log.info("inbox check skipped for %s: %s", r["connection_id"], exc)
            continue
        fresh = sorted(
            (m for m in found if m["internal_ms"] > r["last_seen_ms"]),
            key=lambda m: m["internal_ms"],
        )
        for m in fresh:
            sender = _sender(m["from"])
            body = f"{m['subject']} — {m['snippet']}"
            alerts += await deliver(
                conn,
                pusher,
                workspace_id=r["workspace_id"],
                user_id=r["owner"],
                title=f"📧 Important: {sender}"[:120],
                body=body if len(body) <= 160 else body[:157] + "…",
                payload={
                    "kind": "mail",
                    "message_id": m["id"],
                    "from": sender,
                    "subject": m["subject"],
                },
                data={"url": "/", "kind": "mail"},
                event_key=f"mail:{m['id']}",
                channel_id="mail",
            )
        newest = max([r["last_seen_ms"], *(m["internal_ms"] for m in fresh)])
        await conn.execute(
            "update public.inbox_watch set last_seen_ms = %s, checked_at = now()"
            " where connection_id = %s",
            (newest, r["connection_id"]),
        )
    return alerts
