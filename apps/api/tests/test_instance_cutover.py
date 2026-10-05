"""The cutover command copies a deployment's objects into its index (§813).

`backfill()` was the cutover's migration step with nothing to run it: these
drive `instance_cutover.run` as the one-off task would, with the owner role,
against the OpenSearch fixture server over a real socket, after objects were
synced on Postgres the ordinary way.
"""
from __future__ import annotations

import asyncio
import io
import os
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import instance_cutover, instance_store  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

API_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def opensearch() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    script = os.path.join(API_DIR, "tests", "opensearch_fixture_server.py")
    proc = subprocess.Popen([sys.executable, script, str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{base}/", timeout=0.5).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("the OpenSearch fixture server did not start")
    yield base
    proc.terminate()


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("cutover"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def synced(client, fx, csv: bytes, key: str) -> dict:
    """A type with one source, synced on Postgres (no index configured)."""
    tag = uuid.uuid4().hex[:6]
    wbase = f"/api/workspaces/{fx.workspace}"
    pbase = f"{wbase}/projects/{fx.project}"
    r = client.post(f"{pbase}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"Cut {tag}"},
                    files={"file": ("cut.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]
    r = client.post(f"{wbase}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"cut_{tag}", "display_name": f"Cut {tag}",
        "properties": [{"api_name": "name", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(f"{pbase}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "dataset_id": dataset, "primary_key_column": key,
        "column_mappings": {"name": "name"}})
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(f"{pbase}/object-type-sources/{source_id}/sync", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return {"type_id": type_id, "source_id": source_id}


def cutover(opensearch: str, workspace_id=None) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go() -> dict:
        gateway = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
        engine = create_async_engine(ADMIN_DSN.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            async with engine.connect() as conn:
                return await instance_cutover.run(conn, gateway, workspace_id=workspace_id)
        finally:
            await gateway.close()
            await engine.dispose()

    return asyncio.run(go())


def indexed(opensearch: str, fx, type_id: str) -> dict[str, dict]:
    import json

    with psycopg.connect(ADMIN_DSN) as conn:
        prefix = conn.execute("SELECT search_prefix FROM workspaces WHERE id = %s",
                              (str(fx.workspace),)).fetchone()[0]
    req = urllib.request.Request(
        f"{opensearch}/{prefix}objects-{type_id}/_search", method="POST",
        data=json.dumps({"query": {"match_all": {}}, "size": 100}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        hits = json.loads(resp.read())["hits"]["hits"]
    return {hit["_source"]["primary_key"]: hit["_source"] for hit in hits}


def probe_run(fx, type_id: str, instance_id) -> str:
    """A historical action run that names an instance by its Postgres id."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        action_type = conn.execute(
            "INSERT INTO action_types (workspace_id, object_type_id, api_name, display_name) "
            "VALUES (%s, %s, %s, 'Cutover probe') RETURNING id",
            (str(fx.workspace), type_id, f"probe_{uuid.uuid4().hex[:6]}")).fetchone()[0]
        return conn.execute(
            "INSERT INTO action_runs (action_type_id, instance_id, status, submitted_values) "
            "VALUES (%s, %s, 'succeeded', '{}'::jsonb) RETURNING id",
            (action_type, instance_id)).fetchone()[0]


def postgres_ids(type_id: str) -> dict[str, tuple]:
    with psycopg.connect(ADMIN_DSN) as conn:
        return {r[2]: (r[0], r[1]) for r in conn.execute(
            "SELECT id, source_id, primary_key FROM object_instances WHERE object_type_id = %s",
            (type_id,)).fetchall()}


def test_the_cutover_copies_a_workspace_and_moves_its_audit_trail(client, fx, opensearch) -> None:
    people = synced(client, fx, b"pid,name\np1,Ada\np2,Grace\n", "pid")
    ids = postgres_ids(people["type_id"])
    run_id = probe_run(fx, people["type_id"], ids["p1"][0])

    report = cutover(opensearch, uuid.UUID(str(fx.workspace)))
    assert [w["workspace_id"] for w in report["workspaces"]] == [str(fx.workspace)]
    assert report["instances"] >= 2 and report["action_runs_remapped"] >= 1
    assert {k: v["properties"] for k, v in indexed(opensearch, fx, people["type_id"]).items()} == {
        "p1": {"name": "Ada"}, "p2": {"name": "Grace"}}
    # Committed: the run's instance is its document's id now, seen from a
    # connection of its own.
    with psycopg.connect(ADMIN_DSN) as conn:
        moved = conn.execute("SELECT instance_id FROM action_runs WHERE id = %s",
                             (run_id,)).fetchone()[0]
    assert str(moved) == instance_store._doc_id(uuid.UUID(str(ids["p1"][1])), "p1")


def test_a_second_run_catches_up_without_duplicating(client, fx, opensearch) -> None:
    """Backfill, flip, backfill again: the second pass is the catch-up."""
    made = synced(client, fx, b"pid,name\nq1,One\n", "pid")
    cutover(opensearch, uuid.UUID(str(fx.workspace)))
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO object_instances (object_type_id, source_id, primary_key, properties) "
            "VALUES (%s, %s, 'q2', '{\"name\": \"Two\"}'::jsonb)",
            (made["type_id"], made["source_id"]))
    again = cutover(opensearch, uuid.UUID(str(fx.workspace)))
    assert sorted(indexed(opensearch, fx, made["type_id"])) == ["q1", "q2"]
    # Every run already points at its document: nothing left to move.
    assert again["action_runs_remapped"] == 0


def test_a_workspace_larger_than_a_page_arrives_whole(client, fx, opensearch, monkeypatch) -> None:
    """Paged by (source, key): a page boundary inside one source and between
    two, and an audit trail spanning pages, lose nothing."""
    monkeypatch.setattr(instance_store, "BACKFILL_PAGE", 2)
    first = synced(client, fx, b"pid,name\na1,A\na2,B\na3,C\n", "pid")
    second = synced(client, fx, b"pid,name\nb1,D\nb2,E\n", "pid")
    runs = {}
    for made, key in ((first, "a3"), (second, "b1")):
        old, source = postgres_ids(made["type_id"])[key]
        runs[probe_run(fx, made["type_id"], old)] = instance_store._doc_id(uuid.UUID(str(source)), key)
    report = cutover(opensearch, uuid.UUID(str(fx.workspace)))
    assert sorted(indexed(opensearch, fx, first["type_id"])) == ["a1", "a2", "a3"]
    assert sorted(indexed(opensearch, fx, second["type_id"])) == ["b1", "b2"]
    with psycopg.connect(ADMIN_DSN) as conn:
        for run_id, expected in runs.items():
            got = conn.execute("SELECT instance_id FROM action_runs WHERE id = %s",
                               (run_id,)).fetchone()[0]
            assert str(got) == expected
    with psycopg.connect(ADMIN_DSN) as conn:
        total = conn.execute(
            "SELECT count(*), count(DISTINCT i.source_id) FROM object_instances i "
            "JOIN object_types t ON t.id = i.object_type_id WHERE t.workspace_id = %s",
            (str(fx.workspace),)).fetchone()
    assert (report["instances"], report["workspaces"][0]["sources"]) == total


def test_every_workspace_when_none_is_named(fx, monkeypatch) -> None:
    """Each workspace once, committed after its own copy. `backfill` is
    stubbed: the development database holds every workspace every test run
    ever made, and copying them all would test patience, not the loop."""
    from sqlalchemy.ext.asyncio import create_async_engine

    seen: list[tuple[str, str]] = []

    async def stub(conn, gateway, *, workspace_id, search_prefix):
        seen.append((str(workspace_id), search_prefix))
        return {"instances": 1, "sources": 1, "action_runs_remapped": 0}

    monkeypatch.setattr(instance_store, "backfill", stub)

    async def go() -> dict:
        engine = create_async_engine(ADMIN_DSN.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            async with engine.connect() as conn:
                return await instance_cutover.run(conn, object())
        finally:
            await engine.dispose()

    report = asyncio.run(go())
    with psycopg.connect(ADMIN_DSN) as conn:
        expected = sorted((str(r[0]), r[1]) for r in conn.execute(
            "SELECT id, search_prefix FROM workspaces"))
    assert sorted(seen) == expected
    assert len(seen) == len(set(seen))
    assert report["instances"] == len(expected)
    assert [w["workspace_id"] for w in report["workspaces"]] == [w for w, _ in seen]


def test_it_refuses_to_start_without_an_index() -> None:
    env = {k: v for k, v in os.environ.items()
           if k not in ("OPENSEARCH_ENDPOINT", "OPENSEARCH_SECRET_ARN")}
    env["OPENSEARCH_ENDPOINT"] = "https://search.example"
    done = subprocess.run([sys.executable, "-m", "src.services.instance_cutover"],
                          cwd=API_DIR, env=env, capture_output=True, text=True, timeout=60)
    assert done.returncode == 2, done.stderr
    assert "OPENSEARCH_SECRET_ARN" in done.stderr
