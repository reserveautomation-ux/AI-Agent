from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel
from workforce_core.db import record_audit
from workforce_core.integrations import PROVIDERS
from workforce_core.tools import TOOLS

from ..auth import AdminDep, UserDep
from ..deps import ConnDep
from ..schemas import AuditEventOut, KillSwitchRequest, MeOut, WorkspaceOut

router = APIRouter(tags=["workspace"])


async def _workspace(conn, user) -> WorkspaceOut:
    row = await (
        await conn.execute(
            "select id::text, name, kill_switch from public.workspaces where id = %s",
            (user.workspace_id,),
        )
    ).fetchone()
    return WorkspaceOut(**row, role=user.role)


@router.get("/me", response_model=MeOut)
async def me(user: UserDep, conn: ConnDep) -> MeOut:
    return MeOut(user_id=user.user_id, email=user.email, workspace=await _workspace(conn, user))


@router.post("/workspace/kill-switch", response_model=WorkspaceOut)
async def set_kill_switch(body: KillSwitchRequest, user: AdminDep, conn: ConnDep) -> WorkspaceOut:
    """Emergency stop: blocks new tasks and (from week 2) halts all agent tool calls."""
    async with conn.transaction():
        await conn.execute(
            "update public.workspaces set kill_switch = %s where id = %s",
            (body.enabled, user.workspace_id),
        )
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="workspace.kill_switch_on" if body.enabled else "workspace.kill_switch_off",
            target_type="workspace",
            target_id=user.workspace_id,
            event={"reason": body.reason},
        )
    return await _workspace(conn, user)


@router.get("/audit", response_model=list[AuditEventOut])
async def list_audit(
    user: AdminDep, conn: ConnDep, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[AuditEventOut]:
    rows = await (
        await conn.execute(
            "select id, actor_type, actor_id, action, target_type, target_id, event_json,"
            " created_at from public.audit_events where workspace_id = %s"
            " order by id desc limit %s",
            (user.workspace_id, limit),
        )
    ).fetchall()
    return [AuditEventOut(**r) for r in rows]


class IntegrationOut(BaseModel):
    key: str
    name: str
    category: str
    access: str
    notes: str
    tools: list[str]


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(user: UserDep) -> list[IntegrationOut]:
    return [
        IntegrationOut(
            key=p.key,
            name=p.name,
            category=p.category,
            access=p.access.value,
            notes=p.notes,
            tools=[t.name for t in TOOLS if t.provider == p.key],
        )
        for p in PROVIDERS
    ]
