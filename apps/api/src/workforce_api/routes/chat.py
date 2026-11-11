"""Chat with your assistant: conversations and a streaming reply endpoint.

POST /chat streams Server-Sent Events: ``data: {json}`` lines with
{"type": "conversation"}, then "text" chunks, "task" / "memory" events, and a
final "done" (or "error"). Conversations are private to the person.
"""

import asyncio
import base64
import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, model_validator
from workforce_core.schedules import create_schedule

from .. import chat as engine
from ..auth import CurrentUser, UserDep
from ..deps import ConnDep, SettingsDep
from ..schemas import TaskCreate
from .tasks import WorkspaceStopped, insert_task
from .workspace import assistant_name

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    content: str = Field(default="", max_length=8000)
    conversation_id: str | None = None
    via: Literal["text", "voice"] = "text"
    attachments: list[str] = Field(default_factory=list, max_length=5)  # chat_files ids

    @model_validator(mode="after")
    def not_blank(self) -> "ChatIn":
        self.content = self.content.strip()
        if not self.content and not self.attachments:
            raise ValueError("message must not be blank")
        return self


IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE = 5 * 1024 * 1024  # Claude's limit per image
MAX_PDF = 10 * 1024 * 1024
MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
    "application/pdf": (b"%PDF",),
}


class FileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    media_type: str
    data: str = Field(min_length=4, max_length=15_000_000)  # base64


class FileOut(BaseModel):
    id: str
    name: str
    media_type: str
    size_bytes: int


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class TaskRef(BaseModel):
    id: str
    title: str
    status: str
    waiting_for_connection: list[str] = []


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    via: str
    meta: dict[str, Any]
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    tasks: dict[str, TaskRef]  # every task mentioned in the messages, with its current status


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= 60 else line[:57].rstrip() + "…"


