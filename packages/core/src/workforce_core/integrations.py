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
    BROWSER = "browser"  # sandboxed browser, only on sites whose terms allow automation


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
        "claude_code",
        "Claude code execution",
        "compute",
        Access.OFFICIAL_API,
        "Sandboxed code runs on the Claude API: data analysis, charts, file conversion, "
        "and Word/Excel/PowerPoint/PDF generation.",
    ),
    Provider(
        "browser",
        "Sandboxed browser",
        "compute",
        Access.BROWSER,
        "Playwright in an isolated worker for pages that need a real browser. Form "
        "submission only on sites whose terms permit automation; never stores passwords.",
    ),
    Provider(
        "google_drive",
        "Google Drive, Docs & Sheets",
        "documents",
        Access.OFFICIAL_API,
        "Drive and Sheets APIs via Google OAuth (per-file or app-folder scope).",
    ),
    Provider(
        "whatsapp",
        "WhatsApp Business",
        "communication",
        Access.OFFICIAL_API,
        "WhatsApp Cloud API needs a business number; messages to people who have not "
        "written first must use pre-approved templates.",
    ),
    Provider(
        "social",
        "LinkedIn / X / Instagram",
        "marketing",
        Access.OFFICIAL_API,
        "Official posting APIs; Instagram requires a business or creator account. "
        "Each network needs its own app approval.",
    ),
    Provider(
        "telegram",
        "Telegram",
        "communication",
        Access.OFFICIAL_API,
        "Bot API with the owner's own bot token; people must start a chat with the bot first.",
    ),
    Provider(
        "slack",
        "Slack",
        "communication",
        Access.OFFICIAL_API,
        "Sign in with Slack; posts approved messages to channels.",
    ),
    Provider(
        "cloudflare_ai",
        "Cloudflare AI (pictures)",
        "creative",
        Access.OFFICIAL_API,
        "Owner's own Cloudflare account; Workers AI image model (FLUX.1 schnell). Free "
        "allowance of 10,000 'neurons' a day, about 230 pictures at default settings.",
    ),
    Provider(
        "whatsapp_personal",
        "WhatsApp (your normal app)",
        "communication",
        Access.DEEP_LINK,
        "Click-to-chat links (wa.me): WhatsApp opens with the message filled in and you tap Send. "
        "Works with any WhatsApp. Automating a personal account is against WhatsApp's terms.",
    ),
    Provider(
        "gmail_inbox",
        "Gmail inbox",
        "communication",
        Access.OFFICIAL_API,
        "Separate connection with read + compose permission: agents search and read your mail, "
        "save reply drafts in Gmail (never sent by them), and alert you about important mail. "
        "Reading mail is a Google 'restricted' permission: fine for up to 100 users, then Google's "
        "review and security assessment are needed.",
    ),
    Provider(
        "gmail",
        "Gmail",
        "communication",
        Access.OFFICIAL_API,
        "Connect in Settings. Send-only permission (gmail.send): agents can send emails you "
        "approve but can't read or delete your mail. Drafts stay in Workforce OS.",
    ),
    Provider(
        "google_calendar",
        "Google Calendar",
        "communication",
        Access.OFFICIAL_API,
        "Connect in Settings. Sees only free/busy (not meeting details) and creates events "
        "you approve on calendars you own.",
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
        "Ola / Rapido / Swiggy / Zomato / BookMyShow / Amazon / Flipkart",
        "commerce",
        Access.DEEP_LINK,
        "No public consumer ordering APIs. The agent finds options and prepares a link; "
        "the owner confirms and pays in the provider's app.",
    ),
)

PROVIDERS_BY_KEY: dict[str, Provider] = {p.key: p for p in PROVIDERS}
