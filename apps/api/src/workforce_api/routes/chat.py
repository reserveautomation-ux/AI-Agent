"""Chat with your assistant: conversations and a streaming reply endpoint.

POST /chat streams Server-Sent Events: ``data: {json}`` lines with
{"type": "conversation"}, then "text" chunks, "task" / "memory" events, and a
final "done" (or "error"). Conversations are private to the person.
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, field_validator

from .. import chat as engine
from ..auth import CurrentUser, UserDep
from ..deps import ConnDep, SettingsDep
from ..schemas import TaskCreate
from .tasks import WorkspaceStopped, insert_task
from .workspace import assistant_name

router = APIRouter(tags=["chat"])


class ChatIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    via: Literal["text", "voice"] = "text"

    @field_validator("content")
    @classmethod
    def not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message must not be blank")
        return v.strip()


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

    async def remember(self, content: str, kind: str, trusted: bool) -> str:
        return await engine.save_memory(
            self.conn, self.user.workspace_id, content, kind, trusted=trusted
        )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


@router.post("/chat")
async def chat(body: ChatIn, request: Request, user: UserDep, conn: ConnDep, settings: SettingsDep):
    model: engine.ChatModel | None = request.app.state.chat_model
    if model is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The assistant isn't set up on the server yet (ANTHROPIC_API_KEY).",
        )
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

    async with conn.transaction():
        if body.conversation_id:
            conv = await _own_conversation(conn, user, body.conversation_id)
        else:
            conv = await (
                await conn.execute(
                    "insert into public.conversations (workspace_id, user_id, title)"
                    " values (%s, %s, %s) returning id::text, title, created_at, updated_at",
                    (user.workspace_id, user.user_id, _title(body.content)),
                )
            ).fetchone()
        await conn.execute(
            "insert into public.chat_messages (conversation_id, workspace_id, role, content, via)"
            " values (%s, %s, 'user', %s, %s)",
            (conv["id"], user.workspace_id, body.content, body.via),
        )
        await conn.execute(
            "update public.conversations set updated_at = now() where id = %s", (conv["id"],)
        )

    pool: AsyncConnectionPool = request.app.state.pool
    who = user.email or "the user"
    name = await assistant_name(conn, user)

    async def stream():
        yield _sse({"type": "conversation", "id": conv["id"], "title": conv["title"]})
        text, saved = "", False
        async with pool.connection() as c:
            try:
                system = await engine.system_prompt(
                    c,
                    workspace_id=user.workspace_id,
                    conversation_id=conv["id"],
                    who=who,
                    query=body.content,
                    voice=body.via == "voice",
                    name=name,
                )
                params = {
                    "model": settings.chat_model,
                    "max_tokens": 4000,
                    "system": system,
                    "messages": await engine.history(c, conv["id"]),
                    "tools": engine.TOOLS,
                    "thinking": {"type": "adaptive"},
                    "output_config": {"effort": settings.chat_effort},
                    "cache_control": {"type": "ephemeral"},
                }
                async for event in engine.reply(
                    model,
                    c,
                    _Tools(c, user, conv["id"]),
                    params=params,
                    workspace_id=user.workspace_id,
                ):
                    if event["type"] == "text":
                        text += event["text"]
                    if event["type"] != "end":
                        yield _sse(event)
                        continue
                    msg = await _save_reply(c, conv["id"], user.workspace_id, event, body.via)
                    saved = True
                    yield _sse({"type": "done", "message_id": msg, "text": event["text"]})
            except Exception as exc:  # noqa: BLE001 - tell the app, keep what was said
                if not saved:
                    await _save_reply(
                        c,
                        conv["id"],
                        user.workspace_id,
                        {"text": text.strip() or "(no reply)", "tasks": [], "memories": []},
                        body.via,
                        error=True,
                    )
                    saved = True
                message = (
                    "The assistant is busy right now. Please try again in a moment."
                    if "anthropic" in type(exc).__module__
                    else "Something went wrong while replying. Please try again."
                )
                yield _sse({"type": "error", "message": message})
            finally:
                if not saved and text.strip():  # the app disconnected mid-reply
                    await asyncio.shield(
                        _save_reply(
                            c,
                            conv["id"],
                            user.workspace_id,
                            {"text": text.strip(), "tasks": [], "memories": []},
                            body.via,
                            error=True,
                        )
                    )

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