async def _own_conversation(conn, user: CurrentUser, conversation_id: str) -> dict:
    row = await (
        await conn.execute(
            "select id::text, title, created_at, updated_at from public.conversations"
            " where id::text = %s and user_id = %s and workspace_id = %s"
            " and archived_at is null",
            (conversation_id, user.user_id, user.workspace_id),
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
    return row


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(user: UserDep, conn: ConnDep) -> list[ConversationOut]:
    rows = await (
        await conn.execute(
            "select id::text, title, created_at, updated_at from public.conversations"
            " where user_id = %s and workspace_id = %s and archived_at is null"
            " order by updated_at desc limit 100",
            (user.user_id, user.workspace_id),
        )
    ).fetchall()
    return [ConversationOut(**r) for r in rows]


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str, user: UserDep, conn: ConnDep
) -> ConversationDetail:
    conv = await _own_conversation(conn, user, conversation_id)
    rows = await (
        await conn.execute(
            "select id::text, role, content, via, meta, created_at from public.chat_messages"
            " where conversation_id = %s order by created_at limit 500",
            (conversation_id,),
        )
    ).fetchall()
    task_ids = {r["meta"].get("task_id") for r in rows} | {
        t.get("id") for r in rows for t in r["meta"].get("tasks", [])
    }
    task_ids.discard(None)
    tasks = await (
        await conn.execute(
            "select id::text, title, status::text, waiting_for_connection from public.tasks"
            " where workspace_id = %s and id::text = any(%s)",
            (user.workspace_id, list(task_ids)),
        )
    ).fetchall()
    return ConversationDetail(
        **conv,
        messages=[MessageOut(**r) for r in rows],
        tasks={t["id"]: TaskRef(**t) for t in tasks},
    )


@router.post("/conversations/{conversation_id}/rename", response_model=ConversationOut)
async def rename(conversation_id: str, body: RenameIn, user: UserDep, conn: ConnDep):
    await _own_conversation(conn, user, conversation_id)
    row = await (
        await conn.execute(
            "update public.conversations set title = %s where id = %s"
            " returning id::text, title, created_at, updated_at",
            (body.title.strip(), conversation_id),
        )
    ).fetchone()
    return ConversationOut(**row)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(conversation_id: str, user: UserDep, conn: ConnDep) -> None:
    await _own_conversation(conn, user, conversation_id)
    await conn.execute(
        "update public.conversations set archived_at = now() where id = %s", (conversation_id,)
    )


class _Tools:
    """What the assistant can do from chat, as this person."""

    def __init__(self, conn, user: CurrentUser, conversation_id: str):
        self.conn, self.user, self.conversation_id = conn, user, conversation_id

    async def start_task(self, objective: str, title: str) -> dict:
        if not objective.strip():
            raise ValueError("the task needs an objective")
        try:
            row = await insert_task(
                self.conn,
                self.user,
                TaskCreate(objective=objective, title=(title.strip() or None) and title[:60]),
                conversation_id=self.conversation_id,
                source="chat",
            )
        except WorkspaceStopped as exc:
            raise ValueError(
                "Emergency stop is on, so no new work can start. They can resume in Settings."
            ) from exc
        return {"id": row["id"], "title": row["title"], "status": str(row["status"])}

    async def schedule(self, args: dict) -> dict:
        made = await create_schedule(
            self.conn,
            workspace_id=self.user.workspace_id,
            user_id=self.user.user_id,
            kind=str(args.get("kind", "reminder")),
            what=str(args.get("what", "")),
            at=str(args.get("at", "")),
            repeat=str(args.get("repeat") or "none"),
            title=(str(args["title"])[:60] if args.get("title") else None),
            conversation_id=self.conversation_id,
        )
        return {
            "id": made.id,
            "title": made.title,
            "kind": made.kind,
            "repeat": made.repeat,
            "next_run_at": made.next_run_at.isoformat(),
            "text": made.text,
        }

    async def remember(self, content: str, kind: str, trusted: bool) -> str:
        return await engine.save_memory(
            self.conn, self.user.workspace_id, content, kind, trusted=trusted
        )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


async def check_limits(conn, user: CurrentUser, settings) -> None:
    """Per-person rate limit and per-workspace daily chat budget (until billing exists)."""
    recent = await (
        await conn.execute(
            "select count(*) as n from public.chat_messages m"
            " join public.conversations c on c.id = m.conversation_id"
            " where m.workspace_id = %s and c.user_id = %s and m.role = 'user'"
            " and m.created_at > now() - interval '1 minute'",
            (user.workspace_id, user.user_id),
        )
    ).fetchone()
    if recent["n"] >= settings.chat_messages_per_minute:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Slow down a little and try again.")
    if await engine.chat_spend_today(conn, user.workspace_id) >= settings.chat_daily_budget_usd:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Today's chat limit is used up. Tasks still run; chat is back within 24 hours.",
        )


async def save_user_message(
    conn, user: CurrentUser, conversation_id: str | None, content: str, via: str, attachments: list
) -> dict:
    async with conn.transaction():
        if conversation_id:
            conv = await _own_conversation(conn, user, conversation_id)
        else:
            conv = await (
                await conn.execute(
                    "insert into public.conversations (workspace_id, user_id, title)"
                    " values (%s, %s, %s) returning id::text, title, created_at, updated_at",
                    (user.workspace_id, user.user_id, _title(content or attachments[0]["name"])),
                )
            ).fetchone()
        await conn.execute(
            "insert into public.chat_messages"
            " (conversation_id, workspace_id, role, content, via, meta)"
            " values (%s, %s, 'user', %s, %s, %s)",
            (
                conv["id"],
                user.workspace_id,
                content,
                via,
                Jsonb({"attachments": attachments} if attachments else {}),
            ),
        )
        await conn.execute(
            "update public.conversations set updated_at = now() where id = %s", (conv["id"],)
        )
    return conv


