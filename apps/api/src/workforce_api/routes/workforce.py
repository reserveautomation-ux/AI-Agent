"""Workforce: org chart, hiring the initial team, cloning, promotion, retirement."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from psycopg import errors as pg_errors
from psycopg.types.json import Jsonb
from pydantic import BaseModel
from workforce_core.db import record_audit, set_actor
from workforce_core.lifecycle import (
    DEFAULT_THRESHOLDS,
    Evaluation,
    LifecycleAction,
    promotion_allowed,
    recommend,
)
from workforce_core.workforce import AGENTS, DEPARTMENTS, MODEL_PROFILES

from ..auth import AdminDep, CurrentUser, UserDep
from ..deps import ConnDep

router = APIRouter(tags=["workforce"])

AGENT_COLUMNS = """
    a.id::text, a.name, a.role, a.status, a.version, a.template_key, a.model_profile,
    a.department_id::text, a.parent_agent_id::text, a.lineage_id::text,
    a.cloned_from::text, a.allowed_tools, a.config_json, a.created_at, a.retired_at
"""


class AgentOut(BaseModel):
    id: str
    name: str
    role: str
    status: str
    version: int
    template_key: str | None
    model_profile: str
    department_id: str | None
    parent_agent_id: str | None
    lineage_id: str | None
    cloned_from: str | None
    allowed_tools: list[str]
    description: str | None = None
    latest_evaluation: dict[str, Any] | None = None
    lessons: list[str] = []  # working rules learned from the checker's feedback
    generation: int = 1  # 1 = original, 2 = first clone, ...


class DepartmentOut(BaseModel):
    id: str
    key: str | None
    name: str
    manager_agent_id: str | None


class WorkforceOut(BaseModel):
    departments: list[DepartmentOut]
    agents: list[AgentOut]
    auto_improve: bool = True  # nightly clone / trial / retire
    last_improved_at: datetime | None = None


class AutoImproveIn(BaseModel):
    enabled: bool


class LifecycleDecision(BaseModel):
    agent_id: str
    agent_name: str
    action: LifecycleAction
    reason: str
    applied: bool
    new_agent_id: str | None = None


def _agent_out(row: dict, evaluation: dict | None = None) -> AgentOut:
    return AgentOut(
        **{k: row[k] for k in AgentOut.model_fields if k in row},
        description=(row.get("config_json") or {}).get("description"),
        latest_evaluation=evaluation,
        lessons=list((row.get("config_json") or {}).get("lessons") or []),
        generation=int((row.get("config_json") or {}).get("generation") or 1),
    )


async def _latest_evaluations(conn, workspace_id: str) -> dict[str, dict]:
    rows = await (
        await conn.execute(
            """select distinct on (agent_id) agent_id::text, agent_version, sample_size,
                      success_rate::float, quality_score::float, cost_usd::float,
                      p50_latency_ms, created_at
               from public.agent_evaluations where workspace_id = %s
               order by agent_id, created_at desc""",
            (workspace_id,),
        )
    ).fetchall()
    return {r["agent_id"]: r for r in rows}


async def _safety_violations(conn, workspace_id: str, agent_id: str) -> int:
    row = await (
        await conn.execute(
            """select count(*) as n from public.audit_events
               where workspace_id = %s and actor_type = 'agent' and actor_id = %s
                 and action like 'policy.violation%%'""",
            (workspace_id, agent_id),
        )
    ).fetchone()
    return row["n"]


def _to_evaluation(ev: dict | None, violations: int) -> Evaluation | None:
    if ev is None:
        return Evaluation(0, 0.0, 0.0, violations) if violations else None
    successes = (ev["success_rate"] or 0) * ev["sample_size"]
    return Evaluation(
        sample_size=ev["sample_size"],
        success_rate=ev["success_rate"] or 0.0,
        quality_score=ev["quality_score"] or 0.0,
        safety_violations=violations,
        cost_per_success_usd=(ev["cost_usd"] / successes) if ev["cost_usd"] and successes else None,
    )


@router.get("/workforce", response_model=WorkforceOut)
async def get_workforce(user: UserDep, conn: ConnDep) -> WorkforceOut:
    depts = await (
        await conn.execute(
            "select id::text, key, name, manager_agent_id::text from public.departments"
            " where workspace_id = %s order by created_at",
            (user.workspace_id,),
        )
    ).fetchall()
    agents = await (
        await conn.execute(
            f"select {AGENT_COLUMNS} from public.agents a where a.workspace_id = %s"
            " order by a.created_at",
            (user.workspace_id,),
        )
    ).fetchall()
    evals = await _latest_evaluations(conn, user.workspace_id)
    ws = await (
        await conn.execute(
            "select auto_workforce, evolved_at from public.workspaces where id = %s",
            (user.workspace_id,),
        )
    ).fetchone()
    return WorkforceOut(
        departments=[DepartmentOut(**d) for d in depts],
        agents=[_agent_out(a, evals.get(a["id"])) for a in agents],
        auto_improve=ws["auto_workforce"],
        last_improved_at=ws["evolved_at"],
    )


@router.post("/workforce/auto-improve", response_model=WorkforceOut)
async def set_auto_improve(body: AutoImproveIn, user: AdminDep, conn: ConnDep) -> WorkforceOut:
    """Let the workforce clone strong agents and retire weak ones every night (or not)."""
    await conn.execute(
        "update public.workspaces set auto_workforce = %s where id = %s",
        (body.enabled, user.workspace_id),
    )
    await record_audit(
        conn,
        workspace_id=user.workspace_id,
        actor_type="user",
        actor_id=user.user_id,
        action="workforce.auto_improve_on" if body.enabled else "workforce.auto_improve_off",
        target_type="workspace",
        target_id=user.workspace_id,
        event={},
    )
    return await get_workforce(user, conn)


@router.post("/workforce/bootstrap", response_model=WorkforceOut)
async def bootstrap_workforce(user: AdminDep, conn: ConnDep) -> WorkforceOut:
    """Hire any departments and agents from the templates that this workspace lacks.

    Idempotent: safe to run again after new agent types are added. Agents that
    were retired stay retired (they count as already hired).
    """
    async with conn.transaction():
        # Serialise concurrent bootstraps for this workspace.
        await conn.execute(
            "select id from public.workspaces where id = %s for update", (user.workspace_id,)
        )
        dept_rows = await (
            await conn.execute(
                "select key, id::text from public.departments"
                " where workspace_id = %s and key is not null",
                (user.workspace_id,),
            )
        ).fetchall()
        dept_ids: dict[str, str] = {r["key"]: r["id"] for r in dept_rows}
        agent_rows = await (
            await conn.execute(
                "select template_key, id::text from public.agents"
                " where workspace_id = %s and cloned_from is null and template_key is not null",
                (user.workspace_id,),
            )
        ).fetchall()
        agent_ids: dict[str, str] = {r["template_key"]: r["id"] for r in agent_rows}

        await set_actor(conn, "user", user.user_id, "hire workforce")
        new_depts = 0
        for d in DEPARTMENTS:
            if d.key in dept_ids:
                continue
            row = await (
                await conn.execute(
                    "insert into public.departments (workspace_id, key, name)"
                    " values (%s, %s, %s) returning id::text",
                    (user.workspace_id, d.key, d.name),
                )
            ).fetchone()
            dept_ids[d.key] = row["id"]
            new_depts += 1

        heads = {t.department: t.key for t in AGENTS if t.role == "department_head"}
        hired: list[str] = []
        # Chief first, then heads, then specialists, so parents exist.
        order = {"chief": 0, "verifier": 1, "department_head": 2, "specialist": 3}
        for t in sorted(AGENTS, key=lambda a: order[a.role]):
            if t.key in agent_ids:
                continue
            if t.role == "chief":
                parent = None
            elif t.role == "specialist" and t.department:
                parent = agent_ids[heads[t.department]]
            else:  # verifier, department heads, department-less specialists
                parent = agent_ids["chief"]
            config = {"description": t.description, **MODEL_PROFILES[t.model_profile]}
            row = await (
                await conn.execute(
                    """insert into public.agents
                           (workspace_id, department_id, parent_agent_id, name, role,
                            status, template_key, model_profile, allowed_tools, config_json)
                       values (%s, %s, %s, %s, %s, 'active', %s, %s, %s, %s)
                       returning id::text""",
                    (
                        user.workspace_id,
                        dept_ids[t.department] if t.department else None,
                        parent,
                        t.name,
                        t.role,
                        t.key,
                        t.model_profile,
                        list(t.tools),
                        Jsonb(config),
                    ),
                )
            ).fetchone()
            agent_ids[t.key] = row["id"]
            hired.append(t.key)
            await conn.execute(
                "insert into public.agent_versions (agent_id, version, config_snapshot)"
                " values (%s, 1, %s)",
                (row["id"], Jsonb({**config, "tools": list(t.tools)})),
            )
            if t.role == "department_head":
                await conn.execute(
                    "update public.departments set manager_agent_id = %s"
                    " where id = %s and manager_agent_id is null",
                    (row["id"], dept_ids[t.department]),
                )
        if hired or new_depts:
            await record_audit(
                conn,
                workspace_id=user.workspace_id,
                actor_type="user",
                actor_id=user.user_id,
                action="workforce.hired",
                event={"agents": hired, "departments_added": new_depts},
            )
    return await get_workforce(user, conn)


async def _load_agent(conn, user: CurrentUser, agent_id: str, *, lock: bool = False) -> dict:
    try:
        row = await (
            await conn.execute(
                f"select {AGENT_COLUMNS}, a.department_id as dept_uuid,"
                " a.parent_agent_id as parent_uuid"
                " from public.agents a where a.id = %s and a.workspace_id = %s"
                + (" for update" if lock else ""),
                (agent_id, user.workspace_id),
            )
        ).fetchone()
    except pg_errors.InvalidTextRepresentation:
        row = None
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "agent not found")
    return row


async def _replica_count(conn, workspace_id: str, lineage_id: str) -> int:
    row = await (
        await conn.execute(
            "select count(*) as n from public.agents where workspace_id = %s"
            " and lineage_id = %s and status in ('active', 'sandbox')",
            (workspace_id, lineage_id),
        )
    ).fetchone()
    return row["n"]


async def _clone(conn, user: CurrentUser, src: dict, reason: str) -> str:
    replicas = await _replica_count(conn, user.workspace_id, src["lineage_id"])
    if replicas >= DEFAULT_THRESHOLDS.max_replicas:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"replica cap reached ({DEFAULT_THRESHOLDS.max_replicas} per agent family)",
        )
    config = {**(src["config_json"] or {}), "cloned_from_version": src["version"]}
    row = await (
        await conn.execute(
            """insert into public.agents
                   (workspace_id, department_id, parent_agent_id, name, role, status,
                    template_key, model_profile, allowed_tools, config_json,
                    lineage_id, cloned_from)
               values (%s, %s, %s, %s, %s, 'sandbox', %s, %s, %s, %s, %s, %s)
               returning id::text""",
            (
                user.workspace_id,
                src["dept_uuid"],
                src["parent_uuid"],
                f"{src['name']} #{replicas + 1}",
                src["role"],
                src["template_key"],
                src["model_profile"],
                src["allowed_tools"],
                Jsonb(config),
                src["lineage_id"],
                src["id"],
            ),
        )
    ).fetchone()
    await conn.execute(
        "insert into public.agent_versions (agent_id, version, config_snapshot) values (%s, 1, %s)",
        (row["id"], Jsonb({**config, "tools": src["allowed_tools"]})),
    )
    await record_audit(
        conn,
        workspace_id=user.workspace_id,
        actor_type="user",
        actor_id=user.user_id,
        action="agent.cloned",
        target_type="agent",
        target_id=row["id"],
        event={"source_agent_id": src["id"], "reason": reason},
    )
    return row["id"]


async def _set_status(conn, user: CurrentUser, agent: dict, new_status: str, reason: str) -> None:
    if agent["role"] == "chief" and new_status in ("suspended", "retired"):
        raise HTTPException(status.HTTP_409_CONFLICT, "the Chief AI Executive cannot be removed")
    if agent["status"] == "retired":
        raise HTTPException(status.HTTP_409_CONFLICT, "agent is already retired")
    await conn.execute(
        "update public.agents set status = %s where id = %s", (new_status, agent["id"])
    )
    await record_audit(
        conn,
        workspace_id=user.workspace_id,
        actor_type="user",
        actor_id=user.user_id,
        action=f"agent.{new_status}",
        target_type="agent",
        target_id=agent["id"],
        event={"from_status": agent["status"], "reason": reason},
    )


@router.post("/agents/{agent_id}/clone", response_model=AgentOut, status_code=201)
async def clone_agent(agent_id: str, user: AdminDep, conn: ConnDep) -> AgentOut:
    async with conn.transaction():
        src = await _load_agent(conn, user, agent_id, lock=True)
        if src["status"] != "active":
            raise HTTPException(status.HTTP_409_CONFLICT, "only active agents can be cloned")
        if src["role"] == "chief":
            raise HTTPException(status.HTTP_409_CONFLICT, "there is exactly one Chief AI Executive")
        new_id = await _clone(conn, user, src, "manual clone")
        return _agent_out(await _load_agent(conn, user, new_id))


@router.post("/agents/{agent_id}/promote", response_model=AgentOut)
async def promote_agent(agent_id: str, user: AdminDep, conn: ConnDep) -> AgentOut:
    """Move a sandbox agent (e.g. a clone) into active service if its evaluation passes."""
    async with conn.transaction():
        agent = await _load_agent(conn, user, agent_id, lock=True)
        if agent["status"] != "sandbox":
            raise HTTPException(status.HTTP_409_CONFLICT, "only sandbox agents can be promoted")
        evals = await _latest_evaluations(conn, user.workspace_id)
        violations = await _safety_violations(conn, user.workspace_id, agent_id)
        ok, why = promotion_allowed(_to_evaluation(evals.get(agent_id), violations))
        if not ok:
            raise HTTPException(status.HTTP_409_CONFLICT, f"promotion blocked: {why}")
        await _set_status(conn, user, agent, "active", why)
        return _agent_out(await _load_agent(conn, user, agent_id), evals.get(agent_id))


@router.post("/agents/{agent_id}/suspend", response_model=AgentOut)
async def suspend_agent(agent_id: str, user: AdminDep, conn: ConnDep) -> AgentOut:
    async with conn.transaction():
        agent = await _load_agent(conn, user, agent_id, lock=True)
        await _set_status(conn, user, agent, "suspended", "manual suspension")
        return _agent_out(await _load_agent(conn, user, agent_id))


@router.post("/agents/{agent_id}/retire", response_model=AgentOut)
async def retire_agent(agent_id: str, user: AdminDep, conn: ConnDep) -> AgentOut:
    """'Delete' an agent: it stops receiving work; its history is kept."""
    async with conn.transaction():
        agent = await _load_agent(conn, user, agent_id, lock=True)
        await _set_status(conn, user, agent, "retired", "manual retirement")
        return _agent_out(await _load_agent(conn, user, agent_id))


@router.post("/workforce/lifecycle-review", response_model=list[LifecycleDecision])
async def lifecycle_review(
    user: AdminDep, conn: ConnDep, apply: bool = False
) -> list[LifecycleDecision]:
    """Evaluate every agent; with ``apply=true`` clone strong ones and suspend/retire weak ones."""
    decisions: list[LifecycleDecision] = []
    async with conn.transaction():
        await set_actor(conn, "user", user.user_id, "lifecycle review")
        agents = await (
            await conn.execute(
                f"select {AGENT_COLUMNS}, a.department_id as dept_uuid,"
                " a.parent_agent_id as parent_uuid from public.agents a"
                " where a.workspace_id = %s and a.status in ('active', 'suspended')"
                " order by a.created_at for update",
                (user.workspace_id,),
            )
        ).fetchall()
        evals = await _latest_evaluations(conn, user.workspace_id)
        for agent in agents:
            violations = await _safety_violations(conn, user.workspace_id, agent["id"])
            replicas = await _replica_count(conn, user.workspace_id, agent["lineage_id"])
            action, reason = recommend(
                agent["status"], _to_evaluation(evals.get(agent["id"]), violations), replicas
            )
            if agent["role"] == "chief" and action in (
                LifecycleAction.SUSPEND,
                LifecycleAction.RETIRE,
                LifecycleAction.CLONE,
            ):
                reason = f"{reason} (chief is never auto-removed or cloned; review manually)"
                action = LifecycleAction.KEEP
            decision = LifecycleDecision(
                agent_id=agent["id"],
                agent_name=agent["name"],
                action=action,
                reason=reason,
                applied=False,
            )
            if apply:
                if action == LifecycleAction.CLONE:
                    decision.new_agent_id = await _clone(conn, user, agent, reason)
                    decision.applied = True
                elif action in (LifecycleAction.SUSPEND, LifecycleAction.RETIRE):
                    new_status = "suspended" if action == LifecycleAction.SUSPEND else "retired"
                    await _set_status(conn, user, agent, new_status, reason)
                    decision.applied = True
            decisions.append(decision)
    return decisions
