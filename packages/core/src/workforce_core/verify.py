"""Check an API-key connection works before saving it, and learn who it belongs to.

Each function returns (account_id, display_name) or raises ValueError with a
plain-language reason the person can act on.
"""

import os
from collections.abc import Awaitable, Callable

import httpx

# Meta's Graph API version (current examples use v27.0); override with WHATSAPP_GRAPH_VERSION.
GRAPH = f"https://graph.facebook.com/{os.environ.get('WHATSAPP_GRAPH_VERSION', 'v27.0')}"
GITHUB_HEADERS = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}

Checker = Callable[[httpx.AsyncClient, dict[str, str]], Awaitable[tuple[str, str]]]


async def _telegram(http: httpx.AsyncClient, f: dict[str, str]) -> tuple[str, str]:
    resp = await http.get(f"https://api.telegram.org/bot{f['bot_token']}/getMe")
    body = resp.json() if resp.content else {}
    if not body.get("ok"):
        raise ValueError("Telegram didn't accept that bot token. Copy it again from @BotFather.")
    bot = body["result"]
    return str(bot["id"]), f"@{bot.get('username', 'bot')}"


async def _whatsapp(http: httpx.AsyncClient, f: dict[str, str]) -> tuple[str, str]:
    resp = await http.get(
        f"{GRAPH}/{f['phone_number_id']}",
        params={"fields": "display_phone_number,verified_name"},
        headers={"Authorization": f"Bearer {f['access_token']}"},
    )
    if resp.status_code >= 400:
        raise ValueError(
            "WhatsApp didn't accept that token and phone number ID. Check both in Meta's "
            "WhatsApp → API setup page."
        )
    body = resp.json()
    name = body.get("verified_name") or "WhatsApp"
    return f["phone_number_id"], f"{name} ({body.get('display_phone_number', '')})".strip()


async def _github(http: httpx.AsyncClient, f: dict[str, str]) -> tuple[str, str]:
    resp = await http.get(
        "https://api.github.com/user",
        headers={"Authorization": f"Bearer {f['token']}", **GITHUB_HEADERS},
    )
    if resp.status_code >= 400:
        raise ValueError("GitHub didn't accept that token. Create a new fine-grained token.")
    user = resp.json()
    return str(user["id"]), f"@{user['login']}"


async def _vercel(http: httpx.AsyncClient, f: dict[str, str]) -> tuple[str, str]:
    resp = await http.get(
        "https://api.vercel.com/v2/user", headers={"Authorization": f"Bearer {f['token']}"}
    )
    if resp.status_code >= 400:
        raise ValueError("Vercel didn't accept that token. Create a new one in Account settings.")
    user = resp.json().get("user", {})
    return str(user.get("id", "")), user.get("username") or user.get("email") or "Vercel"


CHECKERS: dict[str, Checker] = {
    "telegram": _telegram,
    "whatsapp": _whatsapp,
    "github": _github,
    "vercel": _vercel,
}
