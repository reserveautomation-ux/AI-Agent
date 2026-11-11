"""Telegram as a chat channel: talk to your assistant through your own bot.

Shared by the API (webhook, replies) and the worker (forwarding alerts and task updates).
Telegram's Bot API: https://core.telegram.org/bots/api
"""

import hashlib
import logging
import secrets as pysecrets
from typing import Any

import httpx
from psycopg import AsyncConnection

from .secrets import SecretBox, SecretError, load_secret

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
MAX_TEXT = 4000  # Telegram allows 4096 per message


def new_secret() -> tuple[str, str]:
    """(secret for Telegram's X-Telegram-Bot-Api-Secret-Token header, its hash to store)."""
    secret = pysecrets.token_urlsafe(32)
    return secret, hash_secret(secret)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


async def bot_token(
    conn: AsyncConnection, box: SecretBox, workspace_id: str
) -> tuple[str, str] | None:
    """(bot token, connection id) of the workspace's connected Telegram bot, if any."""
    row = await (
        await conn.execute(
            "select id::text, secret_ref::text from public.tool_connections where workspace_id = %s"
            " and provider = 'telegram' and connection_status = 'active' and secret_ref is not null"
            " order by created_at desc limit 1",
            (workspace_id,),
        )
    ).fetchone()
    if row is None:
        return None
    try:
        secret = await load_secret(
            conn, box, secret_id=row["secret_ref"], workspace_id=workspace_id, provider="telegram"
        )
    except SecretError:
        return None
    return secret["bot_token"], row["id"]


async def call(http: httpx.AsyncClient, token: str, method: str, payload: dict[str, Any]) -> dict:
    resp = await http.post(f"{API}/bot{token}/{method}", json=payload)
    body = resp.json() if resp.content else {}
    if not body.get("ok"):
        raise ValueError(
            body.get("description") or f"Telegram {method} failed ({resp.status_code})"
        )
    return body.get("result") or {}


def chunks(text: str) -> list[str]:
    text = text.strip() or "…"
    out = []
    while text:
        if len(text) <= MAX_TEXT:
            out.append(text)
            break
        cut = text.rfind("\n", 0, MAX_TEXT)
        cut = cut if cut > MAX_TEXT // 2 else MAX_TEXT
        out.append(text[:cut])
        text = text[cut:].lstrip()
    return out


async def send(http: httpx.AsyncClient, token: str, chat_id: int, text: str) -> None:
    for part in chunks(text):
        await call(http, token, "sendMessage", {"chat_id": chat_id, "text": part})


async def forward(
    conn: AsyncConnection,
    box: SecretBox | None,
    http: httpx.AsyncClient,
    *,
    workspace_id: str,
    user_id: str,
    text: str,
) -> bool:
    """Send an alert to the person's linked Telegram chat, if they linked one."""
    if box is None:
        return False
    link = await (
        await conn.execute(
            "select chat_id from public.telegram_links where user_id = %s and workspace_id = %s"
            " and chat_id is not null",
            (user_id, workspace_id),
        )
    ).fetchone()
    if link is None:
        return False
    found = await bot_token(conn, box, workspace_id)
    if found is None:
        return False
    try:
        await send(http, found[0], link["chat_id"], text)
        return True
    except (ValueError, httpx.HTTPError) as exc:
        log.info("telegram forward failed: %s", exc)
        return False
