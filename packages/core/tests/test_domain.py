from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from workforce_core.approvals import ApprovalBinding, ApprovalError, canonical_json, check_approval
from workforce_core.integrations import PROVIDERS_BY_KEY
from workforce_core.lifecycle import Evaluation, LifecycleAction, promotion_allowed, recommend
from workforce_core.policy import ActionContext, Decision, Policy, RiskTier, decide
from workforce_core.task_states import TERMINAL, TaskStatus, can_transition, is_terminal
from workforce_core.tools import TOOLS

# --- task state machine -------------------------------------------------------


def test_completed_only_reachable_through_verifying():
    sources = [s for s in TaskStatus if can_transition(s, TaskStatus.COMPLETED)]
    assert sources == [TaskStatus.VERIFYING]


def test_terminal_states():
    assert {TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.EXPIRED} == TERMINAL
    assert is_terminal("completed")
    assert not can_transition("completed", "running")


def test_cancellable_from_every_non_terminal_waiting_state():
    for s in ("draft", "planned", "queued", "running", "waiting_for_approval", "blocked"):
        assert can_transition(s, "cancelled"), s


# --- policy engine ------------------------------------------------------------


def _policy(**tiers):
    return Policy.from_row("p1", 1, {"tiers": tiers} if tiers else {})


def test_default_policy_by_tier():
    p = _policy()
    expect = {
        RiskTier.READ: Decision.ALLOW,
        RiskTier.INTERNAL_WRITE: Decision.ALLOW,
        RiskTier.EXTERNAL_COMMITMENT: Decision.REQUIRE_APPROVAL,
        RiskTier.FINANCIAL: Decision.REQUIRE_OWNER_APPROVAL,
        RiskTier.DESTRUCTIVE: Decision.DENY,
    }
    for tier, decision in expect.items():
        assert decide(p, ActionContext("t", tier)) == decision


def test_policy_cannot_loosen_hard_floors():
    p = _policy(**{"3": "allow", "4": "allow"})
    assert decide(p, ActionContext("pay", RiskTier.FINANCIAL)) == Decision.REQUIRE_OWNER_APPROVAL
    assert decide(p, ActionContext("rm", RiskTier.DESTRUCTIVE)) == Decision.DENY


def test_policy_can_tighten():
    p = _policy(**{"0": "require_approval"})
    assert decide(p, ActionContext("search", RiskTier.READ)) == Decision.REQUIRE_APPROVAL


def test_kill_switch_and_agent_allowlist_deny():
    p = _policy()
    assert decide(p, ActionContext("search", RiskTier.READ, kill_switch=True)) == Decision.DENY
    ctx = ActionContext("search", RiskTier.READ, agent_allowed_tools=frozenset({"web_fetch"}))
    assert decide(p, ctx) == Decision.DENY


# --- approvals ----------------------------------------------------------------


def _binding(**overrides):
    base = dict(
        task_id="t1",
        action="book_flight",
        payload={"offer": "abc"},
        amount=Decimal("120.50"),
        currency="USD",
        recipient="Airline",
        item="DEL-BOM",
        account_ref="acct1",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        policy_version=1,
    )
    base.update(overrides)
    return ApprovalBinding(**base)


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [1, 2]}) == canonical_json({"a": [1, 2], "b": 1})
    assert canonical_json({"x": Decimal("1.50")}) == canonical_json({"x": Decimal("1.5")})


def test_approval_accepts_identical_action():
    b = _binding()
    check_approval(b, b.action_hash(), "approved")


@pytest.mark.parametrize(
    "change",
    [
        {"amount": Decimal("120.51")},
        {"recipient": "Other"},
        {"currency": "INR"},
        {"payload": {"offer": "xyz"}},
        {"policy_version": 2},
        {"account_ref": "acct2"},
    ],
)
def test_approval_rejects_any_material_change(change):
    approved = _binding()
    with pytest.raises(ApprovalError, match="differs"):
        check_approval(
            _binding(**{**approved.__dict__, **change}), approved.action_hash(), "approved"
        )


def test_approval_rejects_expired_or_unapproved():
    b = _binding(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(ApprovalError, match="expired"):
        check_approval(b, b.action_hash(), "approved")
    b = _binding()
    with pytest.raises(ApprovalError, match="pending"):
        check_approval(b, b.action_hash(), "pending")


# --- lifecycle ----------------------------------------------------------------


def test_lifecycle_needs_data_before_judging():
    action, _ = recommend("active", Evaluation(5, 0.1, 0.1), replicas=1)
    assert action == LifecycleAction.INSUFFICIENT_DATA


def test_lifecycle_clones_strong_performers_up_to_cap():
    strong = Evaluation(50, 0.95, 0.9)
    assert recommend("active", strong, replicas=1)[0] == LifecycleAction.CLONE
    assert recommend("active", strong, replicas=3)[0] == LifecycleAction.KEEP


def test_lifecycle_suspends_then_retires_weak_performers():
    weak = Evaluation(50, 0.4, 0.5)
    assert recommend("active", weak, replicas=1)[0] == LifecycleAction.SUSPEND
    assert recommend("suspended", weak, replicas=1)[0] == LifecycleAction.RETIRE


def test_lifecycle_safety_violation_suspends_regardless_of_sample_size():
    action, _ = recommend("active", Evaluation(1, 1.0, 1.0, safety_violations=1), replicas=1)
    assert action == LifecycleAction.SUSPEND


def test_promotion_requires_passing_evaluation():
    assert not promotion_allowed(None)[0]
    assert not promotion_allowed(Evaluation(50, 0.7, 0.9))[0]
    assert promotion_allowed(Evaluation(50, 0.9, 0.9))[0]


# --- registries ---------------------------------------------------------------


def test_every_tool_maps_to_a_known_provider():
    for t in TOOLS:
        assert t.provider in PROVIDERS_BY_KEY, t.name


def test_money_moving_tools_are_tier_three_or_higher():
    for name in ("book_flight", "place_stock_order", "play_store_release", "app_store_submit"):
        assert next(t for t in TOOLS if t.name == name).risk_tier >= RiskTier.FINANCIAL
