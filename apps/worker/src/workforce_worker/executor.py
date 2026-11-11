"""Carry out actions the owner approved.

Only actions with a working integration actually run; for everything else we
say plainly that it wasn't done. Never pretend an action happened.
"""

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx
from psycopg import AsyncConnection
from workforce_core.google import (
    EventExists,
    GoogleConfig,
    GoogleError,
    GoogleOAuth,
    GrantRevoked,
    build_email,
    build_event,
    calendar_busy,
    calendar_insert,
    event_id_for,
    fresh_access_token,
    gmail_send,
)
from workforce_core.integrations import PROVIDERS_BY_KEY
from workforce_core.secrets import SecretBox, SecretError, load_secret, update_secret
from workforce_core.tools import TOOLS_BY_NAME

from .browser import BrowserService

ACTION_LABELS = {
    "send_email": "Send email",
    "send_whatsapp": "Send WhatsApp",
    "calendar_create_event": "Calendar event",
    "post_social": "Social post",
    "deploy_web": "Website deploy",
    "book_flight": "Flight booking",
    "place_stock_order": "Stock order",
    "play_store_release": "Play Store release",
    "app_store_submit": "App Store submission",
    "browser_submit_form": "Web form",
}


class NotConnected(Exception):
    """The integration for this action isn't set up yet."""


class ActionFailed(Exception):
    """The provider refused or failed; nothing was done."""


@dataclass
class Integrations:
    """Server-side credentials the worker needs to act for the owner."""

    box: SecretBox | None = None
    google: GoogleOAuth | None = None

    @classmethod
    def from_env(cls) -> "Integrations":
        box = SecretBox.from_env()
        cid, csecret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
        google = None
        if cid and csecret:
            config = GoogleConfig(cid, csecret, os.environ.get("GOOGLE_REDIRECT_URI", ""))
            google = GoogleOAuth(config, httpx.AsyncClient(timeout=30))
        return cls(box=box, google=google)


SERVICE_NAMES = {"gmail": "Gmail", "google_calendar": "Google Calendar"}


@dataclass
class GoogleSession:
    """A ready-to-use access token for one connected Google service."""

    token: str
    email: str
    http: httpx.AsyncClient
    mark: Any  # async (status, error) -> None


async def google_session(
    conn: AsyncConnection, workspace_id: str, provider: str, integ: Integrations
) -> GoogleSession:
    name = SERVICE_NAMES[provider]
    if integ.box is None or integ.google is None:
        raise NotConnected(f"{name} isn't set up on the server yet, so this wasn't done.")
    row = await (
        await conn.execute(
            """select id::text, secret_ref::text, display_name from public.tool_connections
               where workspace_id = %s and provider = %s and connection_status = 'active'
                 and secret_ref is not null
               order by updated_at desc limit 1""",
            (workspace_id, provider),
        )
    ).fetchone()
    if row is None:
        raise NotConnected(
            f"{name} isn't connected yet, so this wasn't done. Connect {name} in Settings first."
        )

    async def mark(status: str | None, error: str | None) -> None:
        await conn.execute(
            "update public.tool_connections set connection_status = coalesce(%s,"
            " connection_status), last_error = %s, last_used_at = now(), updated_at = now()"
            " where id = %s",
            (status, error, row["id"]),
        )

    try:
        secret = await load_secret(
            conn,
            integ.box,
            secret_id=row["secret_ref"],
            workspace_id=workspace_id,
            provider=provider,
        )
        token, refreshed = await fresh_access_token(integ.google, secret)
    except (GrantRevoked, SecretError) as exc:
        await mark("expired", str(exc))
        raise NotConnected(
            f"{name} access has expired or was removed, so this wasn't done. Reconnect {name} "
            "in Settings, then ask again."
        ) from exc
    if refreshed:
        await update_secret(
            conn,
            integ.box,
            secret_id=row["secret_ref"],
            workspace_id=workspace_id,
            provider=provider,
            data=secret,
        )
    return GoogleSession(
        token=token,
        email=secret.get("email") or row["display_name"] or "",
        http=integ.google.http,
        mark=mark,
    )


async def _google_call(session: GoogleSession, provider: str, call):
    """Run a Google request, translating auth failures and recording the outcome."""
    name = SERVICE_NAMES[provider]
    try:
        result = await call()
    except GrantRevoked as exc:
        await session.mark("expired", str(exc))
        raise NotConnected(
            f"{name} access has expired or was removed, so this wasn't done. Reconnect {name} "
            "in Settings, then ask again."
        ) from exc
    except EventExists:
        raise
    except GoogleError as exc:
        await session.mark(None, str(exc))
        raise ActionFailed(str(exc)) from exc
    await session.mark(None, None)
    return result


