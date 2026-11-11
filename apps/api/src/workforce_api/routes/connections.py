"""Connections: browse the catalog and connect services when you need them.

* Sign-in services (Google, Slack): POST /connections/{key}/start returns the
  provider's own sign-in URL; the provider sends the browser back to
  /connections/oauth/callback, which stores the tokens encrypted.
* Key services (WhatsApp, Telegram, GitHub, Vercel): POST /connections/{key}/key
  checks the key with the provider first, then stores it encrypted.
* Connecting wakes any task that was waiting for that service.
Secrets never go back to the app or the browser.
"""

import secrets as pysecrets
import uuid
from datetime import datetime
from html import escape
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field
from workforce_core.connectors import CONNECTORS, CONNECTORS_BY_KEY, AuthKind, Connector
from workforce_core.db import record_audit
from workforce_core.google import new_pkce
from workforce_core.oauth import OAuthApp, OAuthError
from workforce_core.secrets import SecretBox, load_secret, store_secret
from workforce_core.verify import CHECKERS

from ..auth import AdminDep, CurrentUser, UserDep
from ..config import Settings
from ..deps import ConnDep, SettingsDep

router = APIRouter(prefix="/connections", tags=["connections"])
catalog_router = APIRouter(prefix="/connectors", tags=["connections"])

CONNECTABLE = (AuthKind.OAUTH2, AuthKind.API_KEY)


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


class FieldOut(BaseModel):
    key: str
    label: str
    secret: bool
    help: str
    placeholder: str


class ConnectorOut(BaseModel):
    key: str
    name: str
    category: str
    icon: str
    description: str
    auth: str
    live: bool
    available: bool  # can be connected on this server right now
    plan: str
    note: str
    how_to_get: str
    open_url: str
    fields: list[FieldOut]
    accounts: list[AccountOut]


class StartRequest(BaseModel):
    redirect_to: str = Field(min_length=3, max_length=500)


class StartResponse(BaseModel):
    auth_url: str


class KeyRequest(BaseModel):
    fields: dict[str, str]


# --- helpers ------------------------------------------------------------------------


def _connector(key: str) -> Connector:
    c = CONNECTORS_BY_KEY.get(key)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown service {key!r}")
    return c


def _available(c: Connector, settings: Settings) -> bool:
    if not c.live:
        return False
    if c.auth == AuthKind.OAUTH2:
        return bool(c.oauth and settings.oauth_client(c.oauth.client_env))
    if c.auth == AuthKind.API_KEY:
        return bool(settings.token_encryption_key)
    return True


def _oauth_app(c: Connector, settings: Settings, request: Request) -> OAuthApp:
    creds = settings.oauth_client(c.oauth.client_env) if c.oauth else None
    if creds is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{c.name} isn't set up on the server yet.",
        )
    cid, secret, redirect = creds
    return OAuthApp(c, cid, secret, redirect, request.app.state.google_http)


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


async def _accounts(conn, workspace_id: str) -> dict[str, list[AccountOut]]:
    rows = await (
        await conn.execute(
            """select id::text, provider, display_name, connection_status as status, scopes,
                      created_at, last_used_at, last_error
               from public.tool_connections
               where workspace_id = %s and connection_status <> 'revoked'
               order by created_at""",
            (workspace_id,),
        )
    ).fetchall()
    out: dict[str, list[AccountOut]] = {}
    for r in rows:
        out.setdefault(r["provider"], []).append(AccountOut(**r))
    return out


async def _save_connection(
    conn,
    settings: Settings,
    *,
    workspace_id: str,
    user_id: str,
    connector: Connector,
    account_id: str,
    display_name: str,
    scopes: list[str],
    secret: dict,
) -> str:
    """Encrypt and store a connection, replace an older one, wake waiting tasks."""
    box = SecretBox(settings.token_encryption_key or "")
    async with conn.transaction():
        secret_id = await store_secret(
            conn, box, workspace_id=workspace_id, provider=connector.key, data=secret
        )
        previous = await (
            await conn.execute(
                "select secret_ref::text as secret from public.tool_connections"
                " where workspace_id = %s and provider = %s and account_ref = %s for update",
                (workspace_id, connector.key, account_id),
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
                (workspace_id, connector.key, account_id, scopes, secret_id, display_name, user_id),
            )
        ).fetchone()
        if previous and previous["secret"]:
            await conn.execute(
                "delete from public.connection_secrets where id = %s", (previous["secret"],)
            )
        woken = await (
            await conn.execute(
                "select public.wake_tasks_for_connection(%s, %s) as n",
                (workspace_id, connector.key),
            )
        ).fetchone()
        await record_audit(
            conn,
            workspace_id=workspace_id,
            actor_type="user",
            actor_id=user_id,
            action="connection.connected",
            target_type="connection",
            target_id=saved["id"],
            event={
                "provider": connector.key,
                "account": display_name,
                "scopes": scopes,
                "tasks_resumed": woken["n"],
            },
        )
    return saved["id"]


# --- catalog ------------------------------------------------------------------------


@catalog_router.get("", response_model=list[ConnectorOut])
async def catalog(user: UserDep, conn: ConnDep, settings: SettingsDep) -> list[ConnectorOut]:
    accounts = await _accounts(conn, user.workspace_id)
    return [
        ConnectorOut(
            key=c.key,
            name=c.name,
            category=c.category,
            icon=c.icon,
            description=c.description,
            auth=c.auth.value,
            live=c.live,
            available=_available(c, settings),
            plan=c.plan,
            note=c.note,
            how_to_get=c.how_to_get,
            open_url=c.open_url,
            fields=[FieldOut(**f.__dict__) for f in c.fields],
            accounts=accounts.get(c.key, []),
        )
        for c in CONNECTORS
    ]


