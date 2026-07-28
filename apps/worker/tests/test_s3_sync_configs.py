"""Scheduled sync against an S3 / object-storage source.

Same reason test_mysql_sync_configs.py exists: the worker has its own
connector registry, so a source type working in the API proves nothing about
its *scheduled* path. This one additionally covers the format question - the
worker must ingest a Parquet object as Parquet, not push it through the CSV
reader - and the object-as-cursor semantics.

Runs against a real moto.server process over HTTP; skips if moto is absent.
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

pytest.importorskip("moto", reason="moto not installed")
import boto3  # noqa: E402

import anchor_worker.jobs.sync_configs as sync_configs  # noqa: E402
from anchor_worker.connectors import S3Connector, get_connector  # noqa: E402
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

BUCKET = "anchor-worker-bucket"
PREFIX = "landing/"
ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
REGION = "eu-north-1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def s3_endpoint():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover - environment guard
        proc.terminate()
        pytest.skip("moto server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module", autouse=True)
def _fake_secrets():
    import unittest.mock as mock

    with mock.patch.object(
        sync_configs,
        "_read_secret",
        lambda arn: {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY},
    ):
        yield


@pytest.fixture(scope="module")
def s3(s3_endpoint: str):
    client = boto3.client(
        "s3", endpoint_url=s3_endpoint, region_name=REGION,
        aws_access_key_id=ACCESS_KEY, aws_secret_access_key=SECRET_KEY,
    )
    client.create_bucket(
        Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    return client


@pytest.fixture(scope="module")
def s3_config(s3_endpoint: str, s3) -> dict:
    return {
        "bucket": BUCKET, "prefix": PREFIX, "region": REGION,
        "endpoint_url": s3_endpoint,
    }


def _ctx():
    return build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})


def test_worker_registry_has_the_s3_connector() -> None:
    assert isinstance(get_connector("s3"), S3Connector)


def test_scheduled_sync_of_a_csv_object(workspace: dict, s3_config: dict, s3) -> None:
    key = f"items-{uuid.uuid4().hex[:6]}.csv"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{key}", Body=b"id,val\n1,a\n2,b\n")
    cid = _create_connection(
        workspace, s3_config, mode="full", dataset_name="s3_items",
        source_type="s3", source_schema="", source_table=key,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1

    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (1, 2)


def test_scheduled_sync_ingests_parquet_as_parquet(
    workspace: dict, s3_config: dict, s3, tmp_path
) -> None:
    """The worker has its own reader table; a Parquet object routed through the
    CSV reader would fail outright or produce one garbage column."""
    import duckdb

    local = str(tmp_path / "m.parquet")
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT 1::BIGINT AS id, 2.5::DOUBLE AS score UNION ALL SELECT 2, 7.5) "
        f"TO '{local}' (FORMAT parquet)"
    )
    con.close()
    key = f"metrics-{uuid.uuid4().hex[:6]}.parquet"
    with open(local, "rb") as fh:
        s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{key}", Body=fh.read())

    cid = _create_connection(
        workspace, s3_config, mode="full", dataset_name="s3_metrics",
        source_type="s3", source_schema="", source_table=key,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1

    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (1, 2)

    import json
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        schema = conn.execute(
            "SELECT table_schema FROM datasets WHERE id = %s", (row["sync_dataset_id"],)
        ).fetchone()[0]
    if isinstance(schema, str):
        schema = json.loads(schema)
    types = {c["name"]: c["data_type"] for c in schema}
    assert types["id"] == "BIGINT" and types["score"] == "DOUBLE"


def test_incremental_skips_an_unchanged_object(workspace: dict, s3_config: dict, s3) -> None:
    key = f"feed-{uuid.uuid4().hex[:6]}.csv"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{key}", Body=b"id,val\n1,a\n2,b\n")
    cid = _create_connection(
        workspace, s3_config, mode="incremental", dataset_name="s3_feed",
        primary_key_column="id", cursor_column="id",
        source_type="s3", source_schema="", source_table=key,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (1, 2)

    # Unchanged object: the run succeeds and writes no new version.
    _make_due(cid)
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    assert _dataset_rows(row["sync_dataset_id"]) == (1, 2)

    # Rewritten object: its rows merge in by primary key.
    time.sleep(1.1)
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{key}", Body=b"id,val\n2,B\n3,c\n")
    _make_due(cid)
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    version, rows = _dataset_rows(row["sync_dataset_id"])
    assert (version, rows) == (2, 3)


def test_missing_object_fails_only_its_own_candidate(
    workspace: dict, s3_config: dict, s3
) -> None:
    good_key = f"ok-{uuid.uuid4().hex[:6]}.csv"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{good_key}", Body=b"id,val\n1,a\n")
    bad = _create_connection(
        workspace, s3_config, mode="full", dataset_name="s3_missing",
        source_type="s3", source_schema="", source_table="not-there.csv",
    )
    good = _create_connection(
        workspace, s3_config, mode="full", dataset_name="s3_present",
        source_type="s3", source_schema="", source_table=good_key,
    )
    run_due_scheduled_syncs(_ctx())

    bad_row = _connection_row(bad)
    assert bad_row["status"] == "error"
    assert "does not exist" in (bad_row["last_error"] or "")
    assert bad_row["sync_next_run_at"] is not None
    good_row = _connection_row(good)
    assert good_row["status"] == "ok", good_row["last_error"]


def _make_due(connection_id) -> None:
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        conn.execute(
            "UPDATE connections SET sync_next_run_at = now() - interval '1 minute' WHERE id=%s",
            (connection_id,),
        )
