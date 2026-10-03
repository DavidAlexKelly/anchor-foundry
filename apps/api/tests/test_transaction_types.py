"""Transaction types on dataset versions (§747; decision 0020; db 0144;
Foundry `data-integration` p.22-26).

> "There are four possible transaction types: SNAPSHOT, APPEND, UPDATE, and
>  DELETE." (p.22)

Every writer says how its version relates to the one before. Each test below
drives a real writer and reads the type it stored, so a writer that names the
wrong one, or none, fails here. The action cases reuse
`test_action_undo_effects`' world.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_action_undo_effects import (  # noqa: E402,F401 (fixtures)
    client, define, fx, keys, pbase, run_action, undo_run, world,
)
from test_rollback_incremental import Synced, _source  # noqa: E402
from test_connections import source_database  # noqa: E402,F401 (fixture)
from src.routes import connections as conn_routes  # noqa: E402
from src.services import dataset_engine as engine  # noqa: E402
from src.services import datasets as dataset_service  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module", autouse=True)
def _secrets(client) -> None:
    """The syncs below make connections, which keep a password."""
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())


def types(dataset_id: str) -> list[str]:
    with psycopg.connect(ADMIN_DSN) as conn:
        return [r[0] for r in conn.execute(
            "SELECT transaction_type FROM dataset_versions WHERE dataset_id = %s "
            "ORDER BY version_number", (dataset_id,)).fetchall()]


def upload(client: TestClient, fx: Fixture, body: bytes = ROWS, filename: str = "a.csv") -> dict:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Txn {uuid.uuid4().hex[:6]}"},
        files={"file": (filename, io.BytesIO(body), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()


def add_file(client, fx, did: str, body: bytes, filename: str) -> None:
    r = client.post(f"{pbase(fx)}/datasets/{did}/files", headers=hdr(fx.editor_sub),
                    files={"file": (filename, io.BytesIO(body), "text/csv")})
    assert r.status_code == 200, r.text


# ---- the column ------------------------------------------------------------------

def test_a_version_must_say_its_type_and_only_a_known_one(client, fx) -> None:
    """No default once the backfill is done (db 0144), so a writer that leaves
    it out fails rather than becoming a SNAPSHOT by omission."""
    did = upload(client, fx)["id"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute("INSERT INTO dataset_versions (dataset_id, version_number) "
                         "VALUES (%s, 99)", (did,))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO dataset_versions (dataset_id, version_number, "
                         "transaction_type) VALUES (%s, 99, 'DELETE')", (did,))


@pytest.mark.anyio
async def test_staging_refuses_a_type_it_does_not_know(client, fx) -> None:
    with pytest.raises(ValueError, match="unknown transaction type 'snapshot'"):
        await dataset_service.stage_version(
            None, None, dataset_id=uuid.uuid4(), workspace_id=uuid.uuid4(),
            parquet_bytes=b"", schema=[], row_count=0, produced_by_kind="upload",
            produced_by_id=None, created_by=uuid.uuid4(), transaction_type="snapshot")


def test_a_write_that_only_adds_rows_appends() -> None:
    assert dataset_service.written_transaction([], []) == "APPEND"
    assert dataset_service.written_transaction([], None) == "APPEND"
    # An update that set nothing changed nothing.
    assert dataset_service.written_transaction([("k1", {})], []) == "APPEND"
    assert dataset_service.written_transaction([("k1", {"name": "x"})], []) == "UPDATE"
    assert dataset_service.written_transaction([], ["k1"]) == "UPDATE"


def test_a_merge_says_whether_it_replaced_a_row(tmp_path) -> None:
    import duckdb

    con = duckdb.connect()
    old, new, both = (str(tmp_path / f"{n}.parquet") for n in ("old", "new", "both"))
    con.execute(f"COPY (SELECT * FROM (VALUES (1, 'a'), (2, 'b')) t(id, v)) TO '{old}' (FORMAT parquet)")
    con.execute(f"COPY (SELECT * FROM (VALUES (3, 'c')) t(id, v)) TO '{new}' (FORMAT parquet)")
    con.execute(f"COPY (SELECT * FROM (VALUES (2, 'B'), (4, 'd')) t(id, v)) TO '{both}' (FORMAT parquet)")
    assert engine.merge_transaction(None, new, "id") == "SNAPSHOT"
    assert engine.merge_transaction(old, new, "id") == "APPEND"
    assert engine.merge_transaction(old, both, "id") == "UPDATE"


# ---- the writers -----------------------------------------------------------------

def test_an_uploaded_dataset_through_its_life(client, fx) -> None:
    """p.10's two uploads are p.22's two types; everything that rewrites the
    whole view is a SNAPSHOT."""
    did = upload(client, fx)["id"]
    add_file(client, fx, did, b"id,val\n3,30\n", "b.csv")              # v2 append
    add_file(client, fx, did, b"id,val\n1,11\n", "a.csv")              # v3 replace
    r = client.post(f"{pbase(fx)}/datasets/{did}/parse", headers=hdr(fx.editor_sub),
                    json={"add_row_number": True})                     # v4 re-parse
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/datasets/{did}/rollback", headers=hdr(fx.editor_sub),
                    json={"version_number": 2})                        # v5 rollback
    assert r.status_code == 200, r.text
    assert types(did) == ["SNAPSHOT", "APPEND", "UPDATE", "SNAPSHOT", "SNAPSHOT"]
    versions = client.get(f"{pbase(fx)}/datasets/{did}/versions", headers=hdr(fx.viewer_sub))
    assert [v["transaction_type"] for v in versions.json()] == [
        "SNAPSHOT", "SNAPSHOT", "UPDATE", "APPEND", "SNAPSHOT"]

    r = client.post(f"{pbase(fx)}/datasets/{did}/fork", headers=hdr(fx.editor_sub),
                    json={"version_number": 3, "name": f"Fork {uuid.uuid4().hex[:6]}"})
    assert r.status_code in (200, 201), r.text
    assert types(r.json()["id"]) == ["SNAPSHOT"]


def test_an_incremental_sync_appends_unless_it_replaces(client, fx, source_database) -> None:
    """Decided per run (decision 0020 §2): a run whose keys are all new adds to
    the view; one that brings back a key the view holds replaced its row."""
    _source("DELETE FROM public.orders")
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(1, 'a@example.com', 10), (2, 'b@example.com', 20)")
    synced = Synced(client, fx, source_database, f"Txn sync {uuid.uuid4().hex[:6]}")
    # Cursor on the total, so a changed total brings an old key back.
    r = client.put(synced.schedule, headers=hdr(fx.editor_sub), json={
        "mode": "incremental", "source_table": "orders", "dataset_name": f"Txn {fx.tag} {uuid.uuid4().hex[:4]}",
        "primary_key_column": "id", "cursor_column": "total_pence"})
    assert r.status_code == 200, r.text
    synced.run()                                                       # v1
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(3, 'c@example.com', 30)")
    synced.run()                                                       # v2: + 3
    _source("UPDATE public.orders SET total_pence = 50 WHERE id = 1")
    synced.run()                                                       # v3: 1 replaced
    assert types(str(synced.dataset_id)) == ["SNAPSHOT", "APPEND", "UPDATE"]
    assert synced.rows() == 3


def test_a_full_sync_is_a_snapshot_every_time(client, fx, source_database) -> None:
    _source("DELETE FROM public.orders")
    _source("INSERT INTO public.orders (id, customer_email, total_pence) VALUES "
            "(1, 'a@example.com', 10)")
    synced = Synced(client, fx, source_database, f"Txn full {uuid.uuid4().hex[:6]}", mode="full")
    synced.run()
    synced.run()
    assert types(str(synced.dataset_id)) == ["SNAPSHOT", "SNAPSHOT"]


def test_an_action_appends_only_when_it_only_creates(client, fx, world) -> None:
    create = define(client, fx, world, "txn_create", [
        {"api_name": "new_key", "display_name": "Key", "data_type": "string"},
        {"api_name": "new_name", "display_name": "Name", "data_type": "string"}], [
        {"kind": "create_object", "config": {
            "primary_key": "new_key", "properties": {"name": "new_name"}}}])
    rename = define(client, fx, world, "txn_rename", [
        {"api_name": "name", "display_name": "Name", "data_type": "string"}], [
        {"kind": "modify_object", "config": {"property": "name", "parameter": "name"}}])
    remove = define(client, fx, world, "txn_remove", [],
                    [{"kind": "delete_object", "config": {}}])
    did = world["dataset_id"]
    anyone = keys(client, fx, world)["p3"]

    before = len(types(did))
    made = run_action(client, fx, create, anyone["id"], {"new_key": "t1", "new_name": "Tess"})
    run_action(client, fx, rename, anyone["id"], {"name": "Alan M. Turing"})
    run_action(client, fx, remove, keys(client, fx, world)["t1"]["id"], {})
    assert types(did)[before:] == ["APPEND", "UPDATE", "UPDATE"]

    # An undo is typed by what it does: undoing the create deletes a row.
    again = run_action(client, fx, create, anyone["id"], {"new_key": "t2", "new_name": "Tom"})
    assert undo_run(client, fx, create, again["run_id"]).status_code == 200
    assert types(did)[-2:] == ["APPEND", "UPDATE"]
    assert made["run_id"]


def test_a_listener_archive_appends(client, fx) -> None:
    from test_listener_archive import archive, listener, send

    made = listener(client, fx, f"Txn {uuid.uuid4().hex[:6]}")
    send(client, made, b"one")
    assert archive(client, fx, made).status_code == 200
    send(client, made, b"two")
    assert archive(client, fx, made).status_code == 200
    with psycopg.connect(ADMIN_DSN) as conn:
        (did,) = conn.execute("SELECT archive_dataset_id FROM listeners WHERE id = %s",
                              (made["id"],)).fetchone()
    assert types(str(did)) == ["APPEND", "APPEND"]


def test_a_batch_of_edits_is_one_update(client, fx, world) -> None:
    rename = define(client, fx, world, "txn_batch_rename", [
        {"api_name": "name", "display_name": "Name", "data_type": "string"}], [
        {"kind": "modify_object", "config": {"property": "name", "parameter": "name"}}])
    now = keys(client, fx, world)
    r = client.post(f"{pbase(fx)}/actions/{rename}/execute-batch", headers=hdr(fx.editor_sub),
                    json={"edits": [
                        {"instance_id": now["p1"]["id"], "values": {"name": "A. Lovelace"}},
                        {"instance_id": now["p4"]["id"], "values": {"name": "H. Lamarr"}}]})
    assert r.status_code == 200, r.text
    assert types(world["dataset_id"])[-1] == "UPDATE"


def test_a_model_run_writes_a_snapshot(client, fx) -> None:
    source = upload(client, fx)
    model = client.post(f"{pbase(fx)}/models", headers=hdr(fx.editor_sub), json={
        "name": f"Txn copy {uuid.uuid4().hex[:6]}", "code": "SELECT * FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    assert model.status_code == 201, model.text
    for _ in range(2):
        run = client.post(f"{pbase(fx)}/models/{model.json()['id']}/run", headers=hdr(fx.editor_sub))
        assert run.status_code in (200, 201), run.text
    assert types(run.json()["output_dataset"]["id"]) == ["SNAPSHOT", "SNAPSHOT"]
