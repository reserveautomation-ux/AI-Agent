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
    ToolSpec(
        "browse_page",
        "research",
        "Open a page in a sandboxed browser and read it (JavaScript-heavy sites).",
        T.READ,
        "browser",
        {
            "type": "object",
            "properties": {
                "url": _S,
                "follow_links": {
                    "type": "array",
                    "items": _S,
                    "description": "Visible link texts to click through in order (optional)",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "recall",
        "memory",
        "Search long-term memory for your preferences, contacts and past results.",
        T.READ,
        "internal",
        _obj(query=_S),
    ),
    # Internal work (tier 1)
    ToolSpec(
        "run_code",
        "compute",
        "Run code in a sandbox: analyse data, build charts, convert files.",
        T.INTERNAL_WRITE,
        "claude_code",
        _obj(task=_S),
    ),
    ToolSpec(
        "create_document",
        "artifacts",
        "Create a document file. Word/PDF/Excel/PowerPoint export is coming; for now "
        "write Markdown, HTML or CSV.",
        T.INTERNAL_WRITE,
        "internal",
        {
            "type": "object",
            "properties": {
                "name": _S,
                "format": {
                    "type": "string",
                    "enum": ["csv", "markdown", "json", "html", "css", "js", "txt", "svg"],
                },
                "content": _S,
            },
            "required": ["name", "format", "content"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "make_image",
        "creative",
        "Create a picture from a description (photo-like or illustration) and save it as a "
        "JPEG file in this task. Uses the owner's own Cloudflare AI account (free daily "
        "allowance). For logos, icons and diagrams prefer an SVG file via create_document.",
        T.INTERNAL_WRITE,
        "cloudflare_ai",
        {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description, max 2000 chars.",
                },
                "name": {"type": "string", "description": "File name, e.g. cafe-poster"},
            },
            "required": ["prompt"],
        },
    ),
    ToolSpec(
        "save_to_drive",
        "documents",
        "Save a file or update a sheet in your Google Drive.",
        T.INTERNAL_WRITE,
        "google_drive",
        _obj(path=_S, artifact_id=_S),
    ),
    ToolSpec(
        "set_reminder",
        "personal",
        "Remind the owner at a time (phone notification + chat). 'at' is their local time like "
        "2026-11-20T16:00; repeat: none, daily, weekdays, weekly or monthly.",
        T.INTERNAL_WRITE,
        "internal",
        {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "at": {"type": "string"},
                "repeat": {
                    "type": "string",
                    "enum": ["none", "daily", "weekdays", "weekly", "monthly"],
                },
            },
            "required": ["message", "at"],
        },
    ),
    ToolSpec(
        "watch",
        "monitoring",
        "Check a price, page or stock on a schedule and alert you on a change.",
        T.INTERNAL_WRITE,
        "internal",
        _obj(target=_S, condition=_S, every=_S),
    ),
    ToolSpec(
        "create_report",
        "artifacts",
        "Save a report file (CSV, Markdown, JSON or HTML) as the task deliverable.",
        T.INTERNAL_WRITE,
        "internal",
        {
            "type": "object",
            "properties": {
                "name": _S,
                "format": {
                    "type": "string",
                    "enum": ["csv", "markdown", "json", "html", "css", "js", "txt", "svg"],
                },
                "content": _S,
            },
            "required": ["name", "format", "content"],
            "additionalProperties": False,
        },
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
        "gmail_search",
        "communication",
        "Search the owner's Gmail (Gmail search syntax, e.g. 'is:unread newer_than:2d', "
        "'from:rahul subject:invoice'). Returns sender, subject, date, snippet and ids.",
        T.READ,
        "gmail_inbox",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        "gmail_read",
        "communication",
        "Read one email in full by its id (from gmail_search).",
        T.READ,
        "gmail_inbox",
        _obj(message_id=_S),
    ),
    ToolSpec(
        "gmail_create_draft",
        "communication",
        "Save an email draft in the owner's Gmail (not sent; they review and send it). "
        "Give reply_to_id to draft a reply in the same thread.",
        T.INTERNAL_WRITE,
        "gmail_inbox",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc": {"type": "string"},
                "reply_to_id": {"type": "string"},
            },
            "required": ["to", "subject", "body"],
        },
    ),
    ToolSpec(
        "save_to_drive",
        "documents",
        "Save files made in this task to the owner's Google Drive. as='doc' makes a Google Doc "
        "(from markdown/html/txt), 'sheet' a Google Sheet (from csv), 'file' keeps it as is.",
        T.INTERNAL_WRITE,
        "google_drive",
        {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}},
                "as": {"type": "string", "enum": ["doc", "sheet", "file"]},
            },
            "required": ["files"],
        },
    ),
    ToolSpec(
        "remember",
        "memory",
        "Save something worth remembering to long-term memory.",
        T.INTERNAL_WRITE,
        "internal",
        {
            "type": "object",
            "properties": {
                "content": _S,
                "memory_type": {
                    "type": "string",
                    "enum": ["preference", "fact", "contact", "learning"],
                },
                "about": {
                    "type": "string",
                    "enum": ["owner", "my_work"],
                    "description": "'owner' = about the owner (shared with all agents); "
                    "'my_work' = a private lesson for doing your own job better",
                },
            },
            "required": ["content", "memory_type", "about"],
            "additionalProperties": False,
        },
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
        "Add an event to the owner's Google Calendar (and invite attendees). Needs approval.",
        T.EXTERNAL_COMMITMENT,
        "google_calendar",
        {
            "type": "object",
            "properties": {
                "title": _S,
                "start": {
                    "type": "string",
                    "description": "Local start date and time, e.g. 2026-11-20T16:00",
                },
                "end": {"type": "string", "description": "Local end time (or use duration)"},
                "duration_minutes": {"type": "integer"},
                "timezone": {"type": "string", "description": "IANA zone; default: owner's"},
                "attendees": {
                    "type": "string",
                    "description": "Comma-separated emails; they get Google invitations",
                },
                "location": _S,
                "description": _S,
            },
            "required": ["title", "start"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "calendar_check_availability",
        "communication",
        "See when the owner is busy between two times (not what the meetings are).",
        T.READ,
        "google_calendar",
        {
            "type": "object",
            "properties": {
                "time_min": {"type": "string", "description": "e.g. 2026-11-20T09:00"},
                "time_max": {"type": "string", "description": "e.g. 2026-11-20T19:00"},
                "timezone": {"type": "string"},
            },
            "required": ["time_min", "time_max"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "deploy_web",
        "software",
        "Put a website made of this task's files (index.html, styles.css, …) online. "
        "Needs approval.",
        T.EXTERNAL_COMMITMENT,
        "vercel",
        {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Short name, e.g. asha-bakery"},
                "files": {"type": "array", "items": _S, "description": "File names to publish"},
            },
            "required": ["project", "files"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "send_whatsapp",
        "communication",
        "Send a WhatsApp message from the owner's business number. Needs approval.",
        T.EXTERNAL_COMMITMENT,
        "whatsapp",
        {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Phone with country code, e.g. +9198…"},
                "message": _S,
            },
            "required": ["to", "message"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "send_telegram",
        "communication",
        "Send a Telegram message through the owner's bot. Needs approval.",
        T.EXTERNAL_COMMITMENT,
        "telegram",
        {
            "type": "object",
            "properties": {
                "chat": {"type": "string", "description": "Chat ID or @channelname"},
                "message": _S,
            },
            "required": ["chat", "message"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "post_slack",
        "communication",
        "Post a message to a Slack channel. Needs approval.",
        T.EXTERNAL_COMMITMENT,
        "slack",
        {
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "e.g. #general or a channel ID"},
                "message": _S,
            },
            "required": ["channel", "message"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "github_save_files",
        "software",
        "Save files from this task (made with create_document) to a GitHub repository. "
        "Needs approval.",
        T.EXTERNAL_COMMITMENT,
        "github",
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name, e.g. bakery-site"},
                "files": {"type": "array", "items": _S, "description": "File names to save"},
                "message": {"type": "string", "description": "What changed"},
                "private": {"type": "boolean"},
            },
            "required": ["repo", "files"],
            "additionalProperties": False,
        },
    ),
    ToolSpec(
        "post_social",
        "marketing",
        "Publish a post on LinkedIn, X or Instagram.",
        T.EXTERNAL_COMMITMENT,
        "social",
        _obj(network=_S, text=_S),
    ),
    ToolSpec(
        "browser_submit_form",
        "commerce",
        "Fill and submit a web form in the sandboxed browser (permitted sites only).",
        T.EXTERNAL_COMMITMENT,
        "browser",
        _obj(url=_S, fields=_S),
    ),
    ToolSpec(
        "prepare_booking_link",
        "commerce",
        "Prepare a ride, food, movie or shopping order for you to confirm in the provider app.",
        T.INTERNAL_WRITE,
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