async def assistant_events(
    pool: AsyncConnectionPool,
    model: "engine.ChatModel",
    settings,
    user: CurrentUser,
    conversation_id: str,
    query: str,
    via: str,
):
    """Run the assistant on a conversation; yields chat events and ends with done/error.
    The reply is saved even if the caller stops listening part-way."""
    text, saved = "", False
    async with pool.connection() as c:
        try:
            system = await engine.system_prompt(
                c,
                workspace_id=user.workspace_id,
                conversation_id=conversation_id,
                who=user.email or "the user",
                query=query,
                voice=via == "voice",
                name=await assistant_name(c, user),
            )
            params = {
                "model": settings.chat_model,
                "max_tokens": 4000,
                "system": system,
                "messages": await engine.history(c, conversation_id),
                "tools": engine.TOOLS,
                "thinking": {"type": "adaptive"},
                "output_config": {"effort": settings.chat_effort},
                "cache_control": {"type": "ephemeral"},
            }
            async for event in engine.reply(
                model,
                c,
                _Tools(c, user, conversation_id),
                params=params,
                workspace_id=user.workspace_id,
            ):
                if event["type"] == "text":
                    text += event["text"]
                if event["type"] != "end":
                    yield event
                    continue
                msg = await _save_reply(c, conversation_id, user.workspace_id, event, via)
                saved = True
                yield {"type": "done", "message_id": msg, "text": event["text"]}
        except Exception as exc:  # noqa: BLE001 - tell the app, keep what was said
            if not saved:
                await _save_reply(
                    c,
                    conversation_id,
                    user.workspace_id,
                    {"text": text.strip() or "(no reply)", "tasks": [], "memories": []},
                    via,
                    error=True,
                )
                saved = True
            message = (
                "The assistant is busy right now. Please try again in a moment."
                if "anthropic" in type(exc).__module__
                else "Something went wrong while replying. Please try again."
            )
            yield {"type": "error", "message": message}
        finally:
            if not saved and text.strip():  # the listener went away mid-reply
                await asyncio.shield(
                    _save_reply(
                        c,
                        conversation_id,
                        user.workspace_id,
                        {"text": text.strip(), "tasks": [], "memories": []},
                        via,
                        error=True,
                    )
                )


@router.post("/chat")
async def chat(body: ChatIn, request: Request, user: UserDep, conn: ConnDep, settings: SettingsDep):
    model: engine.ChatModel | None = request.app.state.chat_model
    if model is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The assistant isn't set up on the server yet (ANTHROPIC_API_KEY).",
        )
    await check_limits(conn, user, settings)

    attachments: list[dict] = []
    if body.attachments:
        found = await (
            await conn.execute(
                "select id::text, name, media_type from public.chat_files"
                " where id::text = any(%s) and user_id = %s and workspace_id = %s",
                (body.attachments, user.user_id, user.workspace_id),
            )
        ).fetchall()
        by_id = {f["id"]: f for f in found}
        if len(by_id) != len(set(body.attachments)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "attachment not found")
        attachments = [dict(by_id[i]) for i in dict.fromkeys(body.attachments)]

    conv = await save_user_message(
        conn, user, body.conversation_id, body.content, body.via, attachments
    )
    pool: AsyncConnectionPool = request.app.state.pool
    query = body.content or " ".join(a["name"] for a in attachments)

    async def stream():
        yield _sse({"type": "conversation", "id": conv["id"], "title": conv["title"]})
        async for event in assistant_events(
            pool, model, settings, user, conv["id"], query, body.via
        ):
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _save_reply(conn, conversation_id, workspace_id, event, via, *, error=False) -> str:
    meta: dict[str, Any] = {"kind": "reply"}
    if event.get("tasks"):
        meta["tasks"] = event["tasks"]
    if event.get("memories"):
        meta["memories"] = event["memories"]
    if event.get("schedules"):
        meta["schedules"] = event["schedules"]
    if error:
        meta["interrupted"] = True
    row = await (
        await conn.execute(
            "insert into public.chat_messages (conversation_id, workspace_id, role, content, via,"
            " meta) values (%s, %s, 'assistant', %s, %s, %s) returning id::text",
            (conversation_id, workspace_id, event["text"][:40000], via, Jsonb(meta)),
        )
    ).fetchone()
    await conn.execute(
        "update public.conversations set updated_at = now() where id = %s", (conversation_id,)
    )
    return row["id"]


