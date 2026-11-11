import base64
import os
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient
from test_api import SECRET, SUPABASE_URL, auth
from workforce_api.config import Settings
from workforce_api.main import create_app
from workforce_core.google import GMAIL_SEND_SCOPE
from workforce_core.secrets import SecretBox, secret_context

KEY = base64.b64encode(os.urandom(32)).decode()
WEB = "http://localhost:3000"


class FakeGoogle:
    def __init__(self):
        self.revoked: list[str] = []
        self.token_forms: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/token":
            form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
            self.token_forms.append(form)
            scope = (
                "openid email"
                if form.get("code") == "no-send"
                else f"openid email {GMAIL_SEND_SCOPE}"
            )
            if form.get("code") == "bad":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(
                200,
                json={
                    "access_token": f"at-{form['code']}",
                    "refresh_token": f"rt-{form['code']}",
                    "expires_in": 3599,
                    "scope": scope,
                },
            )
        if req.url.path == "/v1/userinfo":
            return httpx.Response(200, json={"sub": "1098765", "email": "asha@gmail.com"})
        if req.url.path == "/revoke":
            self.revoked.append(parse_qs(req.content.decode())["token"][0])
            return httpx.Response(200)
        return httpx.Response(404)


@pytest.fixture(scope="module")
def google():
    return FakeGoogle()


@pytest.fixture(scope="module")
def gclient(database_url, google):
    settings = Settings(
        database_url=database_url,
        supabase_url=SUPABASE_URL,
        supabase_jwt_secret=SECRET,
        cors_origins=[WEB],
        google_client_id="cid",
        google_client_secret="csecret",
        google_redirect_uri="https://api.example.com/connections/gmail/callback",
        token_encryption_key=KEY,
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(google))
    with TestClient(create_app(settings, google_http=http)) as c:
        yield c


def _start(client, h, redirect=f"{WEB}/integrations"):
    r = client.post("/connections/gmail/start", json={"redirect_to": redirect}, headers=h)
    assert r.status_code == 200, r.text
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.json()["auth_url"]).query).items()}
    return q["state"]


def _callback(client, state, code="good"):
    return client.get(
        f"/connections/gmail/callback?state={state}&code={code}", follow_redirects=False
    )


def test_connect_gmail_end_to_end(gclient, google, make_user, db):
    h = auth(make_user())
    ws = gclient.get("/me", headers=h).json()["workspace"]["id"]
    assert gclient.get("/connections", headers=h).json()[0]["accounts"] == []

    state = _start(gclient, h)
    r = _callback(gclient, state)
    assert r.status_code == 302 and r.headers["location"] == f"{WEB}/integrations?connected=gmail"
    assert google.token_forms[-1]["code_verifier"]  # PKCE verifier sent with the code

    accounts = gclient.get("/connections", headers=h).json()[0]["accounts"]
    assert [(a["display_name"], a["status"]) for a in accounts] == [("asha@gmail.com", "active")]
    assert GMAIL_SEND_SCOPE in accounts[0]["scopes"]

    # Tokens are stored only encrypted, bound to this workspace.
    blob = db.execute(
        "select s.ciphertext from connection_secrets s join tool_connections c"
        " on c.secret_ref = s.id where c.workspace_id = %s",
        (ws,),
    ).fetchone()[0]
    assert b"rt-good" not in bytes(blob)
    secret = SecretBox(KEY).decrypt(blob, secret_context(ws, "gmail"))
    assert secret["refresh_token"] == "rt-good" and secret["email"] == "asha@gmail.com"

    # The same link can't be used twice.
    assert _callback(gclient, state).status_code == 400

    # Reconnecting replaces the old secret instead of piling up.
    _callback(gclient, _start(gclient, h), code="again")
    assert (
        db.execute(
            "select count(*) from connection_secrets where workspace_id = %s", (ws,)
        ).fetchone()[0]
        == 1
    )

    # Disconnect: Google is told to revoke, and the secret is deleted.
    conn_id = gclient.get("/connections", headers=h).json()[0]["accounts"][0]["id"]
    assert gclient.post(f"/connections/{conn_id}/disconnect", headers=h).status_code == 204
    assert google.revoked[-1] == "rt-again"
    assert gclient.get("/connections", headers=h).json()[0]["accounts"] == []
    assert (
        db.execute(
            "select count(*) from connection_secrets where workspace_id = %s", (ws,)
        ).fetchone()[0]
        == 0
    )
    actions = [a["action"] for a in gclient.get("/audit", headers=h).json()]
    assert "connection.connected" in actions and "connection.disconnected" in actions


def test_unchecked_send_permission_and_errors(gclient, google, make_user):
    h = auth(make_user())
    r = _callback(gclient, _start(gclient, h), code="no-send")
    assert r.headers["location"].endswith("connect=gmail&status=missing_permission")
    assert google.revoked[-1] == "at-no-send"  # partial grant handed back
    r = _callback(gclient, _start(gclient, h), code="bad")
    assert r.headers["location"].endswith("status=error")
    r = gclient.get(
        f"/connections/gmail/callback?state={_start(gclient, h)}&error=access_denied",
        follow_redirects=False,
    )
    assert r.headers["location"].endswith("status=cancelled")
    assert gclient.get("/connections", headers=h).json()[0]["accounts"] == []
    assert _callback(gclient, "made-up-state").status_code == 400


def test_redirects_only_to_our_apps(gclient, make_user):
    h = auth(make_user())
    for bad in ("https://evil.example/steal", "javascript:alert(1)", "//evil.example"):
        r = gclient.post("/connections/gmail/start", json={"redirect_to": bad}, headers=h)
        assert r.status_code == 422, bad
    state = _start(gclient, h, redirect="workforceos://settings")
    assert _callback(gclient, state).headers["location"] == "workforceos://settings?connected=gmail"


def test_only_owner_or_admin_can_connect(gclient, make_user, db):
    owner, member = make_user(), make_user()
    ws = gclient.get("/me", headers=auth(owner)).json()["workspace"]["id"]
    db.execute(
        "insert into workspace_members (workspace_id, user_id, role) values (%s, %s, 'member')",
        (ws, member),
    )
    r = gclient.post(
        "/connections/gmail/start",
        json={"redirect_to": WEB},
        headers={**auth(member), "X-Workspace-Id": ws},
    )
    assert r.status_code == 403


def test_not_configured_server_explains(client, make_user):
    r = client.post(
        "/connections/gmail/start", json={"redirect_to": WEB}, headers=auth(make_user())
    )
    assert r.status_code == 503 and "isn't set up" in r.text
    assert client.get("/connections", headers=auth(make_user())).json()[0]["configured"] is False
