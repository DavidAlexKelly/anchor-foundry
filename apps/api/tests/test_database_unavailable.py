"""A database that is briefly unavailable is a 503, not a fault (§951).

A failover, a maintenance restart or a pool with no connection free reached
the generic handler as an anonymous 500, and its log line on `anchor.error`
fired the alarm that is there for faults in the code. They are answered as
busy now, with `Retry-After`, and logged where that alarm does not look.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import main  # noqa: E402
from src.lib import db  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture
def client():
    app = main.create_app()

    @app.get("/api/_terminated", include_in_schema=False)
    async def terminated() -> dict:
        # What a failover does to every open session: the server ends it
        # (57P01, "terminating connection due to administrator command").
        async with db.user_connection(uuid.uuid4()) as conn:
            await conn.execute(text("SELECT pg_terminate_backend(pg_backend_pid())"))
        return {}

    @app.get("/api/_pool_exhausted", include_in_schema=False)
    async def pool_exhausted() -> dict:
        raise PoolTimeout("QueuePool limit of size 10 overflow 20 reached")

    @app.get("/api/_a_bug", include_in_schema=False)
    async def a_bug() -> dict:
        async with db.user_connection(uuid.uuid4()) as conn:
            await conn.execute(text("SELECT * FROM no_such_table_here"))
        return {}

    @app.get("/api/_quick", include_in_schema=False)
    async def quick() -> dict:
        async with db.user_connection(uuid.uuid4()) as conn:
            return {"one": (await conn.execute(text("SELECT 1"))).scalar_one()}

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "anchor.error"]


def test_a_failover_is_a_503_and_not_an_unhandled_error(client, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="anchor"):
        r = client.get("/api/_terminated")
    assert r.status_code == 503, r.text
    assert r.headers["retry-after"] == "5"
    assert r.json()["detail"] == main.UNAVAILABLE_DETAIL
    assert not _errors(caplog)
    assert [rec.name for rec in caplog.records if rec.name == "anchor.unavailable"]
    # The pool drops the dead connection; the next request is served.
    assert client.get("/api/_quick").json() == {"one": 1}


def test_a_pool_with_nothing_free_is_a_503(client, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="anchor"):
        r = client.get("/api/_pool_exhausted")
    assert (r.status_code, r.headers.get("retry-after")) == (503, "5")
    assert not _errors(caplog)


def test_a_statement_the_code_got_wrong_is_still_a_500(client, caplog) -> None:
    with caplog.at_level(logging.INFO, logger="anchor"):
        r = client.get("/api/_a_bug")
    assert r.status_code == 500
    assert _errors(caplog), "a fault in the code still reaches the alarm"


class OperationalError(Exception):
    def __init__(self, sqlstate=None):
        super().__init__("x")
        self.sqlstate = sqlstate


@pytest.mark.parametrize("sqlstate, invalidated, expected", [
    ("57P01", False, True),   # admin_shutdown
    ("57P03", False, True),   # cannot_connect_now: starting up
    ("08006", False, True),   # connection_failure
    (None, False, True),      # gone before the server said anything
    ("25P03", True, True),    # a disconnect SQLAlchemy saw, whatever its code
    ("25P03", False, False),
    ("42P01", False, False),  # undefined_table: the code's own mistake
    ("23505", False, False),
    ("57014", False, False),  # a statement timeout has its own answer
])
def test_which_errors_say_the_database_is_unavailable(sqlstate, invalidated, expected) -> None:
    exc = DBAPIError("SELECT 1", None, OperationalError(sqlstate),
                     connection_invalidated=invalidated)
    assert main.database_unavailable(exc) is expected


def test_an_error_with_no_sqlstate_that_is_not_operational_is_not_unavailable() -> None:
    exc = DBAPIError("SELECT 1", None, SimpleNamespace(sqlstate=None))
    assert main.database_unavailable(exc) is False
