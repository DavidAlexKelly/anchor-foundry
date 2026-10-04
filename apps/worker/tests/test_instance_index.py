"""The scheduled sync writes the object index when a deployment has one (§811).

The API reads a type's objects from OpenSearch when `OPENSEARCH_ENDPOINT` and
`OPENSEARCH_SECRET_ARN` are set, and this job wrote Postgres regardless - so
with the index switched on, a scheduled sync reported "ok" and the objects the
API served never changed. Driven here over a real socket, through the real
`opensearchpy` client, against the API's own fixture server
(`apps/api/tests/opensearch_fixture_server.py`): the same standard the API's
store is held to, and the same server, so the two are judged by one referee.
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

import duckdb
import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import instance_index  # noqa: E402
from anchor_worker.jobs import instance_syncs  # noqa: E402
from anchor_worker.jobs.instance_syncs import run_due_object_source_syncs  # noqa: E402
from test_instance_syncs import (  # noqa: E402,F401
    ADMIN_DSN, _ctx, _instances, _set_due, _source_row, storage_root, workspace,
)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
API_SERVICES = os.path.join(ROOT, "api", "src", "services")
FIXTURE_SERVER = os.path.join(ROOT, "api", "tests", "opensearch_fixture_server.py")


@pytest.fixture(scope="module")
def cluster() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen([sys.executable, FIXTURE_SERVER, str(port)],
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


@pytest.fixture()
def index(cluster: str, monkeypatch) -> str:
    """The job's index pointed at the fixture, as `from_env` would build it
    from a deployment's endpoint and secret."""
    call(cluster, "POST", "/__reset", {})
    monkeypatch.setattr(instance_index, "from_env",
                        lambda: instance_index.InstanceIndex(cluster, "admin", "admin"))
    return cluster


