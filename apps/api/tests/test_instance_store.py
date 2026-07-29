"""Instance store tests (ROADMAP Objects item 1).

Two halves:

  * `OpenSearchInstanceStore` against a real HTTP server speaking the
    OpenSearch REST subset it uses (`opensearch_fixture_server.py`, its own
    process), driven through the real `opensearchpy` client. The same
    standard the REST connector is held to. This proves the gateway forms
    correct requests and reads responses correctly; it cannot prove a real
    cluster agrees, and STATUS says so rather than implying otherwise.
  * The cutover itself: the whole objects API running against the OpenSearch
    store instead of Postgres, and the backfill that moves existing data
    across without orphaning the audit trail.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import instance_store  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PORT = 9209
BASE = f"http://127.0.0.1:{PORT}"
PREFIX = "ws-fixture-"
CSV = b"employee_id,full_name,department\n1,Ada,Engineering\n2,Grace,Research\n"


@pytest.fixture
def anyio_backend() -> str:
    # anyio's pytest plugin needs this; the rest of the suite is synchronous
    # (TestClient), so there is no project-wide async configuration to lean on.
    return "asyncio"


@pytest.fixture(scope="module")
def opensearch() -> str:
    """A real socket, in its own process."""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "opensearch_fixture_server.py")
    proc = subprocess.Popen([sys.executable, script, str(PORT)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/", timeout=0.5).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("the OpenSearch fixture server did not start")
    yield BASE
    proc.terminate()
    proc.wait(timeout=5)


def reset(base: str) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{base}/__reset", method="POST", data=b""), timeout=2
    ).read()


@pytest.fixture()
async def store(opensearch: str):
    reset(opensearch)
    gateway = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    yield gateway
    # Closed inside the test's own loop - aiohttp sessions belong to the loop
    # that created them, so a close() from anywhere else is worse than none.
    await gateway.close()


def _rows(n: int = 2) -> list[tuple[str, dict]]:
    return [(str(i), {"full_name": f"person-{i}", "rank": i}) for i in range(1, n + 1)]


# ---- the gateway itself, over real HTTP -------------------------------------
@pytest.mark.anyio
async def test_upsert_is_idempotent_on_the_same_source_row(store) -> None:
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)

    assert await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=_rows(2), synced_at=now,
    ) == 2
    rows, total = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=50, offset=0
    )
    assert total == 2

    # Re-syncing the same source rows updates rather than duplicating - the
    # whole reason the doc id is derived from (source_id, primary_key).
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=[("1", {"full_name": "renamed", "rank": 1})],
        synced_at=now + timedelta(seconds=1),
    )
    rows, total = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=50, offset=0
    )
    assert total == 2
    assert rows[0]["properties"]["full_name"] == "renamed"
    assert rows[0]["id"] == instance_store._doc_id(source_id, "1")
    uuid.UUID(rows[0]["id"])  # a real uuid, not "source:key"


@pytest.mark.anyio
async def test_stale_instances_are_removed_and_others_are_not(store) -> None:
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    other_source = uuid.uuid4()
    first = datetime.now(timezone.utc)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=_rows(3), synced_at=first,
    )
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=other_source,
        rows=_rows(1), synced_at=first,
    )

    second = first + timedelta(minutes=1)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=_rows(1), synced_at=second,
    )
    removed = await store.delete_stale_instances(
        search_prefix=PREFIX, source_id=source_id, synced_before=second
    )
    assert removed == 2, "rows 2 and 3 vanished upstream"

    _, total = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=50, offset=0
    )
    assert total == 2, "the other source's instance is untouched"


@pytest.mark.anyio
async def test_reads_are_scoped_by_object_type(store) -> None:
    mine, theirs, source_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=mine, source_id=source_id,
        rows=_rows(1), synced_at=now,
    )
    doc = instance_store._doc_id(source_id, "1")

    found = await store.get_instance(
        search_prefix=PREFIX, object_type_id=mine, instance_id=doc
    )
    assert found is not None and found["primary_key"] == "1"

    # It exists, but under another type - not this caller's to see.
    assert await store.get_instance(
        search_prefix=PREFIX, object_type_id=theirs, instance_id=doc
    ) is None
    assert await store.get_instance(
        search_prefix=PREFIX, object_type_id=mine, instance_id=str(uuid.uuid4())
    ) is None


@pytest.mark.anyio
async def test_paging_and_ordering(store) -> None:
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    base = datetime.now(timezone.utc)
    for i in range(1, 6):
        await store.upsert_instances(
            search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
            rows=[(str(i), {"rank": i})], synced_at=base + timedelta(seconds=i),
        )

    page, total = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=2, offset=0
    )
    assert total == 5
    assert [r["primary_key"] for r in page] == ["5", "4"], "newest first"
    page, _ = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=2, offset=2
    )
    assert [r["primary_key"] for r in page] == ["3", "2"]

    with pytest.raises(ValueError, match="search_after"):
        await store.list_for_type(
            search_prefix=PREFIX, object_type_id=type_id, limit=50,
            offset=instance_store.MAX_RESULT_WINDOW,
        )


@pytest.mark.anyio
async def test_update_properties_merges_and_refuses_a_missing_instance(store) -> None:
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=[("1", {"full_name": "Ada", "rank": 1})],
        synced_at=datetime.now(timezone.utc),
    )
    doc = instance_store._doc_id(source_id, "1")

    await store.update_properties(
        search_prefix=PREFIX, object_type_id=type_id, instance_id=doc,
        properties={"rank": 9},
    )
    found = await store.get_instance(
        search_prefix=PREFIX, object_type_id=type_id, instance_id=doc
    )
    assert found["properties"] == {"full_name": "Ada", "rank": 9}, "merged, not replaced"

    with pytest.raises(LookupError):
        await store.update_properties(
            search_prefix=PREFIX, object_type_id=type_id,
            instance_id=str(uuid.uuid4()), properties={"rank": 1},
        )


@pytest.mark.anyio
async def test_each_workspace_gets_its_own_index(store) -> None:
    """The isolation anchor: a query against one workspace's index cannot
    reach another's documents even if a filter were forgotten."""
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    await store.upsert_instances(
        search_prefix="ws-alpha-", object_type_id=type_id, source_id=source_id,
        rows=_rows(2), synced_at=now,
    )
    await store.upsert_instances(
        search_prefix="ws-beta-", object_type_id=type_id, source_id=source_id,
        rows=_rows(1), synced_at=now,
    )
    _, alpha = await store.list_for_type(
        search_prefix="ws-alpha-", object_type_id=type_id, limit=50, offset=0
    )
    _, beta = await store.list_for_type(
        search_prefix="ws-beta-", object_type_id=type_id, limit=50, offset=0
    )
    assert (alpha, beta) == (2, 1)

    from src.services.instance_store import _index_name

    assert _index_name("ws-alpha-") != _index_name("ws-beta-")


