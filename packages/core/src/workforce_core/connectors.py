"""The connection catalog: every service a person can connect, and how.

People connect services when they need them (often in the middle of a task:
"Connect WhatsApp to continue"). Each connector says how it is connected:

* ``oauth2``   - sign in on the provider's own page; the platform owner registers
                 one app with the provider (client id/secret in server env).
* ``api_key``  - the person pastes their own key/token from the provider (stored
                 encrypted). Works without any platform-level registration.
* ``deep_link``- no public API: agents prepare the action and the person confirms
                 it in the provider's app.
* ``builtin``  - nothing to connect.

``live`` means the agents can actually act through it today; otherwise it is
listed as coming soon and can't be connected yet (we never pretend).
"""

import os
from dataclasses import dataclass
from enum import StrEnum


class AuthKind(StrEnum):
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    DEEP_LINK = "deep_link"
    BUILTIN = "builtin"


@dataclass(frozen=True)
class KeyField:
    key: str
    label: str
    secret: bool = True
    help: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class OAuthSpec:
    authorize_url: str
    token_url: str
    scopes: tuple[str, ...]
    required_scopes: tuple[str, ...]
    client_env: str  # env prefix: <PREFIX>_CLIENT_ID / <PREFIX>_CLIENT_SECRET
    scope_param: str = "scope"
    scope_separator: str = " "
    pkce: bool = True
    extra_params: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Connector:
    key: str
    name: str
    category: str
    icon: str
    description: str
    auth: AuthKind
    live: bool
    tools: tuple[str, ...] = ()
    oauth: OAuthSpec | None = None
    fields: tuple[KeyField, ...] = ()
    how_to_get: str = ""  # for api_key: where the person finds their key
    plan: str = "free"  # minimum plan to use it (enforced once billing is on)
    note: str = ""  # honest limitations
    open_url: str = ""  # deep links: the app/site the person confirms in

    def configured(self) -> bool:
        """Can people connect this on this server right now?"""
        if not self.live:
            return False
        if self.auth == AuthKind.OAUTH2 and self.oauth:
            p = self.oauth.client_env
            return bool(os.environ.get(f"{p}_CLIENT_ID") and os.environ.get(f"{p}_CLIENT_SECRET"))
        return True


G = "https://www.googleapis.com/auth/"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_EXTRA = (
    ("access_type", "offline"),
    ("prompt", "consent"),
    ("include_granted_scopes", "true"),
)


def _google(scopes: tuple[str, ...], required: tuple[str, ...]) -> OAuthSpec:
    return OAuthSpec(
        GOOGLE_AUTH,
        GOOGLE_TOKEN,
        ("openid", "email", *scopes),
        required,
        "GOOGLE",
        extra_params=GOOGLE_EXTRA,
    )


C = Connector
A = AuthKind

