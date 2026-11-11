"""Approval centre: the owner approves, edits-and-approves, or rejects prepared actions.

An approval covers exactly what the owner saw: the client sends back the hash
it displayed, and the server refuses if the stored action changed since (or if
the stored row no longer matches its own hash). Money and other high-impact
actions (risk tier 3) can only be approved by the workspace owner.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field
from workforce_core.approvals import ApprovalError, apply_edits, binding_for, binding_from_row
from workforce_core.db import record_audit, set_actor

from ..auth import CurrentUser, UserDep
from ..deps import ConnDep

router = APIRouter(prefix="/approvals", tags=["approvals"])

APPROVAL_SELECT = """
    select a.id::text, a.task_id::text, t.title as task_title, a.action, a.action_payload,
           a.action_hash, a.amount, a.currency, a.recipient, a.item, a.account_ref,
           a.policy_version, a.risk_tier, a.status::text as status, a.expires_at,
           a.created_at, a.decided_at, i.status as execution_status,
           coalesce(i.error, i.result_json->>'text') as execution_result
    from public.approval_requests a
    join public.tasks t on t.id = a.task_id
    left join public.tool_invocations i on i.id = a.tool_invocation_id
"""


class ApprovalItem(BaseModel):
    id: str
    task_id: str
    task_title: str
    action: str
    action_payload: dict[str, Any]
    action_hash: str
    amount: Decimal | None
    currency: str | None
    recipient: str | None
    item: str | None
    risk_tier: int
    status: str
    expires_at: datetime
    created_at: datetime
    decided_at: datetime | None
    execution_status: str | None
    execution_result: str | None
    owner_only: bool


class ApproveRequest(BaseModel):
    action_hash: str = Field(min_length=64, max_length=64)
    changes: dict[str, str] | None = None


class RejectRequest(BaseModel):
    action_hash: str = Field(min_length=64, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


def _item(row: dict) -> ApprovalItem:
    fields = {k: row[k] for k in ApprovalItem.model_fields if k in row}
    return ApprovalItem(**fields, owner_only=row["risk_tier"] >= 3)


@router.get("", response_model=list[ApprovalItem])
async def list_approvals(
    user: UserDep,
    conn: ConnDep,
    state: Literal["pending", "decided"] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ApprovalItem]:
    await conn.execute("select public.expire_approvals()")
    where = "a.status = 'pending'" if state == "pending" else "a.status <> 'pending'"
    order = "a.expires_at" if state == "pending" else "coalesce(a.decided_at, a.created_at) desc"
    rows = await (
        await conn.execute(
            f"{APPROVAL_SELECT} where a.workspace_id = %s and {where} order by {order} limit %s",
            (user.workspace_id, limit),
        )
    ).fetchall()
    return [_item(r) for r in rows]


async def _load_for_decision(conn, user: CurrentUser, approval_id: str, shown_hash: str) -> dict:
    try:
        row = await (
            await conn.execute(
                f"{APPROVAL_SELECT} where a.id = %s and a.workspace_id = %s for update of a",
                (approval_id, user.workspace_id),
            )
        ).fetchone()
    except pg_errors.InvalidTextRepresentation:
        row = None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "approval not found")
    if row["status"] != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, f"this was already {row['status']}")
    if row["expires_at"] <= datetime.now(UTC):
        raise HTTPException(status.HTTP_409_CONFLICT, "this approval has expired")
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner or an admin can decide")
    if row["risk_tier"] >= 3 and user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner can approve this")
    # Integrity: the stored action must still match its own hash...
    if binding_from_row(row).action_hash() != row["action_hash"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "this action failed an integrity check")
    # ...and must be exactly what the owner was shown.
    if shown_hash != row["action_hash"]:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this action changed since you opened it; please review again"
        )
    return row


async def _event(conn, user: CurrentUser, row: dict, decision: str, reason: str | None) -> None:
    await conn.execute(
        "insert into public.approval_events (workspace_id, approval_id, actor_user_id, decision,"
        " reason) values (%s, %s, %s, %s, %s)",
        (user.workspace_id, row["id"], user.user_id, decision, reason),
    )


async def _resume_task_if_done(conn, user: CurrentUser, task_id: str) -> None:
    pending = await (
        await conn.execute(
            "select count(*) as n from public.approval_requests"
            " where task_id = %s and status = 'pending'",
            (task_id,),
        )
    ).fetchone()
    if pending["n"] == 0:
        await set_actor(conn, "user", user.user_id, "all approvals decided")
        await conn.execute(
            "update public.tasks set status = 'running', run_after = now(),"
            " lease_owner = null, lease_expires_at = null"
            " where id = %s and status = 'waiting_for_approval'",
            (task_id,),
        )


async def _reload(conn, user: CurrentUser, approval_id: str) -> ApprovalItem:
    row = await (
        await conn.execute(
            f"{APPROVAL_SELECT} where a.id = %s and a.workspace_id = %s",
            (approval_id, user.workspace_id),
        )
    ).fetchone()
    return _item(row)


@router.post("/{approval_id}/approve", response_model=ApprovalItem)
async def approve(
    approval_id: str, body: ApproveRequest, user: UserDep, conn: ConnDep
) -> ApprovalItem:
    async with conn.transaction():
        row = await _load_for_decision(conn, user, approval_id, body.action_hash)
        approved_hash = row["action_hash"]

        if body.changes:
            try:
                payload = apply_edits(row["action_payload"], body.changes)
            except ApprovalError as exc:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
            binding = binding_for(
                task_id=row["task_id"],
                action=row["action"],
                args=payload,
                expires_at=row["expires_at"],
                policy_version=row["policy_version"],
                account_ref=row["account_ref"],
            )
            approved_hash = binding.action_hash()
            await conn.execute(
                """update public.approval_requests
                   set action_payload = %s, action_hash = %s, amount = %s, currency = %s,
                       recipient = %s, item = %s
                   where id = %s""",
                (
                    Jsonb(payload),
                    approved_hash,
                    binding.amount,
                    binding.currency,
                    binding.recipient,
                    binding.item,
                    approval_id,
                ),
            )
            await conn.execute(
                """update public.tool_invocations set arguments_json = %s, arguments_hash = %s
                   where id = (select tool_invocation_id from public.approval_requests
                               where id = %s)""",
                (Jsonb(payload), approved_hash, approval_id),
            )
            await _event(conn, user, row, "edited", ", ".join(sorted(body.changes)))

        await conn.execute(
            "update public.approval_requests set status = 'approved', decided_at = now()"
            " where id = %s",
            (approval_id,),
        )
        await _event(conn, user, row, "approved", None)
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="approval.approved",
            target_type="approval",
            target_id=approval_id,
            event={
                "action": row["action"],
                "action_hash": approved_hash,
                "edited": bool(body.changes),
                "task_id": row["task_id"],
            },
        )
        await _resume_task_if_done(conn, user, row["task_id"])
    return await _reload(conn, user, approval_id)


@router.post("/{approval_id}/reject", response_model=ApprovalItem)
async def reject(
    approval_id: str, body: RejectRequest, user: UserDep, conn: ConnDep
) -> ApprovalItem:
    async with conn.transaction():
        row = await _load_for_decision(conn, user, approval_id, body.action_hash)
        reason = body.reason or "declined by owner"
        await conn.execute(
            "update public.approval_requests set status = 'rejected', decided_at = now()"
            " where id = %s",
            (approval_id,),
        )
        await conn.execute(
            """update public.tool_invocations set status = 'denied', error = %s,
                   completed_at = now()
               where id = (select tool_invocation_id from public.approval_requests
                           where id = %s)""",
            (f"Declined by the owner: {reason}", approval_id),
        )
        await _event(conn, user, row, "rejected", reason)
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="approval.rejected",
            target_type="approval",
            target_id=approval_id,
            event={"action": row["action"], "reason": reason, "task_id": row["task_id"]},
        )
        await _resume_task_if_done(conn, user, row["task_id"])
    return await _reload(conn, user, approval_id)
