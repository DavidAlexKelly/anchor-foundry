"""Two requests changing one thing at once are told so, not given a 500 (§862).

The loser of a race fails in the database: a unique violation on a number both
took, a deadlock, a serialization failure. Uncaught, each reached the 500
handler, and the person was told the server was broken when trying again a
moment later would succeed.
"""
from __future__ import annotations

import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib.db import get_engine  # noqa: E402
from src.main import create_app  # noqa: E402


@pytest.fixture
def client():
    app = create_app()

    @app.get("/api/_race/{kind}", include_in_schema=False)
    async def race(kind: str):
        errors = {
            "deadlock": OperationalError("UPDATE", {}, psycopg.errors.DeadlockDetected("deadlock")),
            "serialization": OperationalError(
                "UPDATE", {}, psycopg.errors.SerializationFailure("could not serialize")),
            "other": DBAPIError("SELECT", {}, psycopg.errors.UndefinedTable("no table")),
        }
        raise errors[kind]

    @app.get("/api/_duplicate", include_in_schema=False)
    async def duplicate():
        # A real one, so the constraint's name arrives the way it does in
        # production: two rows with one key in a table that refuses that.
        async with get_engine().connect() as conn:
            await conn.execute(text("CREATE TEMP TABLE once (k int CONSTRAINT once_k UNIQUE)"))
            await conn.execute(text("INSERT INTO once VALUES (1), (1)"))
        return {}

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("kind", ["deadlock", "serialization"])
def test_a_lost_race_is_a_conflict_to_retry(client, kind) -> None:
    r = client.get(f"/api/_race/{kind}")
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "this was changed by another request at the same time - reload and try again")


def test_a_duplicate_says_what_it_duplicates(client) -> None:
    r = client.get("/api/_duplicate")
    assert r.status_code == 409, r.text
    assert "would duplicate something that already exists" in r.json()["detail"]
    assert "(once_k)" in r.json()["detail"]


def test_any_other_database_fault_is_still_a_500(client) -> None:
    assert client.get("/api/_race/other").status_code == 500


def test_the_integrity_error_class_is_not_what_decides() -> None:
    """By SQLSTATE: a foreign-key violation is an IntegrityError too, and is a
    fault in whatever let it through, not a race."""
    from src import main

    assert main.CONCURRENT_CHANGE_SQLSTATES == frozenset({"23505", "40001", "40P01"})
    assert psycopg.errors.ForeignKeyViolation.sqlstate not in main.CONCURRENT_CHANGE_SQLSTATES
