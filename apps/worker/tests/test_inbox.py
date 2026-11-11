"""Gmail inbox (search, read, drafts), Google Drive saving, and important-email alerts."""

import asyncio
import base64
import email
import json
import os

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row
from test_pipeline import new_task
from workforce_core.google import GoogleConfig, GoogleOAuth
from workforce_core.secrets import SecretBox, store_secret
from workforce_worker.executor import (
    Integrations,
    NotConnected,
    drive_save,
    inbox_draft,
    inbox_read,
    inbox_search,
)
from workforce_worker.inbox import check_inboxes

KEY = base64.b64encode(os.urandom(32)).decode()


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


MAILS = {
    "msg00001": {
        "id": "msg00001",
        "threadId": "thr001",
        "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
        "snippet": "Can we move the demo to 4pm?",
        "internalDate": "1763000000000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Rahul Mehta <rahul@example.com>"},
                {"name": "To", "value": "asha@gmail.com"},
                {"name": "Subject", "value": "Demo timing"},
                {"name": "Date", "value": "Wed, 12 Nov 2026 10:00:00 +0530"},
                {"name": "Message-ID", "value": "<abc@mail.example.com>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": b64("Hi Asha,\nCan we move the demo to 4pm?\nRahul")},
                },
                {"mimeType": "text/html", "body": {"data": b64("<p>ignored</p>")}},
            ],
        },
    },
    "msg00002": {
        "id": "msg00002",
        "threadId": "thr002",
        "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
        "snippet": "Invoice attached",
        "internalDate": "1763000500000",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "From", "value": "Accounts <billing@vendor.in>"},
                {"name": "Subject", "value": "Invoice #42"},
                {"name": "Date", "value": "Wed, 12 Nov 2026 10:05:00 +0530"},
            ],
            "body": {
                "data": b64(
                    "<html><style>x{}</style><p>Invoice <b>#42</b> attached.</p><br>Thanks</html>"
                )
            },
        },
    },
}


class FakeGoogle:
    def __init__(self):
        self.queries: list[str] = []
        self.drafts: list[dict] = []
        self.uploads: list[tuple[dict, str, bytes]] = []
        self.visible = ["msg00001", "msg00002"]

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/token":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
        assert req.headers["authorization"] == "Bearer at"
        path = req.url.path
        if path.endswith("/users/me/messages"):
            self.queries.append(req.url.params["q"])
            return httpx.Response(
                200,
                json={
                    "messages": [{"id": i, "threadId": MAILS[i]["threadId"]} for i in self.visible]
                },
            )
        if "/users/me/messages/" in path:
            mid = path.rsplit("/", 1)[-1]
            if mid not in MAILS:
                return httpx.Response(404, json={"error": {"message": "Not Found"}})
            return httpx.Response(200, json=MAILS[mid])
        if path.endswith("/users/me/drafts"):
            body = json.loads(req.content)
            self.drafts.append(body)
            return httpx.Response(200, json={"id": "r-123", "message": {"id": "m1"}})
        if path == "/upload/drive/v3/files":
            raw = req.content
            boundary = req.headers["content-type"].split("boundary=")[1]
            parts = raw.split(f"--{boundary}".encode())
            meta = json.loads(parts[1].split(b"\r\n\r\n", 1)[1].strip())
            head, media = parts[2].split(b"\r\n\r\n", 1)
            kind = head.decode().split("Content-Type: ")[1].strip()
            self.uploads.append((meta, kind, media.rstrip(b"\r\n")))
            return httpx.Response(
                200,
                json={
                    "id": "f1",
                    "name": meta["name"],
                    "webViewLink": "https://docs.google.com/d/f1",
                },
            )
        return httpx.Response(404)


def _integ(fake) -> Integrations:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    return Integrations(
        box=SecretBox(KEY), google=GoogleOAuth(GoogleConfig("c", "s", "https://x/cb"), http)
    )


async def _connect(c, ws, provider):
    sid = await store_secret(
        c,
        SecretBox(KEY),
        workspace_id=ws,
        provider=provider,
        data={"refresh_token": "rt", "expires_at": 0, "email": "asha@gmail.com"},
    )
    row = await (
        await c.execute(
            "insert into tool_connections (workspace_id, provider, account_ref, scopes,"
            " secret_ref, display_name)"
            " values (%s, %s, 'sub-1', '{}', %s, 'asha@gmail.com') returning id::text",
            (ws, provider, sid),
        )
    ).fetchone()
    return row["id"]


def run(database_url, fn):
    async def go():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as c:
            return await fn(c)

    return asyncio.run(go())


