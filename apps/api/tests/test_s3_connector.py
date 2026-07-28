"""S3 / object-storage connector tests - the first non-relational source type.

Runs against a real `moto.server` process over HTTP rather than moto's
in-process patching: the connector builds its own boto3 client and the
endpoint_url/credential config path is a real part of what shipped (it is what
makes S3-compatible stores work), so the test drives genuine signed HTTP
requests instead of asserting against a patched botocore. Skips cleanly if
moto isn't installed.

The interesting assertions here are the ones a relational connector can't
make: that a Parquet object lands as Parquet (never round-tripped through
CSV), that "incremental" means the object changed rather than rows being new,
and that the connection's configured prefix is a real boundary.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("moto", reason="moto not installed")
import boto3  # noqa: E402

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.connectors import (  # noqa: E402
    ConnectorConfigError,
    S3Connector,
    SourceReadError,
    get_connector,
)
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

BUCKET = "anchor-source-bucket"
PREFIX = "landing/"
ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
REGION = "eu-north-1"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def s3_endpoint() -> str:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover - environment guard
        proc.terminate()
        pytest.skip("moto server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def s3(s3_endpoint: str):
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        region_name=REGION,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )
    client.create_bucket(
        Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    return client


@pytest.fixture(scope="module")
def seeded_bucket(s3, tmp_path_factory: pytest.TempPathFactory) -> dict:
    """A CSV, a Parquet, a nested file, an unsupported file, and a folder
    marker - so discovery has something to filter and something to nest."""
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{PREFIX}orders.csv",
        Body=b"id,customer_email,total_pence\n1,a@example.com,1200\n2,b@example.com,80\n",
    )
    # Parquet built for real, so the type-preservation assertion means something.
    import duckdb

    parquet_path = str(tmp_path_factory.mktemp("pq") / "events.parquet")
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT 1::BIGINT AS id, 'launch' AS label, 4.5::DOUBLE AS score "
        "UNION ALL SELECT 2, 'retry', 9.25) "
        f"TO '{parquet_path}' (FORMAT parquet)"
    )
    con.close()
    with open(parquet_path, "rb") as fh:
        s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}events.parquet", Body=fh.read())

    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}nested/regions.csv", Body=b"code,name\nse,Sweden\n")
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}notes.txt", Body=b"not a dataset")
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}emptyfolder/", Body=b"")
    # Outside the configured prefix - must never be reachable through it.
    s3.put_object(Bucket=BUCKET, Key="private/secrets.csv", Body=b"k,v\ntop,secret\n")
    return {"bucket": BUCKET}


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("s3-sync-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def _config(s3_endpoint: str) -> dict:
    return {
        "bucket": BUCKET,
        "prefix": PREFIX,
        "region": REGION,
        "endpoint_url": s3_endpoint,
    }


@pytest.fixture(scope="module")
def connection_id(client: TestClient, fx: Fixture, s3_endpoint: str, seeded_bucket: dict) -> str:
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"Landing bucket {uuid.uuid4().hex[:6]}",
            "source_type": "s3",
            "config": _config(s3_endpoint),
            "secret": {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY},
        },
    )
    assert r.status_code == 201, r.text
    assert SECRET_KEY not in r.text
    return r.json()["id"]


# ---- registry & config -------------------------------------------------------
def test_s3_is_registered_and_offered(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{cbase(fx)}/source-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    types = {t["type"]: t for t in r.json()}
    assert {"postgres", "mysql", "s3"} <= set(types)
    s3_type = types["s3"]
    assert s3_type["secret_fields"] == ["access_key_id", "secret_access_key"]
    assert {"bucket", "prefix", "region", "endpoint_url"} <= set(
        s3_type["config_schema"]["properties"]
    )
    assert isinstance(get_connector("s3"), S3Connector)


def test_prefix_is_normalised_and_traversal_refused() -> None:
    c = S3Connector()
    assert c.validate_config({"bucket": "abc", "prefix": "raw"})["prefix"] == "raw/"
    assert c.validate_config({"bucket": "abc", "prefix": "/raw/"})["prefix"] == "raw/"
    assert c.validate_config({"bucket": "abc"})["prefix"] == ""
    with pytest.raises(ConnectorConfigError) as exc:
        c.validate_config({"bucket": "abc", "prefix": "raw/../../etc"})
    assert "prefix" in str(exc.value)
    with pytest.raises(ConnectorConfigError):
        c.validate_config({"bucket": "no"})  # below S3's 3-char minimum


# ---- test & discover ---------------------------------------------------------
def test_test_endpoint_reaches_the_bucket(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["error"] is None
    assert body["connection"]["status"] == "ok"


def test_test_endpoint_reports_a_missing_bucket_cleanly(
    client: TestClient, fx: Fixture, s3_endpoint: str
) -> None:
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"Missing bucket {uuid.uuid4().hex[:6]}",
            "source_type": "s3",
            "config": {**_config(s3_endpoint), "bucket": "no-such-bucket-here"},
            "secret": {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY},
        },
    )
    cid = r.json()["id"]
    r = client.post(f"{cbase(fx)}/{cid}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert "does not exist" in r.json()["error"]
    assert client.delete(f"{cbase(fx)}/{cid}", headers=hdr(fx.editor_sub)).status_code == 204


def test_discover_lists_files_with_inferred_columns(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(f"{cbase(fx)}/{connection_id}/discover", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    found = {(t["schema_name"], t["name"]): t for t in r.json()}

    # Files at the prefix root report an empty "folder"; nesting is preserved.
    orders = found[("", "orders.csv")]
    assert orders["kind"] == "file"
    assert [c["name"] for c in orders["columns"]] == ["id", "customer_email", "total_pence"]
    assert found[("nested", "regions.csv")]["kind"] == "file"

    # Parquet types come back as Parquet's, not re-inferred from text.
    events = found[("", "events.parquet")]
    types = {c["name"]: c["data_type"] for c in events["columns"]}
    assert types["id"] == "BIGINT" and types["score"] == "DOUBLE"

    # Unsupported extensions and folder markers are filtered out, and nothing
    # outside the configured prefix is ever listed.
    assert ("", "notes.txt") not in found
    assert not any(name.endswith("/") for _, name in found)
    assert not any("secrets.csv" == name for _, name in found)


# ---- sync --------------------------------------------------------------------
def test_full_sync_of_a_csv_object(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={
            "source_schema": "",
            "source_table": "orders.csv",
            "dataset_name": f"S3 Orders {fx.tag}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["created_dataset"] is True and body["rows_synced"] == 2

    did = body["dataset"]["id"]
    preview = client.get(f"{dbase(fx)}/{did}/preview", headers=hdr(fx.viewer_sub)).json()
    assert preview["total_rows"] == 2


def test_parquet_object_keeps_its_types(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """The reason `snapshot` returns an Extract instead of always writing CSV:
    a Parquet source already carries its types, and routing it through CSV
    would throw them away and re-guess."""
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={
            "source_schema": "",
            "source_table": "events.parquet",
            "dataset_name": f"S3 Events {fx.tag}",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["rows_synced"] == 2

    detail = client.get(
        f"{dbase(fx)}/{body['dataset']['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    schema = {c["name"]: c["data_type"] for c in detail["table_schema"]}
    assert schema["id"] == "BIGINT"
    assert schema["score"] == "DOUBLE"


def test_nested_folder_object_syncs(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={
            "source_schema": "nested",
            "source_table": "regions.csv",
            "dataset_name": f"S3 Regions {fx.tag}",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert r.json()["rows_synced"] == 1


def test_missing_object_is_a_clean_failed_run(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_schema": "", "source_table": "nope.csv"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "does not exist" in r.json()["error"]


def test_unsupported_file_type_is_refused(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_schema": "", "source_table": "notes.txt"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "unsupported file type" in r.json()["error"]


def test_the_configured_prefix_is_a_boundary(s3_endpoint: str) -> None:
    """`private/secrets.csv` exists in the bucket but outside the connection's
    prefix. No combination of folder/name may reach it - the prefix is the
    thing an operator scopes a connection with, so it has to hold."""
    connector = S3Connector()
    config = connector.validate_config(_config(s3_endpoint))
    secret = {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY}
    import tempfile

    for schema, table in [
        ("..", "secrets.csv"),
        ("../private", "secrets.csv"),
        ("", "../private/secrets.csv"),
        ("", "nested/regions.csv"),  # a slash in the file name is not a path
    ]:
        with tempfile.TemporaryDirectory() as tmp, pytest.raises(SourceReadError):
            connector.snapshot(
                config,
                secret,
                source_schema=schema,
                source_table=table,
                dest_dir=tmp,
                max_bytes=1024 * 1024,
            )


def test_size_cap_refuses_an_oversized_object(s3_endpoint: str, seeded_bucket: dict) -> None:
    connector = S3Connector()
    config = connector.validate_config(_config(s3_endpoint))
    secret = {"access_key_id": ACCESS_KEY, "secret_access_key": SECRET_KEY}
    import tempfile

    with tempfile.TemporaryDirectory() as tmp, pytest.raises(SourceReadError) as exc:
        connector.snapshot(
            config,
            secret,
            source_schema="",
            source_table="orders.csv",
            dest_dir=tmp,
            max_bytes=8,  # the object is comfortably larger than this
        )
    assert "exceeds" in str(exc.value)


# ---- incremental: the object is the unit of change ---------------------------
def test_incremental_resyncs_only_when_the_object_changes(
    client: TestClient, fx: Fixture, connection_id: str, s3
) -> None:
    name = f"S3 Incremental {fx.tag}"
    r = client.put(
        f"{cbase(fx)}/{connection_id}/scheduled-sync",
        headers=hdr(fx.editor_sub),
        json={
            "mode": "incremental",
            "source_schema": "",
            "source_table": "feed.csv",
            "dataset_name": name,
            "primary_key_column": "id",
            "cursor_column": "id",  # accepted and ignored for object storage
        },
    )
    assert r.status_code == 200, r.text

    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}feed.csv", Body=b"id,val\n1,a\n2,b\n")
    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["rows_synced"] == 2
    did = body["dataset"]["id"]
    first_version = body["dataset"]["current_version"]

    # Unchanged object: nothing to do, and no pointless new version.
    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert r.json()["dataset"]["current_version"] == first_version

    # Rewritten object: its rows merge in by primary key.
    time.sleep(1.1)  # LastModified has second resolution on some backends
    s3.put_object(Bucket=BUCKET, Key=f"{PREFIX}feed.csv", Body=b"id,val\n2,B\n3,c\n")
    r = client.post(f"{cbase(fx)}/{connection_id}/scheduled-sync/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body["error"]
    assert body["dataset"]["current_version"] > first_version
    assert body["rows_synced"] == 3, "id 1 kept, id 2 updated, id 3 added"

    preview = client.get(f"{dbase(fx)}/{did}/preview", headers=hdr(fx.viewer_sub)).json()
    assert preview["total_rows"] == 3
