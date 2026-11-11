"""Carry out actions the owner approved, through the services they connected.

Only actions with a working connection actually run; for everything else we
say plainly that it wasn't done. Never pretend an action happened.
"""

import base64
import json
import mimetypes
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from psycopg import AsyncConnection
from workforce_core.connectors import CONNECTORS_BY_KEY, AuthKind, connector_for_tool
from workforce_core.google import (
    GOOGLE_DOC,
    GOOGLE_SHEET,
    EventExists,
    GoogleConfig,
    GoogleError,
    GoogleOAuth,
    GrantRevoked,
    build_email,
    build_event,
    calendar_busy,
    calendar_insert,
    drive_upload,
    event_id_for,
    fresh_access_token,
    gmail_create_draft,
    gmail_get,
    gmail_search,
    gmail_send,
)
from workforce_core.secrets import SecretBox, SecretError, load_secret, update_secret
from workforce_core.tools import TOOLS_BY_NAME
from workforce_core.verify import GITHUB_HEADERS, GRAPH

from .browser import BrowserService

ACTION_LABELS = {
    "send_email": "Send email",
    "send_whatsapp": "Send WhatsApp",
    "send_telegram": "Send Telegram message",
    "post_slack": "Post to Slack",
    "calendar_create_event": "Calendar event",
    "post_social": "Social post",
    "deploy_web": "Put website online",
    "github_save_files": "Save to GitHub",
    "book_flight": "Flight booking",
    "place_stock_order": "Stock order",
    "play_store_release": "Play Store release",
    "app_store_submit": "App Store submission",
    "browser_submit_form": "Web form",
}


class NotConnected(Exception):
    """The service this needs isn't connected (or set up on the server)."""

    def __init__(self, message: str, connector: str | None = None, fixable: bool = True):
        super().__init__(message)
        self.connector = connector
        # True when connecting it in the app fixes it (vs. a server setup problem).
        self.fixable = fixable


class ActionFailed(Exception):
    """The provider refused or failed; nothing was done."""


@dataclass
class Integrations:
    """Server-side credentials the worker needs to act for people."""

    box: SecretBox | None = None
    google: GoogleOAuth | None = None
    http: httpx.AsyncClient = field(default_factory=lambda: httpx.AsyncClient(timeout=30))

    @classmethod
    def from_env(cls) -> "Integrations":
        box = SecretBox.from_env()
        http = httpx.AsyncClient(timeout=30)
        cid, csecret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
        google = None
        if cid and csecret:
            google = GoogleOAuth(GoogleConfig(cid, csecret, ""), http)
        return cls(box=box, google=google, http=http)

    @property
    def client(self) -> httpx.AsyncClient:
        return self.google.http if self.google else self.http


@dataclass
class Session:
    """A connected account, ready to use."""

    key: str
    name: str
    secret: dict[str, Any]
    display: str
    http: httpx.AsyncClient
    mark: Any  # async (status, error) -> None

    @property
    def token(self) -> str:
        return self.secret.get("access_token") or self.secret.get("token") or ""


def _expired(name: str, key: str) -> NotConnected:
    return NotConnected(
        f"{name} access has expired or was removed, so this wasn't done. Reconnect {name} in "
        "Connections, then it continues.",
        key,
    )


async def is_connected(conn: AsyncConnection, workspace_id: str, key: str) -> bool:
    row = await (
        await conn.execute(
            "select 1 from public.tool_connections where workspace_id = %s and provider = %s"
            " and connection_status = 'active' and secret_ref is not null limit 1",
            (workspace_id, key),
        )
    ).fetchone()
    return row is not None


