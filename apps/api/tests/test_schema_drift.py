"""Schema drift detection (roadmap Connections item 6, migration 0018).

A source that adds, drops, or retypes a column used to slide through
silently: the sync succeeded, the dataset quietly changed shape, and whatever
read it downstream broke later somewhere else. Each sync now records the diff
against the version it replaced on its `sync_runs` row.

The diff itself is pure and tested directly; the recording is tested end to
end through the real sync path against the real Postgres source database, by
actually altering the source table between syncs.

Also covers the health surface that exposes it (roadmap item 7) - the two ship
together, and the runs this module already produces are exactly what a health
summary has to aggregate.
"""
from __future__ import annotations

import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_connections import (  # noqa: E402,F401 (fixture used by name)
    SOURCE_DB,
    SOURCE_PASSWORD,
    SOURCE_USER,
    source_database,
)
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.dataset_engine import ColumnSchema, diff_schemas  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


def _source_dsn() -> str:
    return ADMIN_DSN.replace("/platform?", f"/{SOURCE_DB}?")


# ---- the diff itself ---------------------------------------------------------
def _cols(*pairs: tuple[str, str]) -> list[ColumnSchema]:
    return [ColumnSchema(name=n, data_type=t) for n, t in pairs]


def test_no_baseline_is_not_drift() -> None:
    """A dataset's first version has nothing to compare against - reporting
    every column as 'added' would make the first sync of every table look like
    a schema incident."""
    assert diff_schemas(None, _cols(("id", "BIGINT"))) is None
    assert diff_schemas([], _cols(("id", "BIGINT"))) is None


def test_unchanged_schema_reports_nothing() -> None:
    previous = [{"name": "id", "data_type": "BIGINT"}, {"name": "email", "data_type": "VARCHAR"}]
    assert diff_schemas(previous, _cols(("id", "BIGINT"), ("email", "VARCHAR"))) is None


def test_reordering_columns_is_not_drift() -> None:
    """A source reordering its SELECT changes nothing a consumer can read;
    reporting it would bury the changes that matter."""
    previous = [{"name": "id", "data_type": "BIGINT"}, {"name": "email", "data_type": "VARCHAR"}]
    assert diff_schemas(previous, _cols(("email", "VARCHAR"), ("id", "BIGINT"))) is None


def test_added_removed_and_retyped_are_reported_separately() -> None:
    previous = [
        {"name": "id", "data_type": "BIGINT"},
        {"name": "email", "data_type": "VARCHAR"},
        {"name": "legacy", "data_type": "VARCHAR"},
    ]
    changes = diff_schemas(
        previous, _cols(("id", "BIGINT"), ("email", "BIGINT"), ("created_at", "TIMESTAMP"))
    )
    assert changes == {
        "added": [{"name": "created_at", "data_type": "TIMESTAMP"}],
        "removed": [{"name": "legacy", "data_type": "VARCHAR"}],
        "retyped": [{"name": "email", "from": "VARCHAR", "to": "BIGINT"}],
    }
    # Only non-empty keys are present, so a consumer can test truthiness.
    only_added = diff_schemas(previous, _cols(
        ("id", "BIGINT"), ("email", "VARCHAR"), ("legacy", "VARCHAR"), ("extra", "BIGINT")
    ))
    assert only_added is not None and set(only_added) == {"added"}


# ---- recorded on the run, end to end ----------------------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("drift-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def cbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/connections"


