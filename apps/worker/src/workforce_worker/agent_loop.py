"""One agent doing one step: a tool-use loop with structured final output."""

import json
from typing import Any

from psycopg import AsyncConnection

from .gateway import AgentInfo, ToolGateway
from .llm import LLM, call, text_of
from .prompts import SPECIALIST

MAX_TURNS = 24

STEP_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-4 sentences: what you did and found"},
        "result": {
            "type": "string",
            "description": "The full step output in Markdown (lists, tables, sources, drafts)",
        },
        "files_saved": {"type": "array", "items": {"type": "string"}},
        "waiting_for_approval": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Actions you prepared that are held for the owner's approval",
        },
        "limitations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything you could not do, and why",
        },
    },
    "required": ["summary", "result", "files_saved", "waiting_for_approval", "limitations"],
    "additionalProperties": False,
}


class AgentError(RuntimeError):
    pass


def _parse_result(resp: Any) -> dict[str, Any]:
    text = text_of(resp)
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "summary" in data:
            return data
    except ValueError:
        pass
    # A fallback model may answer in plain text; keep the work rather than fail.
    return {
        "summary": text[:500],
        "result": text,
        "files_saved": [],
        "waiting_for_approval": [],
        "limitations": [],
    }


async def run_agent(
    llm: LLM,
    conn: AsyncConnection,
    gateway: ToolGateway,
    *,
    instructions: str,
    context: str,
    purpose: str = "step",
) -> dict[str, Any]:
    agent: AgentInfo = gateway.agent
    ctx = gateway.ctx
    system = SPECIALIST.format(name=agent.name, description=agent.description) + agent.lessons
    tools = gateway.tool_definitions()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"{context}\n\n## Your step\n{instructions}"}
    ]

    for _ in range(MAX_TURNS):
        resp = await call(
            llm,
            conn,
            workspace_id=ctx.workspace_id,
            task_id=ctx.task_id,
            agent_id=agent.id,
            purpose=purpose,
            budget_usd=ctx.budget_usd,
            model=agent.model,
            max_tokens=16000,
            system=system,
            tools=tools,
            messages=messages,
            output_config={
                "effort": agent.effort,
                "format": {"type": "json_schema", "schema": STEP_RESULT_SCHEMA},
            },
        )
        # Append the full content (thinking blocks included) unchanged.
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "pause_turn":
            continue  # a server tool (web search) paused; resend to continue
        if resp.stop_reason == "max_tokens":
            raise AgentError("the agent ran out of output space for this step")

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if not tool_uses:
            return _parse_result(resp)

        results = []
        for tu in tool_uses:
            text, is_error = await gateway.execute(tu.id, tu.name, dict(tu.input or {}))
            block: dict[str, Any] = {"type": "tool_result", "tool_use_id": tu.id, "content": text}
            if is_error:
                block["is_error"] = True
            results.append(block)
        # All results for one turn go back in a single message.
        messages.append({"role": "user", "content": results})

    raise AgentError(f"the step did not finish within {MAX_TURNS} turns")
