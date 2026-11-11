"""Approved actions on WhatsApp, Telegram, Slack, GitHub and Vercel, against fake providers."""

import asyncio
import base64
import json
import os

import httpx
import psycopg
import pytest
from psycopg.rows import dict_row
from test_pipeline import new_task
from workforce_core.secrets import SecretBox, store_secret
from workforce_worker.executor import ActionFailed, Integrations, NotConnected, execute_action

KEY = base64.b64encode(os.urandom(32)).decode()


class Fake:
    """Records every request and answers with the handler for its host."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        return self.handler(req)


def _integ(fake) -> Integrations:
    return Integrations(
        box=SecretBox(KEY), http=httpx.AsyncClient(transport=httpx.MockTransport(fake))
    )


async def _connect(c, ws_id, provider, secret, display):
    sid = await store_secret(c, SecretBox(KEY), workspace_id=ws_id, provider=provider, data=secret)
    await c.execute(
        "insert into tool_connections (workspace_id, provider, account_ref, scopes, secret_ref,"
        " display_name) values (%s, %s, %s, '{}', %s, %s)",
        (ws_id, provider, display, sid, display),
    )


def _act(database_url, ws_id, provider, secret, action, args, fake, task_id="", files=None):
    async def go():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as c:
            if secret is not None:
                await _connect(c, ws_id, provider, secret, "Asha's account")
            for name, content in (files or {}).items():
                await c.execute(
                    "insert into artifacts (workspace_id, task_id, name, storage_uri, file_type,"
                    " checksum_sha256, size_bytes, content) values (%s, %s, %s, 'inline',"
                    " 'text/plain', 'x', %s, %s)",
                    (ws_id, task_id, name, len(content), content.encode()),
                )
            return await execute_action(
                action,
                args,
                None,
                conn=c,
                workspace_id=ws_id,
                integrations=_integ(fake),
                key="appr-1",
                task_id=task_id,
            )

    return asyncio.run(go())


def _status(db, ws_id, provider):
    return db.execute(
        "select connection_status, last_error from tool_connections"
        " where workspace_id = %s and provider = %s",
        (ws_id, provider),
    ).fetchone()


# --- WhatsApp --------------------------------------------------------------------------

WA = {"access_token": "wa-token", "phone_number_id": "1055"}


def test_whatsapp_message_is_sent(database_url, workspace):
    fake = Fake(lambda r: httpx.Response(200, json={"messages": [{"id": "wamid.1"}]}))
    text = _act(
        database_url,
        workspace.id,
        "whatsapp",
        WA,
        "send_whatsapp",
        {"to": "+91 98765-43210", "message": "Running 10 min late"},
        fake,
    )
    assert "to +919876543210" in text and "wamid.1" in text
    req = fake.requests[0]
    assert req.url.path.endswith("/1055/messages")
    assert req.headers["authorization"] == "Bearer wa-token"
    body = json.loads(req.content)
    assert body["to"] == "919876543210" and body["text"] == {"body": "Running 10 min late"}


def test_whatsapp_24_hour_rule_is_explained(database_url, db, workspace):
    fake = Fake(
        lambda r: httpx.Response(400, json={"error": {"code": 131047, "message": "Re-engage"}})
    )
    with pytest.raises(ActionFailed, match="last 24 hours"):
        _act(
            database_url,
            workspace.id,
            "whatsapp",
            WA,
            "send_whatsapp",
            {"to": "919876543210", "message": "hi"},
            fake,
        )
    assert _status(db, workspace.id, "whatsapp")[0] == "active"


def test_whatsapp_expired_token_needs_reconnect(database_url, db, workspace):
    fake = Fake(lambda r: httpx.Response(401, json={"error": {"code": 190, "message": "expired"}}))
    with pytest.raises(NotConnected) as exc:
        _act(
            database_url,
            workspace.id,
            "whatsapp",
            WA,
            "send_whatsapp",
            {"to": "919876543210", "message": "hi"},
            fake,
        )
    assert exc.value.fixable and exc.value.connector == "whatsapp"
    assert _status(db, workspace.id, "whatsapp")[0] == "expired"


def test_not_connected_is_fixable(database_url, workspace):
    fake = Fake(lambda r: httpx.Response(500))
    with pytest.raises(NotConnected) as exc:
        _act(
            database_url,
            workspace.id,
            "whatsapp",
            None,
            "send_whatsapp",
            {"to": "919876543210", "message": "hi"},
            fake,
        )
    assert exc.value.fixable and "Connect WhatsApp" in str(exc.value)
    assert fake.requests == []


# --- Telegram & Slack --------------------------------------------------------------------


def test_telegram_message_and_friendly_errors(database_url, workspace):
    fake = Fake(lambda r: httpx.Response(200, json={"ok": True, "result": {"message_id": 7}}))
    text = _act(
        database_url,
        workspace.id,
        "telegram",
        {"bot_token": "123:abc"},
        "send_telegram",
        {"chat": "@asha", "message": "Done!"},
        fake,
    )
    assert text.startswith("Sent on Telegram")
    assert fake.requests[0].url.path == "/bot123:abc/sendMessage"
    assert json.loads(fake.requests[0].content) == {"chat_id": "@asha", "text": "Done!"}

    fail = Fake(
        lambda r: httpx.Response(
            400, json={"ok": False, "description": "Bad Request: chat not found"}
        )
    )
    with pytest.raises(ActionFailed, match="hasn't started a chat with your bot"):
        _act(
            database_url,
            workspace.id,
            "telegram",
            None,
            "send_telegram",
            {"chat": "@rahul", "message": "hi"},
            fail,
        )


def test_slack_post_and_errors(database_url, db, workspace):
    fake = Fake(lambda r: httpx.Response(200, json={"ok": True, "ts": "1.2"}))
    text = _act(
        database_url,
        workspace.id,
        "slack",
        {"access_token": "xoxb-1"},
        "post_slack",
        {"channel": "#general", "message": "Standup moved to 11"},
        fake,
    )
    assert text == "Posted to #general in Asha's account."
    req = fake.requests[0]
    assert req.headers["authorization"] == "Bearer xoxb-1"
    assert json.loads(req.content) == {"channel": "general", "text": "Standup moved to 11"}

    not_in = Fake(lambda r: httpx.Response(200, json={"ok": False, "error": "not_in_channel"}))
    with pytest.raises(ActionFailed, match="add it there first"):
        _act(
            database_url,
            workspace.id,
            "slack",
            None,
            "post_slack",
            {"channel": "C1", "message": "x"},
            not_in,
        )

    revoked = Fake(lambda r: httpx.Response(200, json={"ok": False, "error": "token_revoked"}))
    with pytest.raises(NotConnected):
        _act(
            database_url,
            workspace.id,
            "slack",
            None,
            "post_slack",
            {"channel": "C1", "message": "x"},
            revoked,
        )
    assert _status(db, workspace.id, "slack")[0] == "expired"


# --- GitHub & Vercel ---------------------------------------------------------------------


class FakeGitHub:
    def __init__(self, repo_exists=False):
        self.repo_exists = repo_exists
        self.created: list[dict] = []
        self.files: dict[str, dict] = {"README.md": {"sha": "old-sha"}}
        self.puts: list[tuple[str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        assert req.headers["authorization"] == "Bearer ghp_x"
        assert req.headers["x-github-api-version"]
        path = req.url.path
        if path == "/user":
            return httpx.Response(200, json={"login": "asha"})
        if path == "/repos/asha/cafe-site" and req.method == "GET":
            return httpx.Response(200 if self.repo_exists or self.created else 404, json={})
        if path == "/user/repos":
            self.created.append(json.loads(req.content))
            return httpx.Response(201, json={"full_name": "asha/cafe-site"})
        if path.startswith("/repos/asha/cafe-site/contents/"):
            name = path.rsplit("/", 1)[-1]
            if req.method == "GET":
                f = self.files.get(name)
                return httpx.Response(200, json=f) if f else httpx.Response(404, json={})
            body = json.loads(req.content)
            self.puts.append((name, body))
            return httpx.Response(201, json={"content": {"sha": "new"}})
        return httpx.Response(404, json={"message": "Not Found"})


SITE = {"index.html": "<h1>Cafe</h1>", "README.md": "# Cafe"}


def test_github_creates_repo_and_saves_files(database_url, db, workspace):
    task = new_task(db, workspace, "Make a cafe website")
    gh = FakeGitHub()
    text = _act(
        database_url,
        workspace.id,
        "github",
        {"token": "ghp_x"},
        "github_save_files",
        {"repo": "cafe-site", "files": ["index.html", "README.md"], "message": "First version"},
        Fake(gh),
        task_id=task,
        files=SITE,
    )
    assert text == "Saved 2 file(s) to https://github.com/asha/cafe-site."
    assert gh.created == [{"name": "cafe-site", "private": True, "auto_init": True}]
    puts = dict(gh.puts)
    assert base64.b64decode(puts["index.html"]["content"]).decode() == "<h1>Cafe</h1>"
    assert "sha" not in puts["index.html"]  # new file
    assert puts["README.md"]["sha"] == "old-sha"  # update needs the current sha
    assert puts["README.md"]["message"] == "First version"


def test_github_only_uses_files_from_this_task(database_url, db, workspace):
    task = new_task(db, workspace, "Make a cafe website")
    with pytest.raises(ValueError, match="weren't made in this task: secrets.txt"):
        _act(
            database_url,
            workspace.id,
            "github",
            {"token": "ghp_x"},
            "github_save_files",
            {"repo": "cafe-site", "files": ["secrets.txt"]},
            Fake(FakeGitHub()),
            task_id=task,
        )


def test_vercel_deploys_the_task_files(database_url, db, workspace):
    task = new_task(db, workspace, "Make a cafe website")
    fake = Fake(
        lambda r: httpx.Response(
            200, json={"id": "dpl_1", "url": "cafe-abc.vercel.app", "alias": ["cafe.vercel.app"]}
        )
    )
    text = _act(
        database_url,
        workspace.id,
        "vercel",
        {"token": "vc_x"},
        "deploy_web",
        {"project": "Cafe Site!", "files": ["index.html"]},
        fake,
        task_id=task,
        files=SITE,
    )
    assert "https://cafe.vercel.app" in text
    req = fake.requests[0]
    assert req.url.path == "/v13/deployments" and req.headers["authorization"] == "Bearer vc_x"
    body = json.loads(req.content)
    assert body["name"] == "cafesite" and body["target"] == "production"
    assert body["files"] == [
        {
            "file": "index.html",
            "data": base64.b64encode(b"<h1>Cafe</h1>").decode(),
            "encoding": "base64",
        }
    ]


def test_vercel_needs_an_index_page(database_url, db, workspace):
    task = new_task(db, workspace, "Make a cafe website")
    with pytest.raises(ValueError, match="index.html"):
        _act(
            database_url,
            workspace.id,
            "vercel",
            {"token": "vc_x"},
            "deploy_web",
            {"project": "cafe", "files": ["README.md"]},
            Fake(lambda r: httpx.Response(500)),
            task_id=task,
            files=SITE,
        )


def test_without_encryption_key_it_is_not_fixable(database_url, workspace):
    async def go():
        async with await psycopg.AsyncConnection.connect(
            database_url, autocommit=True, row_factory=dict_row
        ) as c:
            return await execute_action(
                "send_telegram",
                {"chat": "@a", "message": "hi"},
                None,
                conn=c,
                workspace_id=workspace.id,
                integrations=Integrations(),
            )

    with pytest.raises(NotConnected) as exc:
        asyncio.run(go())
    assert not exc.value.fixable and "set up on the server" in str(exc.value)