async def open_session(
    conn: AsyncConnection, workspace_id: str, key: str, integ: Integrations
) -> Session:
    connector = CONNECTORS_BY_KEY[key]
    name = connector.name
    if integ.box is None or (
        connector.oauth and connector.oauth.client_env == "GOOGLE" and integ.google is None
    ):
        raise NotConnected(
            f"{name} isn't set up on the server yet, so this wasn't done.", key, fixable=False
        )
    row = await (
        await conn.execute(
            """select id::text, secret_ref::text, display_name from public.tool_connections
               where workspace_id = %s and provider = %s and connection_status = 'active'
                 and secret_ref is not null
               order by updated_at desc limit 1""",
            (workspace_id, key),
        )
    ).fetchone()
    if row is None:
        raise NotConnected(
            f"{name} isn't connected yet, so this wasn't done. Connect {name} in Connections "
            "and it continues.",
            key,
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
            conn, integ.box, secret_id=row["secret_ref"], workspace_id=workspace_id, provider=key
        )
        if connector.oauth and connector.oauth.client_env == "GOOGLE":
            _, refreshed = await fresh_access_token(integ.google, secret)
            if refreshed:
                await update_secret(
                    conn,
                    integ.box,
                    secret_id=row["secret_ref"],
                    workspace_id=workspace_id,
                    provider=key,
                    data=secret,
                )
    except (GrantRevoked, SecretError) as exc:
        await mark("expired", str(exc))
        raise _expired(name, key) from exc
    return Session(
        key=key,
        name=name,
        secret=secret,
        display=secret.get("email") or row["display_name"] or name,
        http=integ.client,
        mark=mark,
    )


async def _call(session: Session, call):
    """Run a provider request, translating auth failures and recording the outcome."""
    try:
        result = await call()
    except GrantRevoked as exc:
        await session.mark("expired", str(exc))
        raise _expired(session.name, session.key) from exc
    except EventExists:
        raise
    except (GoogleError, ActionFailed) as exc:
        await session.mark(None, str(exc))
        raise ActionFailed(str(exc)) from exc
    await session.mark(None, None)
    return result


def _json_or_text(resp: httpx.Response) -> dict:
    try:
        return resp.json()
    except ValueError:
        return {"error": {"message": resp.text[:200]}}


# --- Google ---------------------------------------------------------------------------


async def _send_email(conn, ws, args, integ, ctx) -> str:
    s = await open_session(conn, ws, "gmail", integ)
    msg = build_email(
        sender=s.display,
        to=str(args.get("to", "")),
        subject=str(args.get("subject", "")),
        body=str(args.get("body", "")),
        cc=args.get("cc"),
    )
    sent = await _call(s, lambda: gmail_send(s.http, s.token, msg))
    return f"Sent from {s.display} to {msg['To']} (Gmail message {sent.get('id', '?')})."


async def workspace_timezone(conn: AsyncConnection, workspace_id: str) -> str:
    row = await (
        await conn.execute("select timezone from public.workspaces where id = %s", (workspace_id,))
    ).fetchone()
    return (row["timezone"] if row else None) or "Asia/Kolkata"


def _when(start: str, end: str, tz: str) -> str:
    a = datetime.fromisoformat(start).astimezone(ZoneInfo(tz))
    b = datetime.fromisoformat(end).astimezone(ZoneInfo(tz))
    return f"{a:%a %d %b, %H:%M}–{b:%H:%M}"


async def _create_event(conn, ws, args, integ, ctx) -> str:
    tz = str(args.get("timezone") or await workspace_timezone(conn, ws))
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
    s = await open_session(conn, ws, "google_calendar", integ)
    when = _when(event["start"]["dateTime"], event["end"]["dateTime"], tz)
    try:
        created = await _call(
            s, lambda: calendar_insert(s.http, s.token, event, event_id=event_id_for(ctx.key))
        )
    except EventExists:
        return f"'{event['summary']}' ({when}) was already on your calendar; not added twice."
    invited = ", ".join(a["email"] for a in event.get("attendees", []))
    text = f"Added '{event['summary']}' on {when} to {s.display}'s calendar"
    text += f"; invitations sent to {invited}." if invited else "."
    if created.get("htmlLink"):
        text += f" Open: {created['htmlLink']}"
    return text


