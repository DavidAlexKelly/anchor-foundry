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


def test_a_scheduled_sync_authenticates_with_openid_connect(
    workspace: dict, s3_config: dict, s3, monkeypatch
) -> None:
    """§599, p.391: a scheduled sync is "a workflow in Foundry … required to
    authenticate with the source system", and it presents the same token an
    interactive one does - signed with the deployment's key, naming the
    source - with no credential stored anywhere."""
    import jwt
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("OIDC_ISSUER", "https://platform.example.test/api/oidc")
    monkeypatch.setenv("OIDC_SIGNING_KEY", key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode())
    traded: list[dict] = []
    real_client = boto3.client

    def spying_client(service, **kwargs):
        made = real_client(service, **kwargs)
        if service == "sts":
            original = made.assume_role_with_web_identity

            def assume(**call):
                traded.append(call)
                return original(**call)
            made.assume_role_with_web_identity = assume
        return made
    monkeypatch.setattr(boto3, "client", spying_client)

    object_key = f"oidc-{uuid.uuid4().hex[:6]}.csv"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{object_key}", Body=b"id,val\n1,a\n")
    role = "arn:aws:iam::123456789012:role/anchor-reader"
    cid = _create_connection(
        workspace, {**s3_config, "oidc_role_arn": role, "oidc_audience": "sts.amazonaws.com"},
        mode="full", dataset_name="s3_oidc", source_type="s3", source_schema="",
        source_table=object_key,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    import psycopg
    with psycopg.connect(os.environ["TEST_ADMIN_DSN"]) as db:
        resource = db.execute("SELECT resource_id FROM connections WHERE id = %s",
                              (cid,)).fetchone()[0]
    [call] = [c for c in traded if c["RoleArn"] == role]
    claims = jwt.decode(call["WebIdentityToken"], key.public_key(), algorithms=["RS256"],
                        audience="sts.amazonaws.com",
                        issuer="https://platform.example.test/api/oidc")
    assert claims["sub"] == f"connection.{resource}"


def test_an_openid_connect_source_the_deployment_cannot_sign_for_fails_alone(
    workspace: dict, s3_config: dict, s3, monkeypatch
) -> None:
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    object_key = f"oidc-{uuid.uuid4().hex[:6]}.csv"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{object_key}", Body=b"id\n1\n")
    cid = _create_connection(
        workspace, {**s3_config, "oidc_role_arn": "arn:aws:iam::123456789012:role/r",
                    "oidc_audience": "sts.amazonaws.com"},
        mode="full", dataset_name="s3_oidc_off", source_type="s3", source_schema="",
        source_table=object_key,
    )
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "error" and "OIDC_ISSUER" in row["last_error"], row


# ---- §750: a file sync on the schedule (decision 0021) -------------------------
def _file_sync(workspace: dict, s3_config: dict, folder: str, transaction: str,
               filters: dict) -> uuid.UUID:
    import json
    import psycopg

    cid = _create_connection(
        workspace, s3_config, mode="files", dataset_name=f"files_{folder}",
        source_type="s3", source_schema=folder, source_table=None,
    )
    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_file_transaction = %s, "
                     "sync_file_filters = %s::jsonb WHERE id = %s",
                     (transaction, json.dumps(filters), cid))
    return cid


def _due_again(cid) -> None:
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_next_run_at = NULL WHERE id = %s", (cid,))


def _versions(dataset_id) -> list[tuple]:
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        return conn.execute(
            "SELECT version_number, transaction_type, row_count FROM dataset_versions "
            "WHERE dataset_id = %s ORDER BY version_number", (dataset_id,)).fetchall()


def _runs(cid) -> list[tuple]:
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        return conn.execute(
            "SELECT mode::text, status, rows_synced, error FROM sync_runs "
            "WHERE connection_id = %s ORDER BY started_at", (cid,)).fetchall()


def test_a_scheduled_append_file_sync_takes_only_new_files(
    workspace: dict, s3_config: dict, s3
) -> None:
    folder = f"drop-{uuid.uuid4().hex[:6]}"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/a.csv", Body=b"id,val\n1,a\n")
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/deep/b.csv", Body=b"id,val\n2,b\n")
    # Not a file a dataset can be read from, so not one the sync lists.
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/notes.txt", Body=b"hello")
    cid = _file_sync(workspace, s3_config, folder, "APPEND",
                     {"exclude_synced": {"by_modified": False, "by_size": False}})
    assert run_due_scheduled_syncs(_ctx()) >= 1
    row = _connection_row(cid)
    assert row["status"] == "ok", row["last_error"]
    dataset = row["sync_dataset_id"]
    assert _versions(dataset) == [(1, "APPEND", 2)]

    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/c.csv", Body=b"id,val\n3,c\n")
    _due_again(cid)
    run_due_scheduled_syncs(_ctx())
    assert _versions(dataset) == [(1, "APPEND", 2), (2, "APPEND", 3)]
    # Nothing new: a run, and no version.
    _due_again(cid)
    run_due_scheduled_syncs(_ctx())
    assert len(_versions(dataset)) == 2
    assert [(m, s, r) for m, s, r, _e in _runs(cid)] == [
        ("files", "succeeded", 2), ("files", "succeeded", 1), ("files", "succeeded", 0)]


