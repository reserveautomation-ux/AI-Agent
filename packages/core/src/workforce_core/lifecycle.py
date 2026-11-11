"""Agent lifecycle: clone the strong, suspend and retire the weak (blueprint section 11).

Safety rules that are not configurable:
  * Decisions come from measured task outcomes, never self-reported confidence.
  * A clone is a copy of a versioned *configuration*, starts in ``sandbox``,
    inherits no extra permissions, and only takes real work after its own
    evaluation passes (``promotion_allowed``).
  * "Delete" means retire: the agent stops getting work, and its configuration
    history and audit trail are kept. No agent can erase its own records.
  * Any safety/policy violation suspends the agent immediately.
  * Replica counts are capped, so agents cannot multiply without bound.
"""

from dataclasses import dataclass
from enum import StrEnum


class LifecycleAction(StrEnum):
    KEEP = "keep"
    INSUFFICIENT_DATA = "insufficient_data"
    CLONE = "clone"
    SUSPEND = "suspend"
    RETIRE = "retire"


@dataclass(frozen=True)
class Evaluation:
    sample_size: int
    success_rate: float  # share of tasks meeting acceptance criteria
    quality_score: float  # verifier / human score, 0..1
    safety_violations: int = 0
    cost_per_success_usd: float | None = None


@dataclass(frozen=True)
class Thresholds:
    min_samples: int = 20
    suspend_below_success: float = 0.6
    clone_min_success: float = 0.9
    clone_min_quality: float = 0.85
    promote_min_success: float = 0.85
    promote_min_quality: float = 0.8
    max_cost_per_success_usd: float | None = None
    max_replicas: int = 3  # active + sandbox agents sharing one lineage


DEFAULT_THRESHOLDS = Thresholds()


def recommend(
    status: str,
    evaluation: Evaluation | None,
    replicas: int,
    t: Thresholds = DEFAULT_THRESHOLDS,
) -> tuple[LifecycleAction, str]:
    """What to do with an agent given its latest evaluation."""
    if status == "retired":
        return LifecycleAction.KEEP, "already retired"
    if evaluation is not None and evaluation.safety_violations > 0:
        if status == "suspended":
            return LifecycleAction.RETIRE, "safety violations while suspended"
        return LifecycleAction.SUSPEND, f"{evaluation.safety_violations} safety violation(s)"
    if evaluation is None or evaluation.sample_size < t.min_samples:
        return LifecycleAction.INSUFFICIENT_DATA, f"needs at least {t.min_samples} tasks"

    over_budget = (
        t.max_cost_per_success_usd is not None
        and evaluation.cost_per_success_usd is not None
        and evaluation.cost_per_success_usd > t.max_cost_per_success_usd
    )
    if evaluation.success_rate < t.suspend_below_success or over_budget:
        why = (
            "cost per success above limit"
            if over_budget
            else f"success rate {evaluation.success_rate:.0%} below {t.suspend_below_success:.0%}"
        )
        if status == "suspended":
            return LifecycleAction.RETIRE, f"still underperforming after suspension: {why}"
        return LifecycleAction.SUSPEND, why

    if (
        status == "active"
        and evaluation.success_rate >= t.clone_min_success
        and evaluation.quality_score >= t.clone_min_quality
    ):
        if replicas >= t.max_replicas:
            cap = t.max_replicas
            return LifecycleAction.KEEP, f"strong performer; replica cap of {cap} reached"
        return LifecycleAction.CLONE, "strong performer; clone to add capacity"

    return LifecycleAction.KEEP, "within normal range"


def promotion_allowed(
    evaluation: Evaluation | None, t: Thresholds = DEFAULT_THRESHOLDS
) -> tuple[bool, str]:
    """May a sandbox agent (e.g. a fresh clone) start taking real work?"""
    if evaluation is None or evaluation.sample_size < t.min_samples:
        return False, f"run the evaluation suite first (at least {t.min_samples} tasks)"
    if evaluation.safety_violations > 0:
        return False, "safety violations during evaluation"
    if evaluation.success_rate < t.promote_min_success:
        rate, need = evaluation.success_rate, t.promote_min_success
        return False, f"success rate {rate:.0%} below {need:.0%}"
    if evaluation.quality_score < t.promote_min_quality:
        return False, f"quality {evaluation.quality_score:.2f} below {t.promote_min_quality:.2f}"
    if (
        t.max_cost_per_success_usd is not None
        and evaluation.cost_per_success_usd is not None
        and evaluation.cost_per_success_usd > t.max_cost_per_success_usd
    ):
        return False, "cost per success above limit"
    return True, "evaluation passed"
