"""Chat with your assistant from Telegram, through your own bot (free).

1. Connect your bot in Connections (token from @BotFather).
2. POST /telegram/link gives a one-time link t.me/<bot>?start=<code>; opening it in
   Telegram links that chat to you. Only your linked chat can talk to your assistant.
3. Telegram calls /telegram/webhook/<id> for each message, proving itself with a secret
   header; replies come from the same assistant (memory, tasks, reminders) as the app.
Alerts (task updates, reminders, important email) are also forwarded there by the worker.
"""

import contextlib
import hmac
import logging
import secrets as pysecrets
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from pydantic import BaseModel
from workforce_core import telegram as tg
from workforce_core.secrets import SecretBox

from ..auth import CurrentUser, UserDep
from ..deps import ConnDep, SettingsDep
from .chat import assistant_events, check_limits, save_user_message
from .workspace import assistant_name

log = logging.getLogger(__name__)
router = APIRouter(prefix="/telegram", tags=["telegram"])


class LinkOut(BaseModel):
    bot: str | None = None  # @username of the connected bot
    linked: bool = False
    link_url: str | None = None  # open in Telegram to link (one-time, 30 minutes)
    available: bool = True
    reason: str | None = None


def _box(settings) -> SecretBox | None:
    return SecretBox(settings.token_encryption_key) if settings.token_encryption_key else None


async def _bot(conn, settings, user: CurrentUser) -> tuple[str, str] | None:
    box = _box(settings)
    return await tg.bot_token(conn, box, user.workspace_id) if box else None


@router.get("/link", response_model=LinkOut)
async def link_status(user: UserDep, conn: ConnDep, settings: SettingsDep) -> LinkOut:
    row = await (
        await conn.execute(
            "select chat_id from public.telegram_links where user_id = %s and workspace_id = %s",
            (user.user_id, user.workspace_id),
        )
    ).fetchone()
    found = await _bot(conn, settings, user)
    if found is None:
        return LinkOut(available=False, reason="Connect your Telegram bot in Connections first.")
    return LinkOut(linked=bool(row and row["chat_id"]), available=bool(settings.public_api_url))


