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
