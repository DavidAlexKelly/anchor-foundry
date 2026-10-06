"""Database access for the API (spec §7: SQLAlchemy 2.0, async).

The API connects as the RLS-subject role ``platform_app`` (db migration
0006). Every request-scoped session sets the RLS context inside its
transaction:

    SET LOCAL app.cognito_sub = <sub from validated JWT>   -- auth lookup only
    SET LOCAL app.user_id     = <resolved user id>          -- everything else

so PostgreSQL row-level security enforces workspace/project isolation as a
second layer independent of the application permission checks (spec §10).
Permission *logic* is never duplicated here - the API calls the same
``effective_workspace_role`` / ``effective_project_role`` functions the RLS
policies use (db migration 0005), keeping one source of truth.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from .config import get_settings

_engine: AsyncEngine | None = None

#: A kiosk session's settings for this request (§684, db 0134), or None. Set
#: by the auth dependency when the credential is a kiosk one, and applied by
#: `user_connection` to every transaction the request opens - so the scope is
#: the database's to enforce, on every query, without a route having to ask.
kiosk_settings: ContextVar[dict[str, str] | None] = ContextVar("kiosk_settings", default=None)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            connect_args=connect_args(settings.statement_timeout_ms),
        )
    return _engine


def connect_args(statement_timeout_ms: int) -> dict[str, str]:
    """Session settings every pooled connection starts with (§833).

    Set when the connection is made rather than per transaction, so it costs
    no round trip and no request can forget it. A cancelled statement is
    answered as a 503 (`main.database_constraint_error`)."""
    if statement_timeout_ms <= 0:
        return {}
    return {"options": f"-c statement_timeout={int(statement_timeout_ms)}"}


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def auth_lookup_connection(cognito_sub: str) -> AsyncIterator[AsyncConnection]:
    """Connection scoped to the pre-auth user lookup (db 0007 keyhole policy).

    Only the single user row matching the validated token's sub (and its
    organisation) is visible in this context. Parameterised set_config - the
    sub comes from a cryptographically validated token but is still treated
    as untrusted input.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.cognito_sub', :sub, true)"), {"sub": cognito_sub}
        )
        yield conn


@asynccontextmanager
async def user_connection(user_id: UUID) -> AsyncIterator[AsyncConnection]:
    """Request-scoped transaction with the user's RLS context applied."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.user_id', :uid, true)"), {"uid": str(user_id)}
        )
        for name, value in (kiosk_settings.get() or {}).items():
            await conn.execute(
                text("SELECT set_config(:name, :value, true)"), {"name": name, "value": value}
            )
        yield conn


async def fetch_one(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> dict[str, Any] | None:
    result = await conn.execute(text(sql), params)
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def fetch_all(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    result = await conn.execute(text(sql), params)
    return [dict(r) for r in result.mappings().all()]
