"""Supabase Auth token verification and workspace resolution."""

from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .deps import ConnDep, SettingsDep

_bearer = HTTPBearer(auto_error=False)
_jwks_clients: dict[str, jwt.PyJWKClient] = {}


@dataclass(frozen=True)
class CurrentUser:
    user_id: str
    email: str | None
    workspace_id: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")


def _unauthorized(detail: str = "invalid or missing token") -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def verify_token(token: str, settings: Settings) -> dict:
    options = {"require": ["exp", "sub", "aud", "iss"]}
    try:
        if settings.supabase_jwt_secret:
            return jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer,
                options=options,
            )
        client = _jwks_clients.setdefault(
            settings.jwks_url, jwt.PyJWKClient(settings.jwks_url, cache_keys=True)
        )
        signing_key = await run_in_threadpool(client.get_signing_key_from_jwt, token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options=options,
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized() from exc


async def get_current_user(
    settings: SettingsDep,
    conn: ConnDep,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    x_workspace_id: Annotated[str | None, Header()] = None,
) -> CurrentUser:
    if creds is None:
        raise _unauthorized()
    claims = await verify_token(creds.credentials, settings)
    user_id = claims["sub"]

    query = (
        "select workspace_id::text, role from public.workspace_members"
        " where user_id = %s and status = 'active'"
    )
    params: tuple = (user_id,)
    if x_workspace_id:
        query += " and workspace_id::text = %s"
        params += (x_workspace_id,)
    query += " order by created_at limit 1"

    row = await (await conn.execute(query, params)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "no active workspace membership")
    return CurrentUser(
        user_id=user_id,
        email=claims.get("email"),
        workspace_id=row["workspace_id"],
        role=row["role"],
    )


UserDep = Annotated[CurrentUser, Depends(get_current_user)]


def require_admin(user: UserDep) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "owner or admin role required")
    return user


AdminDep = Annotated[CurrentUser, Depends(require_admin)]
