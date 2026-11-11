"""Task pipeline: plan -> run steps -> verify -> complete (or wait for approval).

Each stage reads its state from the database and checkpoints back to it, so a
task can be resumed by any worker at any point after a crash or restart.
"""

import contextlib
import json
from dataclasses import dataclass
from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from workforce_core.db import record_audit, set_actor
from workforce_core.memory import format_for_prompt, recall, remember
from workforce_core.policy import Policy

from .agent_loop import AgentError, run_agent
from .artifacts import csv_stats
from .browser import BrowserService
from .evaluations import refresh_evaluations
from .gateway import AgentInfo, StepContext, ToolGateway
from .llm import LLM, call, json_of
from .prompts import CHIEF_PLANNER, VERIFIER

MAX_STEPS = 6
MAX_REWORK = 1
DEFAULT_BUDGET_USD = 5.0


class TaskStopped(Exception):
    """The task was cancelled or the workspace was stopped while we worked."""


@dataclass
class Task:
    id: str
    workspace_id: str
    title: str
    objective: str
    status: str
    budget_limit_usd: float | None
    plan: dict | None
    reply_language: str | None
    rework_count: int
    created_by: str


# --- helpers ----------------------------------------------------------------------


async def load_task(conn: AsyncConnection, task_id: str) -> Task:
    row = await (
        await conn.execute(
            """select id::text, workspace_id::text, title, objective, status::text,
                      budget_limit_usd::float, plan, reply_language, rework_count,
                      created_by::text
               from public.tasks where id = %s""",
            (task_id,),
        )
    ).fetchone()
    return Task(**row)


async def transition(
    conn: AsyncConnection, task: Task, *targets: str, reason: str | None = None, **fields: Any
) -> None:
    """Move the task through one or more statuses, recording why (worker actor)."""
    async with conn.transaction():
        current = await (
            await conn.execute(
                "select t.status::text, w.kill_switch from public.tasks t"
                " join public.workspaces w on w.id = t.workspace_id"
                " where t.id = %s for update of t",
                (task.id,),
            )
        ).fetchone()
        if current["status"] in ("cancelled", "expired"):
            raise TaskStopped(f"task is {current['status']}")
        await set_actor(conn, "worker", None, reason)
        if fields:
            cols = ", ".join(f"{k} = %s" for k in fields)
            vals = [Jsonb(v) if isinstance(v, dict | list) else v for v in fields.values()]
            await conn.execute(f"update public.tasks set {cols} where id = %s", (*vals, task.id))
        for target in targets:
            await conn.execute(
                "update public.tasks set status = %s where id = %s", (target, task.id)
            )
            task.status = target


async def ensure_running(conn: AsyncConnection, task: Task) -> None:
    row = await (
        await conn.execute(
            "select t.status::text, w.kill_switch from public.tasks t"
            " join public.workspaces w on w.id = t.workspace_id where t.id = %s",
            (task.id,),
        )
    ).fetchone()
    if row["kill_switch"]:
        raise TaskStopped("emergency stop is on")
    if row["status"] in ("cancelled", "expired"):
        raise TaskStopped(f"task is {row['status']}")


async def load_policy(conn: AsyncConnection, workspace_id: str) -> Policy:
    row = await (
        await conn.execute(
            "select id::text, version, rules from public.policies where workspace_id = %s"
            " and name = 'default' order by version desc limit 1",
            (workspace_id,),
        )
    ).fetchone()
    return Policy.from_row(row["id"], row["version"], row["rules"])


def budget_for(task: Task, policy: Policy) -> float:
    if task.budget_limit_usd is not None:
        return task.budget_limit_usd
    return policy.max_task_budget_usd or DEFAULT_BUDGET_USD


def _agent_from_row(r: dict) -> AgentInfo:
    cfg = r["config_json"] or {}
    return AgentInfo(
        id=r["id"],
        name=r["name"],
        template_key=r["template_key"],
        role=r["role"],
        description=cfg.get("description", ""),
        allowed_tools=list(r["allowed_tools"] or []),
        model=cfg.get("model", "claude-opus-5-5"),
        effort=cfg.get("effort", "medium"),
    )


async def active_agents(conn: AsyncConnection, workspace_id: str) -> list[AgentInfo]:
    rows = await (
        await conn.execute(
            """select id::text, name, template_key, role, allowed_tools, config_json
               from public.agents where workspace_id = %s and status = 'active'
               order by created_at""",
            (workspace_id,),
        )
    ).fetchall()
    return [_agent_from_row(r) for r in rows]


def _first(agents: list[AgentInfo], **match: str) -> AgentInfo | None:
    return next((a for a in agents if all(getattr(a, k) == v for k, v in match.items())), None)


# --- stage 1: plan ----------------------------------------------------------------