async def check_availability(
    conn: AsyncConnection, workspace_id: str, args: dict[str, Any], integ: Integrations
) -> str:
    """Read-only: busy times between two moments (no meeting details)."""
    tz = str(args.get("timezone") or await workspace_timezone(conn, workspace_id))
    s = await open_session(conn, workspace_id, "google_calendar", integ)
    busy = await _call(
        s,
        lambda: calendar_busy(
            s.http,
            s.token,
            time_min=str(args.get("time_min", "")),
            time_max=str(args.get("time_max", "")),
            timezone=tz,
        ),
    )
    if not busy:
        return f"Free the whole time ({tz})."
    lines = [f"- busy {_when(b['start'], b['end'], tz)}" for b in busy]
    return f"Busy times ({tz}); everything else is free:\n" + "\n".join(lines)


# --- inbox & drive (read / drafts / save: no approval needed, nothing is sent) ----------


def _from_name(value: str) -> str:
    name, addr = parseaddr(value)
    return name or addr or value


async def inbox_search(
    conn: AsyncConnection, ws: str, args: dict[str, Any], integ: Integrations
) -> str:
    s = await open_session(conn, ws, "gmail_inbox", integ)
    query = str(args.get("query") or "in:inbox newer_than:2d")
    found = await _call(
        s, lambda: gmail_search(s.http, s.token, query, int(args.get("max_results") or 10))
    )
    if not found:
        return f"No emails match {query!r}."
    lines = [
        f"- id {m['id']} | {m['date']} | from {m['from']} | {m['subject']}"
        + (" | UNREAD" if "UNREAD" in m["labels"] else "")
        + (" | IMPORTANT" if "IMPORTANT" in m["labels"] else "")
        + f"\n  {m['snippet'][:200]}"
        for m in found
    ]
    return f"{len(found)} email(s) for {query!r}:\n" + "\n".join(lines)


async def inbox_read(
    conn: AsyncConnection, ws: str, args: dict[str, Any], integ: Integrations
) -> str:
    s = await open_session(conn, ws, "gmail_inbox", integ)
    m = await _call(s, lambda: gmail_get(s.http, s.token, str(args.get("message_id", ""))))
    text = m["text"]
    if len(text) > 12_000:
        text = text[:12_000] + "\n[…cut]"
    return (
        f"From: {m['from']}\nTo: {m['to']}\n"
        + (f"Cc: {m['cc']}\n" if m["cc"] else "")
        + f"Date: {m['date']}\nSubject: {m['subject']}\nThread: {m['thread_id']}\n\n{text}"
    )


async def inbox_draft(
    conn: AsyncConnection, ws: str, args: dict[str, Any], integ: Integrations
) -> str:
    s = await open_session(conn, ws, "gmail_inbox", integ)
    subject = str(args.get("subject", ""))
    thread_id, orig = None, None
    if args.get("reply_to_id"):
        orig = await _call(s, lambda: gmail_get(s.http, s.token, str(args["reply_to_id"])))
        thread_id = orig["thread_id"]
        if subject and not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
    msg = build_email(
        sender=s.display,
        to=str(args.get("to", "")),
        subject=subject,
        body=str(args.get("body", "")),
        cc=args.get("cc") or None,
    )
    if orig:
        mid = orig.get("message_id")
        if mid:
            msg["In-Reply-To"] = mid
            msg["References"] = mid
    draft = await _call(s, lambda: gmail_create_draft(s.http, s.token, msg, thread_id))
    return (
        f"Saved a draft in {s.display}'s Gmail to {msg['To']} ({msg['Subject']}). It is not sent; "
        f"the owner can review and send it from Gmail › Drafts (draft {draft.get('id', '?')})."
    )