def test_search_and_read_mail(database_url, workspace):
    fake = FakeGoogle()

    async def go(c):
        await _connect(c, workspace.id, "gmail_inbox")
        found = await inbox_search(
            c, workspace.id, {"query": "is:unread newer_than:1d"}, _integ(fake)
        )
        first = await inbox_read(c, workspace.id, {"message_id": "msg00001"}, _integ(fake))
        html = await inbox_read(c, workspace.id, {"message_id": "msg00002"}, _integ(fake))
        return found, first, html

    found, first, html = run(database_url, go)
    assert fake.queries == ["is:unread newer_than:1d"]
    assert (
        "id msg00001" in found
        and "from Rahul Mehta <rahul@example.com> | Demo timing | UNREAD | IMPORTANT" in found
    )
    assert "Invoice #42" in found
    assert (
        "Subject: Demo timing" in first
        and "Can we move the demo to 4pm?" in first
        and "ignored" not in first
    )
    assert "Invoice #42 attached." in html.replace("  ", " ") and "x{}" not in html


def test_reply_draft_is_saved_in_the_same_thread_not_sent(database_url, workspace):
    fake = FakeGoogle()

    async def go(c):
        await _connect(c, workspace.id, "gmail_inbox")
        return await inbox_draft(
            c,
            workspace.id,
            {
                "to": "rahul@example.com",
                "subject": "Demo timing",
                "body": "4pm works.",
                "reply_to_id": "msg00001",
            },
            _integ(fake),
        )

    text = run(database_url, go)
    assert "not sent" in text and "Drafts" in text
    draft = fake.drafts[0]["message"]
    assert draft["threadId"] == "thr001"
    msg = email.message_from_bytes(base64.urlsafe_b64decode(draft["raw"]))
    assert msg["Subject"] == "Re: Demo timing" and msg["In-Reply-To"] == "<abc@mail.example.com>"
    assert msg["To"] == "rahul@example.com" and "4pm works." in msg.get_payload()


def test_save_files_to_drive_as_doc_and_sheet(database_url, db, workspace):
    fake = FakeGoogle()
    task = new_task(db, workspace, "Caterers list")

    async def go(c):
        await _connect(c, workspace.id, "google_drive")
        for name, content in (
            ("caterers.csv", "name,city\nA,Pune\n"),
            ("notes.md", "# Plan\n- **Call** A\n- Book B\n"),
        ):
            await c.execute(
                "insert into artifacts (workspace_id, task_id, name, storage_uri, file_type,"
                " checksum_sha256, size_bytes, content)"
                " values (%s, %s, %s, 'inline', 'text/plain', 'x', %s, %s)",
                (workspace.id, task, name, len(content), content.encode()),
            )
        sheet = await drive_save(
            c, workspace.id, {"files": ["caterers.csv"], "as": "sheet"}, _integ(fake), task
        )
        doc = await drive_save(
            c, workspace.id, {"files": ["notes.md"], "as": "doc"}, _integ(fake), task
        )
        return sheet, doc

    sheet, doc = run(database_url, go)
    assert "Saved to Google Drive" in sheet and "https://docs.google.com/d/f1" in doc
    (m1, k1, b1), (m2, k2, b2) = fake.uploads
    assert (
        m1 == {"name": "caterers", "mimeType": "application/vnd.google-apps.spreadsheet"}
        and k1 == "text/csv"
    )
    assert b1 == b"name,city\nA,Pune"
    assert m2["mimeType"] == "application/vnd.google-apps.document" and k2 == "text/html"
    assert b"<h1>Plan</h1>" in b2 and b"<li><b>Call</b> A</li>" in b2


def test_not_connected_is_fixable(database_url, workspace):
    async def go(c):
        await inbox_search(c, workspace.id, {"query": "x"}, _integ(FakeGoogle()))

    with pytest.raises(NotConnected) as exc:
        run(database_url, go)
    assert exc.value.fixable and exc.value.connector == "gmail_inbox"


class FakePusher:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, messages):
        self.sent.extend(messages)
        return [{"status": "ok"} for _ in messages]


def test_important_mail_alerts_once_and_only_new_mail(database_url, db, workspace):
    fake = FakeGoogle()
    pusher = FakePusher()
    db.execute(
        "insert into push_devices (workspace_id, user_id, token, platform)"
        " values (%s, %s, %s, 'ios')",
        (workspace.id, workspace.user, f"ExponentPushToken[{workspace.id[:8]}]"),
    )

    async def go(c):
        await _connect(c, workspace.id, "gmail_inbox")
        integ = _integ(fake)
        # First pass right after connecting: remembers "now", no alerts for the backlog.
        first = await check_inboxes(c, integ, pusher, now_ms=1763000200000)
        second = await check_inboxes(c, integ, pusher, now_ms=1763000600000)
        third = await check_inboxes(c, integ, pusher, now_ms=1763000900000)
        return first, second, third

    assert run(database_url, go) == (0, 1, 0)
    assert len(pusher.sent) == 1
    alert = pusher.sent[0]
    assert alert["title"] == "📧 Important: Accounts" and alert["body"].startswith(
        "Invoice #42 — Invoice attached"
    )
    assert alert["channelId"] == "mail"
    assert fake.queries[-1].startswith("is:important is:unread")
