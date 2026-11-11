"""Integration feasibility register (blueprint section 5, "Integration rule").

Every provider an agent might act through, with an honest statement of how we
can integrate. Agents must explain a limitation rather than claim an action
they cannot actually complete. Terms change: re-verify each provider's API
access, automation terms, fees and regional coverage before enabling it.
"""

from dataclasses import dataclass
from enum import StrEnum


class Access(StrEnum):
    OFFICIAL_API = "official_api"  # public API; owner connects their own account
    PARTNER_REQUIRED = "partner_required"  # API exists but needs a business partnership
    DEEP_LINK = "deep_link"  # no API: agent prepares, owner confirms in the provider app
    INTERNAL = "internal"  # built into this system


@dataclass(frozen=True)
class Provider:
    key: str
    name: str
    category: str
    access: Access
    notes: str


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        "internal",
        "Workforce OS",
        "core",
        Access.INTERNAL,
        "Reports, memory and task records stored in Supabase.",
    ),
    Provider(
        "claude_web",
        "Claude web search & fetch",
        "research",
        Access.OFFICIAL_API,
        "Server-side tools on the Claude API; no extra key needed.",
    ),
    Provider(
        "gmail",
        "Gmail",
        "communication",
        Access.OFFICIAL_API,
        "Gmail API via Google OAuth (gmail.compose / gmail.send scopes).",
    ),
    Provider(
        "google_calendar",
        "Google Calendar",
        "communication",
        Access.OFFICIAL_API,
        "Calendar API via Google OAuth.",
    ),
    Provider(
        "github",
        "GitHub",
        "software",
        Access.OFFICIAL_API,
        "GitHub App or fine-grained token scoped to project repos.",
    ),
    Provider(
        "vercel",
        "Vercel",
        "software",
        Access.OFFICIAL_API,
        "Deployments API with a team-scoped token.",
    ),
    Provider(
        "google_play",
        "Google Play Console",
        "software",
        Access.OFFICIAL_API,
        "Play Developer Publishing API with a service account on the owner's developer "
        "account. Google review applies; publication is not guaranteed.",
    ),
    Provider(
        "app_store_connect",
        "App Store Connect",
        "software",
        Access.OFFICIAL_API,
        "App Store Connect API key; builds need a macOS runner (e.g. EAS Build or "
        "GitHub macOS runners). Apple review applies.",
    ),
    Provider(
        "broker_kite",
        "Zerodha Kite Connect",
        "finance",
        Access.OFFICIAL_API,
        "Paid API subscription on the owner's own account. SEBI's retail algo-trading "
        "rules apply to automated orders; start with research and alerts only and add "
        "order placement after compliance review.",
    ),
    Provider(
        "duffel",
        "Duffel (flights)",
        "travel",
        Access.OFFICIAL_API,
        "Flight search and booking API; payments through Duffel.",
    ),
    Provider(
        "irctc",
        "IRCTC (trains)",
        "travel",
        Access.PARTNER_REQUIRED,
        "Booking only through authorised partners.",
    ),
    Provider(
        "uber",
        "Uber rides",
        "commerce",
        Access.PARTNER_REQUIRED,
        "Ride request API is limited to approved partners; use deep links meanwhile.",
    ),
    Provider(
        "deep_links",
        "Ola / Rapido / Swiggy / Zomato / BookMyShow",
        "commerce",
        Access.DEEP_LINK,
        "No public consumer ordering APIs. The agent finds options and prepares a link; "
        "the owner confirms and pays in the provider's app.",
    ),
)

PROVIDERS_BY_KEY: dict[str, Provider] = {p.key: p for p in PROVIDERS}
