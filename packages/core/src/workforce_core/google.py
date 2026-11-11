"""Google OAuth (web-server flow with PKCE) and Gmail sending.

We ask for the least access that works: ``gmail.send`` (send only; it can't
read, delete or search your mail) plus ``openid email`` to show which account
is connected.
"""

import base64
import hashlib
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, getaddresses
from typing import Any
from urllib.parse import urlencode

import httpx

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SCOPES = ("openid", "email", GMAIL_SEND_SCOPE)


class GoogleError(Exception):
    pass


class GrantRevoked(GoogleError):
    """The refresh token no longer works; the owner must reconnect."""


def new_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(os.urandom(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge.rstrip(b"=").decode()


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    redirect_uri: str


class GoogleOAuth:
    def __init__(self, config: GoogleConfig, http: httpx.AsyncClient | None = None):
        self.config = config
        self.http = http or httpx.AsyncClient(timeout=20)

    def auth_url(self, *, state: str, code_challenge: str, scopes=GMAIL_SCOPES) -> str:
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "access_type": "offline",  # we need a refresh token for the background worker
            "prompt": "consent",  # always return a refresh token, even on reconnect
            "include_granted_scopes": "true",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _token_request(self, data: dict[str, str]) -> dict[str, Any]:
        resp = await self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                **data,
            },
        )
        body = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            if body.get("error") == "invalid_grant":
                raise GrantRevoked(body.get("error_description") or "access was revoked")
            raise GoogleError(body.get("error_description") or body.get("error") or resp.text)
        body["expires_at"] = int(time.time()) + int(body.get("expires_in", 3600)) - 60
        return body

    async def exchange_code(self, code: str, code_verifier: str) -> dict[str, Any]:
        return await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "code_verifier": code_verifier,
                "redirect_uri": self.config.redirect_uri,
            }
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._token_request(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )

    async def revoke(self, token: str) -> None:
        await self.http.post(REVOKE_URL, data={"token": token})

    async def userinfo(self, access_token: str) -> dict[str, Any]:
        resp = await self.http.get(
            USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
        )
        if resp.status_code >= 400:
            raise GoogleError("could not read the Google account's email")
        return resp.json()


async def fresh_access_token(oauth: GoogleOAuth, secret: dict[str, Any]) -> tuple[str, bool]:
    """Return (access_token, refreshed). Refreshes when expired or about to expire."""
    if secret.get("access_token") and secret.get("expires_at", 0) > time.time() + 30:
        return secret["access_token"], False
    if not secret.get("refresh_token"):
        raise GrantRevoked("no refresh token stored; reconnect Gmail")
    tokens = await oauth.refresh(secret["refresh_token"])
    secret["access_token"] = tokens["access_token"]
    secret["expires_at"] = tokens["expires_at"]
    if tokens.get("refresh_token"):  # Google may rotate it
        secret["refresh_token"] = tokens["refresh_token"]
    return secret["access_token"], True


# --- email -----------------------------------------------------------------------


