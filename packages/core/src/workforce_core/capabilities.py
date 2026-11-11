"""What the workforce can do, in plain language, for the command screen.

Each capability lists the tools it needs; how it is handled (automatic, asks
your approval, or you confirm in the provider's app) is *derived* from those
tools' risk tiers and integrations, so this list can never promise more than
the policy engine will allow.
"""

from dataclasses import dataclass
from enum import StrEnum

from .integrations import PROVIDERS_BY_KEY, Access
from .policy import RiskTier
from .tools import TOOLS_BY_NAME


class Handling(StrEnum):
    AUTOMATIC = "automatic"
    ASKS_APPROVAL = "asks_approval"
    OWNER_APPROVAL = "owner_approval"
    YOU_CONFIRM_IN_APP = "you_confirm_in_app"


@dataclass(frozen=True)
class Capability:
    key: str
    area: str
    title: str
    example: str
    tools: tuple[str, ...]

    @property
    def handling(self) -> Handling:
        specs = [TOOLS_BY_NAME[t] for t in self.tools]
        if any(PROVIDERS_BY_KEY[s.provider].access == Access.DEEP_LINK for s in specs):
            return Handling.YOU_CONFIRM_IN_APP
        tier = max(s.risk_tier for s in specs)
        if tier >= RiskTier.FINANCIAL:
            return Handling.OWNER_APPROVAL
        if tier >= RiskTier.EXTERNAL_COMMITMENT:
            return Handling.ASKS_APPROVAL
        return Handling.AUTOMATIC


C = Capability