# --- reminders & repeating jobs ------------------------------------------------------------


class ScheduleOut(BaseModel):
    id: str
    kind: str
    title: str
    what: str
    repeat: str
    timezone: str
    next_run_at: datetime | None
    active: bool
    runs: int
    last_run_at: datetime | None


@router.get("/schedules", response_model=list[ScheduleOut])
async def list_schedules(user: UserDep, conn: ConnDep) -> list[ScheduleOut]:
    rows = await (
        await conn.execute(
            "select id::text, kind, title, what, repeat, timezone, next_run_at, active, runs,"
            " last_run_at from public.schedules where user_id = %s and workspace_id = %s"
            " and (active or last_run_at > now() - interval '7 days')"
            " order by active desc, next_run_at nulls last limit 200",
            (user.user_id, user.workspace_id),
        )
    ).fetchall()
    return [ScheduleOut(**r) for r in rows]


@router.post("/schedules/{schedule_id}/cancel", response_model=ScheduleOut)
async def cancel_schedule(schedule_id: str, user: UserDep, conn: ConnDep) -> ScheduleOut:
    row = await (
        await conn.execute(
            "update public.schedules set active = false where id::text = %s and user_id = %s"
            " and workspace_id = %s returning id::text, kind, title, what, repeat, timezone,"
            " next_run_at, active, runs, last_run_at",
            (schedule_id, user.user_id, user.workspace_id),
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "reminder not found")
    return ScheduleOut(**row)


# --- photos & PDFs ---------------------------------------------------------------------------


@router.post("/chat/files", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(body: FileIn, user: UserDep, conn: ConnDep) -> FileOut:
    """Attach a photo (JPEG, PNG, GIF, WebP up to 5 MB) or PDF (up to 10 MB) to a chat."""
    kind = body.media_type.lower()
    if kind not in MAGIC:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send a photo (JPEG, PNG, GIF, WebP) or a PDF."
        )
    try:
        data = base64.b64decode(body.data.split(",", 1)[-1], validate=True)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "file data isn't base64"
        ) from exc
    limit = MAX_IMAGE if kind in IMAGE_TYPES else MAX_PDF
    if not data or len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"That file is too big (max {limit // (1024 * 1024)} MB).",
        )
    if not data.startswith(MAGIC[kind]):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "That file doesn't look like the type it says."
        )
    today = await (
        await conn.execute(
            "select count(*) as n from public.chat_files where user_id = %s"
            " and created_at > now() - interval '1 day'",
            (user.user_id,),
        )
    ).fetchone()
    if today["n"] >= 200:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many files today.")
    name = " ".join(body.name.replace("/", " ").replace("\\", " ").split())[:200] or "file"
    row = await (
        await conn.execute(
            "insert into public.chat_files (workspace_id, user_id, name, media_type, size_bytes,"
            " content) values (%s, %s, %s, %s, %s, %s) returning id::text",
            (user.workspace_id, user.user_id, name, kind, len(data), data),
        )
    ).fetchone()
    return FileOut(id=row["id"], name=name, media_type=kind, size_bytes=len(data))


@router.get("/chat/files/{file_id}")
async def get_file(file_id: str, user: UserDep, conn: ConnDep) -> Response:
    row = await (
        await conn.execute(
            "select name, media_type, content from public.chat_files"
            " where id::text = %s and user_id = %s and workspace_id = %s",
            (file_id, user.user_id, user.workspace_id),
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return Response(
        bytes(row["content"]),
        media_type=row["media_type"],
        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )
