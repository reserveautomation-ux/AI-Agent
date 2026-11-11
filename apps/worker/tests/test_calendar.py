"""Agents check free/busy, prepare events, and approved events land on the calendar once."""

import asyncio
import base64
import json
import os

import httpx
import psycopg
from psycopg.rows import dict_row
from test_approvals import _decide, _summary
from test_pipeline import (
    FakeLLM,
    new_task,
    plan,
    run,
    step_result,
    text_resp,
    tool_resp,
    tool_turns,
    verdict,
)
from workforce_core.google import GoogleConfig, GoogleOAuth, event_id_for
from workforce_core.secrets import SecretBox, store_secret
from workforce_worker.executor import Integrations
from workforce_worker.pipeline import advance

KEY = base64.b64encode(os.urandom(32)).decode()
EVENT = {
    "title": "Design review",
    "start": "2026-11-20T16:00",
    "duration_minutes": 30,
    "attendees": "rahul@example.com",
    "location": "Zoom",
}


class FakeCalendar:
    def __init__(self, duplicate=False):
        self.created: list[tuple[dict, dict]] = []
        self.duplicate = duplicate

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/token":
            return httpx.Response(200, json={"access_token": "cal-at", "expires_in": 3599})
        assert req.headers["authorization"] == "Bearer cal-at"
        if req.url.path.endswith("/freeBusy"):
            return httpx.Response(
                200,
                json={
                    "calendars": {
                        "primary": {
                            "busy": [
                                {"start": "2026-11-20T04:30:00Z", "end": "2026-11-20T06:30:00Z"}
                            ]
                        }
                    }
                },
            )
        if req.url.path.endswith("/calendars/primary/events"):
            if self.duplicate:
                return httpx.Response(409, json={"error": {"message": "already exists"}})
            body = json.loads(req.content)
            self.created.append((body, dict(req.url.params)))
            return httpx.Response(200, json={"id": body["id"], "htmlLink": "https://calendar/e1"})
        return httpx.Response(404)


def _integ(fake):
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    return Integrations(SecretBox(KEY), GoogleOAuth(GoogleConfig("c", "s", "https://x/cb"), http))


def _connect_calendar(database_url, ws_id):
    async def go():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as c:
            sid = await store_secret(
                c,
                SecretBox(KEY),
                workspace_id=ws_id,
                provider="google_calendar",
                data={"refresh_token": "rt", "expires_at": 0, "email": "asha@gmail.com"},
            )
            await c.execute(
                "insert into tool_connections (workspace_id, provider, account_ref, scopes,"
                " secret_ref, display_name) values (%s, 'google_calendar', 'sub-1', '{}', %s,"
                " 'asha@gmail.com')",
                (ws_id, sid),
            )

    asyncio.run(go())


def _scheduling_task(database_url, db, workspace, integ):
    task = new_task(db, workspace, "Set up a design review with Rahul on Friday afternoon")
    seen = {}

    def step(p, n):
        turns = tool_turns(p)
        if turns == 0:
            seen["context"] = p["messages"][0]["content"]
            return tool_resp(
                (
                    "calendar_check_availability",
                    {"time_min": "2026-11-20T09:00", "time_max": "2026-11-20T19:00"},
                )
            )
        if turns == 1:
            seen["availability"] = str(p["messages"][-1]["content"])
            return tool_resp(("calendar_create_event", EVENT))
        return text_resp(step_result("Prepared the meeting", approvals=["Design review"]))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(agent="pe_calendar", deliverable="prepared_action")),
        step,
        lambda p, n: text_resp(verdict()),
    )
    status = run(database_url, lambda c: advance(c, llm, task, integrations=integ))
    return task, status, seen


def test_check_availability_then_create_approved_event(database_url, db, workspace):
    _connect_calendar(database_url, workspace.id)
    fake = FakeCalendar()
    integ = _integ(fake)
    task, status, seen = _scheduling_task(database_url, db, workspace, integ)

    assert status == "waiting_for_approval" and fake.created == []  # nothing before approval
    assert "Now for the owner:" in seen["context"] and "Asia/Kolkata" in seen["context"]
    # 04:30–06:30 UTC is 10:00–12:00 in India.
    assert "busy Fri 20 Nov, 10:00–12:00" in seen["availability"]

    appr = db.execute(
        "select id::text, recipient, item from approval_requests where task_id = %s", (task,)
    ).fetchone()
    assert appr[1:] == ("rahul@example.com", "Design review")

    _decide(db, task, "approved")
    assert (
        run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task, integrations=integ))
        == "completed"
    )
    body, params = fake.created[0]
    assert body["summary"] == "Design review" and body["location"] == "Zoom"
    assert body["start"] == {"dateTime": "2026-11-20T16:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert body["end"]["dateTime"] == "2026-11-20T16:30:00+05:30"
    assert body["attendees"] == [{"email": "rahul@example.com"}]
    assert body["id"] == event_id_for(appr[0]) and params == {"sendUpdates": "all"}
    summary = _summary(db, task)[1]
    assert "Added 'Design review' on Fri 20 Nov, 16:00–16:30" in summary
    assert "invitations sent to rahul@example.com" in summary

    run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task, integrations=integ))
    assert len(fake.created) == 1  # never added twice


def test_event_already_on_calendar_is_not_an_error(database_url, db, workspace):
    _connect_calendar(database_url, workspace.id)
    integ = _integ(FakeCalendar())
    task, _, _ = _scheduling_task(database_url, db, workspace, integ)
    _decide(db, task, "approved")
    dup = _integ(FakeCalendar(duplicate=True))
    assert (
        run(database_url, lambda c: advance(c, FakeLLM(None, None, None), task, integrations=dup))
        == "completed"
    )
    assert "was already on your calendar" in _summary(db, task)[1]


def test_without_calendar_the_agent_is_told_honestly(database_url, db, workspace):
    task, status, seen = _scheduling_task(database_url, db, workspace, _integ(FakeCalendar()))
    assert "Google Calendar isn't connected yet" in seen["availability"]
    _decide(db, task, "approved")
    assert (
        run(
            database_url,
            lambda c: advance(
                c, FakeLLM(None, None, None), task, integrations=_integ(FakeCalendar())
            ),
        )
        == "failed"
    )
    assert "Connect Google Calendar in Settings" in _summary(db, task)[1]
