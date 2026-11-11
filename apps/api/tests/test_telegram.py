"""Chat with your assistant from Telegram through your own bot."""

import base64
import json
import os
from urllib.parse import urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import SECRET, SUPABASE_URL, auth
from test_chat import FakeChat, say
from workforce_api.config import Settings
from workforce_api.main import create_app

KEY = base64.b64encode(os.urandom(32)).decode()


class FakeTelegram:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        body = json.loads(req.content) if req.content else {}
        self.calls.append((method, body))
        if method == "getMe":
            return httpx.Response(
                200, json={"ok": True, "result": {"id": 77, "username": "asha_helper_bot"}}
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    def sent(self):
        return [b["text"] for m, b in self.calls if m == "sendMessage"]


@pytest.fixture
def tclient(database_url):
    fake = FakeTelegram()
    model = FakeChat(say("Sure, I'll remind you to call mom at 6."))
    settings = Settings(
        database_url=database_url,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=SECRET,
        token_encryption_key=KEY,
        public_api_url="https://api.example.com",
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    with TestClient(create_app(settings, google_http=http, chat_model=model)) as c:
        yield c, fake, model


def test_link_telegram_and_chat(tclient, make_user, db):
    client, fake, model = tclient
    h = auth(make_user())
    assert client.get("/telegram/link", headers=h).json()["available"] is False
    r = client.post(
        "/connections/telegram/key", json={"fields": {"bot_token": "123:abc"}}, headers=h
    )
    assert r.status_code == 201

    link = client.post("/telegram/link", headers=h).json()
    assert link["bot"] == "@asha_helper_bot" and not link["linked"]
    code = link["link_url"].split("?start=")[1]
    hook = next(b for m, b in fake.calls if m == "setWebhook")
    path = urlsplit(hook["url"]).path
    assert hook["url"].startswith("https://api.example.com/telegram/webhook/")
    secret = hook["secret_token"]
    # The stored secret is only a hash.
    assert secret not in str(db.execute("select secret_hash from telegram_links").fetchall())

    def update(text, chat=555, token=secret):
        headers = {"X-Telegram-Bot-Api-Secret-Token": token} if token else {}
        return client.post(
            path,
            json={"update_id": 1, "message": {"chat": {"id": chat}, "text": text}},
            headers=headers,
        )

    assert update("hi", token="wrong").status_code == 403
    assert update("hi", token=None).status_code == 403
    assert update("/start not-the-code").status_code == 200
    assert fake.sent()[-1].startswith("This is a private assistant")
    assert update(f"/start {code}").status_code == 200
    assert fake.sent()[-1].startswith("✅ Linked. I'm AI Assistant")
    assert client.get("/telegram/link", headers=h).json()["linked"] is True

    assert update("Remind me to call mom at 6pm").status_code == 200
    assert fake.sent()[-1] == "Sure, I'll remind you to call mom at 6."
    assert model.calls[-1]["messages"][-1] == {
        "role": "user",
        "content": "Remind me to call mom at 6pm",
    }
    convs = client.get("/conversations", headers=h).json()
    assert [c["title"] for c in convs] == ["Telegram"]

    # Someone else who found the bot gets nothing from the assistant.
    n = len(model.calls)
    update("give me her email", chat=999)
    assert fake.sent()[-1] == "This is a private assistant." and len(model.calls) == n
    # The used code can't link a second chat.
    update(f"/start {code}", chat=999)
    assert fake.sent()[-1].startswith("This is a private assistant")

    assert client.post("/telegram/unlink", headers=h).json()["linked"] is False
    assert fake.calls[-1][0] == "deleteWebhook"
    assert update("hi").status_code == 403