def _clean_header(name: str, value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError(f"{name} must be a single line")
    return value.strip()


def _addresses(value: str, field: str) -> list[str]:
    value = _clean_header(field, value)
    found = [addr for _, addr in getaddresses([value]) if addr]
    if not found or any("@" not in a or a.startswith("@") or a.endswith("@") for a in found):
        raise ValueError(f"{field} has an invalid email address: {value!r}")
    if len(found) > 50:
        raise ValueError(f"too many recipients in {field}")
    return found


def build_email(
    *,
    sender: str,
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    sender_name: str | None = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((sender_name or "", sender)) if sender_name else sender
    msg["To"] = ", ".join(_addresses(to, "To"))
    if cc:
        msg["Cc"] = ", ".join(_addresses(cc, "Cc"))
    msg["Subject"] = _clean_header("Subject", subject or "(no subject)")
    msg.set_content(body or "")
    return msg


async def gmail_send(http: httpx.AsyncClient, access_token: str, msg: EmailMessage) -> dict:
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    resp = await http.post(
        GMAIL_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
    )
    if resp.status_code == 401:
        raise GrantRevoked("Gmail rejected the access token")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        raise GoogleError(f"Gmail refused to send: {detail}")
    return resp.json()


# --- calendar --------------------------------------------------------------------

# Narrowest scopes Google offers for this: create events only on calendars you own,
# and see free/busy only (not meeting details).
CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar.events.owned"
CALENDAR_FREEBUSY_SCOPE = "https://www.googleapis.com/auth/calendar.freebusy"
CALENDAR_SCOPES = ("openid", "email", CALENDAR_EVENTS_SCOPE, CALENDAR_FREEBUSY_SCOPE)
CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class EventExists(GoogleError):
    """Google reported this event id already exists (treated as already created).

    Our own at-most-once approval handling is the real guarantee; a fixed event id is
    a second safeguard Google may or may not detect.
    """


def _parse_time(value: str, tz: str) -> datetime:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        zone = ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown time zone {tz!r}") from exc
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{value!r} is not a date and time like 2026-11-15T16:00") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=zone)


def event_id_for(key: str) -> str:
    """Deterministic event id (lowercase hex is valid base32hex) so a retry can't duplicate."""
    return "wf" + hashlib.sha256(key.encode()).hexdigest()[:40]


def build_event(
    *,
    title: str,
    start: str,
    end: str | None = None,
    timezone: str = "Asia/Kolkata",
    duration_minutes: int | None = None,
    attendees: str | list[str] | None = None,
    location: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    if not title or not title.strip():
        raise ValueError("the event needs a title")
    begin = _parse_time(start, timezone)
    if end:
        finish = _parse_time(end, timezone)
    else:
        finish = begin + timedelta(minutes=duration_minutes or 30)
    if finish <= begin:
        raise ValueError("the event must end after it starts")
    if finish - begin > timedelta(days=14):
        raise ValueError("the event is longer than 14 days")
    if isinstance(attendees, str):
        attendees = [a for a in attendees.replace(";", ",").split(",") if a.strip()]
    people = []
    for a in attendees or []:
        people.extend(_addresses(a, "Attendees"))
    body: dict[str, Any] = {
        "summary": _clean_header("Title", title),
        "start": {"dateTime": begin.isoformat(), "timeZone": timezone},
        "end": {"dateTime": finish.isoformat(), "timeZone": timezone},
    }
    if people:
        body["attendees"] = [{"email": p} for p in dict.fromkeys(people)]
    if location:
        body["location"] = location.strip()
    if description:
        body["description"] = description
    return body


async def calendar_insert(
    http: httpx.AsyncClient,
    access_token: str,
    event: dict[str, Any],
    *,
    event_id: str,
) -> dict[str, Any]:
    """Create the event. Attendees (if any) get Google's invitation email, which the
    owner saw on the approval card; Google advises against suppressing it."""
    resp = await http.post(
        f"{CALENDAR_API}/calendars/primary/events",
        params={"sendUpdates": "all"} if event.get("attendees") else {},
        headers={"Authorization": f"Bearer {access_token}"},
        json={**event, "id": event_id},
    )
    if resp.status_code == 401:
        raise GrantRevoked("Google Calendar rejected the access token")
    if resp.status_code == 409:
        raise EventExists("this event was already created")
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            detail = resp.text
        raise GoogleError(f"Google Calendar refused: {detail}")
    return resp.json()


async def calendar_busy(
    http: httpx.AsyncClient, access_token: str, *, time_min: str, time_max: str, timezone: str
) -> list[dict[str, str]]:
    begin, finish = _parse_time(time_min, timezone), _parse_time(time_max, timezone)
    if finish <= begin:
        raise ValueError("time_max must be after time_min")
    if finish - begin > timedelta(days=62):
        raise ValueError("check at most about two months at a time")
    resp = await http.post(
        f"{CALENDAR_API}/freeBusy",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "timeMin": begin.isoformat(),
            "timeMax": finish.isoformat(),
            "timeZone": timezone,
            "items": [{"id": "primary"}],
        },
    )
    if resp.status_code == 401:
        raise GrantRevoked("Google Calendar rejected the access token")
    if resp.status_code >= 400:
        raise GoogleError(f"Google Calendar refused: {resp.text[:200]}")
    cal = resp.json().get("calendars", {}).get("primary", {})
    if cal.get("errors"):
        raise GoogleError(f"Google Calendar couldn't read availability: {cal['errors']}")
    return cal.get("busy", [])


# --- which Google services can be connected ----------------------------------------


@dataclass(frozen=True)
class GoogleService:
    key: str  # tool_connections.provider
    name: str
    scopes: tuple[str, ...]
    required_scope: str  # refuse the connection if this one wasn't granted
    description: str


GOOGLE_SERVICES: dict[str, GoogleService] = {
    "gmail": GoogleService(
        "gmail",
        "Gmail",
        GMAIL_SCOPES,
        GMAIL_SEND_SCOPE,
        "Lets agents send emails you approve. Send only: it can't read or delete your mail.",
    ),
    "google_calendar": GoogleService(
        "google_calendar",
        "Google Calendar",
        CALENDAR_SCOPES,
        CALENDAR_EVENTS_SCOPE,
        "Lets agents see when you're busy (not what your meetings are) and add events you approve.",
    ),
}
