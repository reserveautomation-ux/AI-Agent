"""Deterministic policy engine.

The model may *propose* actions; it never decides whether an action is allowed.
Every tool call passes through :func:`decide` in plain code, so a prompt
injection can at most produce a proposal that gets denied or held for approval.
"""

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any


class RiskTier(IntEnum):
    READ = 0  # search, compare, read permitted records
    INTERNAL_WRITE = 1  # drafts, internal task updates, reports
    EXTERNAL_COMMITMENT = 2  # send email, publish, reserve
    FINANCIAL = 3  # pay, transfer, purchase, trade, subscribe, cancel critical service
    DESTRUCTIVE = 4  # credentials, access grants, production deletes, payout changes


class Decision(StrEnum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    REQUIRE_OWNER_APPROVAL = "require_owner_approval"
    DENY = "deny"


# Stricter decisions sort later; used so a policy file can never loosen a hard floor.
_STRICTNESS = [
    Decision.ALLOW,
    Decision.REQUIRE_APPROVAL,
    Decision.REQUIRE_OWNER_APPROVAL,
    Decision.DENY,
]

# Floors that no workspace policy can relax.
HARD_FLOOR: dict[RiskTier, Decision] = {
    RiskTier.FINANCIAL: Decision.REQUIRE_OWNER_APPROVAL,
    RiskTier.DESTRUCTIVE: Decision.DENY,
}

DEFAULT_TIER_RULES: dict[RiskTier, Decision] = {
    RiskTier.READ: Decision.ALLOW,
    RiskTier.INTERNAL_WRITE: Decision.ALLOW,
    RiskTier.EXTERNAL_COMMITMENT: Decision.REQUIRE_APPROVAL,
    RiskTier.FINANCIAL: Decision.REQUIRE_OWNER_APPROVAL,
    RiskTier.DESTRUCTIVE: Decision.DENY,
}


def _stricter(a: Decision, b: Decision) -> Decision:
    return a if _STRICTNESS.index(a) >= _STRICTNESS.index(b) else b


@dataclass(frozen=True)
class Policy:
    """A parsed, versioned workspace policy (row in ``public.policies``)."""

    id: str
    version: int
    tier_rules: dict[RiskTier, Decision] = field(default_factory=lambda: dict(DEFAULT_TIER_RULES))
    approval_ttl_seconds: int = 86400
    max_task_budget_usd: float | None = None

    @classmethod
    def from_row(cls, policy_id: str, version: int, rules: dict[str, Any]) -> "Policy":
        tier_rules = dict(DEFAULT_TIER_RULES)
        for tier_key, decision in (rules.get("tiers") or {}).items():
            tier_rules[RiskTier(int(tier_key))] = Decision(decision)
        return cls(
            id=policy_id,
            version=version,
            tier_rules=tier_rules,
            approval_ttl_seconds=int(rules.get("approval_ttl_seconds", 86400)),
            max_task_budget_usd=(
                float(rules["max_task_budget_usd"])
                if rules.get("max_task_budget_usd") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ActionContext:
    tool_name: str
    risk_tier: RiskTier
    tool_enabled: bool = True
    kill_switch: bool = False
    agent_allowed_tools: frozenset[str] | None = None  # None = no per-agent restriction


def decide(policy: Policy, ctx: ActionContext) -> Decision:
    if ctx.kill_switch or not ctx.tool_enabled:
        return Decision.DENY
    if ctx.agent_allowed_tools is not None and ctx.tool_name not in ctx.agent_allowed_tools:
        return Decision.DENY
    decision = policy.tier_rules.get(ctx.risk_tier, Decision.DENY)
    floor = HARD_FLOOR.get(ctx.risk_tier)
    return _stricter(decision, floor) if floor else decision
