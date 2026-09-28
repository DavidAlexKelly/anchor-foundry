"""A rollback keeps an incremental sync's place (§607; `data-lineage` p.73).

> "The dataset rollback feature allows you to update the data and job history
>  of a dataset. If the dataset is being built incrementally, the dataset
>  rollback feature also ensures that the incrementality of your dataset is
>  preserved." (p.73)

§361's rollback put the *data* back and left the connection's cursor at the
newest run. An incremental sync asks the source only for rows past its cursor,
so after rolling back to v1 the rows v2 and v3 had brought in were never asked
for again - missing from the dataset, with nothing anywhere to say so. Each
test below syncs, rolls back, syncs again, and counts.
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
    SOURCE_DB, SOURCE_PASSWORD, source_database,  # noqa: F401 (fixture)
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
        LocalStorageGateway(str(tmp_path_factory.mktemp("rollback-incremental-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def _source(sql: str) -> None:
    with psycopg.connect(for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute(sql)


def _admin(sql: str, *args) -> list:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cur = conn.execute(sql, args)
        return cur.fetchall() if cur.description else []


class Synced:
    """One connection syncing `orders` incrementally into its own dataset."""

    def __init__(self, client: TestClient, fx: Fixture, config: dict, name: str,
                 mode: str = "incremental") -> None:
        self.client, self.fx = client, fx
        base = f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        r = client.post(f"{base}/connections", headers=hdr(fx.editor_sub), json={
            "name": name, "source_type": "postgres", "config": config,
            "secret": {"password": SOURCE_PASSWORD}})
        assert r.status_code == 201, r.text
        self.id = r.json()["id"]
        self.schedule = f"{base}/connections/{self.id}/scheduled-sync"
        body = {"mode": mode, "source_table": "orders", "dataset_name": f"{name} {fx.tag}"}
        if mode == "incremental":
            body |= {"primary_key_column": "id", "cursor_column": "id"}
        r = client.put(self.schedule, headers=hdr(fx.editor_sub), json=body)
        assert r.status_code == 200, r.text
        self.datasets = f"{base}/datasets"
        self.dataset_id: str | None = None

    def run(self) -> None:
        r = self.client.post(f"{self.schedule}/run", headers=hdr(self.fx.editor_sub))
        assert r.status_code == 200 and r.json()["ok"], r.text
        self.dataset_id = r.json()["dataset"]["id"]

    def cursor(self) -> str | None:
        r = self.client.get(self.schedule, headers=hdr(self.fx.viewer_sub))
        return r.json()["sync_last_cursor_value"]

    def rows(self) -> int:
        r = self.client.get(f"{self.datasets}/{self.dataset_id}", headers=hdr(self.fx.viewer_sub))
        return r.json()["row_count"]

    def roll_back(self, version: int) -> None:
        r = self.client.post(f"{self.datasets}/{self.dataset_id}/rollback",
                             headers=hdr(self.fx.editor_sub), json={"version_number": version})
        assert r.status_code == 200, r.text

    def cursors(self) -> dict:
        return {int(v): c for v, c in _admin(
            "SELECT version_number, sync_cursor_value FROM dataset_versions "
            "WHERE dataset_id = %s ORDER BY version_number", self.dataset_id)}


@pytest.fixture()
def orders(source_database: dict) -> dict:
    _source("DELETE FROM public.orders")
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(1, 'a@example.com', 10), (2, 'b@example.com', 20)")
    return source_database


def _three_runs(synced: Synced) -> None:
    synced.run()                                                       # v1: 1, 2
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(3, 'c@example.com', 30)")
    synced.run()                                                       # v2: + 3
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(4, 'd@example.com', 40)")
    synced.run()                                                       # v3: + 4


def test_the_cursor_goes_back_with_the_data(client, fx, orders) -> None:
    synced = Synced(client, fx, orders, "Rolled incremental")
    _three_runs(synced)
    assert (synced.rows(), synced.cursor()) == (4, "4")
    assert synced.cursors() == {1: "2", 2: "3", 3: "4"}

    synced.roll_back(1)
    assert (synced.rows(), synced.cursor()) == (2, "2")
    # The new version is v1's data, so it carries v1's cursor too - a rollback
    # to *it* later puts back the same place.
    assert synced.cursors()[4] == "2"

    # **The point.** The next sync asks for rows past 2, which is 3 and 4 -
    # left at 4, it would have asked for nothing and kept two rows.
    synced.run()
    assert (synced.rows(), synced.cursor()) == (4, "4")


def test_a_version_no_incremental_sync_wrote_resets_the_cursor(client, fx, orders) -> None:
    """A version with no recorded place (written before migration 0127, say)
    is rolled back to with no cursor at all: the next sync reads the source
    from the beginning and merges by key - slower, and still every row."""
    synced = Synced(client, fx, orders, "Rolled unrecorded")
    _three_runs(synced)
    _admin("UPDATE dataset_versions SET sync_cursor_value = NULL "
           "WHERE dataset_id = %s AND version_number = 1", synced.dataset_id)
    synced.roll_back(1)
    assert synced.cursor() is None
    synced.run()
    assert (synced.rows(), synced.cursor()) == (4, "4")


def test_a_full_sync_keeps_no_cursor_and_is_left_alone(client, fx, orders) -> None:
    """Also the first test of a full schedule's *Run now*, which raised a
    `TypeError` from the day it was written: the route did not pass the
    `secrets` argument `run_full_sync` declared and never read (§607 removed
    the argument)."""
    synced = Synced(client, fx, orders, "Rolled full", mode="full")
    synced.run()
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(3, 'c@example.com', 30)")
    synced.run()
    assert synced.cursors() == {1: None, 2: None}
    # A full-mode connection can still hold a cursor from when it was
    # incremental; a rollback is not its business, because a full sync never
    # reads it.
    _admin("UPDATE connections SET sync_last_cursor_value = '7' WHERE id = %s", synced.id)
    synced.roll_back(1)
    assert synced.cursor() == "7" and synced.rows() == 2


def test_the_rollback_says_which_cursor_it_moved(client, fx, orders) -> None:
    synced = Synced(client, fx, orders, "Rolled audited")
    _three_runs(synced)
    synced.roll_back(2)
    [(metadata,)] = _admin(
        "SELECT metadata FROM audit_log WHERE action = 'dataset.rollback' "
        "AND resource_id = %s ORDER BY created_at DESC LIMIT 1", synced.dataset_id)
    assert metadata["sync_cursor"] == {"connection_id": synced.id, "value": "3"}
