from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from .config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


async def get_conn(request: Request) -> AsyncIterator[AsyncConnection]:
    """One pooled connection per request (autocommit; writes use conn.transaction())."""
    pool: AsyncConnectionPool = request.app.state.pool
    async with pool.connection() as conn:
        yield conn


SettingsDep = Annotated[Settings, Depends(get_app_settings)]
ConnDep = Annotated[AsyncConnection, Depends(get_conn)]