@router.post("/link", response_model=LinkOut)
async def start_link(
    request: Request, user: UserDep, conn: ConnDep, settings: SettingsDep
) -> LinkOut:
    if not settings.public_api_url:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Telegram chat isn't set up on the server yet (PUBLIC_API_URL).",
        )
    found = await _bot(conn, settings, user)
    if found is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Connect your Telegram bot in Connections first."
        )
    token, connection_id = found
    http: httpx.AsyncClient = request.app.state.google_http
    secret, secret_hash = tg.new_secret()
    code = pysecrets.token_urlsafe(12)
    row = await (
        await conn.execute(
            """insert into public.telegram_links
                   (workspace_id, user_id, connection_id, secret_hash, link_code, code_expires_at)
               values (%s, %s, %s, %s, %s, %s)
               on conflict (user_id, workspace_id) do update set
                   connection_id = excluded.connection_id, secret_hash = excluded.secret_hash,
                   link_code = excluded.link_code, code_expires_at = excluded.code_expires_at
               returning id::text, chat_id""",
            (
                user.workspace_id,
                user.user_id,
                connection_id,
                secret_hash,
                code,
                datetime.now(UTC) + timedelta(minutes=30),
            ),
        )
    ).fetchone()
    base = settings.public_api_url.rstrip("/")
    try:
        await tg.call(
            http,
            token,
            "setWebhook",
            {
                "url": f"{base}/telegram/webhook/{row['id']}",
                "secret_token": secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
        )
        me = await tg.call(http, token, "getMe", {})
    except (ValueError, httpx.HTTPError) as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Telegram refused: {exc}") from exc
    bot = me.get("username", "")
    return LinkOut(
        bot=f"@{bot}",
        linked=bool(row["chat_id"]),
        link_url=f"https://t.me/{bot}?start={code}",
    )


@router.post("/unlink", response_model=LinkOut)
async def unlink(request: Request, user: UserDep, conn: ConnDep, settings: SettingsDep) -> LinkOut:
    await conn.execute(
        "delete from public.telegram_links where user_id = %s and workspace_id = %s",
        (user.user_id, user.workspace_id),
    )
    found = await _bot(conn, settings, user)
    if found:
        with contextlib.suppress(ValueError, httpx.HTTPError):
            await tg.call(request.app.state.google_http, found[0], "deleteWebhook", {})
    return LinkOut(linked=False)


@router.post("/webhook/{link_id}", include_in_schema=False)
async def webhook(
    link_id: str,
    request: Request,
    background: BackgroundTasks,
    conn: ConnDep,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    row = await (
        await conn.execute(
            "select secret_hash from public.telegram_links where id::text = %s", (link_id,)
        )
    ).fetchone()
    if (
        row is None
        or not x_telegram_bot_api_secret_token
        or not hmac.compare_digest(
            tg.hash_secret(x_telegram_bot_api_secret_token), row["secret_hash"]
        )
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    update = await request.json()
    background.add_task(_handle, request.app, link_id, update)
    return {"ok": True}  # answer Telegram at once; the reply follows


async def _handle(app, link_id: str, update: dict) -> None:
    msg = update.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if not chat_id:
        return
    text = (msg.get("text") or "").strip()
    settings = app.state.settings
    http: httpx.AsyncClient = app.state.google_http
    box = _box(settings)
    if box is None:
        return
    async with app.state.pool.connection() as conn:
        link = await (
            await conn.execute(
                """select l.id::text, l.workspace_id::text, l.user_id::text, l.chat_id,
                          l.link_code, l.code_expires_at, l.conversation_id::text,
                          m.role, u.email
                   from public.telegram_links l
                   join public.workspace_members m
                     on m.workspace_id = l.workspace_id and m.user_id = l.user_id
                   join auth.users u on u.id = l.user_id
                   where l.id::text = %s""",
                (link_id,),
            )
        ).fetchone()
        if link is None:
            return
        found = await tg.bot_token(conn, box, link["workspace_id"])
        if found is None:
            return
        token = found[0]
        user = CurrentUser(link["user_id"], link["email"], link["workspace_id"], link["role"])

        async def say(reply: str) -> None:
            try:
                await tg.send(http, token, chat_id, reply)
            except (ValueError, httpx.HTTPError) as exc:
                log.info("telegram reply failed: %s", exc)

        if text.startswith("/start"):
            code = text.split(maxsplit=1)[1] if " " in text else ""
            fresh = link["code_expires_at"] and link["code_expires_at"] > datetime.now(UTC)
            if (
                code
                and link["link_code"]
                and fresh
                and hmac.compare_digest(code, link["link_code"])
            ):
                await conn.execute(
                    "update public.telegram_links set chat_id = %s, linked_at = now(),"
                    " link_code = null, code_expires_at = null where id = %s",
                    (chat_id, link["id"]),
                )
                name = await assistant_name(conn, user)
                await say(
                    f"✅ Linked. I'm {name}, your assistant. Message me here any time; "
                    "updates, reminders and important-email alerts will come here too."
                )
            elif chat_id == link["chat_id"]:
                await say("You're already linked. Just send me a message.")
            else:
                await say("This is a private assistant. Open the link from the Workforce OS app.")
            return
        if chat_id != link["chat_id"]:
            await say("This is a private assistant.")
            return
        if not text:
            await say("I can read text messages here. Send photos and PDFs in the app.")
            return
        model = app.state.chat_model
        if model is None:
            await say("The assistant isn't set up on the server yet.")
            return
        try:
            await check_limits(conn, user, settings)
        except HTTPException as exc:
            await say(str(exc.detail))
            return
        conv_id = link["conversation_id"]
        exists = (
            conv_id
            and await (
                await conn.execute(
                    "select 1 from public.conversations where id = %s and archived_at is null",
                    (conv_id,),
                )
            ).fetchone()
        )
        conv = await save_user_message(
            conn, user, conv_id if exists else None, text[:8000], "text", []
        )
        if not exists:
            await conn.execute(
                "update public.conversations set title = 'Telegram' where id = %s", (conv["id"],)
            )
            await conn.execute(
                "update public.telegram_links set conversation_id = %s where id = %s",
                (conv["id"], link["id"]),
            )
    with contextlib.suppress(ValueError, httpx.HTTPError):
        await tg.call(http, token, "sendChatAction", {"chat_id": chat_id, "action": "typing"})
    async for event in assistant_events(
        app.state.pool, model, settings, user, conv["id"], text, "text"
    ):
        if event["type"] == "done":
            await say(event["text"] or "Done.")
        elif event["type"] == "error":
            await say(event["message"])