def plan_schema(agent_keys: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "understanding": {"type": "string"},
            "reply_language": {"type": "string", "description": "e.g. English, Hindi"},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "clarification_needed": {
                "type": "string",
                "description": "One question for the owner, or empty string if none",
            },
            "success_criteria": {"type": "array", "items": {"type": "string"}},
            "deliverable": {
                "type": "string",
                "enum": ["answer", "file", "prepared_action", "file_and_prepared_action"],
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "agent": {"type": "string", "enum": agent_keys},
                        "instructions": {"type": "string"},
                        "expected_output": {"type": "string"},
                    },
                    "required": ["title", "agent", "instructions", "expected_output"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "understanding",
            "reply_language",
            "assumptions",
            "clarification_needed",
            "success_criteria",
            "deliverable",
            "steps",
        ],
        "additionalProperties": False,
    }


async def plan_task(conn: AsyncConnection, llm: LLM, task: Task, policy: Policy) -> None:
    agents = await active_agents(conn, task.workspace_id)
    chief = _first(agents, role="chief")
    if chief is None:
        raise AgentError("no active Chief AI Executive; hire the workforce first")
    workers = [a for a in agents if a.role == "specialist" and a.template_key]
    # One entry per template (clones share it); the runtime picks the instance.
    roster: dict[str, AgentInfo] = {}
    for a in workers:
        roster.setdefault(a.template_key, a)
    if not roster:
        raise AgentError("no active specialist agents")

    memories = await recall(
        conn, workspace_id=task.workspace_id, query=task.objective, agent_id=chief.id, limit=12
    )
    roster_text = "\n".join(
        f"- {k}: {a.name}. {a.description} Tools: {', '.join(a.allowed_tools) or 'none'}"
        for k, a in roster.items()
    )
    prompt = (
        f"## Owner's instruction\n{task.objective}\n\n"
        f"## Agent roster\n{roster_text}\n\n"
        f"## What you remember about the owner\n{format_for_prompt(memories)}"
    )
    resp = await call(
        llm,
        conn,
        workspace_id=task.workspace_id,
        task_id=task.id,
        agent_id=chief.id,
        purpose="plan",
        budget_usd=budget_for(task, policy),
        model=chief.model,
        max_tokens=16000,
        system=CHIEF_PLANNER,
        messages=[{"role": "user", "content": prompt}],
        output_config={
            "effort": chief.effort,
            "format": {"type": "json_schema", "schema": plan_schema(sorted(roster))},
        },
    )
    plan = json_of(resp)
    steps = plan["steps"][:MAX_STEPS]
    question = plan["clarification_needed"].strip()

    async with conn.transaction():
        await conn.execute(
            "update public.tasks set assigned_agent_id = %s where id = %s", (chief.id, task.id)
        )
        for i, s in enumerate(steps, start=1):
            agent = (
                roster.get(s["agent"]) or roster.get("generalist") or next(iter(roster.values()))
            )
            await conn.execute(
                """insert into public.task_steps
                       (workspace_id, task_id, sequence, step_type, title, description,
                        agent_id, input_json)
                   values (%s, %s, %s, 'agent', %s, %s, %s, %s)""",
                (task.workspace_id, task.id, i, s["title"], s["instructions"], agent.id, Jsonb(s)),
            )

    fields = {
        "plan": plan,
        "success_criteria": plan["success_criteria"],
        "reply_language": plan["reply_language"],
    }
    if question and not steps:
        await transition(
            conn,
            task,
            "planned",
            "blocked",
            reason=f"question for owner: {question}",
            result_summary=question,
            **fields,
        )
        return
    await transition(conn, task, "planned", "queued", reason=f"{len(steps)} step plan", **fields)


# --- stage 2: run steps -----------------------------------------------------------


