"""Scheduled sync against a MySQL/MariaDB source.

The worker carries its own connector registry (anchor_worker.connectors), so
"the API can sync MySQL" is not evidence that a *scheduled* MySQL sync works -
that is a separate dispatch path in a separate deployable image, and the
failure mode when it drifts is silent and per-connection. This file exercises
it for real, against a real MariaDB.

Reuses the workspace/storage/assertion fixtures from test_sync_configs so the
only thing that differs from the Postgres suite is the source system itself.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

pymysql = pytest.importorskip("pymysql", reason="PyMySQL not installed")

import anchor_worker.jobs.sync_configs as sync_configs  # noqa: E402
from anchor_worker.connectors import ConnectorError, MySQLConnector, get_connector  # noqa: E402
from anchor_worker.jobs.sync_configs import run_due_scheduled_syncs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402
from test_sync_configs import (  # noqa: E402,F401 (fixtures used by name)
    _connection_row,
    _create_connection,
    _dataset_rows,
    storage_root,
    workspace,
)

APP_DSN = os.environ["WORKER_DATABASE_URL"]

MYSQL_HOST = os.environ.get("TEST_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3306"))
MYSQL_ADMIN_USER = os.environ.get("TEST_MYSQL_ADMIN_USER", "platform_test")
MYSQL_ADMIN_PASSWORD = os.environ.get("TEST_MYSQL_ADMIN_PASSWORD", "devpass")

SOURCE_DB = "worker_sync_source_mysql"
SOURCE_USER = "worker_mysql_user"
SOURCE_PASSWORD = "w0rker-MySQL-99"


def _admin_connect(database: str = "mysql"):
    return pymysql.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_ADMIN_USER,
        password=MYSQL_ADMIN_PASSWORD, database=database,
        connect_timeout=5, autocommit=True,
    )


try:
    _admin_connect().close()
except Exception as exc:  # pragma: no cover - environment guard
    pytest.skip(
        f"no MySQL/MariaDB reachable at {MYSQL_HOST}:{MYSQL_PORT} ({exc})",
        allow_module_level=True,
    )


@pytest.fixture(scope="module", autouse=True)
def _fake_secrets():
    """Same stand-in as the Postgres suite: no real AWS in tests."""
    import unittest.mock as mock

    with mock.patch.object(sync_configs, "_read_secret", lambda arn: {"password": SOURCE_PASSWORD}):
        yield


@pytest.fixture(scope="module")
def mysql_source():
    with _admin_connect() as conn, conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        cur.execute(f"CREATE DATABASE {SOURCE_DB}")
        cur.execute(
            f"CREATE USER IF NOT EXISTS '{SOURCE_USER}'@'%' IDENTIFIED BY '{SOURCE_PASSWORD}'"
        )
        cur.execute(f"GRANT ALL PRIVILEGES ON {SOURCE_DB}.* TO '{SOURCE_USER}'@'%'")
        cur.execute("FLUSH PRIVILEGES")
    with _admin_connect(SOURCE_DB) as conn, conn.cursor() as cur:
        cur.execute("CREATE TABLE items (id BIGINT PRIMARY KEY, val VARCHAR(64) NOT NULL)")
    yield {
        "host": MYSQL_HOST, "port": MYSQL_PORT, "database": SOURCE_DB,
        "user": SOURCE_USER, "ssl_mode": "disabled",
    }
    with _admin_connect() as conn, conn.cursor() as cur:
        cur.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        cur.execute(f"DROP USER IF EXISTS '{SOURCE_USER}'@'%'")


@pytest.fixture(autouse=True)
def _seed_items(mysql_source: dict) -> None:
    with _admin_connect(SOURCE_DB) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE items")
        cur.execute("INSERT INTO items (id, val) VALUES (1,'a'), (2,'b')")


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def test_worker_registry_covers_every_api_source_type() -> None:
    """The two registries drifting apart is the failure this file exists to
    catch, so assert it directly rather than only through a sync run."""
    assert isinstance(get_connector("mysql"), MySQLConnector)
    assert get_connector("postgres").type_name == "postgres"
    with pytest.raises(ConnectorError) as exc:
        get_connector("oracle")
    assert "cannot be synced on a schedule" in str(exc.value)


def test_scheduled_full_sync_against_mysql(workspace: dict, mysql_source: dict) -> None:
    cid = _create_connection(
        workspace, mysql_source, mode="full", dataset_name="mysql_items",
        source_type="mysql", source_schema=SOURCE_DB,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1

    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    assert row["sync_dataset_id"] is not None
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (1, 2)


def test_scheduled_incremental_sync_against_mysql(workspace: dict, mysql_source: dict) -> None:
    cid = _create_connection(
        workspace, mysql_source, mode="incremental", dataset_name="mysql_incremental",
        primary_key_column="id", cursor_column="id",
        source_type="mysql", source_schema=SOURCE_DB,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    assert row["sync_last_cursor_value"] == "2"
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (1, 2)

    # A new source row merges in rather than replacing the dataset.
    with _admin_connect(SOURCE_DB) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO items (id, val) VALUES (3,'c')")
    _make_due(cid)
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    assert row["sync_last_cursor_value"] == "3"
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (2, 3)


def test_unreadable_mysql_table_fails_only_its_own_candidate(
    workspace: dict, mysql_source: dict
) -> None:
    """A driver error must be recorded as this connection's failed run, not
    escape the per-candidate except and strand every other due connection -
    the bug class this job has now hit three times."""
    bad = _create_connection(
        workspace, mysql_source, mode="full", dataset_name="mysql_missing",
        source_table="no_such_table", source_type="mysql", source_schema=SOURCE_DB,
    )
    good = _create_connection(
        workspace, mysql_source, mode="full", dataset_name="mysql_ok",
        source_type="mysql", source_schema=SOURCE_DB,
    )
    run_due_scheduled_syncs(_ctx())

    bad_row = _connection_row(bad)
    assert bad_row["status"] == "error"
    assert "does not exist" in (bad_row["last_error"] or "")
    # Failure is isolated: the healthy connection still synced, and the failing
    # one is still rescheduled rather than stuck permanently due.
    assert bad_row["sync_next_run_at"] is not None
    good_row = _connection_row(good)
    assert good_row["status"] == "ok", good_row["last_error"]
    assert good_row["sync_dataset_id"] is not None


def _make_due(connection_id: uuid.UUID) -> None:
    """The job advances sync_next_run_at past now() after every run; a second
    run in the same test has to be made due again first."""
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        conn.execute(
            "UPDATE connections SET sync_next_run_at = now() - interval '1 minute' WHERE id=%s",
            (connection_id,),
        )
