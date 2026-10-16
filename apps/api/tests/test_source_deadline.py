"""A customer's database that stops answering is stopped waiting for (§947).

A connect timeout bounded reaching a source and nothing bounded what came
after. A table locked on the source's side is the honest way to build that
here: the connection succeeds and the read waits, as it would behind a long
migration on a customer's system.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.parse
import uuid

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import for_database  # noqa: E402
from src.services import connectors  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
DB = urllib.parse.urlparse(ADMIN_DSN)
SOURCE_DB = f"deadline_{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="module")
def source() -> dict:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"CREATE DATABASE {SOURCE_DB}")
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute("CREATE TABLE public.held (n int)")
        conn.execute("INSERT INTO public.held VALUES (1), (2)")
    yield {"host": DB.hostname, "port": DB.port or 5432, "database": SOURCE_DB,
           "user": DB.username, "sslmode": "disable"}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB} WITH (FORCE)")


@pytest.fixture
def held_table(source):
    """`public.held` locked by another session until the test is done."""
    conn = psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB))
    conn.execute("LOCK TABLE public.held IN ACCESS EXCLUSIVE MODE")
    yield
    conn.rollback()
    conn.close()


def secret() -> dict:
    return {"password": DB.password or ""}


def test_every_source_connection_has_keepalives(source) -> None:
    info = connectors.PostgresConnector()._conninfo(source, secret())
    assert {k: info[k] for k in ("keepalives", "keepalives_idle", "keepalives_interval",
                                 "keepalives_count")} == {
        "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}


@pytest.mark.parametrize("operation", ["snapshot", "preview"])
def test_a_source_that_does_not_answer_is_stopped_at_the_deadline(
    source, held_table, tmp_path, monkeypatch, operation
) -> None:
    monkeypatch.setattr(connectors, "SOURCE_DEADLINE_S", 1)
    connector = connectors.PostgresConnector()
    started = time.monotonic()
    with pytest.raises(connectors.ConnectorOperationError,
                       match="did not finish within 1 seconds"):
        if operation == "snapshot":
            connector.snapshot(source, secret(), source_schema="public", source_table="held",
                               dest_dir=str(tmp_path), max_bytes=1 << 20)
        else:
            connector.preview(source, secret(), source_schema="public", source_table="held")
    assert time.monotonic() - started < 10


def test_an_operation_inside_the_deadline_leaves_no_watchdog(source, tmp_path, monkeypatch) -> None:
    """The watchdog is disarmed when the operation ends. Left armed, every
    operation would leave a thread asleep for the whole deadline - five
    minutes each, on a task that runs many."""
    monkeypatch.setattr(connectors, "SOURCE_DEADLINE_S", 30)

    def timers() -> set[threading.Thread]:
        return {t for t in threading.enumerate() if isinstance(t, threading.Timer)}

    before = timers()
    extract = connectors.PostgresConnector().snapshot(
        source, secret(), source_schema="public", source_table="held",
        dest_dir=str(tmp_path), max_bytes=1 << 20)
    assert open(extract.path).read().splitlines() == ["n", "1", "2"]
    deadline = time.monotonic() + 2
    while timers() - before and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not timers() - before
