"""Connected accounts: connect / list / disconnect Google services (Gmail, Calendar).

Flow: the app calls POST /connections/{service}/start and opens the returned
Google URL. The owner signs in on Google's own page and grants only that
service's permissions. Google redirects the browser to
GET /connections/google/callback, which checks the single-use state, exchanges
the code (PKCE), encrypts the tokens and sends the owner back to the app.
Tokens never reach the app or the browser.
"""

import secrets as pysecrets
import uuid
from datetime import datetime
from html import escape
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from workforce_core.db import record_audit
from workforce_core.google import (
    GOOGLE_SERVICES,
    GoogleConfig,
    GoogleError,
    GoogleOAuth,
    GoogleService,
    new_pkce,
)
from workforce_core.secrets import SecretBox, load_secret, store_secret

from ..auth import AdminDep, UserDep
from ..config import Settings
from ..deps import ConnDep, SettingsDep

router = APIRouter(prefix="/connections", tags=["connections"])


class AccountOut(BaseModel):
    id: str
    display_name: str | None
    status: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    last_error: str | None


class ProviderOut(BaseModel):
    provider: str
    name: str
    description: str
    configured: bool
    accounts: list[AccountOut]


class StartRequest(BaseModel):
    redirect_to: str = Field(min_length=3, max_length=500)


class StartResponse(BaseModel):
    auth_url: str


def _service(provider: str) -> GoogleService:
    service = GOOGLE_SERVICES.get(provider)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown service {provider!r}")
    return service


def _oauth(settings: Settings, request: Request) -> GoogleOAuth:
    return GoogleOAuth(
        GoogleConfig(
            settings.google_client_id or "",
            settings.google_client_secret or "",
            settings.google_redirect_uri or "",
        ),
        request.app.state.google_http,
    )


def _allowed_redirect(settings: Settings, url: str) -> bool:
    """Only send the owner back to our own apps (no open redirects)."""
    if any(url.startswith(s) for s in settings.app_redirect_schemes):
        return True
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    return parts.scheme in ("http", "https") and origin in settings.cors_origins


def _with_params(url: str, **params: str) -> str:
    parts = urlsplit(url)
    query = "&".join(p for p in (parts.query, urlencode(params)) if p)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


@router.get("", response_model=list[ProviderOut])
async def list_connections(
    user: UserDep, conn: ConnDep, settings: SettingsDep
) -> list[ProviderOut]:
    rows = await (
        await conn.execute(
            """select id::text, provider, display_name, connection_status as status, scopes,
                      created_at, last_used_at, last_error
               from public.tool_connections
               where workspace_id = %s and provider = any(%s)
                 and connection_status <> 'revoked'
               order by created_at""",
            (user.workspace_id, list(GOOGLE_SERVICES)),
        )
    ).fetchall()
    return [
        ProviderOut(
            provider=s.key,
            name=s.name,
            description=s.description,
            configured=settings.gmail_configured,
            accounts=[AccountOut(**r) for r in rows if r["provider"] == s.key],
        )
        for s in GOOGLE_SERVICES.values()
    ]


@router.post("/{provider}/start", response_model=StartResponse)
async def start(
    provider: str,
    body: StartRequest,
    request: Request,
    user: AdminDep,
    conn: ConnDep,
    settings: SettingsDep,
) -> StartResponse:
    service = _service(provider)
    if not settings.gmail_configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{service.name} isn't set up on the server yet (Google client ID/secret and "
            "encryption key).",
        )
    if not _allowed_redirect(settings, body.redirect_to):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "redirect_to is not allowed")
    state = pysecrets.token_urlsafe(32)
    verifier, challenge = new_pkce()
    await conn.execute(
        """insert into public.oauth_states
               (state, workspace_id, user_id, provider, code_verifier, redirect_to)
           values (%s, %s, %s, %s, %s, %s)""",
        (state, user.workspace_id, user.user_id, service.key, verifier, body.redirect_to),
    )
    await conn.execute("delete from public.oauth_states where expires_at < now()")
    url = _oauth(settings, request).auth_url(
        state=state, code_challenge=challenge, scopes=service.scopes
    )
    return StartResponse(auth_url=url)


def _error_page(message: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta name=viewport content='width=device-width'>"
        "<body style='font-family:system-ui;padding:24px'><h2>Couldn't connect</h2>"
        f"<p>{escape(message)}</p><p>Go back to the app and try again.</p></body>",
        status_code=400,
    )


