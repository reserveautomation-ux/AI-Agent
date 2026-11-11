"""Claude API access for agents, with cost tracking.

Every call goes through :class:`LLM` so tests can substitute a scripted fake
and so each call is recorded in ``llm_calls`` (model, tokens, cost) and added
to the task's running cost, which is checked against the task budget.

Server-side refusal fallbacks are enabled: if Claude's safety classifiers
decline a request, the API re-runs it on Anthropic's recommended fallback
model inside the same call instead of failing the task.
"""

import json
import time
from decimal import Decimal
from typing import Any, Protocol

import anthropic
from psycopg import AsyncConnection
from workforce_core.llm_cost import (  # noqa: F401  (re-exported for tests)
    FALLBACK_BETA,
    PRICES,
    WEB_SEARCH_USD,
    CallRecord,
)
from workforce_core.llm_cost import usage_of as _usage


class LLM(Protocol):
    async def create(self, **params: Any) -> Any: ...


class AnthropicLLM:
    """Async Claude client using the beta endpoint for server-side fallbacks."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None):
        self.client = client or anthropic.AsyncAnthropic(max_retries=4, timeout=600)

    async def create(self, **params: Any) -> Any:
        return await self.client.beta.messages.create(
            betas=[FALLBACK_BETA], fallbacks="default", **params
        )


class BudgetExceeded(RuntimeError):
    pass


class Refused(RuntimeError):
    pass


async def call(
    llm: LLM,
    conn: AsyncConnection,
    *,
    workspace_id: str,
    task_id: str,
    agent_id: str | None,
    purpose: str,
    budget_usd: float,
    **params: Any,
) -> Any:
    """Make one model call, record its cost, and enforce the task budget."""
    spent = await (
        await conn.execute("select cost_usd from public.tasks where id = %s", (task_id,))
    ).fetchone()
    if float(spent["cost_usd"]) >= budget_usd:
        raise BudgetExceeded(f"task budget of ${budget_usd:.2f} reached")

    params.setdefault("cache_control", {"type": "ephemeral"})
    started = time.monotonic()
    resp = await llm.create(**params)
    rec = _usage(resp)
    rec.latency_ms = int((time.monotonic() - started) * 1000)

    await conn.execute(
        """insert into public.llm_calls
               (workspace_id, task_id, agent_id, model, purpose, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens, cost_usd, latency_ms, stop_reason)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            workspace_id,
            task_id,
            agent_id,
            rec.model or params.get("model", ""),
            purpose,
            rec.input_tokens,
            rec.output_tokens,
            rec.cache_read_tokens,
            rec.cache_write_tokens,
            Decimal(str(round(rec.cost_usd, 6))),
            rec.latency_ms,
            rec.stop_reason,
        ),
    )
    await conn.execute(
        "update public.tasks set cost_usd = cost_usd + %s where id = %s",
        (Decimal(str(round(rec.cost_usd, 6))), task_id),
    )
    if rec.stop_reason == "refusal":
        details = getattr(resp, "stop_details", None)
        raise Refused(getattr(details, "explanation", None) or "the model declined this request")
    return resp


def text_of(resp: Any) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


def json_of(resp: Any) -> dict:
    """Parse a structured-output response (output_config.format guarantees JSON text)."""
    return json.loads(text_of(resp))
