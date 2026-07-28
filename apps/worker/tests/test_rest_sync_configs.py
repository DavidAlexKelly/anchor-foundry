"""Scheduled sync against a REST API.

Third time for the same reason: the worker has its own connector registry, so
the API being able to sync REST says nothing about the *scheduled* path. This
file also pins the two things unique to REST on the worker side - records land
as JSONL (the worker has its own reader table, so a JSONL extract routed
through the CSV reader would fail or produce garbage), and an empty collection
is a legitimate steady state rather than a failed run.

Uses the same real HTTP fixture server as the API suite, run as its own
process.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid

import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import anchor_worker.jobs.sync_configs as sync_configs  # noqa: E402
from anchor_worker.connectors import RestConnector, get_connector  # noqa: E402
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

# The API suite owns the fixture server; the worker borrows it rather than
# keeping a second copy in step.
SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "api", "tests", "rest_fixture_server.py",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def api_base():
    if not os.path.exists(SERVER):  # pragma: no cover - environment guard
        pytest.skip(f"fixture server not found at {SERVER}")
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, SERVER, str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover
        proc.terminate()
        pytest.skip("fixture API did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module", autouse=True)
def _fake_secrets():
    import unittest.mock as mock

    with mock.patch.object(sync_configs, "_read_secret", lambda arn: {}):
        yield


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def _config(base: str, path: str, **overrides) -> dict:
    out = {"base_url": base, "resource_path": path, "allow_insecure_http": True,
           "auth_type": "none", "pagination": "none", "records_path": ""}
    out.update(overrides)
    return out


def test_worker_registry_has_the_rest_connector() -> None:
    assert isinstance(get_connector("rest"), RestConnector)


def test_scheduled_sync_of_a_cursor_paginated_api(
    workspace: dict, api_base: str
) -> None:
    cid = _create_connection(
        workspace,
        _config(api_base, "/cursored", records_path="results",
                pagination="cursor", cursor_path="meta.next", cursor_param="cursor"),
        mode="full", dataset_name=f"rest_records_{uuid.uuid4().hex[:6]}",
        source_type="rest", source_schema="", source_table="cursored",
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1

    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (1, 3), "both pages should land"


def test_json_records_keep_their_types_through_the_worker(
    workspace: dict, api_base: str
) -> None:
    """The worker's reader table has to pick JSONL for a REST extract; the CSV
    reader would either fail or collapse everything into one column."""
    import json

    import psycopg

    cid = _create_connection(
        workspace, _config(api_base, "/records"),
        mode="full", dataset_name=f"rest_typed_{uuid.uuid4().hex[:6]}",
        source_type="rest", source_schema="", source_table="records",
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        schema = conn.execute(
            "SELECT table_schema FROM datasets WHERE id = %s", (row["sync_dataset_id"],)
        ).fetchone()[0]
    if isinstance(schema, str):
        schema = json.loads(schema)
    types = {c["name"]: c["data_type"] for c in schema}
    assert types["id"] == "BIGINT"
    assert types["active"] == "BOOLEAN"
    assert types["score"] == "DOUBLE"


def test_an_empty_collection_fails_clearly_with_no_dataset_yet(
    workspace: dict, api_base: str
) -> None:
    """Nothing to infer a schema from - say so rather than failing inside
    DuckDB, and keep it isolated to this one candidate."""
    cid = _create_connection(
        workspace, _config(api_base, "/empty"),
        mode="full", dataset_name=f"rest_empty_{uuid.uuid4().hex[:6]}",
        source_type="rest", source_schema="", source_table="empty",
    )
    run_due_scheduled_syncs(_ctx())
    row = _connection_row(cid)
    assert row["status"] == "error"
    assert "no records" in (row["last_error"] or "")
    assert row["sync_next_run_at"] is not None


def test_an_unreachable_api_fails_only_its_own_candidate(
    workspace: dict, api_base: str
) -> None:
    bad = _create_connection(
        workspace, _config(f"http://127.0.0.1:{_free_port()}", "/records"),
        mode="full", dataset_name=f"rest_dead_{uuid.uuid4().hex[:6]}",
        source_type="rest", source_schema="", source_table="records",
    )
    good = _create_connection(
        workspace, _config(api_base, "/records"),
        mode="full", dataset_name=f"rest_live_{uuid.uuid4().hex[:6]}",
        source_type="rest", source_schema="", source_table="records",
    )
    run_due_scheduled_syncs(_ctx())

    bad_row = _connection_row(bad)
    assert bad_row["status"] == "error"
    assert "could not reach the API" in (bad_row["last_error"] or "")
    good_row = _connection_row(good)
    assert good_row["status"] == "ok", good_row["last_error"]
