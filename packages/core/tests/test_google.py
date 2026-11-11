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


# --- calendar --------------------------------------------------------------------

from workforce_core.google import (  # noqa: E402
    CALENDAR_EVENTS_SCOPE,
    CALENDAR_SCOPES,
    EventExists,
    build_event,
    calendar_busy,
    calendar_insert,
    event_id_for,
)


def test_calendar_asks_for_the_narrowest_scopes():
    assert CALENDAR_EVENTS_SCOPE.endswith("calendar.events.owned")
    assert set(CALENDAR_SCOPES) == {
        "openid",
        "email",
        CALENDAR_EVENTS_SCOPE,
        "https://www.googleapis.com/auth/calendar.freebusy",
    }
    assert not any(s.endswith("/calendar") or "readonly" in s for s in CALENDAR_SCOPES)


def test_build_event_times_zones_and_attendees():
    ev = build_event(
        title="Design review",
        start="2026-11-20T16:00",
        duration_minutes=45,
        attendees="Rahul <rahul@example.com>; asha@x.in, rahul@example.com",
        location="Zoom",
        timezone="Asia/Kolkata",
    )
    assert ev["start"] == {"dateTime": "2026-11-20T16:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert ev["end"]["dateTime"] == "2026-11-20T16:45:00+05:30"
    assert ev["attendees"] == [{"email": "rahul@example.com"}, {"email": "asha@x.in"}]
    utc = build_event(title="x", start="2026-11-20T10:00Z", end="2026-11-20T11:00Z")
    assert utc["start"]["dateTime"] == "2026-11-20T10:00:00+00:00"
    for bad, msg in [
        (dict(title="x", start="2026-11-20T16:00", end="2026-11-20T15:00"), "end after"),
        (dict(title="x", start="next friday"), "not a date"),
        (dict(title="x", start="2026-11-20T16:00", timezone="Mars/Base"), "time zone"),
        (dict(title=" ", start="2026-11-20T16:00"), "title"),
        (dict(title="x", start="2026-11-20T16:00", attendees="not-an-email"), "invalid email"),
    ]:
        with pytest.raises(ValueError, match=msg):
            build_event(**bad)


def test_calendar_insert_and_busy():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if req.url.path.endswith("/events"):
            body = json.loads(req.content)
            if body["id"] == "dup":
                return httpx.Response(409, json={"error": {"message": "already exists"}})
            return httpx.Response(200, json={"id": body["id"], "htmlLink": "https://cal/e"})
        return httpx.Response(
            200,
            json={
                "calendars": {
                    "primary": {
                        "busy": [
                            {
                                "start": "2026-11-20T10:00:00+05:30",
                                "end": "2026-11-20T11:00:00+05:30",
                            }
                        ]
                    }
                }
            },
        )

    async def go():
        http = _google(handler)
        ev = build_event(title="Review", start="2026-11-20T16:00", attendees="r@example.com")
        eid = event_id_for("approval-1")
        assert eid == event_id_for("approval-1") and set(eid) <= set(
            "0123456789abcdefghijklmnopqrstuvw"
        )
        created = await calendar_insert(http, "at", ev, event_id=eid)
        assert created["htmlLink"] == "https://cal/e"
        assert calls[-1].url.params["sendUpdates"] == "all"  # attendees are invited
        solo = build_event(title="Focus time", start="2026-11-20T09:00")
        await calendar_insert(http, "at", solo, event_id=event_id_for("approval-2"))
        assert "sendUpdates" not in calls[-1].url.params
        with pytest.raises(EventExists):
            await calendar_insert(http, "at", solo, event_id="dup")
        busy = await calendar_busy(
            http,
            "at",
            time_min="2026-11-20T09:00",
            time_max="2026-11-20T18:00",
            timezone="Asia/Kolkata",
        )
        assert busy[0]["start"].startswith("2026-11-20T10:00")
        with pytest.raises(ValueError):
            await calendar_busy(
                http,
                "at",
                time_min="2026-11-20T18:00",
                time_max="2026-11-20T09:00",
                timezone="Asia/Kolkata",
            )

    asyncio.run(go())
