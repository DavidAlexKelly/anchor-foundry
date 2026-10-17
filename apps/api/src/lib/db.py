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
from sqlalchemy.pool import NullPool

from .config import get_settings

_engine: AsyncEngine | None = None

#: A kiosk session's settings for this request (§684, db 0134), or None. Set
#: by the auth dependency when the credential is a kiosk one, and applied by
#: `user_connection` to every transaction the request opens - so the scope is
#: the database's to enforce, on every query, without a route having to ask.
kiosk_settings: ContextVar[dict[str, str] | None] = ContextVar("kiosk_settings", default=None)


#: **How a pooled connection notices its database has gone** (§958), libpq's
#: own settings, which never reach the server. Unset, a database that did not
#: answer the connect held the request until the kernel gave up, minutes; and
#: a connection whose host vanished - a failover - waited on TCP
#: retransmission, a quarter of an hour by default, the pool's own pre-ping as
#: much as any query. Keepalives find an idle connection's dead peer in about
#: a minute; `tcp_user_timeout` ends a call whose data went unacknowledged for
#: 30 seconds, which a slow query never does (TCP acknowledges while it runs).
CONNECTION_SETTINGS: dict[str, int] = {
    "connect_timeout": 10,
    "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3,
    "tcp_user_timeout": 30_000,
}


#: How long a request waits for a pooled connection when all thirty are taken
#: (§984). SQLAlchemy's default is thirty seconds, half of CloudFront's minute
#: (E.31) gone before the request's first statement; it is told the platform
#: is busy sooner now, with a Retry-After (§951).
POOL_WAIT_S = 10


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=10,
            max_overflow=20,
            pool_timeout=POOL_WAIT_S,
            pool_pre_ping=True,
            connect_args={**CONNECTION_SETTINGS,
                          **connect_args(settings.statement_timeout_ms,
                                         settings.idle_in_transaction_timeout_ms)},
        )
    return _engine


def connect_args(statement_timeout_ms: int, idle_in_transaction_timeout_ms: int = 0) -> dict[str, str]:
    """Session settings every pooled connection starts with (§833, §946).

    Set when the connection is made rather than per transaction, so it costs
    no round trip and no request can forget it. A cancelled statement is
    answered as a 503 (`main.database_constraint_error`); a transaction left
    idle past its limit is ended by Postgres, which rolls it back and closes
    the connection, and the pool's pre-ping replaces it."""
    options = []
    if statement_timeout_ms > 0:
        options.append(f"-c statement_timeout={int(statement_timeout_ms)}")
    if idle_in_transaction_timeout_ms > 0:
        options.append(
            f"-c idle_in_transaction_session_timeout={int(idle_in_transaction_timeout_ms)}")
    return {"options": " ".join(options)} if options else {}


async def dispose_engine() -> None:
    global _engine, _health_engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
    if _health_engine is not None:
        await _health_engine.dispose()
        _health_engine = None


_health_engine: AsyncEngine | None = None

#: How long the health check gives the database, in seconds: inside the
#: load balancer's five-second wait, so a slow answer is a 503 it hears
#: rather than a timeout it guesses at.
HEALTH_DEADLINE_S = 3


def get_health_engine() -> AsyncEngine:
    """**The health check's own way to the database, outside the pool** (§956).

    The load balancer asks every thirty seconds and replaces a task that fails
    twice. Through the request pool, a task whose thirty connections were all
    busy - a burst of slow requests, which is load, not a fault - waited for
    one past the check's five seconds, failed, and was replaced: its requests
    landed on the other tasks, which were as busy, and the next one went the
    same way. A fresh connection per check still says whether this task can
    reach its database, which is what the check is for, without queueing
    behind the requests it is meant to keep alive."""
    global _health_engine
    if _health_engine is None:
        _health_engine = create_async_engine(
            get_settings().database_url,
            poolclass=NullPool,
            connect_args={**CONNECTION_SETTINGS, "connect_timeout": HEALTH_DEADLINE_S,
                          **connect_args(HEALTH_DEADLINE_S * 1000)},
        )
    return _health_engine


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