def test_a_scheduled_update_file_sync_replaces_a_changed_file(
    workspace: dict, s3_config: dict, s3
) -> None:
    folder = f"drop-{uuid.uuid4().hex[:6]}"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/a.csv", Body=b"id,val\n1,a\n")
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/b.csv", Body=b"id,val\n2,b\n")
    cid = _file_sync(workspace, s3_config, folder, "UPDATE",
                     {"exclude_synced": {"by_modified": False, "by_size": True}})
    run_due_scheduled_syncs(_ctx())
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/a.csv", Body=b"id,val\n1,a2\n7,g\n")
    _due_again(cid)
    run_due_scheduled_syncs(_ctx())
    dataset = _connection_row(cid)["sync_dataset_id"]
    # a.csv's one row became two, and b.csv's row stayed: three, not four.
    assert _versions(dataset) == [(1, "UPDATE", 2), (2, "UPDATE", 3)]
    # Remembered at its new size: an unchanged folder takes nothing.
    _due_again(cid)
    run_due_scheduled_syncs(_ctx())
    assert len(_versions(dataset)) == 2


def test_a_scheduled_file_sync_that_cannot_read_a_file_commits_nothing(
    workspace: dict, s3_config: dict, s3
) -> None:
    folder = f"drop-{uuid.uuid4().hex[:6]}"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/a.csv", Body=b"id,val\n1,a\n")
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/bad.json", Body=b"{not json")
    cid = _file_sync(workspace, s3_config, folder, "SNAPSHOT", {})
    run_due_scheduled_syncs(_ctx())
    row = _connection_row(cid)
    assert row["status"] == "error" and row["sync_dataset_id"] is None
    assert row["last_error"].startswith("bad.json could not be read")
    [(mode, status, _rows, error)] = _runs(cid)
    assert (mode, status) == ("files", "failed") and "bad.json" in error


def test_the_worker_lists_only_what_the_job_can_read() -> None:
    """`FILE_EXTENSIONS` is the job's `_READERS`, which the connector cannot
    import (the job imports it)."""
    from anchor_worker.connectors import FILE_EXTENSIONS

    assert set(FILE_EXTENSIONS) == set(sync_configs._READERS)


def _files_of(dataset_id) -> list[str]:
    import psycopg

    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        return sorted(r[0] for r in conn.execute(
            "SELECT filename FROM dataset_files WHERE dataset_id = %s", (dataset_id,)).fetchall())


def test_a_scheduled_trailing_window_holds_only_the_new_files(
    workspace: dict, s3_config: dict, s3
) -> None:
    folder = f"drop-{uuid.uuid4().hex[:6]}"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/a.csv", Body=b"id,val\n1,a\n")
    cid = _file_sync(workspace, s3_config, folder, "SNAPSHOT",
                     {"exclude_synced": {"by_modified": False, "by_size": False}})
    run_due_scheduled_syncs(_ctx())
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/b.csv", Body=b"id,val\n2,b\n")
    _due_again(cid)
    run_due_scheduled_syncs(_ctx())
    dataset = _connection_row(cid)["sync_dataset_id"]
    assert _versions(dataset) == [(1, "SNAPSHOT", 1), (2, "SNAPSHOT", 1)]
    assert _files_of(dataset) == ["b.csv"]


def test_a_dataset_a_table_sync_made_is_a_new_view_when_files_take_it_over(
    workspace: dict, s3_config: dict, s3
) -> None:
    import psycopg

    folder = f"drop-{uuid.uuid4().hex[:6]}"
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}{folder}/a.csv", Body=b"id,val\n1,a\n")
    cid = _create_connection(
        workspace, s3_config, mode="full", dataset_name=f"files_{folder}",
        source_type="s3", source_schema=folder, source_table="a.csv")
    run_due_scheduled_syncs(_ctx())
    with psycopg.connect(os.environ["TEST_ADMIN_DSN"], autocommit=True) as conn:
        conn.execute("UPDATE connections SET sync_mode = 'files', sync_source_table = NULL, "
                     "sync_file_transaction = 'APPEND', sync_file_filters = %s::jsonb, "
                     "sync_next_run_at = NULL WHERE id = %s",
                     ('{"exclude_synced": {"by_modified": false, "by_size": false}}', cid))
    run_due_scheduled_syncs(_ctx())
    dataset = _connection_row(cid)["sync_dataset_id"]
    assert [t for _v, t, _r in _versions(dataset)] == ["SNAPSHOT", "SNAPSHOT"]


def test_a_scheduled_file_sync_stays_inside_the_prefix(
    workspace: dict, s3_config: dict, s3
) -> None:
    cid = _file_sync(workspace, s3_config, "../private", "SNAPSHOT", {})
    run_due_scheduled_syncs(_ctx())
    row = _connection_row(cid)
    assert row["status"] == "error" and "invalid folder" in row["last_error"]
