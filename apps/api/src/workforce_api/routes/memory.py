"""Memory: see, search, add, pin and forget what the workforce remembers."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import errors as pg_errors
from pydantic import BaseModel, Field
from workforce_core.db import record_audit
from workforce_core.memory import MemoryError, recall, remember

from ..auth import UserDep
from ..deps import ConnDep

router = APIRouter(prefix="/memories", tags=["memory"])

MEMORY_COLUMNS = """
    m.id::text, m.owner_scope, m.agent_id::text, a.name as agent_name, m.memory_type,
    m.content, m.trusted, m.importance, m.pinned, m.source_type, m.source_ref,
    m.use_count, m.last_used_at, m.created_at
"""


class MemoryOut(BaseModel):
    id: str
    owner_scope: str
    agent_id: str | None
    agent_name: str | None
    memory_type: str
    content: str
    trusted: bool
    importance: int
    pinned: bool
    source_type: str
    source_ref: str | None
    use_count: int
    last_used_at: datetime | None
    created_at: datetime


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    memory_type: Literal["preference", "fact", "contact", "instruction"] = "fact"
    importance: int = Field(default=3, ge=1, le=5)
    pinned: bool = False


class PinRequest(BaseModel):
    pinned: bool


async def _get(conn, user, memory_id: str) -> MemoryOut:
    try:
        row = await (
            await conn.execute(
                f"select {MEMORY_COLUMNS} from public.memories m"
                " left join public.agents a on a.id = m.agent_id"
                " where m.id = %s and m.workspace_id = %s",
                (memory_id, user.workspace_id),
            )
        ).fetchone()
    except pg_errors.InvalidTextRepresentation:
        row = None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "memory not found")
    return MemoryOut(**row)


@router.get("", response_model=list[MemoryOut])
async def list_memories(
    user: UserDep,
    conn: ConnDep,
    q: str | None = None,
    scope: Literal["all", "workspace", "agent"] = "all",
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[MemoryOut]:
    if q and q.strip():
        found = await recall(
            conn,
            workspace_id=user.workspace_id,
            query=q,
            limit=50,
            touch=False,
            include_pinned=False,
        )
        ids = [m.id for m in found]
        if not ids:
            return []
        rows = await (
            await conn.execute(
                f"select {MEMORY_COLUMNS} from public.memories m"
                " left join public.agents a on a.id = m.agent_id"
                " where m.id = any(%s::uuid[])",
                (ids,),
            )
        ).fetchall()
        order = {i: n for n, i in enumerate(ids)}
        return sorted((MemoryOut(**r) for r in rows), key=lambda m: order[m.id])

    query = (
        f"select {MEMORY_COLUMNS} from public.memories m"
        " left join public.agents a on a.id = m.agent_id where m.workspace_id = %s"
        " and (m.expires_at is null or m.expires_at > now())"
    )
    params: list = [user.workspace_id]
    if scope != "all":
        query += " and m.owner_scope = %s"
        params.append(scope)
    query += " order by m.pinned desc, m.updated_at desc limit %s"
    params.append(limit)
    rows = await (await conn.execute(query, params)).fetchall()
    return [MemoryOut(**r) for r in rows]


@router.post("", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(body: MemoryCreate, user: UserDep, conn: ConnDep) -> MemoryOut:
    async with conn.transaction():
        try:
            memory_id, created = await remember(
                conn,
                workspace_id=user.workspace_id,
                content=body.content,
                memory_type=body.memory_type,
                source_type="user",
                importance=body.importance,
                pinned=body.pinned,
            )
        except MemoryError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="memory.created" if created else "memory.merged",
            target_type="memory",
            target_id=memory_id,
            event={"memory_type": body.memory_type},
        )
    return await _get(conn, user, memory_id)


@router.post("/{memory_id}/pin", response_model=MemoryOut)
async def pin_memory(memory_id: str, body: PinRequest, user: UserDep, conn: ConnDep) -> MemoryOut:
    await _get(conn, user, memory_id)
    await conn.execute(
        "update public.memories set pinned = %s where id = %s and workspace_id = %s",
        (body.pinned, memory_id, user.workspace_id),
    )
    return await _get(conn, user, memory_id)


@router.post("/{memory_id}/confirm", response_model=MemoryOut)
async def confirm_memory(memory_id: str, user: UserDep, conn: ConnDep) -> MemoryOut:
    """Mark something an agent noted as verified by you."""
    mem = await _get(conn, user, memory_id)
    async with conn.transaction():
        # Re-attribute to the owner so it may be trusted (agent rows can't be).
        await conn.execute(
            "update public.memories set source_type = 'user', trusted = true"
            " where id = %s and workspace_id = %s",
            (memory_id, user.workspace_id),
        )
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="memory.confirmed",
            target_type="memory",
            target_id=memory_id,
            event={"previous_source": mem.source_type},
        )
    return await _get(conn, user, memory_id)


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def forget_memory(memory_id: str, user: UserDep, conn: ConnDep) -> None:
    await _get(conn, user, memory_id)
    async with conn.transaction():
        await conn.execute(
            "delete from public.memories where id = %s and workspace_id = %s",
            (memory_id, user.workspace_id),
        )
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="memory.forgotten",
            target_type="memory",
            target_id=memory_id,
        )