async def run_steps(
    conn: AsyncConnection, llm: LLM, task: Task, policy: Policy, browser: BrowserService | None
) -> None:
    agents = {a.id: a for a in await active_agents(conn, task.workspace_id)}
    steps = await (
        await conn.execute(
            """select id::text, sequence, title, description, agent_id::text, input_json,
                      output_json, status, retry_count
               from public.task_steps where task_id = %s order by sequence""",
            (task.id,),
        )
    ).fetchall()
    plan = task.plan or {}

    for step in steps:
        if step["status"] in ("succeeded", "skipped"):
            continue
        await ensure_running(conn, task)
        agent = agents.get(step["agent_id"]) or _replacement(agents, step)
        if agent is None:
            raise AgentError(f"no active agent available for step {step['sequence']}")

        await conn.execute(
            "update public.task_steps set status = 'running', agent_id = %s,"
            " started_at = coalesce(started_at, now()) where id = %s",
            (agent.id, step["id"]),
        )
        previous = "\n\n".join(
            f"### Step {s['sequence']}: {s['title']}\n{(s['output_json'] or {}).get('result', '')}"
            for s in steps
            if s["sequence"] < step["sequence"] and s["status"] == "succeeded"
        )[:30_000]
        memories = await recall(
            conn,
            workspace_id=task.workspace_id,
            query=f"{task.objective} {step['title']}",
            agent_id=agent.id,
            limit=8,
        )
        rework = (step["input_json"] or {}).get("rework_feedback")
        context = (
            f"## Owner's instruction\n{task.objective}\n\n"
            f"## Plan understanding\n{plan.get('understanding', '')}\n"
            f"Assumptions: {'; '.join(plan.get('assumptions', [])) or 'none'}\n"
            f"Success criteria: {'; '.join(plan.get('success_criteria', []))}\n"
            f"Reply language for owner-facing text: {task.reply_language or 'English'}\n\n"
            f"## Memories\n{format_for_prompt(memories)}\n\n"
            + (f"## Earlier steps\n{previous}\n\n" if previous else "")
            + (f"## The QA Verifier rejected the last attempt\n{rework}\n\n" if rework else "")
        )
        instructions = (
            f"{step['description']}\n\nExpected output: "
            f"{(step['input_json'] or {}).get('expected_output', '')}"
        )
        ctx = StepContext(
            workspace_id=task.workspace_id,
            task_id=task.id,
            step_id=step["id"],
            policy=policy,
            budget_usd=budget_for(task, policy),
        )
        gateway = ToolGateway(conn, ctx, agent, browser)
        result = await run_agent(llm, conn, gateway, instructions=instructions, context=context)
        result["artifacts"] = ctx.artifacts
        result["approvals"] = ctx.approvals
        await conn.execute(
            "update public.task_steps set status = 'succeeded', output_json = %s,"
            " completed_at = now(), error = null where id = %s",
            (Jsonb(result), step["id"]),
        )
        step["status"], step["output_json"] = "succeeded", result

    await transition(conn, task, "verifying", reason="all steps finished")


def _replacement(agents: dict[str, AgentInfo], step: dict) -> AgentInfo | None:
    """If the planned agent was suspended/retired meanwhile, use an active sibling."""
    key = (step["input_json"] or {}).get("agent")
    return next((a for a in agents.values() if a.template_key == key), None) or next(
        (a for a in agents.values() if a.template_key == "generalist"), None
    )


# --- stage 3: verify --------------------------------------------------------------

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "score": {"type": "number"},
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string"},
                    "met": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["criterion", "met", "note"],
                "additionalProperties": False,
            },
        },
        "issues": {"type": "array", "items": {"type": "string"}},
        "summary_for_owner": {"type": "string"},
    },
    "required": ["passed", "score", "criteria", "issues", "summary_for_owner"],
    "additionalProperties": False,
}


async def automated_checks(conn: AsyncConnection, task: Task) -> tuple[list[str], list[dict]]:
    """Deterministic checks that don't depend on any model's opinion."""
    problems: list[str] = []
    arts = await (
        await conn.execute(
            "select id::text, name, file_type, size_bytes, convert_from(content, 'UTF8') as text"
            " from public.artifacts where task_id = %s order by created_at",
            (task.id,),
        )
    ).fetchall()
    summaries = []
    for a in arts:
        info = {"name": a["name"], "type": a["file_type"], "bytes": a["size_bytes"]}
        if a["file_type"] == "text/csv" and a["text"]:
            rows, header = csv_stats(a["text"])
            lines = [ln for ln in a["text"].splitlines()[1:] if ln.strip()]
            dupes = len(lines) - len(set(lines))
            info.update(rows=rows, columns=header, duplicate_rows=dupes)
            if rows == 0:
                problems.append(f"{a['name']} has no data rows")
            if dupes:
                problems.append(f"{a['name']} has {dupes} duplicate rows")
        info["preview"] = (a["text"] or "")[:1500]
        summaries.append(info)
    deliverable = (task.plan or {}).get("deliverable", "answer")
    if deliverable in ("file", "file_and_prepared_action") and not arts:
        problems.append("the plan promised a file but none was saved")
    return problems, summaries