async def _callback(request: Request, conn, settings: Settings, state: str, code, error):
    # Single use: the state row is deleted as it is read.
    row = await (
        await conn.execute(
            """delete from public.oauth_states where state = %s and expires_at > now()
               returning workspace_id::text, user_id::text, provider, code_verifier,
                         redirect_to""",
            (state,),
        )
    ).fetchone()
    if row is None or row["provider"] not in GOOGLE_SERVICES:
        return _error_page("This sign-in link has expired or was already used.")
    service = GOOGLE_SERVICES[row["provider"]]
    back = row["redirect_to"]
    if error or not code:
        return RedirectResponse(_with_params(back, connect=service.key, status="cancelled"), 302)
    if not settings.gmail_configured:
        return _error_page(f"{service.name} isn't set up on the server.")

    oauth = _oauth(settings, request)
    try:
        tokens = await oauth.exchange_code(code, row["code_verifier"])
        granted = set(tokens.get("scope", "").split())
        if service.required_scope not in granted:
            if tokens.get("access_token"):
                await oauth.revoke(tokens["access_token"])
            return RedirectResponse(
                _with_params(back, connect=service.key, status="missing_permission"), 302
            )
        info = await oauth.userinfo(tokens["access_token"])
    except GoogleError:
        return RedirectResponse(_with_params(back, connect=service.key, status="error"), 302)

    account = info.get("sub") or info.get("email")
    email = info.get("email")
    box = SecretBox(settings.token_encryption_key or "")
    async with conn.transaction():
        secret_id = await store_secret(
            conn,
            box,
            workspace_id=row["workspace_id"],
            provider=service.key,
            data={
                "refresh_token": tokens.get("refresh_token"),
                "access_token": tokens["access_token"],
                "expires_at": tokens["expires_at"],
                "email": email,
            },
        )
        previous = await (
            await conn.execute(
                "select secret_ref::text as secret from public.tool_connections"
                " where workspace_id = %s and provider = %s and account_ref = %s for update",
                (row["workspace_id"], service.key, account),
            )
        ).fetchone()
        saved = await (
            await conn.execute(
                """insert into public.tool_connections
                       (workspace_id, provider, account_ref, scopes, secret_ref,
                        connection_status, display_name, connected_by)
                   values (%s, %s, %s, %s, %s, 'active', %s, %s)
                   on conflict (workspace_id, provider, account_ref) do update set
                       scopes = excluded.scopes, connection_status = 'active',
                       display_name = excluded.display_name, last_error = null,
                       connected_by = excluded.connected_by, updated_at = now(),
                       secret_ref = excluded.secret_ref
                   returning id::text""",
                (
                    row["workspace_id"],
                    service.key,
                    account,
                    sorted(granted),
                    secret_id,
                    email,
                    row["user_id"],
                ),
            )
        ).fetchone()
        if previous and previous["secret"]:
            await conn.execute(
                "delete from public.connection_secrets where id = %s", (previous["secret"],)
            )
        await record_audit(
            conn,
            workspace_id=row["workspace_id"],
            actor_type="user",
            actor_id=row["user_id"],
            action="connection.connected",
            target_type="connection",
            target_id=saved["id"],
            event={"provider": service.key, "account": email, "scopes": sorted(granted)},
        )
    return RedirectResponse(_with_params(back, connected=service.key), 302)


@router.get("/google/callback", include_in_schema=False)
async def google_callback(
    request: Request,
    conn: ConnDep,
    settings: SettingsDep,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
):
    return await _callback(request, conn, settings, state, code, error)


# Kept so a Google client registered with the earlier Gmail-only URI keeps working.
@router.get("/gmail/callback", include_in_schema=False)
async def gmail_callback(
    request: Request,
    conn: ConnDep,
    settings: SettingsDep,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
):
    return await _callback(request, conn, settings, state, code, error)


@router.post("/{connection_id}/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    connection_id: str, request: Request, user: AdminDep, conn: ConnDep, settings: SettingsDep
) -> None:
    try:
        uuid.UUID(connection_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connection not found") from exc
    row = await (
        await conn.execute(
            "select id::text, provider, secret_ref::text from public.tool_connections"
            " where id = %s and workspace_id = %s",
            (connection_id, user.workspace_id),
        )
    ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connection not found")

    # Tell Google to cancel the access too (best effort; we forget it regardless).
    if row["secret_ref"] and settings.gmail_configured:
        try:
            secret = await load_secret(
                conn,
                SecretBox(settings.token_encryption_key or ""),
                secret_id=row["secret_ref"],
                workspace_id=user.workspace_id,
                provider=row["provider"],
            )
            token = secret.get("refresh_token") or secret.get("access_token")
            if token:
                await _oauth(settings, request).revoke(token)
        except Exception:  # noqa: BLE001 - revocation is best effort
            pass

    async with conn.transaction():
        await conn.execute(
            "update public.tool_connections set connection_status = 'revoked',"
            " secret_ref = null, updated_at = now() where id = %s",
            (connection_id,),
        )
        if row["secret_ref"]:
            await conn.execute(
                "delete from public.connection_secrets where id = %s", (row["secret_ref"],)
            )
        await record_audit(
            conn,
            workspace_id=user.workspace_id,
            actor_type="user",
            actor_id=user.user_id,
            action="connection.disconnected",
            target_type="connection",
            target_id=connection_id,
            event={"provider": row["provider"]},
        )
