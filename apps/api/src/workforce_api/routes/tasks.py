from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from psycopg import errors as pg_errors
from workforce_core.db import record_audit, set_actor
from workforce_core.policy import Policy
from workforce_core.task_states import TaskStatus, can_transition, is_terminal

from ..auth import CurrentUser, UserDep
from ..deps import ConnDep
from ..schemas import (
    ApprovalOut,
    ArtifactOut,
    CancelRequest,
    RetryRequest,
    StepOut,
    TaskCreate,
    TaskDetail,
    TaskEventOut,
    TaskOut,
)

router = APIRouter(prefix="/tasks", tags=["tasks"])

TASK_COLUMNS = """
    id::text, title, objective, status, priority, deadline, budget_limit_usd,
    result_summary, created_by::text, created_at, updated_at, completed_at, cost_usd,
    waiting_for_connection
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


class WorkspaceStopped(Exception):
    pass


async def insert_task(
    conn,
    user: CurrentUser,
    body: TaskCreate,
    *,
    conversation_id: str | None = None,
    source: str = "app",
) -> dict:
    """Create a task for the workforce (used by the app and by the chat assistant)."""
    async with conn.transaction():
        ws = await (
            await conn.execute(
                "select kill_switch, status from public.workspaces where id = %s for share",
                (user.workspace_id,),
            )
        ).fetchone()
        if ws["kill_switch"] or ws["status"] != "active":
            raise WorkspaceStopped("workspace is stopped (kill switch on)")

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
                         budget_limit_usd, created_by, conversation_id)
                    values (%s, %s, %s, %s, %s, %s, %s, %s)
                    returning {TASK_COLUMNS}""",
                (
                    user.workspace_id,
                    body.resolved_title(),
                    body.objective,
                    body.priority,
                    body.deadline,
                    body.budget_limit_usd,
                    user.user_id,
                    conversation_id,
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
            event={"title": row["title"], "policy_version": policy.version, "source": source},
        )
    return row


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskOut)
async def create_task(body: TaskCreate, user: UserDep, conn: ConnDep) -> TaskOut:
    try:
        row = await insert_task(conn, user, body)
    except WorkspaceStopped as exc:
        raise HTTPException(status.HTTP_423_LOCKED, str(exc)) from exc
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
    extra = await (
        await conn.execute(
            "select plan, verification, last_error from public.tasks where id = %s", (task_id,)
        )
    ).fetchone()
    events = await (
        await conn.execute(
            "select id, from_status, to_status, actor_type, actor_id, reason, created_at"
            " from public.task_events where task_id = %s and workspace_id = %s order by id",
            (task_id, user.workspace_id),
        )
    ).fetchall()
    steps = await (
        await conn.execute(
            """select s.sequence, s.title, s.status, s.agent_id::text, a.name as agent_name,
                      s.output_json->>'summary' as summary, s.output_json->>'result' as result,
                      coalesce(s.output_json->'limitations', '[]'::jsonb) as limitations,
                      s.error, s.started_at, s.completed_at
               from public.task_steps s left join public.agents a on a.id = s.agent_id
               where s.task_id = %s and s.workspace_id = %s order by s.sequence""",
            (task_id, user.workspace_id),
        )
    ).fetchall()
    artifacts = await (
        await conn.execute(
            "select id::text, name, file_type, size_bytes, preview, created_at"
            " from public.artifacts where task_id = %s and workspace_id = %s order by created_at",
            (task_id, user.workspace_id),
        )
    ).fetchall()
    approvals = await (
        await conn.execute(
            """select id::text, action, action_payload, amount, currency, recipient, risk_tier,
                      status::text, expires_at, created_at
               from public.approval_requests where task_id = %s and workspace_id = %s
               order by created_at""",
            (task_id, user.workspace_id),
        )
    ).fetchall()
    return TaskDetail(
        **row,
        **extra,
        events=[TaskEventOut(**e) for e in events],
        steps=[StepOut(**s) for s in steps],
        artifacts=[ArtifactOut(**a) for a in artifacts],
        approvals=[ApprovalOut(**a) for a in approvals],
    )


@router.post("/{task_id}/retry", response_model=TaskOut)
async def retry_task(
    task_id: str, user: UserDep, conn: ConnDep, body: RetryRequest | None = None
) -> TaskOut:
    """Resume a blocked or failed task, optionally answering the Chief's question
    or raising the budget."""
    body = body or RetryRequest()
    async with conn.transaction():
        row = await _get_task_row(conn, user, task_id, lock=True)
        current = TaskStatus(row["status"])
        if current not in (TaskStatus.BLOCKED, TaskStatus.FAILED):
            raise HTTPException(status.HTTP_409_CONFLICT, f"a {current} task can't be retried")
        if body.budget_limit_usd is not None:
            policy = await _load_policy(conn, user.workspace_id)
            if policy.max_task_budget_usd and body.budget_limit_usd > policy.max_task_budget_usd:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    f"budget exceeds policy maximum of {policy.max_task_budget_usd} USD per task",
                )
        has_steps = (
            await (
                await conn.execute(
                    "select count(*) as n from public.task_steps where task_id = %s", (task_id,)
                )
            ).fetchone()
        )["n"] > 0
        # No plan yet (the Chief asked a question) -> plan again; otherwise resume.
        target = "planned" if current == TaskStatus.BLOCKED and not has_steps else "queued"
        await set_actor(conn, "user", user.user_id, body.answer or "retry")
        await conn.execute(
            """update public.tasks set
                   objective = case when %(answer)s::text is null then objective
                                    else objective || E'\n\nOwner''s answer: ' || %(answer)s end,
                   budget_limit_usd = coalesce(%(budget)s, budget_limit_usd),
                   attempts = 0, rework_count = 0, run_after = now(), last_error = null,
                   lease_owner = null, lease_expires_at = null
               where id = %(id)s""",
            {"answer": body.answer, "budget": body.budget_limit_usd, "id": task_id},
        )
        await conn.execute(
            "update public.task_steps set status = 'pending', error = null"
            " where task_id = %s and status in ('failed', 'running')",
            (task_id,),
        )
        await conn.execute("update public.tasks set status = %s where id = %s", (target, task_id))
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="task.retried",
            target_type="task",
            target_id=task_id,
            event={"from_status": current.value, "answered": body.answer is not None},
        )
        row = await _get_task_row(conn, user, task_id)
    return TaskOut(**row)


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


artifacts_router = APIRouter(prefix="/artifacts", tags=["tasks"])


@artifacts_router.get("/{artifact_id}")
async def download_artifact(artifact_id: str, user: UserDep, conn: ConnDep) -> Response:
    try:
        row = await (
            await conn.execute(
                "select name, file_type, content from public.artifacts"
                " where id = %s and workspace_id = %s",
                (artifact_id, user.workspace_id),
            )
        ).fetchone()
    except pg_errors.InvalidTextRepresentation:
        row = None
    if row is None or row["content"] is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return Response(
        content=bytes(row["content"]),
        media_type=row["file_type"],
        headers={"Content-Disposition": f'attachment; filename="{row["name"]}"'},
    )
