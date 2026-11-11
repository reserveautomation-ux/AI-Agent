import asyncio
import base64
import email
import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from workforce_core.google import (
    GMAIL_SEND_SCOPE,
    GoogleConfig,
    GoogleOAuth,
    GrantRevoked,
    build_email,
    fresh_access_token,
    gmail_send,
    new_pkce,
)
from workforce_core.secrets import SecretBox, SecretError, secret_context

KEY = base64.b64encode(os.urandom(32)).decode()
CFG = GoogleConfig("cid.apps.googleusercontent.com", "csecret", "https://api.example.com/cb")


# --- secrets ---------------------------------------------------------------------


def test_secret_box_roundtrip_and_binding():
    box = SecretBox(KEY)
    ctx = secret_context("ws1", "gmail")
    blob = box.encrypt({"refresh_token": "1//super-secret"}, ctx)
    assert b"super-secret" not in blob
    assert box.decrypt(blob, ctx) == {"refresh_token": "1//super-secret"}
    with pytest.raises(SecretError):  # same row, other workspace
        box.decrypt(blob, secret_context("ws2", "gmail"))
    with pytest.raises(SecretError):  # other key
        SecretBox(base64.b64encode(os.urandom(32)).decode()).decrypt(blob, ctx)
    with pytest.raises(SecretError):
        SecretBox(base64.b64encode(b"short").decode())


# --- oauth -----------------------------------------------------------------------


def test_auth_url_asks_for_send_only_with_pkce_and_offline_access():
    verifier, challenge = new_pkce()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert challenge == expected.decode()
    url = GoogleOAuth(CFG).auth_url(state="st", code_challenge=challenge)
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert q["scope"].split() == ["openid", "email", GMAIL_SEND_SCOPE]
    assert "gmail.readonly" not in url and "mail.google.com" not in url
    assert q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["code_challenge_method"] == "S256" and q["state"] == "st"
    assert q["redirect_uri"] == CFG.redirect_uri


def _google(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_exchange_refresh_and_revoked_grant():
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        form = parse_qs(req.content.decode())
        seen.append(form)
        if form["grant_type"] == ["authorization_code"]:
            return httpx.Response(
                200,
                json={
                    "access_token": "at1",
                    "refresh_token": "rt1",
                    "expires_in": 3599,
                    "scope": GMAIL_SEND_SCOPE,
                },
            )
        if form["refresh_token"] == ["rt1"]:
            return httpx.Response(200, json={"access_token": "at2", "expires_in": 3599})
        return httpx.Response(
            400,
            json={
                "error": "invalid_grant",
                "error_description": "Token has been expired or revoked.",
            },
        )

    async def go():
        oauth = GoogleOAuth(CFG, _google(handler))
        tokens = await oauth.exchange_code("code123", "verifier")
        assert tokens["refresh_token"] == "rt1" and tokens["expires_at"] > time.time()
        secret = {"refresh_token": "rt1", "access_token": "old", "expires_at": 0}
        token, refreshed = await fresh_access_token(oauth, secret)
        assert (token, refreshed) == ("at2", True) and secret["access_token"] == "at2"
        token, refreshed = await fresh_access_token(oauth, secret)
        assert refreshed is False  # still valid, no new call
        with pytest.raises(GrantRevoked):
            await fresh_access_token(oauth, {"refresh_token": "dead", "expires_at": 0})

    asyncio.run(go())
    assert seen[0]["code_verifier"] == ["verifier"] and seen[0]["client_secret"] == ["csecret"]


# --- email -----------------------------------------------------------------------


def test_build_email_and_header_injection_guard():
    msg = build_email(
        sender="asha@gmail.com",
        to="Rahul <rahul@example.com>, b@x.in",
        subject="Review moved",
        body="Friday 4pm.\nThanks!",
    )
    assert msg["To"] == "rahul@example.com, b@x.in"
    assert msg.get_content().strip() == "Friday 4pm.\nThanks!"
    with pytest.raises(ValueError, match="single line"):
        build_email(sender="a@b.c", to="x@y.z", subject="Hi\r\nBcc: evil@x.com", body="")
    with pytest.raises(ValueError, match="invalid email"):
        build_email(sender="a@b.c", to="not-an-address", subject="Hi", body="")


def test_gmail_send_posts_raw_rfc822():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["auth"] = req.headers["authorization"]
        captured["raw"] = json.loads(req.content)["raw"]
        return httpx.Response(200, json={"id": "18c0ffee", "threadId": "18c0ffee"})

    msg = build_email(
        sender="asha@gmail.com", to="rahul@example.com", subject="Hi", body="Moved to Friday"
    )
    result = asyncio.run(gmail_send(_google(handler), "at1", msg))
    assert result["id"] == "18c0ffee" and captured["auth"] == "Bearer at1"
    parsed = email.message_from_bytes(base64.urlsafe_b64decode(captured["raw"]))
    assert parsed["To"] == "rahul@example.com" and "Moved to Friday" in parsed.get_payload()
