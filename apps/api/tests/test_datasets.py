"""Datasets layer tests: real DuckDB, real local storage gateway, real RLS.

The sandbox tests are the security core: user SQL must be unable to reach the
filesystem or network once the dataset is materialised.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway, StorageKeyError, validate_key  # noqa: E402

CSV = b"id,email,total_pence\n1,a@example.com,1200\n2,b@example.com,80\n3,c@example.com,455\n"
JSONL = b'{"sku":"A1","qty":4}\n{"sku":"B2","qty":1}\n'


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("anchor-storage")))


@pytest.fixture(scope="module")
def client(storage: LocalStorageGateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(storage)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def upload(client: TestClient, fx: Fixture, sub: str, *, name: str,
           filename: str = "orders.csv", content: bytes = CSV):
    return client.post(
        f"{base(fx)}/upload",
        headers=hdr(sub),
        data={"name": name},
        files={"file": (filename, io.BytesIO(content), "text/csv")},
    )


# ---- storage key validation --------------------------------------------------
def test_storage_keys_reject_traversal() -> None:
    good = f"workspaces/ops-abc123/datasets/{uuid.uuid4()}/v1/data.parquet"
    assert validate_key(good) == good
    for bad in [
        "workspaces/ops/datasets/../../etc/passwd",
        "/etc/passwd",
        "workspaces/ops/datasets/notauuid/v1/data.parquet",
        "other/place/file",
    ]:
        with pytest.raises(StorageKeyError):
            validate_key(bad)


# ---- upload ------------------------------------------------------------------
def test_editor_uploads_csv_schema_and_rows_inferred(client: TestClient, fx: Fixture) -> None:
    r = upload(client, fx, fx.editor_sub, name=f"Orders {fx.tag}")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["origin"] == "upload" and body["row_count"] == 3
    assert body["current_version"] == 1
    cols = {c["name"]: c["data_type"] for c in body["table_schema"]}
    assert set(cols) == {"id", "email", "total_pence"}
    assert "BIGINT" in cols["id"]
    assert "s3_location" not in body  # storage keys are internal


def test_upload_jsonl(client: TestClient, fx: Fixture) -> None:
    r = upload(client, fx, fx.editor_sub, name=f"Stock {fx.tag}",
               filename="stock.jsonl", content=JSONL)
    assert r.status_code == 201, r.text
    assert r.json()["row_count"] == 2


def test_viewer_cannot_upload(client: TestClient, fx: Fixture) -> None:
    assert upload(client, fx, fx.viewer_sub, name="Nope").status_code == 403


def test_unsupported_extension_rejected(client: TestClient, fx: Fixture) -> None:
    r = upload(client, fx, fx.editor_sub, name="Sheet",
               filename="sheet.xlsx", content=b"PK\x03\x04")
    assert r.status_code == 422
    assert "supported" in r.json()["detail"]


def test_duplicate_name_conflicts(client: TestClient, fx: Fixture) -> None:
    assert upload(client, fx, fx.editor_sub, name=f"Orders {fx.tag}").status_code == 409


def test_malformed_file_is_clean_422(client: TestClient, fx: Fixture) -> None:
    r = upload(client, fx, fx.editor_sub, name=f"Broken {fx.tag}",
               filename="broken.parquet", content=b"this is not parquet at all")
    assert r.status_code == 422
    assert "detail" in r.json()


def _dataset_id(client: TestClient, fx: Fixture, name: str) -> str:
    r = client.get(base(fx), headers=hdr(fx.viewer_sub))
    return next(d["id"] for d in r.json() if d["name"] == name)


# ---- preview / query / export ------------------------------------------------
def test_viewer_previews_data(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    r = client.get(f"{base(fx)}/{did}/preview", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_rows"] == 3 and body["truncated"] is False
    assert ["id", "email", "total_pence"] == [c["name"] for c in body["columns"]]
    assert body["rows"][0][1] == "a@example.com"


def test_query_runs_sql_over_dataset(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    r = client.post(
        f"{base(fx)}/{did}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT sum(total_pence) AS total FROM dataset WHERE total_pence > 100"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[1655]]


def test_query_sandbox_blocks_filesystem(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    for sql in [
        "SELECT * FROM read_csv_auto('/etc/passwd')",
        "COPY dataset TO '/tmp/exfil.csv'",
        "SELECT * FROM read_parquet('/home/claude/pgdata/PG_VERSION')",
    ]:
        r = client.post(f"{base(fx)}/{did}/query", headers=hdr(fx.viewer_sub), json={"sql": sql})
        assert r.status_code == 422, f"{sql} -> {r.status_code}"
        assert "root" not in r.text  # no /etc/passwd contents anywhere


def test_bad_sql_is_clean_422(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    r = client.post(f"{base(fx)}/{did}/query", headers=hdr(fx.viewer_sub),
                    json={"sql": "SELEC broken"})
    assert r.status_code == 422
    assert "SELEC" in r.json()["detail"] or "Parser" in r.json()["detail"]


def test_export_parquet_and_csv(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    r = client.get(f"{base(fx)}/{did}/export?format=parquet", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert r.content[:4] == b"PAR1"  # parquet magic
    assert "attachment" in r.headers["content-disposition"]
    r = client.get(f"{base(fx)}/{did}/export?format=csv", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert b"a@example.com" in r.content
    assert r.text.splitlines()[0] == "id,email,total_pence"


def test_versions_listed(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    r = client.get(f"{base(fx)}/{did}/versions", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert [v["version_number"] for v in r.json()] == [1]
    assert r.json()[0]["produced_by_kind"] == "upload"


# ---- isolation & lifecycle ---------------------------------------------------
def test_outsider_gets_404_everywhere(client: TestClient, fx: Fixture) -> None:
    did = _dataset_id(client, fx, f"Orders {fx.tag}")
    for path in ["", f"/{did}", f"/{did}/preview"]:
        r = client.get(f"{base(fx)}{path}", headers=hdr(fx.outsider_sub))
        assert r.status_code == 404, path


def test_delete_removes_row_and_files(
    client: TestClient, fx: Fixture, storage: LocalStorageGateway
) -> None:
    r = upload(client, fx, fx.editor_sub, name=f"Doomed {fx.tag}")
    did = r.json()["id"]
    # preview materialises the file → confirms bytes exist
    assert client.get(f"{base(fx)}/{did}/preview", headers=hdr(fx.editor_sub)).status_code == 200
    assert client.delete(f"{base(fx)}/{did}", headers=hdr(fx.editor_sub)).status_code == 204
    assert client.get(f"{base(fx)}/{did}", headers=hdr(fx.editor_sub)).status_code == 404
    # files under the dataset prefix are gone
    root = storage._root  # test-only reach-in
    leftovers = [p for p in root.rglob("*") if did in str(p)]
    assert leftovers == []


def test_sidebar_count_includes_datasets(client: TestClient, fx: Fixture) -> None:
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}", headers=hdr(fx.viewer_sub)
    )
    assert r.json()["resource_counts"]["datasets"] >= 2


def test_data_actions_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {"dataset.upload", "dataset.query", "dataset.export", "dataset.delete"} <= actions
