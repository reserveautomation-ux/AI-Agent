"""Claude usage and cost, shared by the API (chat) and the worker (agents)."""

from dataclasses import dataclass
from typing import Any

FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: (input, output, cache read, cache write).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
WEB_SEARCH_USD = 0.01  # per search


@dataclass
class CallRecord:
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    web_searches: int
    cost_usd: float
    latency_ms: int
    stop_reason: str | None


def usage_of(resp: Any) -> CallRecord:
    u = getattr(resp, "usage", None)

    def g(name: str) -> int:
        return int(getattr(u, name, 0) or 0) if u is not None else 0

    stu = getattr(u, "server_tool_use", None) if u is not None else None
    searches = int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
    model = getattr(resp, "model", "") or ""
    price = next((p for m, p in PRICES.items() if model.startswith(m)), PRICES["claude-opus-5-5"])
    rec = CallRecord(
        model=model,
        input_tokens=g("input_tokens"),
        output_tokens=g("output_tokens"),
        cache_read_tokens=g("cache_read_input_tokens"),
        cache_write_tokens=g("cache_creation_input_tokens"),
        web_searches=searches,
        cost_usd=0.0,
        latency_ms=0,
        stop_reason=getattr(resp, "stop_reason", None),
    )
    rec.cost_usd = (
        rec.input_tokens * price[0]
        + rec.output_tokens * price[1]
        + rec.cache_read_tokens * price[2]
        + rec.cache_write_tokens * price[3]
    ) / 1_000_000 + searches * WEB_SEARCH_USD
    return rec
