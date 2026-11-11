"""Approved emails really go out through the owner's Gmail, exactly as approved."""

import asyncio
import base64
import email
import json
import os
from urllib.parse import parse_qs

import httpx
import psycopg
from psycopg.rows import dict_row
from test_approvals import _decide, _prepared_email_task, _summary
from test_pipeline import (
    FakeLLM,
    new_task,
    plan,
    run,
    step_result,
    text_resp,
    tool_resp,
    tool_turns,
)
from test_pipeline import verdict as ok_verdict
from workforce_core.google import GoogleConfig, GoogleOAuth
from workforce_core.secrets import SecretBox, secret_context, store_secret
from workforce_worker.executor import Integrations
from workforce_worker.pipeline import advance

KEY = base64.b64encode(os.urandom(32)).decode()


class FakeGoogle:
    def __init__(self, refresh="ok", send="ok"):
        self.refresh, self.send = refresh, send
        self.sent: list[email.message.Message] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/token":
            form = parse_qs(req.content.decode())
            assert form["grant_type"] == ["refresh_token"] and form["refresh_token"] == ["rt-1"]
            if self.refresh == "revoked":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "fresh-at", "expires_in": 3599})
        if req.url.path.endswith("/messages/send"):
            assert req.headers["authorization"] == "Bearer fresh-at"
            if self.send == "error":
                return httpx.Response(400, json={"error": {"message": "Invalid To header"}})
            raw = json.loads(req.content)["raw"]
            self.sent.append(email.message_from_bytes(base64.urlsafe_b64decode(raw)))
            return httpx.Response(200, json={"id": "18cabc", "threadId": "18cabc"})
        return httpx.Response(404)


def _integrations(google: FakeGoogle) -> Integrations:
    http = httpx.AsyncClient(transport=httpx.MockTransport(google))
    return Integrations(
        box=SecretBox(KEY), google=GoogleOAuth(GoogleConfig("cid", "cs", "https://x/cb"), http)
    )


def _connect_gmail(database_url, ws_id):
    async def go():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as c:
            sid = await store_secret(
                c,
                SecretBox(KEY),
                workspace_id=ws_id,
                provider="gmail",
                data={
                    "refresh_token": "rt-1",
                    "access_token": "stale",
                    "expires_at": 0,
                    "email": "asha@gmail.com",
                },
            )
            await c.execute(
                "insert into tool_connections (workspace_id, provider, account_ref, scopes,"
                " secret_ref, display_name) values (%s, 'gmail', 'sub-1', %s, %s,"
                " 'asha@gmail.com')",
                (ws_id, ["https://www.googleapis.com/auth/gmail.send"], sid),
            )
            return sid

    return asyncio.run(go())


def _approve_and_run(database_url, db, task, integ):
    _decide(db, task, "approved")
    return run(
        database_url, lambda c: advance(c, FakeLLM(None, None, None), task, integrations=integ)
    )


def test_approved_email_is_sent_from_gmail(database_url, db, workspace):
    sid = _connect_gmail(database_url, workspace.id)
    task = _prepared_email_task(database_url, db, workspace)
    google = FakeGoogle()
    assert _approve_and_run(database_url, db, task, _integrations(google)) == "completed"

    assert len(google.sent) == 1
    msg = google.sent[0]
    assert msg["To"] == "rahul@example.com" and msg["Subject"] == "Moved"
    assert msg["From"] == "asha@gmail.com" and "Friday 4pm" in msg.get_payload()
    assert "Sent from asha@gmail.com to rahul@example.com" in _summary(db, task)[1]

    # The refreshed access token was saved back, still encrypted.
    blob = db.execute("select ciphertext from connection_secrets where id = %s", (sid,)).fetchone()[
        0
    ]
    saved = SecretBox(KEY).decrypt(blob, secret_context(workspace.id, "gmail"))
    assert saved["access_token"] == "fresh-at" and saved["refresh_token"] == "rt-1"
    assert db.execute(
        "select last_used_at is not null from tool_connections where secret_ref = %s", (sid,)
    ).fetchone()[0]

    # Running the finished task again never sends a second email.
    run(
        database_url,
        lambda c: advance(c, FakeLLM(None, None, None), task, integrations=_integrations(google)),
    )
    assert len(google.sent) == 1


def test_revoked_access_marks_connection_expired(database_url, db, workspace):
    _connect_gmail(database_url, workspace.id)
    task = _prepared_email_task(database_url, db, workspace)
    google = FakeGoogle(refresh="revoked")
    assert _approve_and_run(database_url, db, task, _integrations(google)) == "failed"
    assert "Reconnect Gmail" in _summary(db, task)[1] and google.sent == []
    assert (
        db.execute(
            "select connection_status from tool_connections where workspace_id = %s",
            (workspace.id,),
        ).fetchone()[0]
        == "expired"
    )


def test_gmail_error_is_reported(database_url, db, workspace):
    _connect_gmail(database_url, workspace.id)
    task = _prepared_email_task(database_url, db, workspace)
    assert (
        _approve_and_run(database_url, db, task, _integrations(FakeGoogle(send="error")))
        == "failed"
    )
    assert "Gmail refused to send: Invalid To header" in _summary(db, task)[1]


def test_without_a_connection_nothing_is_sent(database_url, db, workspace):
    task = _prepared_email_task(database_url, db, workspace)
    google = FakeGoogle()
    assert _approve_and_run(database_url, db, task, _integrations(google)) == "failed"
    assert "Gmail isn't connected yet" in _summary(db, task)[1] and google.sent == []


def test_draft_email_is_saved_as_a_file(database_url, db, workspace):
    task = new_task(db, workspace, "Draft a thank-you email to Rahul")

    def step(p, n):
        if tool_turns(p) == 0:
            return tool_resp(
                (
                    "draft_email",
                    {
                        "to": "rahul@example.com",
                        "subject": "Thanks",
                        "body": "Thanks for the review!",
                    },
                )
            )
        return text_resp(step_result("drafted"))

    llm = FakeLLM(
        lambda p, n: text_resp(plan(agent="pe_email")), step, lambda p, n: text_resp(ok_verdict())
    )
    assert run(database_url, lambda c: advance(c, llm, task)) == "completed"
    body = db.execute(
        "select convert_from(content, 'UTF8') from artifacts where task_id = %s", (task,)
    ).fetchone()[0]
    assert "**To:** rahul@example.com" in body and "Thanks for the review!" in body
    assert (
        db.execute("select count(*) from approval_requests where task_id = %s", (task,)).fetchone()[
            0
        ]
        == 0
    )  # a draft never needs approval