def _md_to_html(md: str) -> str:
    """Just enough Markdown for a tidy Google Doc: headings, lists, bold, paragraphs."""
    out: list[str] = []
    in_list = False
    for line in md.splitlines():
        text = escape(line.strip())
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        bullet = re.match(r"^[-*•]\s+(.*)", text)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{bullet.group(1)}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        heading = re.match(r"^(#{1,3})\s+(.*)", text)
        if heading:
            n = len(heading.group(1))
            out.append(f"<h{n}>{heading.group(2)}</h{n}>")
        elif text:
            out.append(f"<p>{text}</p>")
    if in_list:
        out.append("</ul>")
    return "<html><body>" + "\n".join(out) + "</body></html>"


async def drive_save(
    conn: AsyncConnection, ws: str, args: dict[str, Any], integ: Integrations, task_id: str
) -> str:
    s = await open_session(conn, ws, "google_drive", integ)
    files = await _task_files(conn, task_id, [str(f) for f in args.get("files") or []])
    mode = str(args.get("as") or "doc")
    saved = []
    for name, content in files.items():
        stem, _, ext = name.rpartition(".")
        stem, ext = (stem or name), ext.lower()
        if mode == "sheet" and ext == "csv":
            kind, convert, body, title = "text/csv", GOOGLE_SHEET, content, stem
        elif mode == "doc" and ext in ("md", "txt", "html"):
            if ext == "md":
                body, kind = _md_to_html(content.decode("utf-8", "replace")).encode(), "text/html"
            else:
                body, kind = content, ("text/html" if ext == "html" else "text/plain")
            convert, title = GOOGLE_DOC, stem
        else:
            kind = mimetypes.guess_type(name)[0] or "application/octet-stream"
            convert, body, title = None, content, name
        made = await _call(
            s,
            lambda title=title, body=body, kind=kind, convert=convert: drive_upload(
                s.http, s.token, name=title, content=body, source_type=kind, convert_to=convert
            ),
        )
        saved.append(f"{made.get('name', title)}: {made.get('webViewLink', 'in your Drive')}")
    return "Saved to Google Drive:\n" + "\n".join(f"- {x}" for x in saved)


# --- messaging ------------------------------------------------------------------------


async def _send_whatsapp(conn, ws, args, integ, ctx) -> str:
    s = await open_session(conn, ws, "whatsapp", integ)
    to = "".join(ch for ch in str(args.get("to", "")) if ch.isdigit())
    text = str(args.get("message", "")).strip()
    if len(to) < 8 or not text:
        raise ValueError("WhatsApp needs a phone number with country code and a message")

    async def send():
        resp = await s.http.post(
            f"{GRAPH}/{s.secret['phone_number_id']}/messages",
            headers={"Authorization": f"Bearer {s.secret['access_token']}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text[:4096]},
            },
        )
        body = _json_or_text(resp)
        if resp.status_code in (401, 403) and body.get("error", {}).get("code") == 190:
            raise GrantRevoked("WhatsApp token expired")
        if resp.status_code >= 400:
            err = body.get("error", {})
            if err.get("code") == 131047:
                raise ActionFailed(
                    "they haven't messaged you in the last 24 hours, so WhatsApp "
                    "only allows an approved template message"
                )
            raise ActionFailed(f"WhatsApp refused: {err.get('message', resp.text[:200])}")
        return body

    sent = await _call(s, send)
    return f"Sent on WhatsApp from {s.display} to +{to} (message {sent['messages'][0]['id']})."


