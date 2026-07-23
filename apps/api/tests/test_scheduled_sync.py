"""Scheduled/incremental sync configuration tests — the API half of the
worker's scheduled_connection_syncs job (apps/worker/tests/test_sync_configs.py
covers the worker's firing side). Reuses the source database + orders table
from test_connections; "run now" here executes the identical pipeline the
worker uses, just triggered inline instead of by cron.
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
        LocalStorageGateway(str(tmp_path_factory.mktemp("scheduled-sync-storage")))
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
               (2, 'b@example.com', 80, now())"""
        )
    return source_database


@pytest.fixture(scope="module")
def connection_id(client: TestClient, fx: Fixture, seeded_source: dict[str, object]) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections",
        headers=hdr(fx.editor_sub),
        json={
            "name": "Scheduled Sync Source",
            "source_type": "postgres",
            "config": seeded_source,
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def base(fx: Fixture, connection_id: str) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections/{connection_id}/scheduled-sync"


def test_default_schedule_is_unconfigured(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.get(base(fx, connection_id), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sync_mode"] == "federated"
    assert body["sync_schedule"] is None
    assert body["sync_source_table"] is None
    assert body["sync_next_run_at"] is None


def test_viewer_cannot_set_schedule(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.put(
        base(fx, connection_id), headers=hdr(fx.viewer_sub),
        json={"mode": "full", "source_table": "orders"},
    )
    assert r.status_code == 403


def test_incremental_requires_pk_and_cursor(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.put(
        base(fx, connection_id), headers=hdr(fx.editor_sub),
        json={"mode": "incremental", "source_table": "orders"},
    )
    assert r.status_code == 422
    assert "cursor" in r.json()["detail"] or "primary key" in r.json()["detail"]


def test_set_incremental_schedule_computes_next_run_at(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.put(
        base(fx, connection_id), headers=hdr(fx.editor_sub),
        json={
            "mode": "incremental", "source_table": "orders",
            "dataset_name": f"Scheduled Orders {fx.tag}",
            "primary_key_column": "id", "cursor_column": "id",
            "cron_schedule": "*/15 * * * *",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sync_mode"] == "incremental"
    assert body["sync_source_table"] == "orders"
    assert body["sync_primary_key_column"] == "id"
    assert body["sync_cursor_column"] == "id"
    assert body["sync_schedule"] == "*/15 * * * *"
    assert body["sync_next_run_at"] is not None
    assert body["sync_dataset_id"] is None  # nothing has run yet

    r = client.get(base(fx, connection_id), headers=hdr(fx.viewer_sub))
    assert r.json()["sync_source_table"] == "orders"


def test_invalid_cron_expression_is_422(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.put(
        base(fx, connection_id), headers=hdr(fx.editor_sub),
        json={
            "mode": "full", "source_table": "orders",
            "cron_schedule": "not a cron expression",
        },
    )
    assert r.status_code == 422


def test_run_now_incremental_creates_then_merges(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.post(f"{base(fx, connection_id)}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["created_dataset"] is True
    assert body["rows_synced"] == 2
    assert body["dataset"]["current_version"] == 1

    schedule = client.get(base(fx, connection_id), headers=hdr(fx.viewer_sub)).json()
    assert schedule["sync_dataset_id"] == body["dataset"]["id"]
    assert schedule["sync_last_cursor_value"] == "2"

    with psycopg.connect(_source_dsn(), autocommit=True) as conn:
        conn.execute("INSERT INTO public.orders (id, customer_email, total_pence) VALUES (3, 'c@example.com', 99)")

    r = client.post(f"{base(fx, connection_id)}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body2 = r.json()
    assert body2["ok"] is True and body2["created_dataset"] is False
    assert body2["rows_synced"] == 3  # merged, not just the new row
    assert body2["dataset"]["current_version"] == 2

    schedule2 = client.get(base(fx, connection_id), headers=hdr(fx.viewer_sub)).json()
    assert schedule2["sync_last_cursor_value"] == "3"


def test_viewer_cannot_run_now(client: TestClient, fx: Fixture, connection_id: str) -> None:
    r = client.post(f"{base(fx, connection_id)}/run", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403


def test_clear_schedule_stops_cron_but_keeps_target(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    r = client.delete(base(fx, connection_id), headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sync_schedule"] is None
    assert body["sync_next_run_at"] is None
    assert body["sync_source_table"] == "orders"  # target survives

    # "run now" still works off the retained target.
    r = client.post(f"{base(fx, connection_id)}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_run_now_without_target_configured_is_422(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections",
        headers=hdr(fx.editor_sub),
        json={"name": "No Schedule Yet", "source_type": "postgres",
              "config": {"host": "h", "database": "d", "user": "u"}},
    )
    assert r.status_code == 201
    cid = r.json()["id"]
    r = client.post(f"{base(fx, cid)}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 422
    assert "scheduled-sync" in r.json()["detail"]


def test_scheduled_sync_actions_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {
        "connection.scheduled_sync.set", "connection.scheduled_sync.clear",
        "connection.scheduled_sync.run",
    } <= actions
