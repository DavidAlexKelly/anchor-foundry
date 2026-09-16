"""Scheduled/incremental sync configuration tests - the API half of the
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

from test_api import Fixture, LocalVerifier, for_database, hdr  # noqa: E402
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
    return for_database(ADMIN_DSN, SOURCE_DB)


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


# ---- p.175's initial incremental state (§363) --------------------------------

def _set(client: TestClient, fx: Fixture, connection_id: str, **body):
    body.setdefault("mode", "incremental")
    body.setdefault("source_table", "orders")
    body.setdefault("primary_key_column", "id")
    body.setdefault("cursor_column", "id")
    return client.put(base(fx, connection_id), headers=hdr(fx.editor_sub), json=body)


def _stored(client: TestClient, fx: Fixture, connection_id: str) -> str | None:
    r = client.get(base(fx, connection_id), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()["sync_last_cursor_value"]


def test_an_incremental_sync_can_be_told_where_to_start(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """p.175 step 4: "This state consists of an incremental column **and an
    initial value**". Without it, converting a table that is already loaded
    re-reads all of it on the first run — the cost p.174 says incremental
    syncs exist to avoid."""
    r = _set(client, fx, connection_id, cursor_start_value="2000")
    assert r.status_code == 200, r.text
    assert r.json()["sync_last_cursor_value"] == "2000"
    assert _stored(client, fx, connection_id) == "2000"


def test_saving_the_schedule_again_does_not_wipe_the_progress(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """**The decision the setter turns on.** Somebody editing a cron
    expression on a sync that has been running for a month has not asked to
    re-read the whole table, and a blank field is not a request to."""
    assert _set(client, fx, connection_id, cursor_start_value="2000").status_code == 200
    again = _set(client, fx, connection_id, cron_schedule="0 * * * *")
    assert again.status_code == 200, again.text
    assert again.json()["sync_last_cursor_value"] == "2000", "the progress survived"
    assert again.json()["sync_schedule"] == "0 * * * *", "and the edit landed"


def test_changing_the_cursor_column_clears_the_stored_value(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """A value read from `id` means nothing against `placed_at`, and carrying
    it across would filter the next sync on a comparison nobody intended —
    skipping rows silently, which is the one failure an incremental sync must
    not have."""
    assert _set(client, fx, connection_id, cursor_start_value="2000").status_code == 200
    moved = _set(client, fx, connection_id, cursor_column="placed_at")
    assert moved.status_code == 200, moved.text
    assert moved.json()["sync_cursor_column"] == "placed_at"
    assert moved.json()["sync_last_cursor_value"] is None


def test_a_new_start_value_wins_over_the_column_change(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """Both at once is the ordinary case — moving to a different column is
    exactly when somebody knows where the new one should start."""
    assert _set(client, fx, connection_id, cursor_start_value="2000").status_code == 200
    moved = _set(
        client, fx, connection_id,
        cursor_column="placed_at", cursor_start_value="2024-01-01",
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["sync_last_cursor_value"] == "2024-01-01"


def test_the_stored_cursor_can_be_forgotten(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """**The remedy the sync's own refusal already names.** `run_incremental_sync`
    tells a caller to "clear the schedule's stored cursor and run a full sync
    first", and until this existed there was no way to do that — an error
    message pointing at a button nobody had."""
    assert _set(client, fx, connection_id, cursor_start_value="2000").status_code == 200
    r = client.delete(f"{base(fx, connection_id)}/cursor", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["sync_last_cursor_value"] is None
    assert _stored(client, fx, connection_id) is None


def test_forgetting_the_cursor_keeps_the_rest_of_the_configuration(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """It is "start from the beginning", not "unconfigure this sync" — the
    table, the columns and the cron all have to survive, or the remedy costs
    more than the problem."""
    assert _set(
        client, fx, connection_id, cursor_start_value="2000", cron_schedule="*/15 * * * *"
    ).status_code == 200
    r = client.delete(f"{base(fx, connection_id)}/cursor", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sync_source_table"] == "orders"
    assert body["sync_cursor_column"] == "id"
    assert body["sync_primary_key_column"] == "id"
    assert body["sync_schedule"] == "*/15 * * * *"
    assert body["sync_mode"] == "incremental"


def test_a_viewer_cannot_forget_the_cursor(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """The next sync reads the whole table again, and a viewer cannot make a
    connection do work."""
    assert _set(client, fx, connection_id, cursor_start_value="2000").status_code == 200
    r = client.delete(f"{base(fx, connection_id)}/cursor", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403
    assert _stored(client, fx, connection_id) == "2000"


def test_forgetting_the_cursor_is_audited(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    assert client.delete(
        f"{base(fx, connection_id)}/cursor", headers=hdr(fx.editor_sub)
    ).status_code == 200
    entries = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert "connection.scheduled_sync.forget_cursor" in {e["action"] for e in entries.json()}