async def _send_telegram(conn, ws, args, integ, ctx) -> str:
    s = await open_session(conn, ws, "telegram", integ)
    chat, text = str(args.get("chat", "")).strip(), str(args.get("message", "")).strip()
    if not chat or not text:
        raise ValueError("Telegram needs a chat and a message")

    async def send():
        resp = await s.http.post(
            f"https://api.telegram.org/bot{s.secret['bot_token']}/sendMessage",
            json={"chat_id": chat, "text": text[:4096]},
        )
        body = _json_or_text(resp)
        if resp.status_code == 401:
            raise GrantRevoked("Telegram bot token no longer valid")
        if not body.get("ok"):
            desc = body.get("description", "unknown error")
            if "chat not found" in desc or "bot can't initiate" in desc:
                desc = "the person hasn't started a chat with your bot yet"
            raise ActionFailed(f"Telegram refused: {desc}")
        return body

    await _call(s, send)
    return f"Sent on Telegram by {s.display} to {chat}."


async def _post_slack(conn, ws, args, integ, ctx) -> str:
    s = await open_session(conn, ws, "slack", integ)
    channel, text = str(args.get("channel", "")).strip(), str(args.get("message", "")).strip()
    if not channel or not text:
        raise ValueError("Slack needs a channel and a message")

    async def send():
        resp = await s.http.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {s.token}"},
            json={
                "channel": channel.lstrip("#") if channel.startswith("#") else channel,
                "text": text,
            },
        )
        body = _json_or_text(resp)
        if not body.get("ok"):
            err = body.get("error", "unknown_error")
            if err in ("invalid_auth", "token_revoked", "account_inactive"):
                raise GrantRevoked(err)
            friendly = {
                "not_in_channel": "the app isn't in that channel; add it there first",
                "channel_not_found": "that channel doesn't exist or is private",
            }.get(err, err)
            raise ActionFailed(f"Slack refused: {friendly}")
        return body

    await _call(s, send)
    return f"Posted to {channel} in {s.display}."


# --- build & deploy -------------------------------------------------------------------


async def _task_files(conn: AsyncConnection, task_id: str, names: list[str]) -> dict[str, bytes]:
    if not names:
        raise ValueError("no files were listed")
    rows = await (
        await conn.execute(
            "select distinct on (name) name, content from public.artifacts"
            " where task_id = %s and name = any(%s) order by name, created_at desc",
            (task_id, names),
        )
    ).fetchall()
    found = {r["name"]: bytes(r["content"]) for r in rows if r["content"] is not None}
    missing = [n for n in names if n not in found]
    if missing:
        raise ValueError(f"these files weren't made in this task: {', '.join(missing)}")
    return found


async def _github_save(conn, ws, args, integ, ctx) -> str:
    s = await open_session(conn, ws, "github", integ)
    repo = "".join(ch for ch in str(args.get("repo", "")) if ch.isalnum() or ch in "-_.")[:90]
    if not repo:
        raise ValueError("GitHub needs a repository name")
    files = await _task_files(conn, ctx.task_id, [str(f) for f in args.get("files") or []])
    headers = {"Authorization": f"Bearer {s.secret['token']}", **GITHUB_HEADERS}
    api = "https://api.github.com"

    async def save():
        me = await s.http.get(f"{api}/user", headers=headers)
        if me.status_code == 401:
            raise GrantRevoked("GitHub token no longer valid")
        owner = me.json()["login"]
        existing = await s.http.get(f"{api}/repos/{owner}/{repo}", headers=headers)
        if existing.status_code == 404:
            made = await s.http.post(
                f"{api}/user/repos",
                headers=headers,
                json={"name": repo, "private": bool(args.get("private", True)), "auto_init": True},
            )
            if made.status_code >= 400:
                raise ActionFailed(
                    f"GitHub couldn't create the repository: "
                    f"{_json_or_text(made).get('message', made.text[:200])}"
                )
        for name, content in files.items():
            url = f"{api}/repos/{owner}/{repo}/contents/{name}"
            current = await s.http.get(url, headers=headers)
            body = {
                "message": str(args.get("message") or f"Add {name}"),
                "content": base64.b64encode(content).decode(),
            }
            if current.status_code == 200:
                body["sha"] = current.json()["sha"]
            put = await s.http.put(url, headers=headers, json=body)
            if put.status_code >= 400:
                raise ActionFailed(
                    f"GitHub refused {name}: {_json_or_text(put).get('message', put.text[:200])}"
                )
        return owner

    owner = await _call(s, save)
    return f"Saved {len(files)} file(s) to https://github.com/{owner}/{repo}."