CONNECTORS: tuple[Connector, ...] = (
    # --- communication ----------------------------------------------------------
    C(
        "gmail",
        "Gmail",
        "Communication",
        "✉️",
        "Send emails you approve. Send only: it can't read or delete your mail.",
        A.OAUTH2,
        True,
        ("send_email",),
        oauth=_google((G + "gmail.send",), (G + "gmail.send",)),
    ),
    C(
        "google_calendar",
        "Google Calendar",
        "Communication",
        "📅",
        "See when you're busy (not what your meetings are) and add events you approve.",
        A.OAUTH2,
        True,
        ("calendar_check_availability", "calendar_create_event"),
        oauth=_google(
            (G + "calendar.events.owned", G + "calendar.freebusy"), (G + "calendar.events.owned",)
        ),
    ),
    C(
        "whatsapp",
        "WhatsApp Business",
        "Communication",
        "💬",
        "Send WhatsApp messages you approve from your WhatsApp Business number.",
        A.API_KEY,
        True,
        ("send_whatsapp",),
        fields=(
            KeyField(
                "access_token",
                "Access token",
                help="System user token with whatsapp_business_messaging permission",
            ),
            KeyField(
                "phone_number_id",
                "Phone number ID",
                secret=False,
                help="From WhatsApp Manager → API setup",
                placeholder="1234567890",
            ),
        ),
        how_to_get="Meta for Developers → your app → WhatsApp → API setup.",
        note="WhatsApp only allows free-form messages to people who messaged you in the last "
        "24 hours; others need a pre-approved template.",
    ),
    C(
        "telegram",
        "Telegram",
        "Communication",
        "✈️",
        "Send Telegram messages you approve through your own bot.",
        A.API_KEY,
        True,
        ("send_telegram",),
        fields=(
            KeyField("bot_token", "Bot token", help="From @BotFather", placeholder="123:ABC…"),
        ),
        how_to_get="In Telegram, message @BotFather → /newbot, then copy the token.",
        note="A bot can only message people who have started a chat with it first.",
    ),
    C(
        "slack",
        "Slack",
        "Communication",
        "🟪",
        "Post messages you approve to Slack channels.",
        A.OAUTH2,
        True,
        ("post_slack",),
        oauth=OAuthSpec(
            "https://slack.com/oauth/v2/authorize",
            "https://slack.com/api/oauth.v2.access",
            ("chat:write", "chat:write.public", "channels:read"),
            ("chat:write",),
            "SLACK",
            scope_separator=",",
            pkce=False,
        ),
    ),
    C(
        "outlook",
        "Outlook & Microsoft 365",
        "Communication",
        "📧",
        "Send email and manage your Outlook calendar.",
        A.OAUTH2,
        False,
        (),
    ),
    # --- build & deploy -----------------------------------------------------------
    C(
        "github",
        "GitHub",
        "Build & deploy",
        "🐙",
        "Save websites and code agents build to a repository you approve.",
        A.API_KEY,
        True,
        ("github_save_files",),
        fields=(
            KeyField(
                "token",
                "Personal access token",
                help="Fine-grained token with Administration and Contents: read & write",
                placeholder="github_pat_…",
            ),
        ),
        how_to_get="GitHub → Settings → Developer settings → Fine-grained tokens → Generate.",
    ),
    C(
        "vercel",
        "Vercel",
        "Build & deploy",
        "▲",
        "Put websites agents build online at a public link, after you approve.",
        A.API_KEY,
        True,
        ("deploy_web",),
        fields=(KeyField("token", "Access token", placeholder="vercel token"),),
        how_to_get="Vercel → Account settings → Tokens → Create.",
    ),
    C(
        "google_play",
        "Google Play Console",
        "Build & deploy",
        "▶️",
        "Publish Android apps.",
        A.API_KEY,
        False,
        ("play_store_release",),
        note="Needs a Google Play developer account; Google reviews every release.",
    ),
    C(
        "app_store_connect",
        "App Store Connect",
        "Build & deploy",
        "🍏",
        "Publish iPhone apps.",
        A.API_KEY,
        False,
        ("app_store_submit",),
        note="Needs an Apple Developer account; Apple reviews every release.",
    ),
    # --- documents & work ---------------------------------------------------------
    C(
        "google_drive",
        "Google Drive",
        "Documents",
        "🗂️",
        "Save files agents make to your Drive.",
        A.OAUTH2,
        False,
        ("save_to_drive",),
    ),
    C(
        "notion",
        "Notion",
        "Documents",
        "📝",
        "Save notes and reports to Notion.",
        A.OAUTH2,
        False,
        (),
    ),
    # --- money --------------------------------------------------------------------
    C(
        "broker_kite",
        "Zerodha Kite",
        "Money",
        "📈",
        "Market data and order preparation.",
        A.API_KEY,
        False,
        ("market_data", "place_stock_order"),
        plan="pro",
        note="Paid Kite Connect subscription on your own account; SEBI rules apply to "
        "automated orders.",
    ),
    C(
        "duffel",
        "Flights (Duffel)",
        "Travel",
        "🛫",
        "Search and book flights.",
        A.API_KEY,
        False,
        ("book_flight",),
        plan="pro",
    ),
    C(
        "social",
        "LinkedIn / X / Instagram",
        "Marketing",
        "📣",
        "Publish posts you approve.",
        A.OAUTH2,
        False,
        ("post_social",),
    ),
    # --- confirm in the provider's app (no public booking APIs) -----------------------
    C(
        "uber",
        "Uber",
        "Rides",
        "🚕",
        "Agents find the ride; you confirm in Uber.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://m.uber.com/",
    ),
    C(
        "ola",
        "Ola",
        "Rides",
        "🛺",
        "Agents find the ride; you confirm in Ola.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://book.olacabs.com/",
    ),
    C(
        "rapido",
        "Rapido",
        "Rides",
        "🏍️",
        "Agents find the ride; you confirm in Rapido.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://www.rapido.bike/",
    ),
    C(
        "swiggy",
        "Swiggy",
        "Food & shopping",
        "🍲",
        "Agents pick the food; you order in Swiggy.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://www.swiggy.com/",
    ),
    C(
        "zomato",
        "Zomato",
        "Food & shopping",
        "🍛",
        "Agents pick the food; you order in Zomato.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://www.zomato.com/",
    ),
    C(
        "amazon",
        "Amazon",
        "Food & shopping",
        "📦",
        "Agents compare; you buy on Amazon.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://www.amazon.in/",
    ),
    C(
        "flipkart",
        "Flipkart",
        "Food & shopping",
        "🛒",
        "Agents compare; you buy on Flipkart.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://www.flipkart.com/",
    ),
    C(
        "bookmyshow",
        "BookMyShow",
        "Tickets",
        "🎬",
        "Agents find shows; you book in BookMyShow.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://in.bookmyshow.com/",
    ),
    C(
        "irctc",
        "IRCTC trains",
        "Tickets",
        "🚆",
        "Agents find trains; you book on IRCTC.",
        A.DEEP_LINK,
        True,
        ("prepare_booking_link",),
        open_url="https://www.irctc.co.in/",
    ),
    # --- built in -----------------------------------------------------------------
    C(
        "claude_web",
        "Web search",
        "Built in",
        "🔎",
        "Search and read the web.",
        A.BUILTIN,
        True,
        ("web_search", "web_fetch"),
    ),
    C(
        "browser",
        "Agent browser",
        "Built in",
        "🌐",
        "Open websites, read them and fill forms you approve.",
        A.BUILTIN,
        True,
        ("browse_page", "browser_submit_form"),
    ),
    C(
        "internal",
        "Files & memory",
        "Built in",
        "🧠",
        "Reports, documents, website files and long-term memory.",
        A.BUILTIN,
        True,
        ("create_report", "create_document", "remember", "recall", "draft_email"),
    ),
)

CONNECTORS_BY_KEY: dict[str, Connector] = {c.key: c for c in CONNECTORS}

# Which connector a tool needs before it can act (built-ins and deep links need none).
TOOL_CONNECTOR: dict[str, str] = {
    tool: c.key
    for c in CONNECTORS
    if c.auth in (AuthKind.OAUTH2, AuthKind.API_KEY)
    for tool in c.tools
}


def connector_for_tool(tool: str) -> Connector | None:
    key = TOOL_CONNECTOR.get(tool)
    return CONNECTORS_BY_KEY[key] if key else None


__all__ = [
    "AuthKind",
    "CONNECTORS",
    "CONNECTORS_BY_KEY",
    "Connector",
    "KeyField",
    "OAuthSpec",
    "TOOL_CONNECTOR",
    "connector_for_tool",
]