@pytest.fixture(scope="module")
def drift_table(source_database: dict) -> str:
    """A table this module owns outright, so altering it can't disturb the
    shared `orders` fixture other suites assert against."""
    table = "drifting"
    with psycopg.connect(_source_dsn(), autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS public.{table}")
        conn.execute(
            f"CREATE TABLE public.{table} (id bigint PRIMARY KEY, label text, legacy text)"
        )
        conn.execute(f"INSERT INTO public.{table} VALUES (1,'a','x'), (2,'b','y')")
        # source_database's blanket GRANT ran before this table existed, so it
        # needs its own - a grant covers the tables present when it is issued.
        conn.execute(f"GRANT ALL ON public.{table} TO {SOURCE_USER}")
    yield table
    with psycopg.connect(_source_dsn(), autocommit=True) as conn:
        conn.execute(f"DROP TABLE IF EXISTS public.{table}")


@pytest.fixture(scope="module")
def connection_id(client: TestClient, fx: Fixture, source_database: dict) -> str:
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"Drift source {fx.tag}",
            "source_type": "postgres",
            "config": source_database,
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sync(client: TestClient, fx: Fixture, connection_id: str, table: str, name: str) -> dict:
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": table, "dataset_name": name},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    return r.json()


def _latest_run(client: TestClient, fx: Fixture, connection_id: str) -> dict:
    r = client.get(f"{cbase(fx)}/{connection_id}/sync-runs", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()[0]


def test_drift_is_recorded_on_the_run_that_caused_it(
    client: TestClient, fx: Fixture, connection_id: str, drift_table: str
) -> None:
    name = f"Drift dataset {fx.tag}"

    # First sync: a dataset's first version has no baseline.
    _sync(client, fx, connection_id, drift_table, name)
    assert _latest_run(client, fx, connection_id)["schema_changes"] is None

    # Second sync, source unchanged: still nothing to report.
    _sync(client, fx, connection_id, drift_table, name)
    assert _latest_run(client, fx, connection_id)["schema_changes"] is None

    # Now actually drift the source: drop a column, add another, retype a third.
    # The retype has to carry values that read as the new type - drift compares
    # what *landed*, and the CSV wire format re-infers types (a column altered
    # to bigint but left all-NULL comes back from DuckDB as text, so nothing
    # would have changed as far as the dataset is concerned).
    with psycopg.connect(_source_dsn(), autocommit=True) as conn:
        conn.execute(f"ALTER TABLE public.{drift_table} DROP COLUMN legacy")
        conn.execute(f"ALTER TABLE public.{drift_table} ADD COLUMN score double precision")
        conn.execute(
            f"ALTER TABLE public.{drift_table} ALTER COLUMN label TYPE bigint USING (id * 10)"
        )
        conn.execute(f"UPDATE public.{drift_table} SET score = id * 1.5")

    _sync(client, fx, connection_id, drift_table, name)
    changes = _latest_run(client, fx, connection_id)["schema_changes"]
    assert changes is not None, "a dropped, added and retyped column must be reported"
    assert [c["name"] for c in changes["removed"]] == ["legacy"]
    assert [c["name"] for c in changes["added"]] == ["score"]
    assert [c["name"] for c in changes["retyped"]] == ["label"]
    assert changes["retyped"][0]["from"] != changes["retyped"][0]["to"]

    # And the next unchanged sync goes quiet again - drift is reported on the
    # run that caused it, not sticky forever afterwards.
    _sync(client, fx, connection_id, drift_table, name)
    assert _latest_run(client, fx, connection_id)["schema_changes"] is None


def test_drift_is_visible_to_a_viewer(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    """Sync health is a read surface - a viewer must be able to see that a
    source changed shape without being able to trigger anything."""
    r = client.get(f"{cbase(fx)}/{connection_id}/sync-runs", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert any(run["schema_changes"] for run in r.json())


# ---- sync health summary (roadmap item 7) -----------------------------------
def _health(client: TestClient, fx: Fixture, connection_id: str) -> dict:
    r = client.get(f"{cbase(fx)}/sync-health", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    match = [h for h in r.json() if h["connection_id"] == connection_id]
    assert match, "the connection should appear in its own project's health list"
    return match[0]


def test_health_summarises_the_recent_runs(
    client: TestClient, fx: Fixture, connection_id: str, drift_table: str
) -> None:
    health = _health(client, fx, connection_id)
    assert health["total_runs"] >= 4  # the drift test above ran several
    assert health["succeeded"] == health["total_runs"]
    assert health["failed"] == 0
    assert health["success_rate"] == 1.0
    assert health["last_status"] == "succeeded"
    assert health["last_rows_synced"] == 2
    # Duration is derived from the run's own timestamps, so it is real elapsed
    # time rather than a placeholder.
    assert health["last_duration_seconds"] is not None
    assert health["last_duration_seconds"] >= 0
    assert health["drifted"] >= 1, "the earlier retype/add/drop must be counted"


def test_a_failed_run_moves_the_success_rate(
    client: TestClient, fx: Fixture, connection_id: str
) -> None:
    before = _health(client, fx, connection_id)
    r = client.post(
        f"{cbase(fx)}/{connection_id}/sync",
        headers=hdr(fx.editor_sub),
        json={"source_table": "table_that_is_not_there"},
    )
    assert r.status_code == 200 and r.json()["ok"] is False

    after = _health(client, fx, connection_id)
    assert after["failed"] == before["failed"] + 1
    assert after["last_status"] == "failed"
    assert after["last_error"] and "does not exist" in after["last_error"]
    assert after["success_rate"] < 1.0


def test_health_covers_every_connection_including_never_synced(
    client: TestClient, fx: Fixture, source_database: dict
) -> None:
    """A connection with no runs still needs a row - the list page renders one
    per connection, and a missing entry would read as "loading" forever."""
    r = client.post(
        cbase(fx),
        headers=hdr(fx.editor_sub),
        json={
            "name": f"Never synced {fx.tag}",
            "source_type": "postgres",
            "config": source_database,
            "secret": {"password": SOURCE_PASSWORD},
        },
    )
    assert r.status_code == 201
    cid = r.json()["id"]

    health = _health(client, fx, cid)
    assert health["total_runs"] == 0
    assert health["success_rate"] is None  # nothing to rate, not "0% healthy"
    assert health["last_status"] is None
    assert health["last_duration_seconds"] is None
    assert health["next_run_at"] is None and health["sync_schedule"] is None
    assert client.delete(f"{cbase(fx)}/{cid}", headers=hdr(fx.editor_sub)).status_code == 204


def test_health_reports_the_schedule_and_next_run(
    client: TestClient, fx: Fixture, connection_id: str, drift_table: str
) -> None:
    r = client.put(
        f"{cbase(fx)}/{connection_id}/scheduled-sync",
        headers=hdr(fx.editor_sub),
        json={
            "mode": "full",
            "source_schema": "public",
            "source_table": drift_table,
            "dataset_name": f"Drift dataset {fx.tag}",
            "cron_schedule": "0 * * * *",
        },
    )
    assert r.status_code == 200, r.text

    health = _health(client, fx, connection_id)
    assert health["sync_schedule"] == "0 * * * *"
    assert health["next_run_at"] is not None


def test_outsider_cannot_read_sync_health(client: TestClient, fx: Fixture) -> None:
    assert client.get(
        f"{cbase(fx)}/sync-health", headers=hdr(fx.outsider_sub)
    ).status_code == 404
