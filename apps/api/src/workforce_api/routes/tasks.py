from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from psycopg import errors as pg_errors
from workforce_core.db import record_audit, set_actor
from workforce_core.policy import Policy
from workforce_core.task_states import TaskStatus, can_transition, is_terminal

from ..auth import UserDep
from ..deps import ConnDep
from ..schemas import CancelRequest, TaskCreate, TaskDetail, TaskEventOut, TaskOut

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_COLUMNS = """
    id::text, title, objective, status, priority, deadline, budget_limit_usd,
    result_summary, created_by::text, created_at, updated_at, completed_at
"""


async def _load_policy(conn, workspace_id: str) -> Policy:
    row = await (
        await conn.execute(
            "select id::text, version, rules from public.policies"
            " where workspace_id = %s and name = 'default'"
            " order by version desc limit 1",
            (workspace_id,),
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "workspace has no default policy")
    return Policy.from_row(row["id"], row["version"], row["rules"])


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskOut)
async def create_task(body: TaskCreate, user: UserDep, conn: ConnDep) -> TaskOut:
    async with conn.transaction():
        ws = await (
            await conn.execute(
                "select kill_switch, status from public.workspaces where id = %s for share",
                (user.workspace_id,),
            )
        ).fetchone()
        if ws["kill_switch"] or ws["status"] != "active":
            raise HTTPException(status.HTTP_423_LOCKED, "workspace is stopped (kill switch on)")

        policy = await _load_policy(conn, user.workspace_id)
        if (
            body.budget_limit_usd is not None
            and policy.max_task_budget_usd is not None
            and body.budget_limit_usd > policy.max_task_budget_usd
        ):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"budget exceeds policy maximum of {policy.max_task_budget_usd} USD per task",
            )

        await set_actor(conn, "user", user.user_id, "task submitted")
        row = await (
            await conn.execute(
                f"""insert into public.tasks
                        (workspace_id, title, objective, priority, deadline,
                         budget_limit_usd, created_by)
                    values (%s, %s, %s, %s, %s, %s, %s)
                    returning {TASK_COLUMNS}""",
                (
                    user.workspace_id,
                    body.resolved_title(),
                    body.objective,
                    body.priority,
                    body.deadline,
                    body.budget_limit_usd,
                    user.user_id,
                ),
            )
        ).fetchone()
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="task.created",
            target_type="task",
            target_id=row["id"],
            event={"title": row["title"], "policy_version": policy.version},
        )
    # Week 2: start the durable TaskWorkflow here (after commit) and move the
    # task draft -> planned -> queued as the planner runs.
    return TaskOut(**row)


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    user: UserDep,
    conn: ConnDep,
    status_filter: Annotated[TaskStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[TaskOut]:
    query = f"select {TASK_COLUMNS} from public.tasks where workspace_id = %s"
    params: list = [user.workspace_id]
    if status_filter is not None:
        query += " and status = %s"
        params.append(status_filter.value)
    query += " order by created_at desc limit %s"
    params.append(limit)
    rows = await (await conn.execute(query, params)).fetchall()
    return [TaskOut(**r) for r in rows]


async def _get_task_row(conn, user, task_id: str, *, lock: bool = False) -> dict:
    try:
        row = await (
            await conn.execute(
                f"select {TASK_COLUMNS} from public.tasks where id = %s and workspace_id = %s"
                + (" for update" if lock else ""),
                (task_id, user.workspace_id),
            )
        ).fetchone()
    except pg_errors.InvalidTextRepresentation:
        row = None  # malformed UUID
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return row


@router.get("/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str, user: UserDep, conn: ConnDep) -> TaskDetail:
    row = await _get_task_row(conn, user, task_id)
    events = await (
        await conn.execute(
            "select id, from_status, to_status, actor_type, actor_id, reason, created_at"
            " from public.task_events where task_id = %s and workspace_id = %s order by id",
            (task_id, user.workspace_id),
        )
    ).fetchall()
    return TaskDetail(**row, events=[TaskEventOut(**e) for e in events])


@router.post("/{task_id}/cancel", response_model=TaskOut)
async def cancel_task(
    task_id: str, user: UserDep, conn: ConnDep, body: CancelRequest | None = None
) -> TaskOut:
    reason = (body.reason if body else None) or "cancelled by user"
    async with conn.transaction():
        row = await _get_task_row(conn, user, task_id, lock=True)
        current = TaskStatus(row["status"])
        if is_terminal(current) or not can_transition(current, TaskStatus.CANCELLED):
            raise HTTPException(status.HTTP_409_CONFLICT, f"cannot cancel a {current} task")

        await set_actor(conn, "user", user.user_id, reason)
        row = await (
            await conn.execute(
                f"update public.tasks set status = 'cancelled' where id = %s"
                f" returning {TASK_COLUMNS}",
                (task_id,),
            )
        ).fetchone()
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="task.cancelled",
            target_type="task",
            target_id=task_id,
            event={"from_status": current.value, "reason": reason},
        )
    # Week 2: also signal the running workflow to stop.
    return TaskOut(**row)
