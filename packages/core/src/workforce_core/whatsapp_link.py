"""Messages for your normal (personal) WhatsApp: the assistant writes it, WhatsApp opens with
the text filled in (and the contact, if the number is known), and you tap Send.

This uses WhatsApp's official click-to-chat links (https://wa.me), so it works with any
WhatsApp account and nothing is sent without you. Automating a personal account from a
server breaks WhatsApp's terms and gets numbers banned, so we never do that.
"""

from dataclasses import dataclass
from urllib.parse import quote

MAX_TEXT = 4000


@dataclass(frozen=True)
class WhatsAppLink:
    url: str
    to: str  # "+919876543210", or "" to pick the contact in WhatsApp
    text: str


def normalise_number(raw: str, default_country: str = "91") -> str:
    """Digits with country code. A 10-digit number gets the default country (India: 91)."""
    raw = (raw or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return ""
    if raw.startswith("00"):
        digits = digits[2:]
    elif not raw.startswith("+") and len(digits) == 11 and digits.startswith("0"):
        digits = default_country + digits[1:]  # 0 98765 43210
    elif not raw.startswith("+") and len(digits) == 10:
        digits = default_country + digits
    if not 8 <= len(digits) <= 15:
        raise ValueError("that phone number doesn't look right; include the country code")
    return digits


def build(to: str, text: str, default_country: str = "91") -> WhatsAppLink:
    text = (text or "").strip()
    if not text:
        raise ValueError("the WhatsApp message is empty")
    if len(text) > MAX_TEXT:
        raise ValueError("that message is too long for one WhatsApp message")
    number = normalise_number(to, default_country)
    url = (
        f"https://wa.me/{number}?text={quote(text)}"
        if number
        else f"https://wa.me/?text={quote(text)}"
    )
    return WhatsAppLink(url=url, to=f"+{number}" if number else "", text=text)


def default_country_for(timezone: str | None) -> str:
    return {
        "Asia/Kolkata": "91",
        "Asia/Dubai": "971",
        "Asia/Singapore": "65",
        "Europe/London": "44",
        "America/New_York": "1",
        "America/Los_Angeles": "1",
        "Australia/Sydney": "61",
    }.get(timezone or "", "91")