async def _deploy_web(conn, ws, args, integ, ctx) -> str:
    s = await open_session(conn, ws, "vercel", integ)
    project = "".join(
        ch for ch in str(args.get("project", "")).lower() if ch.isalnum() or ch == "-"
    ).strip("-")[:90]
    if not project:
        raise ValueError("the website needs a short project name")
    files = await _task_files(conn, ctx.task_id, [str(f) for f in args.get("files") or []])
    if "index.html" not in files:
        raise ValueError("a website needs an index.html file")

    async def deploy():
        resp = await s.http.post(
            "https://api.vercel.com/v13/deployments",
            headers={"Authorization": f"Bearer {s.secret['token']}"},
            json={
                "name": project,
                "target": "production",
                "projectSettings": {"framework": None},
                "files": [
                    {"file": n, "data": base64.b64encode(c).decode(), "encoding": "base64"}
                    for n, c in files.items()
                ],
            },
        )
        body = _json_or_text(resp)
        if resp.status_code in (401, 403):
            raise GrantRevoked("Vercel token no longer valid")
        if resp.status_code >= 400:
            raise ActionFailed(f"Vercel refused: {body.get('error', {}).get('message', '')}")
        return body

    body = await _call(s, deploy)
    url = next(iter(body.get("alias") or []), None) or body.get("url", "")
    return (
        f"Your website is going live at https://{url} (it can take a minute to finish). "
        f"Published {len(files)} file(s) from your Vercel account."
    )


# --- dispatch -------------------------------------------------------------------------


@dataclass
class ActionContext:
    key: str  # approval id: duplicate safety
    task_id: str


EXECUTORS = {
    "send_email": _send_email,
    "calendar_create_event": _create_event,
    "send_whatsapp": _send_whatsapp,
    "send_telegram": _send_telegram,
    "post_slack": _post_slack,
    "github_save_files": _github_save,
    "deploy_web": _deploy_web,
}


async def execute_action(
    action: str,
    args: dict[str, Any],
    browser: BrowserService | None,
    *,
    conn: AsyncConnection | None = None,
    workspace_id: str | None = None,
    integrations: Integrations | None = None,
    key: str = "",
    task_id: str = "",
) -> str:
    """Run one approved action."""
    integ = integrations or Integrations()
    if action in EXECUTORS and conn is not None and workspace_id:
        ctx = ActionContext(key=key or json.dumps(args, sort_keys=True), task_id=task_id)
        return await EXECUTORS[action](conn, workspace_id, args, integ, ctx)

    if action == "browser_submit_form":
        if browser is None:
            raise NotConnected(
                "The browser isn't running on this worker, so the form wasn't sent.", fixable=False
            )
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

    connector = connector_for_tool(action)
    spec = TOOLS_BY_NAME.get(action)
    name = connector.name if connector else (spec.provider if spec else action)
    raise NotConnected(
        f"{name} isn't available yet, so this wasn't done. Nothing was sent.",
        connector.key if connector else None,
        fixable=False,
    )


def needs_connection(action: str) -> str | None:
    """The connector key an action needs (live, connectable), if any."""
    c = connector_for_tool(action)
    if c and c.live and c.auth in (AuthKind.OAUTH2, AuthKind.API_KEY):
        return c.key
    return None


def can_connect(key: str, integ: Integrations) -> bool:
    """Would connecting it in the app make it work on this server?"""
    c = CONNECTORS_BY_KEY[key]
    if integ.box is None:
        return False
    if c.oauth and c.oauth.client_env == "GOOGLE":
        return integ.google is not None
    return c.auth == AuthKind.API_KEY or c.configured()