@router.get("", response_model=list[ProviderOut])
async def list_connections(
    user: UserDep, conn: ConnDep, settings: SettingsDep
) -> list[ProviderOut]:
    """Connectable services that are live (compact view used by Settings/Approvals)."""
    accounts = await _accounts(conn, user.workspace_id)
    return [
        ProviderOut(
            provider=c.key,
            name=c.name,
            description=c.description,
            configured=_available(c, settings),
            accounts=accounts.get(c.key, []),
        )
        for c in CONNECTORS
        if c.auth in CONNECTABLE and c.live
    ]


# --- sign-in (OAuth) services ----------------------------------------------------------


@router.post("/{key}/start", response_model=StartResponse)
async def start(
    key: str,
    body: StartRequest,
    request: Request,
    user: AdminDep,
    conn: ConnDep,
    settings: SettingsDep,
) -> StartResponse:
    c = _connector(key)
    if c.auth != AuthKind.OAUTH2 or not c.live:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{c.name} isn't connected by signing in")
    if not _available(c, settings):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"{c.name} isn't set up on the server yet (client ID/secret and encryption key).",
        )
    if not _allowed_redirect(settings, body.redirect_to):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "redirect_to is not allowed")
    app = _oauth_app(c, settings, request)
    state = pysecrets.token_urlsafe(32)
    verifier, challenge = new_pkce()
    await conn.execute(
        """insert into public.oauth_states
               (state, workspace_id, user_id, provider, code_verifier, redirect_to)
           values (%s, %s, %s, %s, %s, %s)""",
        (state, user.workspace_id, user.user_id, c.key, verifier, body.redirect_to),
    )
    await conn.execute("delete from public.oauth_states where expires_at < now()")
    return StartResponse(auth_url=app.auth_url(state=state, code_challenge=challenge))


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
    c = CONNECTORS_BY_KEY.get(row["provider"]) if row else None
    if row is None or c is None or c.auth != AuthKind.OAUTH2:
        return _error_page("This sign-in link has expired or was already used.")
    back = row["redirect_to"]
    if error or not code:
        return RedirectResponse(_with_params(back, connect=c.key, status="cancelled"), 302)
    if not _available(c, settings):
        return _error_page(f"{c.name} isn't set up on the server.")

    app = _oauth_app(c, settings, request)
    try:
        tokens = await app.exchange(code, row["code_verifier"])
        if not set(c.oauth.required_scopes) <= tokens.scopes:
            await app.revoke(tokens.access_token)
            return RedirectResponse(
                _with_params(back, connect=c.key, status="missing_permission"), 302
            )
    except OAuthError:
        return RedirectResponse(_with_params(back, connect=c.key, status="error"), 302)

    await _save_connection(
        conn,
        settings,
        workspace_id=row["workspace_id"],
        user_id=row["user_id"],
        connector=c,
        account_id=tokens.account_id,
        display_name=tokens.display_name,
        scopes=sorted(tokens.scopes),
        secret=tokens.secret(),
    )
    return RedirectResponse(_with_params(back, connected=c.key), 302)


async def _callback_route(
    request: Request,
    conn: ConnDep,
    settings: SettingsDep,
    state: str = "",
    code: str | None = None,
    error: str | None = None,
):
    return await _callback(request, conn, settings, state, code, error)


# One callback for every provider; the Google/Gmail paths keep earlier setups working.
for _path in ("/oauth/callback", "/google/callback", "/gmail/callback"):
    router.add_api_route(_path, _callback_route, methods=["GET"], include_in_schema=False)


# --- key services --------------------------------------------------------------------


@router.post("/{key}/key", status_code=status.HTTP_201_CREATED)
async def connect_with_key(
    key: str,
    body: KeyRequest,
    request: Request,
    user: AdminDep,
    conn: ConnDep,
    settings: SettingsDep,
) -> dict:
    c = _connector(key)
    if c.auth != AuthKind.API_KEY or not c.live:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{c.name} isn't connected with a key")
    if not settings.token_encryption_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Connections aren't set up on the server yet."
        )
    fields = {f.key: (body.fields.get(f.key) or "").strip() for f in c.fields}
    missing = [f.label for f in c.fields if not fields[f.key]]
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Please fill in: {', '.join(missing)}"
        )
    if any(len(v) > 2000 for v in fields.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A value is too long")
    try:
        account_id, display = await CHECKERS[c.key](request.app.state.google_http, fields)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except Exception as exc:  # network errors etc.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Couldn't reach {c.name} to check the key."
        ) from exc
    connection_id = await _save_connection(
        conn,
        settings,
        workspace_id=user.workspace_id,
        user_id=user.user_id,
        connector=c,
        account_id=account_id,
        display_name=display,
        scopes=[],
        secret=fields,
    )
    return {"id": connection_id, "display_name": display}


# --- disconnect ----------------------------------------------------------------------


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
    await _revoke_at_provider(row, user, conn, settings, request)
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


async def _revoke_at_provider(row, user: CurrentUser, conn, settings, request) -> None:
    """Tell sign-in providers to cancel access too (best effort; we forget it regardless)."""
    c = CONNECTORS_BY_KEY.get(row["provider"])
    if not (row["secret_ref"] and c and c.auth == AuthKind.OAUTH2 and _available(c, settings)):
        return
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
            await _oauth_app(c, settings, request).revoke(token)
    except Exception:  # noqa: BLE001 - revocation is best effort
        pass
