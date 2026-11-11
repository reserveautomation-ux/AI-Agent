"""Tool gateway: the only way an agent touches the world.

For every tool call it checks the agent's allowlist, the kill switch and the
workspace policy (in plain code), records the invocation with an idempotency
key, and then either runs the tool, holds it for the owner's approval with an
exact-action binding, or refuses it. Agents never see credentials.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from workforce_core.approvals import binding_for, canonical_json
from workforce_core.db import record_audit
from workforce_core.memory import MemoryRejected, format_for_prompt, recall, remember
from workforce_core.policy import ActionContext, Decision, Policy, decide
from workforce_core.tools import TOOLS_BY_NAME

from .artifacts import csv_stats, save_artifact
from .browser import BlockedURL, BrowserError, BrowserService
from .prompts import untrusted

# Tools executed by Anthropic's servers (declared, not run by us).
SERVER_TOOLS = {"web_search", "web_fetch", "run_code"}
MAX_RESULT_CHARS = 15_000

BOOKING_SITES = {
    "uber": "https://m.uber.com/",
    "ola": "https://book.olacabs.com/",
    "rapido": "https://www.rapido.bike/",
    "swiggy": "https://www.swiggy.com/search?query={q}",
    "zomato": "https://www.zomato.com/",
    "bookmyshow": "https://in.bookmyshow.com/explore/home",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "irctc": "https://www.irctc.co.in/",
}


@dataclass
class AgentInfo:
    id: str
    name: str
    template_key: str | None
    role: str
    description: str
    allowed_tools: list[str]
    model: str = "claude-opus-5-5"
    effort: str = "medium"


@dataclass
class StepContext:
    workspace_id: str
    task_id: str
    step_id: str | None
    policy: Policy
    budget_usd: float
    artifacts: list[dict] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)


class ToolGateway:
    def __init__(
        self,
        conn: AsyncConnection,
        ctx: StepContext,
        agent: AgentInfo,
        browser: BrowserService | None = None,
    ):
        self.conn = conn
        self.ctx = ctx
        self.agent = agent
        self.browser = browser

    # --- what the model sees ------------------------------------------------------

    def tool_definitions(self) -> list[dict[str, Any]]:
        names = set(self.agent.allowed_tools)
        defs: list[dict[str, Any]] = []
        if "web_search" in names:
            defs.append({"type": "web_search_20260209", "name": "web_search", "max_uses": 10})
        if "web_fetch" in names:
            defs.append({"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 10})
        # The web tools already run code for filtering; declaring a second code
        # environment alongside them confuses the model, so only add it alone.
        if "run_code" in names and not names & {"web_search", "web_fetch"}:
            defs.append({"type": "code_execution_20260521", "name": "code_execution"})
        for name in sorted(names - SERVER_TOOLS):
            if name == "browse_page" and self.browser is None:
                continue
            spec = TOOLS_BY_NAME[name]
            defs.append(
                {"name": name, "description": spec.description, "input_schema": spec.input_schema}
            )
        return defs

    # --- execution ------------------------------------------------------------------

    async def execute(self, tool_use_id: str, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Run one tool call. Returns (result text, is_error)."""
        spec = TOOLS_BY_NAME.get(name)
        if spec is None or name not in self.agent.allowed_tools:
            await self._audit("policy.violation.tool_not_allowed", {"tool": name})
            return f"Tool {name!r} is not available to you.", True

        ks = await (
            await self.conn.execute(
                "select kill_switch from public.workspaces where id = %s", (self.ctx.workspace_id,)
            )
        ).fetchone()
        decision = decide(
            self.ctx.policy,
            ActionContext(
                name,
                spec.risk_tier,
                kill_switch=ks["kill_switch"],
                agent_allowed_tools=frozenset(self.agent.allowed_tools),
            ),
        )
        idem = f"{self.ctx.task_id}:{self.ctx.step_id}:{tool_use_id}"
        args_hash = hashlib.sha256(canonical_json(args).encode()).hexdigest()

        existing = await (
            await self.conn.execute(
                "select status, result_json from public.tool_invocations"
                " where workspace_id = %s and idempotency_key = %s",
                (self.ctx.workspace_id, idem),
            )
        ).fetchone()
        if existing and existing["status"] == "succeeded":
            return existing["result_json"]["text"], False  # replay after a crash

        inv_id = await self._record(name, spec.risk_tier, idem, args_hash, args, decision)

        if decision == Decision.DENY:
            reason = "the emergency stop is on" if ks["kill_switch"] else "policy forbids it"
            await self._audit("policy.denied", {"tool": name, "reason": reason})
            return f"Not allowed: {reason}. Explain this to the owner instead.", True

        if decision in (Decision.REQUIRE_APPROVAL, Decision.REQUIRE_OWNER_APPROVAL):
            approval_id = await self._request_approval(inv_id, name, spec.risk_tier, args)
            return (
                f"Held for the owner's approval (request {approval_id}). It will run only after "
                "the owner approves this exact action. Do not retry it; continue with the rest of "
                "the step and mention what is waiting for approval in your result.",
                False,
            )

        try:
            text = await self._run(name, args)
            is_error = False
        except (BlockedURL, BrowserError, MemoryRejected, ValueError) as exc:
            text, is_error = f"Error: {exc}", True
        except NotImplementedError as exc:
            text, is_error = str(exc), True
        text = text[:MAX_RESULT_CHARS]
        await self.conn.execute(
            "update public.tool_invocations set status = %s, result_json = %s,"
            " error = %s, completed_at = now() where id = %s",
            (
                "failed" if is_error else "succeeded",
                Jsonb({"text": text}),
                text if is_error else None,
                inv_id,
            ),
        )
        return text, is_error

    async def _record(self, name, tier, idem, args_hash, args, decision) -> str:
        status = {
            Decision.DENY: "denied",
            Decision.ALLOW: "running",
        }.get(decision, "awaiting_approval")
        row = await (
            await self.conn.execute(
                """insert into public.tool_invocations
                       (workspace_id, task_id, step_id, agent_id, tool_name, risk_tier,
                        idempotency_key, arguments_hash, arguments_json, status)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   on conflict (workspace_id, idempotency_key) do update
                       set status = excluded.status, started_at = now()
                   returning id::text""",
                (
                    self.ctx.workspace_id,
                    self.ctx.task_id,
                    self.ctx.step_id,
                    self.agent.id,
                    name,
                    int(tier),
                    idem,
                    args_hash,
                    Jsonb(args),
                    status,
                ),
            )
        ).fetchone()
        return row["id"]

    async def _request_approval(self, inv_id: str, name: str, tier, args: dict) -> str:
        expires = datetime.now(UTC) + timedelta(seconds=self.ctx.policy.approval_ttl_seconds)
        binding = binding_for(
            task_id=self.ctx.task_id,
            action=name,
            args=args,
            expires_at=expires,
            policy_version=self.ctx.policy.version,
        )
        amount, recipient, item = binding.amount, binding.recipient, binding.item
        row = await (
            await self.conn.execute(
                """insert into public.approval_requests
                       (workspace_id, task_id, tool_invocation_id, action, action_payload,
                        action_hash, amount, currency, recipient, item, policy_id,
                        policy_version, risk_tier, expires_at)
                   values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   returning id::text""",
                (
                    self.ctx.workspace_id,
                    self.ctx.task_id,
                    inv_id,
                    name,
                    Jsonb(args),
                    binding.action_hash(),
                    amount,
                    binding.currency,
                    recipient,
                    item,
                    self.ctx.policy.id,
                    self.ctx.policy.version,
                    int(tier),
                    expires,
                ),
            )
        ).fetchone()
        self.ctx.approvals.append(row["id"])
        await self._audit("approval.requested", {"tool": name, "approval_id": row["id"]})
        return row["id"]

    async def _audit(self, action: str, event: dict) -> None:
        await record_audit(
            self.conn,
            workspace_id=self.ctx.workspace_id,
            actor_type="agent",
            actor_id=self.agent.id,
            action=action,
            target_type="task",
            target_id=self.ctx.task_id,
            event=event,
        )

    # --- tool implementations -------------------------------------------------------

    async def _run(self, name: str, args: dict[str, Any]) -> str:
        if name == "browse_page":
            if self.browser is None:
                raise NotImplementedError("The browser is not available on this worker.")
            page = await self.browser.read_page(
                args["url"], follow_links=args.get("follow_links") or []
            )
            links = "\n".join(f"- {t}: {h}" for t, h in page.links[:25])
            body = f"Title: {page.title}\n\n{page.text}\n\nLinks:\n{links}"
            if page.truncated:
                body += "\n\n[page text truncated]"
            return untrusted(page.final_url, body)

        if name == "recall":
            found = await recall(
                self.conn,
                workspace_id=self.ctx.workspace_id,
                query=args.get("query", ""),
                agent_id=self.agent.id,
            )
            return format_for_prompt(found)

        if name == "remember":
            own = args.get("about") == "my_work"
            memory_type = "learning" if own else args.get("memory_type", "fact")
            if memory_type == "learning" and not own:
                memory_type = "fact"
            _, created = await remember(
                self.conn,
                workspace_id=self.ctx.workspace_id,
                content=args["content"],
                memory_type=memory_type,
                source_type="agent",
                agent_id=self.agent.id,
                agent_scope=own,
                source_ref=self.ctx.task_id,
            )
            return "Saved to memory." if created else "Already known; memory updated."

        if name in ("create_report", "create_document"):
            fmt = args.get("format", "markdown")
            content = args.get("content", "")
            extra = ""
            if fmt == "csv":
                rows, header = csv_stats(content)
                extra = f" ({rows} rows; columns: {', '.join(header)})"
            elif fmt == "json":
                json.loads(content)  # raises ValueError if invalid
            art = await save_artifact(
                self.conn,
                workspace_id=self.ctx.workspace_id,
                task_id=self.ctx.task_id,
                step_id=self.ctx.step_id,
                name=args.get("name", "report"),
                fmt=fmt,
                content=content,
            )
            self.ctx.artifacts.append(art)
            return f"Saved file {art['name']}{extra}."

        if name == "draft_email":
            # A draft is just text for the owner to see; sending is a separate,
            # approval-gated action (send_email), so no mail account is needed here.
            to, subject = str(args.get("to", "")), str(args.get("subject", ""))
            body = str(args.get("body", ""))
            art = await save_artifact(
                self.conn,
                workspace_id=self.ctx.workspace_id,
                task_id=self.ctx.task_id,
                step_id=self.ctx.step_id,
                name=f"email draft {subject or to}"[:60],
                fmt="markdown",
                content=f"**To:** {to}\n\n**Subject:** {subject}\n\n{body}\n",
            )
            self.ctx.artifacts.append(art)
            return f"Saved the draft as {art['name']}. To send it, use send_email (needs approval)."

        if name == "prepare_booking_link":
            provider = str(args.get("provider", "")).lower().strip()
            details = str(args.get("details", ""))
            template = next((u for k, u in BOOKING_SITES.items() if k in provider), None)
            link = template.format(q=quote_plus(details[:80])) if template else None
            card = (
                f"# Ready to book: {args.get('provider')}\n\n{details}\n\n"
                + (f"Open: {link}\n\n" if link else "")
                + "Confirm and pay in the provider's app or website. "
                "Nothing has been booked or paid yet."
            )
            art = await save_artifact(
                self.conn,
                workspace_id=self.ctx.workspace_id,
                task_id=self.ctx.task_id,
                step_id=self.ctx.step_id,
                name=f"booking {provider or 'details'}",
                fmt="markdown",
                content=card,
            )
            self.ctx.artifacts.append(art)
            return f"Prepared booking card {art['name']}" + (f" with link {link}" if link else "")

        provider = TOOLS_BY_NAME[name].provider
        raise NotImplementedError(
            f"The {name} tool isn't connected yet ({provider} integration is planned). "
            "Do the closest useful thing instead, e.g. prepare a draft in your result."
        )
