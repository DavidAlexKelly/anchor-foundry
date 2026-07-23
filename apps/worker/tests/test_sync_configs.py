"""Scheduled/incremental connection sync job tests — a real Postgres source
database (a separate database + login role, standing in for a customer's
system, same pattern as apps/api/tests/test_connections.py) plus real
Parquet files on disk. secretsmanager is monkeypatched out: the worker only
knows how to fetch credentials via boto3 in production, so tests stand in a
fake `_read_secret` rather than pull in moto for a single password."""
from __future__ import annotations

import json
import os
import sys
import uuid

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import anchor_worker.jobs.sync_configs as sync_configs  # noqa: E402
from anchor_worker.jobs.sync_configs import run_due_scheduled_syncs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]

SOURCE_DB = "worker_sync_source_test"
SOURCE_USER = "worker_sync_source_user"
SOURCE_PASSWORD = "w0rker-Source-99"


@pytest.fixture(scope="module", autouse=True)
def _fake_secrets():
    """No real AWS in tests: every connection in this file uses the fixed
    source-database password regardless of the (fake) secret_arn stored."""
    import unittest.mock as mock

    with mock.patch.object(sync_configs, "_read_secret", lambda arn: {"password": SOURCE_PASSWORD}):
        yield


@pytest.fixture(scope="module")
def source_database():
    """A dedicated database + role acting as the customer's Postgres, with
    one table (`items`) whose `id` doubles as primary key and sync cursor."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")
        conn.execute(f"CREATE ROLE {SOURCE_USER} LOGIN PASSWORD '{SOURCE_PASSWORD}'")
        conn.execute(f"GRANT {SOURCE_USER} TO platform")
        conn.execute(f"CREATE DATABASE {SOURCE_DB} OWNER {SOURCE_USER}")
    src_dsn = ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute("CREATE TABLE public.items (id bigint PRIMARY KEY, val text NOT NULL)")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")
    yield {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")


@pytest.fixture(autouse=True)
def _seed_items(source_database: dict) -> None:
    """Reset the shared source table to its known two rows before every
    test — tests share source_database (module-scoped, expensive to set
    up) but must not see each other's row mutations."""
    src_dsn = ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE public.items")
        conn.execute("INSERT INTO public.items (id, val) VALUES (1,'a'), (2,'b')")


@pytest.fixture()
def storage_root(tmp_path, monkeypatch) -> str:
    root = str(tmp_path / "storage")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", root)
    monkeypatch.delenv("DATA_BUCKET", raising=False)
    return root


@pytest.fixture()
def workspace(storage_root: str):
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"SyncOrg {tag}", f"sync-org-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"sync-{tag}@example.com", "Sync", f"sub-sync-{tag}"),
        ).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                       search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", f"workspaces/w-{tag}/", f"ws_{short}", f"ws-{short}-", user),
        )
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) VALUES (%s,%s,%s,%s) RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user),
        ).fetchone()[0]
    return {"tag": tag, "workspace_id": wid, "project_id": pid, "user_id": user}


