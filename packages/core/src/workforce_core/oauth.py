"""Generic OAuth 2.0 for connectors (Google, Slack, ...), with per-provider adapters.

The platform owner registers one app per provider and sets <PREFIX>_CLIENT_ID /
<PREFIX>_CLIENT_SECRET. People then connect their own accounts by signing in on
the provider's page. Tokens are returned to the caller to be encrypted.
"""

import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .connectors import Connector
from .google import USERINFO_URL, GoogleError, new_pkce

__all__ = ["OAuthApp", "OAuthError", "TokenSet", "new_pkce"]


class OAuthError(GoogleError):
    pass


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_at: int | None
    scopes: set[str]
    account_id: str
    display_name: str

    def secret(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at or 0,
            "email": self.display_name,
        }


@dataclass
class OAuthApp:
    connector: Connector
    client_id: str
    client_secret: str
    redirect_uri: str
    http: httpx.AsyncClient

    @classmethod
    def from_env(
        cls, connector: Connector, redirect_uri: str, http: httpx.AsyncClient
    ) -> "OAuthApp | None":
        spec = connector.oauth
        if spec is None:
            return None
        cid = os.environ.get(f"{spec.client_env}_CLIENT_ID")
        secret = os.environ.get(f"{spec.client_env}_CLIENT_SECRET")
        if not (cid and secret):
            return None
        return cls(connector, cid, secret, redirect_uri, http)

    def auth_url(self, *, state: str, code_challenge: str | None) -> str:
        spec = self.connector.oauth
        assert spec is not None
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            spec.scope_param: spec.scope_separator.join(spec.scopes),
            "state": state,
            **dict(spec.extra_params),
        }
        if spec.pkce and code_challenge:
            params |= {"code_challenge": code_challenge, "code_challenge_method": "S256"}
        return f"{spec.authorize_url}?{urlencode(params)}"

    async def exchange(self, code: str, code_verifier: str | None) -> TokenSet:
        spec = self.connector.oauth
        assert spec is not None
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        }
        if spec.pkce and code_verifier:
            data["code_verifier"] = code_verifier
        resp = await self.http.post(spec.token_url, data=data)
        try:
            body = resp.json()
        except ValueError as exc:
            raise OAuthError(f"unexpected reply from {self.connector.name}") from exc
        if resp.status_code >= 400 or body.get("ok") is False or "error" in body:
            raise OAuthError(str(body.get("error_description") or body.get("error") or resp.text))
        return await IDENTITY[spec.client_env](self, body)

    async def revoke(self, token: str) -> None:
        spec = self.connector.oauth
        if spec and spec.client_env == "GOOGLE":
            await self.http.post("https://oauth2.googleapis.com/revoke", data={"token": token})
        elif spec and spec.client_env == "SLACK":
            await self.http.post(
                "https://slack.com/api/auth.revoke", headers={"Authorization": f"Bearer {token}"}
            )


def _expires(body: dict) -> int | None:
    return int(time.time()) + int(body["expires_in"]) - 60 if body.get("expires_in") else None


async def _google_identity(app: OAuthApp, body: dict) -> TokenSet:
    info = await app.http.get(
        USERINFO_URL, headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    if info.status_code >= 400:
        raise OAuthError("could not read the Google account's email")
    who = info.json()
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_at=_expires(body),
        scopes=set(body.get("scope", "").split()),
        account_id=who.get("sub") or who.get("email", ""),
        display_name=who.get("email", ""),
    )


async def _slack_identity(app: OAuthApp, body: dict) -> TokenSet:
    team = body.get("team") or {}
    return TokenSet(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),  # only with token rotation enabled
        expires_at=_expires(body),
        scopes=set(body.get("scope", "").split(",")),
        account_id=team.get("id", ""),
        display_name=f"{team.get('name', 'Slack')} (Slack)",
    )


IDENTITY = {"GOOGLE": _google_identity, "SLACK": _slack_identity}