def call(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{base}{path}", method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read() or b"{}")


def search_prefix(workspace: dict) -> str:
    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute("SELECT search_prefix FROM workspaces WHERE id = %s",
                            (workspace["workspace_id"],)).fetchone()[0]


def index_of(workspace: dict) -> str:
    return f"{search_prefix(workspace)}objects-{workspace['object_type_id']}"


def documents(base: str, workspace: dict) -> dict[str, dict]:
    hits = call(base, "POST", f"/{index_of(workspace)}/_search",
                {"query": {"match_all": {}}, "size": 100})["hits"]["hits"]
    return {hit["_id"]: hit["_source"] for hit in hits}


def api_doc_id(source_id, primary_key: str) -> str:
    """The API's own id for an instance, computed from its namespace as
    written in its source - so this test cannot agree with the worker by
    sharing its mistake."""
    with open(os.path.join(API_SERVICES, "instance_store.py")) as handle:
        found = re.search(r'^INSTANCE_NAMESPACE = UUID\("([0-9a-f-]+)"\)', handle.read(), re.M)
    assert found is not None
    return str(uuid.uuid5(uuid.UUID(found.group(1)), f"{source_id}:{primary_key}"))


def replace_dataset(workspace: dict, storage_root: str, version: int, rows: list[tuple]) -> None:
    key = f"{workspace['ws_prefix']}datasets/{workspace['dataset_id']}/v{version}/data.parquet"
    full = os.path.join(storage_root, key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    values = ", ".join(f"({r[0]},'{r[1]}','{r[2]}')" for r in rows)
    duckdb.connect().execute(
        f"COPY (SELECT * FROM (VALUES {values}) t(customer_id, name, email)) "
        f"TO '{full}' (FORMAT parquet)")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET s3_location=%s, current_version=%s WHERE id=%s",
                     (key, version, workspace["dataset_id"]))


def sync(workspace: dict) -> tuple:
    _set_due(workspace["source_id"])
    run_due_object_source_syncs(_ctx())
    return _source_row(workspace["source_id"])[:2]


def test_a_sync_writes_the_index_the_api_reads_and_not_postgres(index, workspace) -> None:
    assert sync(workspace) == ("ok", None)
    sid = workspace["source_id"]
    got = documents(index, workspace)
    assert set(got) == {api_doc_id(sid, "1"), api_doc_id(sid, "2")}, got
    ada = got[api_doc_id(sid, "1")]
    assert ada["properties"] == {"name": "Ada", "email": "ada@example.com"}
    assert (ada["primary_key"], ada["source_id"], ada["object_type_id"]) == (
        "1", str(sid), str(workspace["object_type_id"]))
    # The index the API would have made: its declared mapping, strict.
    mapping = call(index, "GET", f"/{index_of(workspace)}/_mapping")[index_of(workspace)]
    props = mapping["mappings"]["properties"]["properties"]
    assert props["dynamic"] == "strict"
    assert set(props["properties"]) == {"name", "email"}
    # One place, not two: Postgres is not where these objects live now.
    assert _instances(workspace["object_type_id"]) == []


def test_a_resync_sweeps_what_left_and_keeps_what_the_dataset_cannot_say(
    index, workspace, storage_root
) -> None:
    assert sync(workspace) == ("ok", None)
    sid = workspace["source_id"]
    # An edit-only property, written the way the API's actions write one.
    call(index, "POST", f"/{index_of(workspace)}/_update/{api_doc_id(sid, '1')}",
         {"doc": {"properties": {"name": "Ada", "email": "ada@example.com"}}})
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO object_type_properties (object_type_id, api_name, display_name, "
            "data_type) VALUES (%s, 'triage_note', 'Triage note', 'string')",
            (workspace["object_type_id"],))
    call(index, "PUT", f"/{index_of(workspace)}/_mapping",
         {"properties": {"properties": {"properties": {"triage_note": {"type": "keyword"}}}}})
    call(index, "POST", f"/{index_of(workspace)}/_update/{api_doc_id(sid, '1')}",
         {"doc": {"properties": {"triage_note": "call the owner"}}})
    replace_dataset(workspace, storage_root, 2,
                    [(1, "Ada", "ada@newmail.com"), (3, "Carol", "carol@example.com")])
    assert sync(workspace) == ("ok", None)
    got = documents(index, workspace)
    assert set(got) == {api_doc_id(sid, "1"), api_doc_id(sid, "3")}, got
    assert got[api_doc_id(sid, "1")]["properties"] == {
        "name": "Ada", "email": "ada@newmail.com", "triage_note": "call the owner"}


def test_a_property_declared_since_the_last_sync_widens_the_index(
    index, workspace
) -> None:
    assert sync(workspace) == ("ok", None)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO object_type_properties (object_type_id, api_name, display_name, "
            "data_type) VALUES (%s, 'tier', 'Tier', 'integer')",
            (workspace["object_type_id"],))
        conn.execute("UPDATE object_type_sources SET column_mappings = %s WHERE id = %s",
                     (json.dumps({"name": "name", "email": "email", "customer_id": "tier"}),
                      workspace["source_id"]))
    # Refused under `dynamic: "strict"` unless the index learns `tier` first.
    assert sync(workspace) == ("ok", None)
    mapping = call(index, "GET", f"/{index_of(workspace)}/_mapping")[index_of(workspace)]
    assert mapping["mappings"]["properties"]["properties"]["properties"]["tier"] == {
        "type": "long"}
    tiers = {d["primary_key"]: d["properties"]["tier"] for d in documents(index, workspace).values()}
    assert tiers == {"1": 1, "2": 2}


def test_a_sync_longer_than_a_batch_loses_nothing_at_the_seams(
    index, workspace, storage_root, monkeypatch
) -> None:
    monkeypatch.setattr(instance_index.instance_mapping, "BULK_MAX_DOCUMENTS", 3)
    replace_dataset(workspace, storage_root, 2,
                    [(1, "a", "a@x"), (2, "b", "b@x"), (3, "c", "c@x"), (3, "c2", "c2@x"),
                     (4, "d", "d@x"), (4, "d2", "d2@x"), (5, "e", "e@x")])
    assert sync(workspace) == ("ok", None)
    names = {d["primary_key"]: d["properties"]["name"] for d in documents(index, workspace).values()}
    assert names == {"1": "a", "2": "b", "3": "c2", "4": "d2", "5": "e"}


def test_only_the_last_batch_waits_for_a_refresh(index, workspace, storage_root, monkeypatch) -> None:
    """Every batch waiting would be a refresh per thousand rows; none waiting
    would sweep on the pre-sync view and delete what was just rewritten."""
    monkeypatch.setattr(instance_index.instance_mapping, "BULK_MAX_DOCUMENTS", 2)
    # Six rows, so the last batch is a full one: "last" is the batch that
    # reaches the end, not one past it.
    replace_dataset(workspace, storage_root, 2,
                    [(1, "a", "a@x"), (2, "b", "b@x"), (3, "c", "c@x"), (4, "d", "d@x"),
                     (5, "e", "e@x"), (6, "f", "f@x")])
    seen: list = []
    real = instance_index.InstanceIndex.__init__

    def spy(self, *args, **kwargs):
        real(self, *args, **kwargs)
        client = self._client
        bulk, sweep, close = client.bulk, client.delete_by_query, client.close
        client.bulk = lambda **kw: seen.append(("bulk", kw["refresh"])) or bulk(**kw)
        # The sweep refreshes too, so the API's next read does not still see
        # what was swept.
        client.delete_by_query = lambda **kw: seen.append(("sweep", kw["refresh"])) or sweep(**kw)
        client.close = lambda: seen.append(("close",)) or close()

    monkeypatch.setattr(instance_index.InstanceIndex, "__init__", spy)
    assert sync(workspace) == ("ok", None)
    assert seen == [("bulk", "false"), ("bulk", "false"), ("bulk", "wait_for"),
                    ("sweep", True), ("close",)]


def test_a_value_the_index_refuses_fails_this_source_and_says_why(index, workspace) -> None:
    # An index whose mapping disagrees with the declaration - a type changed
    # without its reindex (0006 §4) - refuses the document.
    call(index, "PUT", f"/{index_of(workspace)}", {"mappings": {"properties": {
        "source_id": {"type": "keyword"}, "updated_at": {"type": "date"},
        "properties": {"type": "object", "dynamic": "strict", "properties": {
            "name": {"type": "long"}, "email": {"type": "keyword"}}}}}})
    status, error = sync(workspace)
    assert status == "error"
    assert "refused 2 object(s)" in error, error


def test_an_unreachable_index_fails_the_source_rather_than_the_job(
    workspace, monkeypatch
) -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead = probe.getsockname()[1]
    monkeypatch.setattr(instance_index, "from_env", lambda: instance_index.InstanceIndex(
        f"http://127.0.0.1:{dead}", "admin", "admin"))
    status, error = sync(workspace)
    assert status == "error"
    assert error.startswith("the object index: "), error


def test_an_empty_dataset_sweeps_without_an_index_to_sweep(index, workspace, storage_root) -> None:
    key = f"{workspace['ws_prefix']}datasets/{workspace['dataset_id']}/v2/data.parquet"
    full = os.path.join(storage_root, key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    duckdb.connect().execute(
        "COPY (SELECT 1 AS customer_id, 'x' AS name, 'y' AS email WHERE false) "
        f"TO '{full}' (FORMAT parquet)")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET s3_location=%s WHERE id=%s",
                     (key, workspace["dataset_id"]))
    assert sync(workspace) == ("ok", None)
    # The type's index exists, empty, as it would after a sync that had rows.
    assert documents(index, workspace) == {}


def test_another_sources_objects_are_not_this_ones_to_sweep(index, workspace) -> None:
    """Two datasets can feed one type; instance identity is (source, key)."""
    assert sync(workspace) == ("ok", None)
    other = uuid.uuid4()
    body = "\n".join(json.dumps(line) for line in [
        {"update": {"_index": index_of(workspace), "_id": api_doc_id(other, "9")}},
        {"doc": {"object_type_id": str(workspace["object_type_id"]), "source_id": str(other),
                 "primary_key": "9", "properties": {"name": "Other"},
                 "updated_at": "2020-01-01T00:00:00+00:00"}, "doc_as_upsert": True},
    ]) + "\n"
    urllib.request.urlopen(urllib.request.Request(
        f"{index}/_bulk", method="POST", data=body.encode(),
        headers={"Content-Type": "application/x-ndjson"}), timeout=5).read()
    assert sync(workspace) == ("ok", None)
    assert api_doc_id(other, "9") in documents(index, workspace)


def test_an_array_property_is_mapped_as_its_element_type(index, workspace, storage_root) -> None:
    key = f"{workspace['ws_prefix']}datasets/{workspace['dataset_id']}/v2/data.parquet"
    full = os.path.join(storage_root, key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    duckdb.connect().execute(
        "COPY (SELECT * FROM (VALUES (1, 'Ada', 'a@x', '[7, 8]')) "
        f"t(customer_id, name, email, scores)) TO '{full}' (FORMAT parquet)")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET s3_location=%s WHERE id=%s",
                     (key, workspace["dataset_id"]))
        conn.execute(
            "INSERT INTO object_type_properties (object_type_id, api_name, display_name, "
            "data_type, array_of) VALUES (%s, 'scores', 'Scores', 'array', 'integer')",
            (workspace["object_type_id"],))
        conn.execute("UPDATE object_type_sources SET column_mappings = %s WHERE id = %s",
                     (json.dumps({"name": "name", "email": "email", "scores": "scores"}),
                      workspace["source_id"]))
    assert sync(workspace) == ("ok", None)
    mapping = call(index, "GET", f"/{index_of(workspace)}/_mapping")[index_of(workspace)]
    # OpenSearch has no array type: a list of integers is a `long` field.
    assert mapping["mappings"]["properties"]["properties"]["properties"]["scores"] == {
        "type": "long"}


def test_unconfigured_means_postgres(workspace, monkeypatch) -> None:
    monkeypatch.delenv("OPENSEARCH_ENDPOINT", raising=False)
    monkeypatch.setenv("OPENSEARCH_SECRET_ARN", "arn:aws:secretsmanager:x")
    assert instance_index.from_env() is None
    monkeypatch.setenv("OPENSEARCH_ENDPOINT", "https://search.example")
    monkeypatch.delenv("OPENSEARCH_SECRET_ARN")
    assert instance_index.from_env() is None
    assert sync(workspace) == ("ok", None)
    assert [r[0] for r in _instances(workspace["object_type_id"])] == ["1", "2"]


def test_the_mapping_is_the_apis_file_unchanged() -> None:
    """Copied whole because the two images share no Python (see
    `test_storage_key_parity.py`); compared whole because a mapping that
    differed by one field type would have each service's documents refused
    by the index the other made."""
    with open(os.path.join(API_SERVICES, "instance_mapping.py"), "rb") as api, open(
        instance_syncs.instance_index.instance_mapping.__file__, "rb"
    ) as worker:
        assert api.read() == worker.read()


def test_the_document_id_is_the_apis() -> None:
    sid = uuid.uuid4()
    assert instance_index.doc_id(sid, "k-1") == api_doc_id(sid, "k-1")
