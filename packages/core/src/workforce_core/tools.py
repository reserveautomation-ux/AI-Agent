"""Tool registry: every capability an agent can use, with its risk tier.

This is the single source of truth. The API syncs it into
``public.tool_definitions`` on startup; the tool gateway (week 2) will refuse
any call to a tool that is not registered here.
"""

from dataclasses import dataclass, field
from typing import Any

from .policy import RiskTier


@dataclass(frozen=True)
class ToolSpec:
    name: str
    category: str
    description: str
    risk_tier: RiskTier
    provider: str  # key into integrations.PROVIDERS
    input_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object"})


def _obj(**props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


_S = {"type": "string"}
_N = {"type": "number"}

T = RiskTier

TOOLS: tuple[ToolSpec, ...] = (
    # Research (tier 0)
    ToolSpec(
        "web_search", "research", "Search the public web.", T.READ, "claude_web", _obj(query=_S)
    ),
    ToolSpec(
        "web_fetch", "research", "Read a public web page.", T.READ, "claude_web", _obj(url=_S)
    ),
    ToolSpec(
        "market_data",
        "finance",
        "Quotes, fundamentals and history for a symbol.",
        T.READ,
        "broker_kite",
        _obj(symbol=_S),
    ),
    # Internal work (tier 1)
    ToolSpec(
        "create_report",
        "artifacts",
        "Write a CSV/XLSX/Markdown report artifact.",
        T.INTERNAL_WRITE,
        "internal",
        _obj(name=_S, format=_S, content=_S),
    ),
    ToolSpec(
        "draft_email",
        "communication",
        "Create an email draft (not sent).",
        T.INTERNAL_WRITE,
        "gmail",
        _obj(to=_S, subject=_S, body=_S),
    ),
    ToolSpec(
        "remember",
        "memory",
        "Save a fact or preference to long-term memory.",
        T.INTERNAL_WRITE,
        "internal",
        _obj(memory_type=_S, content=_S),
    ),
    ToolSpec(
        "git_commit_push",
        "software",
        "Commit and push to a project branch.",
        T.INTERNAL_WRITE,
        "github",
        _obj(repo=_S, branch=_S, message=_S),
    ),
    # External commitments (tier 2)
    ToolSpec(
        "send_email",
        "communication",
        "Send an email.",
        T.EXTERNAL_COMMITMENT,
        "gmail",
        _obj(to=_S, subject=_S, body=_S),
    ),
    ToolSpec(
        "calendar_create_event",
        "communication",
        "Create a calendar event.",
        T.EXTERNAL_COMMITMENT,
        "google_calendar",
        _obj(title=_S, start=_S, end=_S),
    ),
    ToolSpec(
        "deploy_web",
        "software",
        "Deploy a web app to production.",
        T.EXTERNAL_COMMITMENT,
        "vercel",
        _obj(project=_S, ref=_S),
    ),
    ToolSpec(
        "prepare_booking_link",
        "commerce",
        "Prepare a ride/food/movie booking for the owner to confirm in the provider app.",
        T.EXTERNAL_COMMITMENT,
        "deep_links",
        _obj(provider=_S, details=_S),
    ),
    # Financial / high impact (tier 3) - owner approval, always
    ToolSpec(
        "book_flight",
        "travel",
        "Book a flight.",
        T.FINANCIAL,
        "duffel",
        _obj(offer_id=_S, amount=_N, currency=_S),
    ),
    ToolSpec(
        "place_stock_order",
        "finance",
        "Place a broker order.",
        T.FINANCIAL,
        "broker_kite",
        _obj(symbol=_S, side=_S, quantity=_N, order_type=_S),
    ),
    ToolSpec(
        "play_store_release",
        "software",
        "Submit a release to Google Play.",
        T.FINANCIAL,
        "google_play",
        _obj(package=_S, track=_S, artifact=_S),
    ),
    ToolSpec(
        "app_store_submit",
        "software",
        "Submit a build for App Store review.",
        T.FINANCIAL,
        "app_store_connect",
        _obj(app_id=_S, build=_S),
    ),
)

TOOLS_BY_NAME: dict[str, ToolSpec] = {t.name: t for t in TOOLS}
