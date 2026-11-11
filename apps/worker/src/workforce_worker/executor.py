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
    GoogleConfig,
    GoogleError,
    GoogleOAuth,
    GrantRevoked,
    build_email,
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


async def _send_email(
    conn: AsyncConnection, workspace_id: str, args: dict[str, Any], integ: Integrations
) -> str:
    if integ.box is None or integ.google is None:
        raise NotConnected("Gmail isn't set up on the server yet, so this wasn't sent.")
    row = await (
        await conn.execute(
            """select id::text, secret_ref::text, display_name from public.tool_connections
               where workspace_id = %s and provider = 'gmail' and connection_status = 'active'
                 and secret_ref is not null
               order by updated_at desc limit 1""",
            (workspace_id,),
        )
    ).fetchone()
    if row is None:
        raise NotConnected(
            "Gmail isn't connected yet, so this wasn't sent. Connect Gmail in Settings first."
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
            provider="gmail",
        )
        token, refreshed = await fresh_access_token(integ.google, secret)
        if refreshed:
            await update_secret(
                conn,
                integ.box,
                secret_id=row["secret_ref"],
                workspace_id=workspace_id,
                provider="gmail",
                data=secret,
            )
        sender = secret.get("email") or row["display_name"] or ""
        msg = build_email(
            sender=sender,
            to=str(args.get("to", "")),
            subject=str(args.get("subject", "")),
            body=str(args.get("body", "")),
            cc=args.get("cc"),
        )
        sent = await gmail_send(integ.google.http, token, msg)
    except (GrantRevoked, SecretError) as exc:
        await mark("expired", str(exc))
        raise NotConnected(
            "Gmail access has expired or was removed, so this wasn't sent. Reconnect Gmail in "
            "Settings, then ask again."
        ) from exc
    except GoogleError as exc:
        await mark(None, str(exc))
        raise ActionFailed(str(exc)) from exc
    await mark(None, None)
    return f"Sent from {sender} to {msg['To']} (Gmail message {sent.get('id', '?')})."


async def execute_action(
    action: str,
    args: dict[str, Any],
    browser: BrowserService | None,
    *,
    conn: AsyncConnection | None = None,
    workspace_id: str | None = None,
    integrations: Integrations | None = None,
) -> str:
    if action == "send_email" and conn is not None and workspace_id:
        return await _send_email(conn, workspace_id, args, integrations or Integrations())

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