# ---- the cutover: the real API on the real store -----------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("instance-store")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture()
def mapped(client: TestClient, fx: Fixture):
    """A dataset mapped to an object type, ready to sync."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"People {tag}"},
        files={"file": ("people.csv", io.BytesIO(CSV), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"person_{tag}", "display_name": f"Person {tag}",
              "properties": [
                  {"api_name": "full_name", "data_type": "string"},
                  {"api_name": "department", "data_type": "string"},
              ]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset,
              "primary_key_column": "employee_id",
              "column_mappings": {"full_name": "full_name", "department": "department"}},
    )
    assert r.status_code == 201, r.text
    return {"type_id": type_id, "source_id": r.json()["id"], "dataset": dataset}


@pytest.fixture()
def on_opensearch(opensearch: str):
    """Installs the OpenSearch store process-wide for the duration of a test.

    The client is deliberately not closed here: it is created outside any
    loop and used inside TestClient's, and aiohttp sessions belong to the
    loop that created them. The interpreter reclaims it at exit, which is
    also exactly what a real API process does.
    """
    reset(opensearch)
    instance_store.configure_instance_store(
        instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    )
    yield
    instance_store.configure_instance_store(None)


def test_the_whole_instance_api_works_on_opensearch(
    client: TestClient, fx: Fixture, mapped: dict, on_opensearch
) -> None:
    """The cutover's real assertion: the same endpoints, the same responses,
    a different store underneath."""
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{mapped['source_id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert r.status_code == 200, r.text
    assert r.json()["upserted"] == 2

    r = client.get(
        f"/api/workspaces/{fx.workspace}/object-types/{mapped['type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 2
    names = {i["properties"]["full_name"] for i in page["items"]}
    assert names == {"Ada", "Grace"}

    instance_id = page["items"][0]["id"]
    r = client.get(
        f"/api/workspaces/{fx.workspace}/object-types/{mapped['type_id']}"
        f"/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert r.json()["id"] == instance_id

    # Nothing landed in Postgres - the store really is the one configured.
    import psycopg
    from test_api import ADMIN_DSN

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        count = conn.execute(
            "SELECT count(*) FROM object_instances WHERE object_type_id = %s",
            (mapped["type_id"],),
        ).fetchone()[0]
    assert count == 0


def test_a_missing_instance_is_still_a_404(
    client: TestClient, fx: Fixture, mapped: dict, on_opensearch
) -> None:
    r = client.get(
        f"/api/workspaces/{fx.workspace}/object-types/{mapped['type_id']}"
        f"/instances/{uuid.uuid4()}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 404


def test_backfill_moves_postgres_instances_and_keeps_the_audit_trail(
    client: TestClient, fx: Fixture, mapped: dict, opensearch: str
) -> None:
    """The cutover procedure: sync on Postgres, backfill, flip, read the same
    data back. `action_runs.instance_id` has to survive the id change."""
    import asyncio

    import psycopg
    from test_api import ADMIN_DSN

    reset(opensearch)
    # Populate Postgres through the normal path.
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{mapped['source_id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert r.json()["upserted"] == 2

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        old = conn.execute(
            "SELECT id, source_id, primary_key FROM object_instances "
            "WHERE object_type_id = %s ORDER BY primary_key",
            (mapped["type_id"],),
        ).fetchall()
        assert len(old) == 2
        # A historical action run pointing at one of them.
        action_type_id = conn.execute(
            """INSERT INTO action_types (workspace_id, object_type_id, api_name,
                                         display_name, editable_properties)
               VALUES (%s, %s, %s, 'Backfill probe', '[]'::jsonb) RETURNING id""",
            (fx.workspace, mapped["type_id"], f"probe_{uuid.uuid4().hex[:6]}"),
        ).fetchone()[0]
        run_id = conn.execute(
            """INSERT INTO action_runs (action_type_id, instance_id, status, submitted_values)
               VALUES (%s, %s, 'succeeded', '{}'::jsonb) RETURNING id""",
            (action_type_id, old[0][0]),
        ).fetchone()[0]

    async def run_backfill() -> dict:
        from src.lib.db import user_connection

        gateway = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
        async with user_connection(fx.owner) as conn:
            prefix = await _search_prefix(conn, fx.workspace)
            return await instance_store.backfill(
                conn, gateway, workspace_id=uuid.UUID(str(fx.workspace)),
                search_prefix=prefix,
            )

    async def _search_prefix(conn, workspace_id):
        from src.services import instances as instances_service

        return await instances_service.workspace_search_prefix(
            conn, uuid.UUID(str(workspace_id))
        )

    result = asyncio.run(run_backfill())
    assert result["instances"] == 2
    assert result["action_runs_remapped"] == 1

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        moved = conn.execute(
            "SELECT instance_id FROM action_runs WHERE id = %s", (run_id,)
        ).fetchone()[0]
    expected = instance_store._doc_id(uuid.UUID(str(old[0][1])), old[0][2])
    assert str(moved) == expected, "the audit trail follows the instance to its new id"

    # Flip, and the same data reads back through the API.
    instance_store.configure_instance_store(
        instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    )
    try:
        r = client.get(
            f"/api/workspaces/{fx.workspace}/object-types/{mapped['type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 2
        assert {i["properties"]["full_name"] for i in r.json()["items"]} == {"Ada", "Grace"}

        # Running it twice is a catch-up, not a duplicate.
        again = asyncio.run(run_backfill())
        assert again["instances"] == 2
        r = client.get(
            f"/api/workspaces/{fx.workspace}/object-types/{mapped['type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        )
        assert r.json()["total"] == 2, "backfill is idempotent"
    finally:
        instance_store.configure_instance_store(None)


# ---- the Object Explorer (roadmap Objects item 2) ---------------------------
def _explore(client: TestClient, fx: Fixture, **params) -> dict:
    r = client.get(
        f"/api/workspaces/{fx.workspace}/object-instances",
        headers=hdr(fx.viewer_sub), params=params,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _second_type(client: TestClient, fx: Fixture, mapped: dict) -> dict:
    """A second mapped type, so "across every object type at once" has more
    than one type to be across. A plain helper rather than a fixture: the
    parametrised test below has to build it *after* choosing a store."""
    tag = uuid.uuid4().hex[:6]
    parts = b"code,label\nX1,Widget\nX2,Gadget\n"
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Parts {tag}"},
        files={"file": ("parts.csv", io.BytesIO(parts), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"part_{tag}", "display_name": f"Part {tag}",
              "properties": [{"api_name": "label", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset,
              "primary_key_column": "code", "column_mappings": {"label": "label"}},
    )
    assert r.status_code == 201, r.text
    for sid in (mapped["source_id"], r.json()["id"]):
        assert client.post(
            f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
            f"/object-type-sources/{sid}/sync",
            headers=hdr(fx.editor_sub),
        ).status_code == 200
    # A value shared with nothing else, to search for without colliding with
    # instances other tests left in this workspace.
    return {"people": mapped["type_id"], "parts": type_id, "tag": tag}


@pytest.mark.parametrize("store_name", ["postgres", "opensearch"])
def test_the_explorer_searches_every_type_at_once(
    client: TestClient, fx: Fixture, mapped: dict, opensearch: str, store_name: str,
) -> None:
    """The same assertions against both stores - the Explorer is the read the
    cutover was for, and it has to work on the fallback too.

    Assertions are scoped to the types this test creates rather than to
    workspace totals: the Explorer is workspace-wide by design, so it also
    sees whatever else lives in the fixture workspace, and asserting a global
    count would be asserting test isolation the feature does not promise.
    """
    reset(opensearch)
    gateway = None
    if store_name == "opensearch":
        gateway = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
        instance_store.configure_instance_store(gateway)
    try:
        types = _second_type(client, fx, mapped)

        # Both types appear in one unfiltered result set, each row saying
        # which it is - the whole point of a cross-type view.
        found: dict[str, str] = {}
        offset = 0
        while offset < 500:
            page = _explore(client, fx, limit=50, offset=offset)
            for item in page["items"]:
                found[item["id"]] = item["object_type_id"]
            offset += 50
            if offset >= page["total"]:
                break
        assert types["people"] in found.values()
        assert types["parts"] in found.values()

        # Search by a property value, across types.
        ada = _explore(client, fx, q="Ada", type_id=types["people"])
        assert ada["total"] == 1, ada
        assert ada["items"][0]["properties"]["full_name"] == "Ada"
        assert ada["items"][0]["object_type_display_name"].startswith("Person")

        widget = _explore(client, fx, q="Widget")
        assert widget["total"] == 1, widget
        assert widget["items"][0]["object_type_id"] == types["parts"]
        assert widget["items"][0]["object_type_api_name"] == f"part_{types['tag']}"

        # Filter by type, with and without a query.
        parts = _explore(client, fx, type_id=types["parts"])
        assert parts["total"] == 2
        assert {i["properties"]["label"] for i in parts["items"]} == {"Widget", "Gadget"}

        assert _explore(client, fx, q="Ada", type_id=types["parts"])["total"] == 0, (
            "the query and the type filter are ANDed"
        )
        assert _explore(client, fx, q=f"nothing-matches-{types['tag']}")["total"] == 0
    finally:
        instance_store.configure_instance_store(None)


def test_the_explorer_pages_and_refuses_an_outsider(
    client: TestClient, fx: Fixture, mapped: dict
) -> None:
    types = _second_type(client, fx, mapped)
    first = _explore(client, fx, type_id=types["parts"], limit=1, offset=0)
    second = _explore(client, fx, type_id=types["parts"], limit=1, offset=1)
    assert first["total"] == second["total"] == 2
    assert first["items"][0]["id"] != second["items"][0]["id"]

    r = client.get(
        f"/api/workspaces/{fx.workspace}/object-instances", headers=hdr(fx.outsider_sub)
    )
    assert r.status_code == 404
