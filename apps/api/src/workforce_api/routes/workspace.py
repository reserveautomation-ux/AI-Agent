from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from workforce_core.capabilities import CAPABILITIES
from workforce_core.db import record_audit
from workforce_core.integrations import PROVIDERS
from workforce_core.tools import TOOLS

from ..auth import AdminDep, UserDep
from ..deps import ConnDep
from ..schemas import (
    AssistantIn,
    AuditEventOut,
    KillSwitchRequest,
    MeOut,
    TimezoneRequest,
    WorkspaceOut,
)

router = APIRouter(tags=["workspace"])


async def _workspace(conn, user) -> WorkspaceOut:
    row = await (
        await conn.execute(
            "select id::text, name, kill_switch, timezone from public.workspaces where id = %s",
            (user.workspace_id,),
        )
    ).fetchone()
    return WorkspaceOut(**row, role=user.role)


async def assistant_name(conn, user) -> str:
    row = await (
        await conn.execute(
            "select assistant_name from public.workspace_members"
            " where user_id = %s and workspace_id = %s",
            (user.user_id, user.workspace_id),
        )
    ).fetchone()
    return row["assistant_name"] if row else "AI Assistant"


@router.get("/me", response_model=MeOut)
async def me(user: UserDep, conn: ConnDep) -> MeOut:
    return MeOut(
        user_id=user.user_id,
        email=user.email,
        workspace=await _workspace(conn, user),
        assistant_name=await assistant_name(conn, user),
    )


@router.post("/me/assistant", response_model=MeOut)
async def name_assistant(body: AssistantIn, user: UserDep, conn: ConnDep) -> MeOut:
    """Give your assistant a name; it introduces itself by it from the next message."""
    await conn.execute(
        "update public.workspace_members set assistant_name = %s"
        " where user_id = %s and workspace_id = %s",
        (body.name, user.user_id, user.workspace_id),
    )
    return await me(user, conn)


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


@router.post("/workspace/timezone", response_model=WorkspaceOut)
async def set_timezone(body: TimezoneRequest, user: AdminDep, conn: ConnDep) -> WorkspaceOut:
    """The owner's time zone: used for calendar events and for 'today' in agent prompts."""
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown time zone {body.timezone!r}"
        ) from exc
    await conn.execute(
        "update public.workspaces set timezone = %s where id = %s",
        (body.timezone, user.workspace_id),
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


class CapabilityOut(BaseModel):
    key: str
    area: str
    title: str
    example: str
    handling: str


@router.get("/capabilities", response_model=list[CapabilityOut])
async def list_capabilities(user: UserDep) -> list[CapabilityOut]:
    return [
        CapabilityOut(
            key=c.key, area=c.area, title=c.title, example=c.example, handling=c.handling.value
        )
        for c in CAPABILITIES
    ]


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    platform: Literal["ios", "android", "web"]
    device_name: str | None = Field(default=None, max_length=120)


class DeviceToken(BaseModel):
    token: str = Field(min_length=10, max_length=300)


@router.post("/devices", status_code=204)
async def register_device(body: DeviceIn, user: UserDep, conn: ConnDep) -> None:
    """Register this phone for push notifications (re-registering moves it to you)."""
    await conn.execute(
        """insert into public.push_devices (workspace_id, user_id, token, platform, device_name)
           values (%s, %s, %s, %s, %s)
           on conflict (token) do update set
               workspace_id = excluded.workspace_id, user_id = excluded.user_id,
               platform = excluded.platform, device_name = excluded.device_name,
               last_seen_at = now(), disabled_at = null""",
        (user.workspace_id, user.user_id, body.token, body.platform, body.device_name),
    )


@router.post("/devices/unregister", status_code=204)
async def unregister_device(body: DeviceToken, user: UserDep, conn: ConnDep) -> None:
    await conn.execute(
        "update public.push_devices set disabled_at = now() where token = %s and user_id = %s",
        (body.token, user.user_id),
    )
