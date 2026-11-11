"""Carry out actions the owner approved.

Only actions with a working integration actually run; for everything else we
say plainly that it wasn't done. Never pretend an action happened.
"""

import json
from typing import Any

from workforce_core.integrations import PROVIDERS_BY_KEY
from workforce_core.tools import TOOLS_BY_NAME

from .browser import BrowserService

ACTION_LABELS = {
    "send_email": "Send email",
    "send_whatsapp": "Send WhatsApp",
    "calendar_create_event": "Calendar event",
    "post_social": "Social post",
    "deploy_web": "Website deploy",
    "book_flight": "Flight booking",
    "place_stock_order": "Stock order",
    "play_store_release": "Play Store release",
    "app_store_submit": "App Store submission",
    "browser_submit_form": "Web form",
}


class NotConnected(Exception):
    """The integration for this action isn't set up yet."""


async def execute_action(action: str, args: dict[str, Any], browser: BrowserService | None) -> str:
    if action == "browser_submit_form":
        if browser is None:
            raise NotConnected("The browser isn't running on this worker, so the form wasn't sent.")
        fields = args.get("fields")
        if isinstance(fields, str):
            fields = json.loads(fields)
        if not isinstance(fields, dict) or not fields:
            raise ValueError("the form fields are missing")
        result = await browser.fill_form(
            args["url"],
            {str(k): str(v) for k, v in fields.items()},
            submit=True,
            owner_approved=True,
        )
        reply = " ".join(result.page_text_after.split())[:240]
        return f"Submitted the form. The site replied: {reply}" if reply else "Submitted the form."

    spec = TOOLS_BY_NAME.get(action)
    provider = PROVIDERS_BY_KEY[spec.provider].name if spec else action
    raise NotConnected(f"{provider} isn't connected yet, so this wasn't done. Nothing was sent.")
