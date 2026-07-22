"""Connection sync tests. Reuses the source database from test_connections
(a real second Postgres database + login role) and the local storage gateway
from the datasets layer — the full pipeline runs for real: COPY out of the
source, DuckDB to Parquet, storage, dataset + version rows.
"""
from __future__ import annotations

import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_connections import (  # noqa: E402
    SOURCE_DB, SOURCE_PASSWORD, SOURCE_USER, source_database,  # noqa: F401 (fixture)
)
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("sync-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def _source_dsn() -> str:
    return ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")


@pytest.fixture(scope="module")
def seeded_source(source_database: dict[str, object]) -> dict[str, object]:
    with psycopg.connect(_source_dsn(), autocommit=True) as conn:
        conn.execute("DELETE FROM public.orders")
        conn.execute(
            """INSERT INTO public.orders (id, customer_email, total_pence, placed_at) VALUES
               (1, 'a@example.com', 1200, now()),
               (2, 'b@example.com', 80, now()),
               (3, 'c@example.com', 455, now())"""
        )
    return source_database


@pytest.fixture(scope="module")
def connection_id(client: TestClient, fx: Fixture, seeded_source: dict[str, object]) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections",
        headers=hdr(fx.editor_sub),
        json={
            "name": "Sync Source",
            "source_type": "postgres",
            "config": seeded_source,
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def test_first_sync_creates_dataset(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "orders", "dataset_name": f"Synced Orders {fx.tag}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["created_dataset"] is True
    assert body["rows_synced"] == 3
    assert body["dataset"]["current_version"] == 1

    # The dataset is a first-class citizen: preview it through the datasets API.
    did = body["dataset"]["id"]
    r = client.get(f"{dbase(fx)}/{did}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    detail = r.json()
    assert detail["origin"] == "sync" and detail["connection_id"] == connection_id
    r = client.get(f"{dbase(fx)}/{did}/preview", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert r.json()["total_rows"] == 3


def test_resync_creates_version_two(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    with psycopg.connect(_source_dsn(), autocommit=True) as conn:
        conn.execute(
            "INSERT INTO public.orders (id, customer_email, total_pence) VALUES (4, 'd@example.com', 3100)"
        )
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "orders", "dataset_name": f"Synced Orders {fx.tag}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["created_dataset"] is False
    assert body["rows_synced"] == 4
    assert body["dataset"]["current_version"] == 2

    did = body["dataset"]["id"]
    r = client.get(f"{dbase(fx)}/{did}/versions", headers=hdr(fx.viewer_sub))
    assert [v["version_number"] for v in r.json()] == [2, 1]
    assert {v["produced_by_kind"] for v in r.json()} == {"sync"}
    # New version is what preview reads.
    r = client.get(f"{dbase(fx)}/{did}/preview", headers=hdr(fx.viewer_sub))
    assert r.json()["total_rows"] == 4


def test_sync_name_collision_with_upload_conflicts(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    import io

    r = client.post(
        f"{dbase(fx)}/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"Handmade {fx.tag}"},
        files={"file": ("x.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")},
    )
    assert r.status_code == 201
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "orders", "dataset_name": f"Handmade {fx.tag}"},
    )
    assert r.status_code == 409  # never silently overwrite an upload


def test_missing_table_is_clean_failure(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "does_not_exist"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and "does not exist" in body["error"]
    assert body["dataset"] is None


def test_bad_identifier_rejected(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "orders; DROP TABLE users"},
    )
    # 63-char pydantic bound may pass, identifier validation must not.
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert r.json()["ok"] is False and "invalid identifier" in r.json()["error"]


def test_incremental_mode_clearly_deferred(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "orders", "mode": "incremental"},
    )
    assert r.status_code == 422
    assert "cursor" in r.json()["detail"]


def test_viewer_cannot_sync_but_sees_history(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.viewer_sub),
        json={"source_table": "orders"},
    )
    assert r.status_code == 403
    r = client.get(f"{cbase(fx)}/{connection_id}/sync-runs", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    runs = r.json()
    assert len(runs) >= 3
    statuses = {run["status"] for run in runs}
    assert "succeeded" in statuses and "failed" in statuses
    ok_run = next(run for run in runs if run["status"] == "succeeded")
    assert ok_run["dataset_name"] and ok_run["rows_synced"] >= 3


def test_connection_shows_last_synced(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.get(cbase(fx), headers=hdr(fx.viewer_sub))
    row = next(c for c in r.json() if c["id"] == connection_id)
    assert row["last_synced_at"] is not None


def test_sync_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert "connection.sync" in {e["action"] for e in r.json()}