async def verify_task(conn: AsyncConnection, llm: LLM, task: Task, policy: Policy) -> None:
    agents = await active_agents(conn, task.workspace_id)
    verifier = _first(agents, role="verifier") or _first(agents, role="chief")
    steps = await (
        await conn.execute(
            "select sequence, title, agent_id::text, output_json from public.task_steps"
            " where task_id = %s order by sequence",
            (task.id,),
        )
    ).fetchall()
    approvals = await (
        await conn.execute(
            "select id::text, action, action_payload from public.approval_requests"
            " where task_id = %s and status = 'pending'",
            (task.id,),
        )
    ).fetchall()
    problems, artifacts = await automated_checks(conn, task)

    evidence = {
        "instruction": task.objective,
        "success_criteria": (task.plan or {}).get("success_criteria", []),
        "steps": [
            {"step": s["sequence"], "title": s["title"], "output": s["output_json"]} for s in steps
        ],
        "files": artifacts,
        "automated_check_problems": problems,
        "waiting_for_owner_approval": [
            {"action": a["action"], "details": a["action_payload"]} for a in approvals
        ],
        "reply_language": task.reply_language or "English",
    }
    resp = await call(
        llm,
        conn,
        workspace_id=task.workspace_id,
        task_id=task.id,
        agent_id=verifier.id if verifier else None,
        purpose="verify",
        budget_usd=budget_for(task, policy),
        model=verifier.model if verifier else "claude-opus-5-5",
        max_tokens=16000,
        system=VERIFIER,
        messages=[
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, default=str)}
        ],
        output_config={
            "effort": verifier.effort if verifier else "high",
            "format": {"type": "json_schema", "schema": VERDICT_SCHEMA},
        },
    )
    verdict = json_of(resp)
    verdict["automated_check_problems"] = problems
    passed = bool(verdict["passed"]) and not problems
    verdict["passed"] = passed
    summary = verdict["summary_for_owner"]
    step_agents = [s["agent_id"] for s in steps if s["agent_id"]]

    if passed:
        if approvals:
            await transition(
                conn,
                task,
                "waiting_for_approval",
                reason=f"verified; {len(approvals)} action(s) need approval",
                verification=verdict,
                result_summary=summary,
            )
        else:
            await transition(
                conn,
                task,
                "completed",
                reason="verified",
                verification=verdict,
                result_summary=summary,
            )
        await _remember_episode(conn, task, summary)
    elif task.rework_count < MAX_REWORK and steps:
        feedback = "\n".join(f"- {i}" for i in [*problems, *verdict["issues"]]) or "- see criteria"
        last = steps[-1]["sequence"]
        await conn.execute(
            """update public.task_steps
               set status = 'pending', input_json = input_json || %s, retry_count = retry_count + 1
               where task_id = %s and sequence = %s""",
            (Jsonb({"rework_feedback": feedback}), task.id, last),
        )
        await transition(
            conn,
            task,
            "running",
            reason="verifier requested rework",
            verification=verdict,
            rework_count=task.rework_count + 1,
        )
    else:
        await transition(
            conn,
            task,
            "failed",
            reason="did not pass verification",
            verification=verdict,
            result_summary=summary,
        )
    await refresh_evaluations(conn, task.workspace_id, step_agents)
    await record_audit(
        conn,
        workspace_id=task.workspace_id,
        actor_type="worker",
        actor_id=None,
        action="task.verified" if passed else "task.verification_failed",
        target_type="task",
        target_id=task.id,
        event={"score": verdict.get("score"), "issues": verdict.get("issues", [])[:10]},
    )


async def _remember_episode(conn: AsyncConnection, task: Task, summary: str) -> None:
    # Memory is best-effort; never fail a verified task over it.
    with contextlib.suppress(Exception):
        await remember(
            conn,
            workspace_id=task.workspace_id,
            content=f"Did: {task.title}. {summary}"[:1500],
            memory_type="episode",
            source_type="system",
            source_ref=task.id,
            importance=2,
        )


# --- driver -----------------------------------------------------------------------


async def advance(
    conn: AsyncConnection, llm: LLM, task_id: str, browser: BrowserService | None = None
) -> str:
    """Advance a task as far as it can go now. Returns the resulting status."""
    task = await load_task(conn, task_id)
    policy = await load_policy(conn, task.workspace_id)

    needs_plan = task.status == "draft" or (
        task.status == "planned"  # e.g. the owner answered the Chief's question
        and (
            await (
                await conn.execute(
                    "select count(*) as n from public.task_steps where task_id = %s", (task_id,)
                )
            ).fetchone()
        )["n"]
        == 0
    )
    if needs_plan:
        await ensure_running(conn, task)
        await plan_task(conn, llm, task, policy)
        task = await load_task(conn, task_id)
    if task.status in ("planned", "queued"):
        targets = ("queued", "running") if task.status == "planned" else ("running",)
        await transition(conn, task, *targets, reason="worker started")
    if task.status == "running":
        await run_steps(conn, llm, task, policy, browser)
    if task.status == "verifying":
        task = await load_task(conn, task_id)
        await verify_task(conn, llm, task, policy)
        task = await load_task(conn, task_id)
        if task.status == "running":  # rework round
            return await advance(conn, llm, task_id, browser)
    return task.status
