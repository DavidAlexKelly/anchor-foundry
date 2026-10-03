"""After a restore, the database, storage and index agree again (§803;
roadmap phase 3, E.7).

> "Backup and restore has never been rehearsed. An untested backup is a
> hope." (`docs/roadmap-phase-3-fidelity.md` E.7)

Each test breaks one store the way a restore can - a file the restored
database still names but the bucket no longer holds, an index older than the
database - and reads the check's report, then repairs it the way the report
says and reads it again.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import restore_check  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PEOPLE = b"person_id,name\np1,Ada\np2,Grace\np3,Alan\n"
# A key twice and a key missing: a sync makes two objects of these four rows.
UNEVEN = b"code,label\nA,one\nA,again\n,nothing\nB,two\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("restore-check")))


@pytest.fixture(scope="module")
def client(storage) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(storage)
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx) -> str:
    return f"{wbase(fx)}/projects/{fx.project}"


def typed(client, fx, name: str, csv: bytes, key: str, prop: str) -> dict:
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"{name} {fx.tag}"},
                    files={"file": (f"{name}.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 201, r.text
    dataset = r.json()
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"{name}_{fx.tag}", "display_name": f"{name} {fx.tag}",
        "properties": [{"api_name": prop, "data_type": "string"}]})
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "dataset_id": dataset["id"], "primary_key_column": key,
        "column_mappings": {prop: prop}})
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    sync(client, fx, source_id)
    return {"dataset_id": dataset["id"], "type_id": type_id, "source_id": source_id}


def sync(client, fx, source_id: str) -> None:
    r = client.post(f"{pbase(fx)}/object-type-sources/{source_id}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text


def report(fx, storage) -> dict:
    """The check, as the owner role runs it after a restore."""
    from uuid import UUID

    from sqlalchemy.ext.asyncio import create_async_engine

    async def run() -> dict:
        engine = create_async_engine(ADMIN_DSN.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            async with engine.connect() as conn:
                return await restore_check.check(conn, storage, workspace_id=UUID(str(fx.workspace)))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def admin(sql: str, params: tuple) -> None:
    import psycopg

    with psycopg.connect(ADMIN_DSN) as conn:
        conn.execute(sql, params)


def dataset_key(dataset_id: str) -> str:
    import psycopg

    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute("SELECT s3_location FROM datasets WHERE id = %s",
                            (dataset_id,)).fetchone()[0]


def test_a_workspace_that_agrees_says_so(client, fx, storage) -> None:
    people = typed(client, fx, "people", PEOPLE, "person_id", "name")
    got = report(fx, storage)
    assert got == {"missing_current_files": [], "missing_version_files": [],
                   "stale_index": [], "index_unchecked": [], "ok": True}, got
    assert people


def test_duplicate_and_empty_keys_are_not_called_stale(client, fx, storage) -> None:
    """Four rows, two objects: what a sync makes is what is expected."""
    typed(client, fx, "uneven", UNEVEN, "code", "label")
    assert report(fx, storage)["stale_index"] == []


def test_an_index_older_than_the_database_is_named_with_its_resync(
    client, fx, storage
) -> None:
    people = typed(client, fx, "older", PEOPLE, "person_id", "name")
    admin("DELETE FROM object_instances WHERE object_type_id = %s AND primary_key = 'p2'",
          (people["type_id"],))
    stale = report(fx, storage)["stale_index"]
    assert stale == [{"object_type_id": people["type_id"], "api_name": f"older_{fx.tag}",
                      "keys_in_datasets": 3, "indexed": 2,
                      "resync_sources": [people["source_id"]]}], stale
    assert report(fx, storage)["ok"] is False
    # What the report says to do, done.
    sync(client, fx, people["source_id"])
    assert report(fx, storage)["stale_index"] == []


def test_a_file_the_bucket_lost_is_named(client, fx, storage) -> None:
    gone = typed(client, fx, "lost", PEOPLE, "person_id", "name")
    key = dataset_key(gone["dataset_id"])
    held = storage.read(key)
    os.remove(storage.local_path(key))
    try:
        got = report(fx, storage)
        assert {"dataset_id": gone["dataset_id"], "name": f"lost {fx.tag}", "key": key} in got[
            "missing_current_files"], got
        assert key in [v["key"] for v in got["missing_version_files"]], got
        assert got["ok"] is False
        # The type over it is not also called stale for want of a file to
        # read: its index cannot be judged until the file is back.
        assert gone["type_id"] not in [s["object_type_id"] for s in got["stale_index"]]
        assert {"object_type_id": gone["type_id"], "api_name": f"lost_{fx.tag}"} in got[
            "index_unchecked"], got
    finally:
        # S3 versioning's repair: the key's previous version, put back.
        storage.put(key, held)
    assert report(fx, storage)["ok"] is True


def test_distinct_keys_reads_each_file_by_its_own_key_column(tmp_path) -> None:
    import duckdb

    first, second = str(tmp_path / "a.parquet"), str(tmp_path / "b.parquet")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES ('x'), ('y'), (NULL), ('x')) t(id)) "
        f"TO '{first}' (FORMAT parquet)")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES (1, 'y'), (2, 'z')) t(n, \"odd \"\"key\")) "
        f"TO '{second}' (FORMAT parquet)")
    assert restore_check.distinct_keys([(first, "id")]) == 2
    assert restore_check.distinct_keys([(first, "id"), (second, 'odd "key')]) == 3
    assert restore_check.distinct_keys([]) == 0


def test_an_index_nothing_ever_built_is_not_stale(client, fx, storage) -> None:
    """Never synced and empty: never built, which is not what a restore does."""
    made = typed(client, fx, "unbuilt", PEOPLE, "person_id", "name")
    admin("UPDATE object_type_sources SET last_synced_at = NULL WHERE id = %s",
          (made["source_id"],))
    admin("DELETE FROM object_instances WHERE object_type_id = %s", (made["type_id"],))
    assert made["type_id"] not in [s["object_type_id"] for s in report(fx, storage)["stale_index"]]
    # Never synced but holding objects - an action log writes its entries
    # straight to the index - is compared like any other.
    sync(client, fx, made["source_id"])
    admin("UPDATE object_type_sources SET last_synced_at = NULL WHERE id = %s",
          (made["source_id"],))
    admin("DELETE FROM object_instances WHERE object_type_id = %s AND primary_key <> 'p1'",
          (made["type_id"],))
    stale = [s for s in report(fx, storage)["stale_index"] if s["object_type_id"] == made["type_id"]]
    assert [(s["keys_in_datasets"], s["indexed"]) for s in stale] == [(3, 1)], stale
    sync(client, fx, made["source_id"])
    assert report(fx, storage)["ok"] is True


def test_an_index_ahead_of_the_database_is_stale_too(client, fx, storage) -> None:
    """A database restored to before a row was added: the file it names
    holds fewer keys than the index, which a re-sync brings back in line."""
    import duckdb

    ahead = typed(client, fx, "ahead", PEOPLE, "person_id", "name")
    key = dataset_key(ahead["dataset_id"])
    held = storage.read(key)
    smaller = os.path.join(os.path.dirname(storage.local_path(key)), "smaller.parquet")
    duckdb.connect().execute(
        f"COPY (SELECT * FROM read_parquet('{storage.local_path(key)}') "
        f"WHERE person_id <> 'p3') TO '{smaller}' (FORMAT parquet)")
    with open(smaller, "rb") as handle:
        storage.put(key, handle.read())
    try:
        stale = [s for s in report(fx, storage)["stale_index"]
                 if s["object_type_id"] == ahead["type_id"]]
        assert [(s["keys_in_datasets"], s["indexed"]) for s in stale] == [(2, 3)], stale
    finally:
        storage.put(key, held)
        os.remove(smaller)


def test_a_key_storage_refuses_is_reported_rather_than_ending_the_check(
    client, fx, storage
) -> None:
    odd = typed(client, fx, "oddkey", PEOPLE, "person_id", "name")
    key = dataset_key(odd["dataset_id"])
    admin("UPDATE datasets SET s3_location = %s WHERE id = %s", ("../outside", odd["dataset_id"]))
    try:
        got = report(fx, storage)
        assert {"dataset_id": odd["dataset_id"], "name": f"oddkey {fx.tag}",
                "key": "../outside"} in got["missing_current_files"], got
    finally:
        admin("UPDATE datasets SET s3_location = %s WHERE id = %s", (key, odd["dataset_id"]))