CAPABILITIES: tuple[Capability, ...] = (
    # Research & information
    C(
        "research",
        "Research",
        "Research anything with sources",
        "Find 50 fitness creators in Mumbai with 10k+ followers and rank them by engagement",
        ("web_search", "web_fetch", "create_report"),
    ),
    C(
        "compare",
        "Research",
        "Compare products, vendors or services",
        "Compare the top 5 CRM tools for a 10-person team, with prices in INR",
        ("web_search", "browse_page", "create_report"),
    ),
    C(
        "leads",
        "Research",
        "Find leads and contacts",
        "List 30 interior designers in Pune with website and phone, as a spreadsheet",
        ("web_search", "web_fetch", "create_document"),
    ),
    # Creative
    C(
        "pictures",
        "Create",
        "Make pictures, posters and logos",
        "Make a Diwali sale poster for my café and a simple logo",
        ("make_image", "create_document"),
    ),
    C(
        "whatsapp_personal",
        "Personal assistant",
        "Write WhatsApp messages for you",
        "WhatsApp mom that I'll be home by 8, in Hindi",
        ("whatsapp_link",),
    ),
    C(
        "upi",
        "Personal assistant",
        "Pay people by UPI",
        "Pay Ramesh ₹500 for milk (ramesh@okhdfcbank)",
        ("upi_link",),
    ),
    # Inbox
    C(
        "inbox",
        "Personal assistant",
        "Read and summarise your email",
        "What important emails did I get today? Summarise them and draft replies",
        ("gmail_search", "gmail_read", "gmail_create_draft"),
    ),
    C(
        "drive",
        "Research",
        "Save results as Google Docs or Sheets",
        "Make a list of 30 caterers in Pune and save it as a Google Sheet",
        ("web_search", "create_document", "save_to_drive"),
    ),
    # Personal assistant
    C(
        "email",
        "Personal",
        "Write and send emails",
        "Email Rahul that the meeting moves to Friday 4pm and ask him to confirm",
        ("draft_email", "send_email"),
    ),
    C(
        "calendar",
        "Personal",
        "Schedule meetings",
        "Book a 30-minute call with the design team next Tuesday morning",
        ("calendar_check_availability", "calendar_create_event"),
    ),
    C(
        "whatsapp",
        "Personal",
        "Send WhatsApp messages",
        "WhatsApp all confirmed guests the venue location and parking details",
        ("send_whatsapp",),
    ),
    C(
        "team_message",
        "Personal",
        "Message your team on Slack or Telegram",
        "Post on #general that the office is closed tomorrow",
        ("post_slack", "send_telegram"),
    ),
    C(
        "remind",
        "Personal",
        "Reminders and follow-ups",
        "Remind me to pay the electricity bill on the 5th of every month",
        ("set_reminder",),
    ),
    C(
        "memory",
        "Personal",
        "Remember your preferences",
        "Remember that I prefer aisle seats and vegetarian meals",
        ("remember",),
    ),
    # Travel & bookings
    C(
        "flights",
        "Travel",
        "Search and book flights",
        "Find the cheapest Delhi to Goa flight next Friday after 6pm and book it",
        ("web_search", "book_flight"),
    ),
    C(
        "cab",
        "Travel",
        "Book a cab",
        "Get me a cab from home to the airport at 6am tomorrow",
        ("web_search", "prepare_booking_link"),
    ),
    C(
        "movies",
        "Travel",
        "Movie and event tickets",
        "Two tickets for the latest Marvel movie this Saturday evening near Andheri",
        ("web_search", "prepare_booking_link"),
    ),
    C(
        "trip",
        "Travel",
        "Plan a whole trip",
        "Plan a 4-day Kerala trip in December for 2 under ₹60,000 with an itinerary",
        ("web_search", "browse_page", "create_document"),
    ),
    # Shopping & food
    C(
        "food",
        "Shopping",
        "Order food",
        "Order a paneer biryani from a well-rated place nearby",
        ("web_search", "prepare_booking_link"),
    ),
    C(
        "shopping",
        "Shopping",
        "Find and order products",
        "Find the best-reviewed running shoes under ₹5,000 in size 9",
        ("web_search", "browse_page", "prepare_booking_link"),
    ),
    C(
        "price_watch",
        "Shopping",
        "Watch prices and alert you",
        "Tell me when the iPhone 17 drops below ₹70,000 on any major site",
        ("browse_page", "watch"),
    ),
    # Money
    C(
        "stock_research",
        "Finance",
        "Research stocks and markets",
        "Research the top 5 mid-cap pharma stocks and summarise risks",
        ("market_data", "web_search", "run_code", "create_report"),
    ),
    C(
        "stock_alerts",
        "Finance",
        "Portfolio and price alerts",
        "Alert me if any stock in my watchlist falls more than 5% in a day",
        ("market_data", "watch"),
    ),
    C(
        "stock_orders",
        "Finance",
        "Place stock orders",
        "Buy 10 shares of Infosys if it drops below ₹1,500",
        ("market_data", "place_stock_order"),
    ),
    # Build
    C(
        "website",
        "Build",
        "Build and launch a website",
        "Build a landing page for my bakery with a menu and WhatsApp order button",
        ("create_document", "github_save_files", "deploy_web"),
    ),
    C(
        "mobile_app",
        "Build",
        "Build and publish a mobile app",
        "Make a simple habit-tracker app and publish it on Play Store and App Store",
        ("create_document", "github_save_files", "play_store_release", "app_store_submit"),
    ),
    # Content
    C(
        "content",
        "Content",
        "Write posts, blogs and scripts",
        "Write 10 Instagram captions for our Diwali sale",
        ("web_search", "create_document"),
    ),
    C(
        "social_post",
        "Content",
        "Publish on social media",
        "Post our product launch announcement on LinkedIn tomorrow at 10am",
        ("post_social",),
    ),
    # Documents & data
    C(
        "documents",
        "Documents",
        "Create documents and presentations",
        "Make a 10-slide investor deck from my notes",
        ("create_document",),
    ),
    C(
        "data",
        "Documents",
        "Analyse spreadsheets and data",
        "Analyse this month's sales sheet and chart the top 10 products",
        ("run_code", "create_document"),
    ),
    C(
        "drive",
        "Documents",
        "Save to Google Drive",
        "Save every report you make to my Drive folder 'AI Reports'",
        ("save_to_drive",),
    ),
    C(
        "forms",
        "Documents",
        "Fill online forms",
        "Fill the event registration form on this page with my details",
        ("browse_page", "browser_submit_form"),
    ),
)

CAPABILITIES_BY_KEY: dict[str, Capability] = {c.key: c for c in CAPABILITIES}
