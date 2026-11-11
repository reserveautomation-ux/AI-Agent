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


def derive_fields(args: dict[str, Any]) -> dict[str, Any]:
    """The binding fields we pull out of a tool's arguments (shown to the owner)."""
    try:
        amount = (
            # Same precision as the database column, so the hash survives a round trip.
            Decimal(str(args["amount"])).quantize(Decimal("0.0001"))
            if args.get("amount") is not None
            else None
        )
    except (ArithmeticError, ValueError):
        amount = None
    return {
        "amount": amount,
        "currency": args.get("currency"),
        "recipient": args.get("to") or args.get("recipient") or args.get("network"),
        "item": args.get("symbol") or args.get("offer_id") or args.get("subject"),
    }


def binding_for(
    *,
    task_id: str,
    action: str,
    args: dict[str, Any],
    expires_at: datetime,
    policy_version: int,
    account_ref: str | None = None,
) -> ApprovalBinding:
    return ApprovalBinding(
        task_id=task_id,
        action=action,
        payload=args,
        expires_at=expires_at,
        policy_version=policy_version,
        account_ref=account_ref,
        **derive_fields(args),
    )


def binding_from_row(row: dict[str, Any]) -> ApprovalBinding:
    """Rebuild the binding from a stored approval_requests row."""
    return ApprovalBinding(
        task_id=str(row["task_id"]),
        action=row["action"],
        payload=row["action_payload"],
        amount=row["amount"],
        currency=row["currency"],
        recipient=row["recipient"],
        item=row["item"],
        account_ref=row["account_ref"],
        expires_at=row["expires_at"],
        policy_version=row["policy_version"],
    )


EDITABLE_MAX_CHARS = 5000


def apply_edits(payload: dict[str, Any], changes: dict[str, str]) -> dict[str, Any]:
    """Owner edits before approving: only existing text fields, never new ones."""
    if not changes:
        raise ApprovalError("no changes given")
    updated = dict(payload)
    for key, value in changes.items():
        if key not in payload or not isinstance(payload[key], str):
            raise ApprovalError(f"{key!r} can't be edited")
        if not isinstance(value, str) or not value.strip():
            raise ApprovalError(f"{key!r} can't be empty")
        if len(value) > EDITABLE_MAX_CHARS:
            raise ApprovalError(f"{key!r} is too long")
        updated[key] = value
    return updated