def _create_connection(
    workspace: dict, source_db: dict, *, mode: str, dataset_name: str,
    primary_key_column: str | None = None, cursor_column: str | None = None,
    source_table: str = "items", cron_schedule: str = "* * * * *", next_run_at=None,
) -> uuid.UUID:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cid = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO connections (id, workspace_id, project_id, scope, name, source_type,
                                     config, secret_arn, sync_mode, sync_schedule,
                                     sync_source_schema, sync_source_table, sync_dataset_name,
                                     sync_primary_key_column, sync_cursor_column, sync_next_run_at,
                                     created_by)
            VALUES (%s,%s,%s,'project',%s,'postgres', %s::jsonb, %s,
                    CAST(%s AS sync_mode), %s, 'public', %s, %s, %s, %s, %s, %s)
            """,
            (
                cid, workspace["workspace_id"], workspace["project_id"], f"Src {uuid.uuid4().hex[:6]}",
                json.dumps(source_db), "fake:secret:arn",
                mode, cron_schedule, source_table, dataset_name,
                primary_key_column, cursor_column, next_run_at, workspace["user_id"],
            ),
        )
    return cid


def _connection_row(connection_id: uuid.UUID) -> dict:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        row = conn.execute(
            """SELECT sync_dataset_id, sync_last_cursor_value, sync_next_run_at, status, last_error
                 FROM connections WHERE id=%s""",
            (connection_id,),
        ).fetchone()
    return {
        "sync_dataset_id": row[0], "sync_last_cursor_value": row[1],
        "sync_next_run_at": row[2], "status": row[3], "last_error": row[4],
    }


def _dataset_rows(dataset_id: uuid.UUID) -> tuple[int, int]:
    """(current_version, row_count)."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        row = conn.execute(
            "SELECT current_version, row_count FROM datasets WHERE id=%s", (dataset_id,)
        ).fetchone()
    return row[0], row[1]


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def test_incremental_sync_first_run_then_merges_new_rows(workspace: dict, source_database: dict) -> None:
    cid = _create_connection(
        workspace, source_database, mode="incremental", dataset_name="synced_items",
        primary_key_column="id", cursor_column="id",
    )
    ran = run_due_scheduled_syncs(_ctx())
    assert ran >= 1

    row = _connection_row(cid)
    assert row["status"] == "ok" and row["last_error"] is None
    assert row["sync_last_cursor_value"] == "2"
    assert row["sync_next_run_at"] is not None
    assert row["sync_dataset_id"] is not None
    version, count = _dataset_rows(row["sync_dataset_id"])
    assert (version, count) == (1, 2)

    # A new upstream row arrives; force the schedule due again and re-run.
    src_dsn = ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")
    with psycopg.connect(src_dsn, autocommit=True) as conn:
        conn.execute("INSERT INTO public.items (id, val) VALUES (3,'c')")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_next_run_at = NULL WHERE id=%s", (cid,))

    run_due_scheduled_syncs(_ctx())
    row2 = _connection_row(cid)
    assert row2["sync_last_cursor_value"] == "3"
    assert row2["sync_dataset_id"] == row["sync_dataset_id"]
    version2, count2 = _dataset_rows(row2["sync_dataset_id"])
    assert (version2, count2) == (2, 3)

    # Steady state: due again, but nothing changed upstream since the cursor.
    # An empty cursor-filtered snapshot must not crash the merge (DuckDB has
    # no rows to infer types from) and must not bump the dataset version.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_next_run_at = NULL WHERE id=%s", (cid,))
    run_due_scheduled_syncs(_ctx())
    row3 = _connection_row(cid)
    assert row3["status"] == "ok" and row3["last_error"] is None
    assert row3["sync_last_cursor_value"] == "3"
    version3, count3 = _dataset_rows(row3["sync_dataset_id"])
    assert (version3, count3) == (2, 3)


def test_full_sync_replaces_dataset_wholesale(workspace: dict, source_database: dict) -> None:
    cid = _create_connection(workspace, source_database, mode="full", dataset_name="full_items")
    run_due_scheduled_syncs(_ctx())
    row = _connection_row(cid)
    assert row["status"] == "ok"
    version, count = _dataset_rows(row["sync_dataset_id"])
    assert (version, count) == (1, 2)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_next_run_at = NULL WHERE id=%s", (cid,))
    run_due_scheduled_syncs(_ctx())
    row2 = _connection_row(cid)
    version2, count2 = _dataset_rows(row2["sync_dataset_id"])
    # Full mode re-snapshots the whole table each time: same 2 rows, new version.
    assert (version2, count2) == (2, 2)


def test_failing_sync_is_recorded_and_schedule_still_advances(workspace: dict, source_database: dict) -> None:
    cid = _create_connection(
        workspace, source_database, mode="full", dataset_name="broken_items",
        source_table="no_such_table",
    )
    run_due_scheduled_syncs(_ctx())
    row = _connection_row(cid)
    assert row["status"] == "error"
    assert row["last_error"] is not None
    assert row["sync_dataset_id"] is None
    # Even a failing source gets its next occurrence scheduled, not retried instantly.
    assert row["sync_next_run_at"] is not None

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        runs = conn.execute(
            "SELECT status FROM sync_runs WHERE connection_id=%s", (cid,)
        ).fetchall()
    assert any(r[0] == "failed" for r in runs)
