"""Approval binding.

An approval covers one exact action. We hash a canonical form of every
material field; at execution time the executor recomputes the hash from the
action it is *about* to perform and refuses to run unless it matches the
approved hash, the approval is unexpired, and it is still in ``approved`` state.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no whitespace, Decimals as strings."""

    def default(o: Any) -> Any:
        if isinstance(o, Decimal):
            return format(o.normalize(), "f")
        if isinstance(o, datetime):
            return o.astimezone(UTC).isoformat()
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")

    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=default)


@dataclass(frozen=True)
class ApprovalBinding:
    """Every field an approval must bind to (blueprint section 6)."""

    task_id: str
    action: str
    payload: dict[str, Any]
    amount: Decimal | None
    currency: str | None
    recipient: str | None
    item: str | None
    account_ref: str | None
    expires_at: datetime
    policy_version: int

    def action_hash(self) -> str:
        return hashlib.sha256(canonical_json(asdict(self)).encode()).hexdigest()


class ApprovalError(Exception):
    pass


def check_approval(
    binding: ApprovalBinding,
    approved_hash: str,
    status: str,
    now: datetime | None = None,
) -> None:
    """Raise :class:`ApprovalError` unless ``binding`` may execute under this approval."""
    now = now or datetime.now(UTC)
    if status != "approved":
        raise ApprovalError(f"approval is {status}, not approved")
    if now >= binding.expires_at:
        raise ApprovalError("approval has expired")
    if binding.action_hash() != approved_hash:
        raise ApprovalError("action differs from what was approved; request a new approval")