async def _send_email(
    conn: AsyncConnection, workspace_id: str, args: dict[str, Any], integ: Integrations
) -> str:
    session = await google_session(conn, workspace_id, "gmail", integ)
    msg = build_email(
        sender=session.email,
        to=str(args.get("to", "")),
        subject=str(args.get("subject", "")),
        body=str(args.get("body", "")),
        cc=args.get("cc"),
    )
    sent = await _google_call(
        session, "gmail", lambda: gmail_send(session.http, session.token, msg)
    )
    return f"Sent from {session.email} to {msg['To']} (Gmail message {sent.get('id', '?')})."


async def workspace_timezone(conn: AsyncConnection, workspace_id: str) -> str:
    row = await (
        await conn.execute("select timezone from public.workspaces where id = %s", (workspace_id,))
    ).fetchone()
    return (row["timezone"] if row else None) or "Asia/Kolkata"


def _when(start: str, end: str, tz: str) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    a = datetime.fromisoformat(start).astimezone(ZoneInfo(tz))
    b = datetime.fromisoformat(end).astimezone(ZoneInfo(tz))
    return f"{a:%a %d %b, %H:%M}–{b:%H:%M}"


async def _create_event(
    conn: AsyncConnection,
    workspace_id: str,
    args: dict[str, Any],
    integ: Integrations,
    key: str,
) -> str:
    tz = str(args.get("timezone") or await workspace_timezone(conn, workspace_id))
    event = build_event(
        title=str(args.get("title", "")),
        start=str(args.get("start", "")),
        end=args.get("end"),
        timezone=tz,
        duration_minutes=args.get("duration_minutes"),
        attendees=args.get("attendees"),
        location=args.get("location"),
        description=args.get("description"),
    )
    session = await google_session(conn, workspace_id, "google_calendar", integ)
    when = _when(event["start"]["dateTime"], event["end"]["dateTime"], tz)
    try:
        created = await _google_call(
            session,
            "google_calendar",
            lambda: calendar_insert(session.http, session.token, event, event_id=event_id_for(key)),
        )
    except EventExists:
        return f"'{event['summary']}' ({when}) was already on your calendar; not added twice."
    invited = ", ".join(a["email"] for a in event.get("attendees", []))
    text = f"Added '{event['summary']}' on {when} to {session.email}'s calendar"
    text += f"; invitations sent to {invited}." if invited else "."
    if created.get("htmlLink"):
        text += f" Open: {created['htmlLink']}"
    return text


async def check_availability(
    conn: AsyncConnection, workspace_id: str, args: dict[str, Any], integ: Integrations
) -> str:
    """Read-only: busy times between two moments (no meeting details)."""
    tz = str(args.get("timezone") or await workspace_timezone(conn, workspace_id))
    session = await google_session(conn, workspace_id, "google_calendar", integ)
    busy = await _google_call(
        session,
        "google_calendar",
        lambda: calendar_busy(
            session.http,
            session.token,
            time_min=str(args.get("time_min", "")),
            time_max=str(args.get("time_max", "")),
            timezone=tz,
        ),
    )
    if not busy:
        return f"Free the whole time ({tz})."
    lines = [f"- busy {_when(b['start'], b['end'], tz)}" for b in busy]
    return f"Busy times ({tz}); everything else is free:\n" + "\n".join(lines)


async def execute_action(
    action: str,
    args: dict[str, Any],
    browser: BrowserService | None,
    *,
    conn: AsyncConnection | None = None,
    workspace_id: str | None = None,
    integrations: Integrations | None = None,
    key: str = "",
) -> str:
    """Run one approved action. ``key`` identifies the approval (used for duplicate safety)."""
    integ = integrations or Integrations()
    if action == "send_email" and conn is not None and workspace_id:
        return await _send_email(conn, workspace_id, args, integ)
    if action == "calendar_create_event" and conn is not None and workspace_id:
        return await _create_event(conn, workspace_id, args, integ, key or str(args))

    if action == "browser_submit_form":
        if browser is None:
            raise NotConnected("The browser isn't running on this worker, so the form wasn't sent.")
        fields = args.get("fields")
        if isinstance(fields, str):
            fields = json.loads(fields)
        if not isinstance(fields, dict) or not fields:
            raise ValueError("the form fields are missing")
        result = await browser.fill_form(
            args["url"],
            {str(k): str(v) for k, v in fields.items()},
            submit=True,
            owner_approved=True,
        )
        reply = " ".join(result.page_text_after.split())[:240]
        return f"Submitted the form. The site replied: {reply}" if reply else "Submitted the form."

    spec = TOOLS_BY_NAME.get(action)
    provider = PROVIDERS_BY_KEY[spec.provider].name if spec else action
    raise NotConnected(f"{provider} isn't connected yet, so this wasn't done. Nothing was sent.")
