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
from src.services import instance_mapping, instance_store  # noqa: E402
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


# What `ontology.list_properties` returns for the type these rows belong to.
#
# **Passed on every upsert, because decision 0006 made an index carry its
# type's mapping.** Without it the index is created with an empty `dynamic:
# "strict"` mapping and every document is refused - which is the intended
# refusal (§5: loudly broken beats quietly wrong) reaching a caller that has
# the declaration and had simply never been asked for it. `rank` is an integer
# on purpose: it is the property whose ordering the whole decision is about, so
# a mapping that lost the type would be visible here rather than only in a
# comparison test.
DECLARED = [
    {"api_name": "full_name", "data_type": "string"},
    {"api_name": "rank", "data_type": "integer"},
]


# ---- the gateway itself, over real HTTP -------------------------------------
@pytest.mark.anyio
async def test_upsert_is_idempotent_on_the_same_source_row(store) -> None:
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)

    assert await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=_rows(2), synced_at=now, declared=DECLARED,
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
        synced_at=now + timedelta(seconds=1), declared=DECLARED,
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
        rows=_rows(3), synced_at=first, declared=DECLARED,
    )
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=other_source,
        rows=_rows(1), synced_at=first, declared=DECLARED,
    )

    second = first + timedelta(minutes=1)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=_rows(1), synced_at=second, declared=DECLARED,
    )
    removed = await store.delete_stale_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        synced_before=second,
    )
    assert removed == 2, "rows 2 and 3 vanished upstream"

    _, total = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=50, offset=0
    )
    assert total == 2, "the other source's instance is untouched"


@pytest.mark.anyio
async def test_declaring_a_new_property_widens_the_index(store) -> None:
    """**Creating is not the only thing an upsert has to do.** Somebody adds a
    property to a type that already has instances, then the next sync carries
    it - and under `dynamic: "strict"` a mapping that was only ever *created*
    refuses that document. The refusal is correct in general (0006 §5) and
    completely wrong here: the property is declared, it is simply newer than
    the index.

    A *changed* type is the other case and is not this: OpenSearch cannot remap
    a field in place, so that is a reindex (0006 §4) with a cost that belongs
    in the impact report rather than inside a sync.
    """
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=[("1", {"full_name": "Ada"})], synced_at=now,
        declared=[{"api_name": "full_name", "data_type": "string"}],
    )

    widened = [*DECLARED, {"api_name": "triage_note", "data_type": "string"}]
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=[("2", {"full_name": "Grace", "rank": 2, "triage_note": "call"})],
        synced_at=now + timedelta(seconds=1), declared=widened,
    )
    rows, total = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=50, offset=0
    )
    assert total == 2
    added = next(r for r in rows if r["primary_key"] == "2")
    assert added["properties"]["triage_note"] == "call"
    assert added["properties"]["rank"] == 2


@pytest.mark.anyio
async def test_reads_are_scoped_by_object_type(store) -> None:
    mine, theirs, source_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=mine, source_id=source_id,
        rows=_rows(1), synced_at=now, declared=DECLARED,
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
async def test_dropping_a_type_forgets_its_instances_and_leaves_the_rest(store) -> None:
    """**A leak nothing closed before decision 0006 §1.** Deleting an object
    type dropped its Postgres rows by cascade and left its documents in the
    workspace's one index, where the explorer - which filters by type only when
    asked - went on returning them: objects of a type nobody could name.

    Asserted through the *explorer*, not through `list_for_type`, because that
    is the read the orphans were visible to. A check scoped to the deleted type
    would pass on a store that had merely stopped answering for it.
    """
    gone, kept, source_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(timezone.utc)
    for type_id in (gone, kept):
        await store.upsert_instances(
            search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
            rows=_rows(2), synced_at=now, declared=DECLARED,
        )
    _, before = await store.search(
        search_prefix=PREFIX, workspace_id=uuid.uuid4(), query=None,
        object_type_ids=None, limit=50, offset=0,
    )
    assert before == 4

    await store.drop_type(search_prefix=PREFIX, object_type_id=gone)

    rows, after = await store.search(
        search_prefix=PREFIX, workspace_id=uuid.uuid4(), query=None,
        object_type_ids=None, limit=50, offset=0,
    )
    assert after == 2, "the deleted type's objects are gone from the explorer"
    assert {r["object_type_id"] for r in rows} == {str(kept)}


@pytest.mark.anyio
async def test_dropping_a_type_that_never_synced_is_not_an_error(store) -> None:
    """A type deleted before its first sync has no index. A delete that raised
    would make such a type undeletable - the ontology's record kept or dropped
    depending on whether anything had happened to be indexed yet."""
    await store.drop_type(search_prefix=PREFIX, object_type_id=uuid.uuid4())


# ---- the 0006 migration: out of the one workspace index ----------------------
async def _seed_legacy(store, prefix: str, docs: list[tuple[str, str, dict]]) -> None:
    """Write straight into the pre-0006 index, as a deployment that has been
    running since before the split holds them.

    Through the client rather than through `upsert_instances`, because that
    method no longer *can* write there - which is the point: this is data the
    current code cannot produce and has to be able to read.
    """
    legacy = instance_mapping.legacy_index_name(prefix)
    await store._client.indices.create(index=legacy, body={"mappings": {}})
    body: list[dict] = []
    for type_id, key, properties in docs:
        body.append({"update": {"_index": legacy,
                                "_id": instance_store._doc_id(uuid.UUID(SOURCE), key)}})
        body.append({"doc": {"object_type_id": type_id, "source_id": SOURCE,
                             "primary_key": key, "properties": properties,
                             "updated_at": "2026-01-01T00:00:00+00:00"},
                     "doc_as_upsert": True})
    await store._client.bulk(body=body, refresh="wait_for")


SOURCE = "33333333-3333-3333-3333-333333333333"


@pytest.mark.anyio
async def test_the_migration_moves_a_type_out_of_the_workspace_index(store) -> None:
    """Decision 0006 §1's data movement, per object type.

    **Read from the old index, not from Postgres**, and this is where that
    matters: a workspace already on OpenSearch has not written to
    `object_instances` since its own cutover, so those rows are a snapshot of
    whenever that happened. Reading them would quietly restore a workspace to
    an old state and report it as a migration.
    """
    prefix = "ws-split-"
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_legacy(store, prefix, [
        (a, "1", {"full_name": "Ada", "rank": 1}),
        (a, "2", {"full_name": "Grace", "rank": 2}),
        (b, "3", {"full_name": "Katherine", "rank": 3}),
    ])

    moved = await store.adopt_legacy_index(
        search_prefix=prefix, object_type_id=uuid.UUID(a), declared=DECLARED
    )
    assert moved == 2, "only this type's documents"

    rows, total = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(a), limit=50, offset=0
    )
    assert total == 2
    assert {r["primary_key"] for r in rows} == {"1", "2"}
    assert {r["properties"]["full_name"] for r in rows} == {"Ada", "Grace"}
    # The other type has not been migrated, so its new index holds nothing -
    # a migration that moved everything on the first call would make the
    # per-type loop above it a decoration.
    _, other = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(b), limit=50, offset=0
    )
    assert other == 0


@pytest.mark.anyio
async def test_the_migration_keeps_the_document_id(store) -> None:
    """`action_runs.instance_id` points at these. An id recomputed rather than
    carried would renumber anything whose id predates the derivation rule, and
    the audit trail would silently lose which instance a historical write
    touched - the FK is ON DELETE SET NULL, so it degrades to null rather than
    failing."""
    prefix = "ws-split-ids-"
    type_id = str(uuid.uuid4())
    await _seed_legacy(store, prefix, [(type_id, "1", {"full_name": "Ada"})])
    await store.adopt_legacy_index(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), declared=DECLARED
    )
    rows, _ = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), limit=50, offset=0
    )
    assert rows[0]["id"] == instance_store._doc_id(uuid.UUID(SOURCE), "1")


@pytest.mark.anyio
async def test_the_migration_carries_an_id_it_could_not_have_derived(store) -> None:
    """**The id is copied, not recomputed**, and this is the only fixture that
    can tell the difference: every document the current code writes already has
    the derived id, so recomputing one gives the same answer and a test seeded
    the ordinary way proves nothing.

    A deployment predating the derivation rule has documents with random ids,
    and `action_runs.instance_id` points at them. Renumbering those loses which
    instance every historical write-back touched - the FK is ON DELETE SET
    NULL, so it degrades to null rather than failing loudly.
    """
    prefix = "ws-split-old-ids-"
    type_id = str(uuid.uuid4())
    legacy = instance_mapping.legacy_index_name(prefix)
    old_id = "9f1d2c3b-4a5e-6f70-8192-a3b4c5d6e7f8"
    assert old_id != instance_store._doc_id(uuid.UUID(SOURCE), "1"), "the fixture is vacuous"

    await store._client.indices.create(index=legacy, body={"mappings": {}})
    await store._client.bulk(refresh="wait_for", body=[
        {"update": {"_index": legacy, "_id": old_id}},
        {"doc": {"object_type_id": type_id, "source_id": SOURCE, "primary_key": "1",
                 "properties": {"full_name": "Ada"},
                 "updated_at": "2026-01-01T00:00:00+00:00"},
         "doc_as_upsert": True},
    ])

    await store.adopt_legacy_index(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), declared=DECLARED
    )
    rows, _ = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), limit=50, offset=0
    )
    assert [r["id"] for r in rows] == [old_id]


@pytest.mark.anyio
async def test_the_migration_pages_past_one_batch(store) -> None:
    """**The failure this test exists for is a silent one.** Offset paging
    stops at `index.max_result_window`, and a migration that moved the first
    batch and stopped would leave a workspace that looks migrated and is
    missing rows. Asserted against a population larger than one batch, with the
    batch made small rather than the population made huge."""
    prefix = "ws-split-paged-"
    type_id = str(uuid.uuid4())
    await _seed_legacy(store, prefix, [
        (type_id, f"{i:03d}", {"full_name": f"person-{i}"}) for i in range(25)
    ])
    original = store.MIGRATION_BATCH
    store.MIGRATION_BATCH = 10
    try:
        moved = await store.adopt_legacy_index(
            search_prefix=prefix, object_type_id=uuid.UUID(type_id), declared=DECLARED
        )
    finally:
        store.MIGRATION_BATCH = original
    assert moved == 25
    _, total = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), limit=50, offset=0
    )
    assert total == 25


@pytest.mark.anyio
async def test_the_migration_keeps_two_sources_that_share_a_key(store) -> None:
    """**Instance identity is (source_id, primary_key), not the key alone**, and
    `delete_instances` says so: two datasets feeding one object type can each
    hold a row keyed "1".

    That makes `primary_key` a non-unique sort, and `search_after` on a
    non-unique sort **skips every document sharing the cursor's value**. Paged
    on the key alone this migration lost one of each colliding pair - quietly,
    and in proportion to how many keys the two datasets happened to share.
    Batched small so the collision straddles a page boundary, which is the only
    arrangement in which the bug appears at all.
    """
    prefix = "ws-split-two-sources-"
    type_id = str(uuid.uuid4())
    other = "44444444-4444-4444-4444-444444444444"
    legacy = instance_mapping.legacy_index_name(prefix)
    await store._client.indices.create(index=legacy, body={"mappings": {}})
    body: list[dict] = []
    for source in (SOURCE, other):
        for key in ("1", "2", "3"):
            body.append({"update": {"_index": legacy,
                                    "_id": instance_store._doc_id(uuid.UUID(source), key)}})
            body.append({"doc": {"object_type_id": type_id, "source_id": source,
                                 "primary_key": key,
                                 "properties": {"full_name": f"{source[:4]}-{key}"},
                                 "updated_at": "2026-01-01T00:00:00+00:00"},
                         "doc_as_upsert": True})
    await store._client.bulk(body=body, refresh="wait_for")

    # **Three, not two.** With a batch of two each colliding pair lands wholly
    # inside one page and the bug cannot appear - the cursor only skips
    # documents that share its value and sit *after* it. Three splits the "2"s
    # across the boundary, which is the arrangement that loses one.
    original = store.MIGRATION_BATCH
    store.MIGRATION_BATCH = 3
    try:
        moved = await store.adopt_legacy_index(
            search_prefix=prefix, object_type_id=uuid.UUID(type_id), declared=DECLARED
        )
    finally:
        store.MIGRATION_BATCH = original

    assert moved == 6, "a shared primary key was paged over"
    rows, total = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), limit=50, offset=0
    )
    assert total == 6
    assert len({r["properties"]["full_name"] for r in rows}) == 6


@pytest.mark.anyio
async def test_the_migration_is_safe_to_run_twice(store) -> None:
    """**Run it, flip, run it again.** Every document id is derived from
    (source_id, primary_key), so a second pass rewrites the same documents - it
    is a catch-up for anything written between the first pass and the flip
    rather than a duplicate. That property is what lets this happen without
    dual-write machinery, so it is worth an assertion rather than a comment."""
    prefix = "ws-split-twice-"
    type_id = str(uuid.uuid4())
    await _seed_legacy(store, prefix, [
        (type_id, "1", {"full_name": "Ada"}), (type_id, "2", {"full_name": "Grace"}),
    ])
    for _ in range(2):
        await store.adopt_legacy_index(
            search_prefix=prefix, object_type_id=uuid.UUID(type_id), declared=DECLARED
        )
    _, total = await store.list_for_type(
        search_prefix=prefix, object_type_id=uuid.UUID(type_id), limit=50, offset=0
    )
    assert total == 2


@pytest.mark.anyio
async def test_a_workspace_with_no_old_index_migrates_to_nothing(store) -> None:
    """A workspace created after the split, or one already moved. Zero rather
    than an error, so the migration can be run over every workspace without
    knowing first which are which."""
    assert await store.adopt_legacy_index(
        search_prefix="ws-never-", object_type_id=uuid.uuid4(), declared=DECLARED
    ) == 0


@pytest.mark.anyio
async def test_the_migration_refuses_a_value_that_does_not_fit(store) -> None:
    """0006 §5: "the reindex refuses and names them. It does not write null,
    and it does not skip the document." Both of those produce an index quietly
    missing rows a filter should have matched, and the first person to notice
    is somebody trusting a count."""
    prefix = "ws-split-bad-"
    type_id = str(uuid.uuid4())
    await _seed_legacy(store, prefix, [(type_id, "1", {"full_name": "Ada", "rank": "n/a"})])
    with pytest.raises(RuntimeError, match="refusal"):
        await store.adopt_legacy_index(
            search_prefix=prefix, object_type_id=uuid.UUID(type_id), declared=DECLARED
        )


@pytest.mark.anyio
async def test_paging_and_ordering(store) -> None:
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    base = datetime.now(timezone.utc)
    for i in range(1, 6):
        await store.upsert_instances(
            search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
            rows=[(str(i), {"rank": i})], synced_at=base + timedelta(seconds=i),
            declared=DECLARED,
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
        synced_at=datetime.now(timezone.utc), declared=DECLARED,
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
        rows=_rows(2), synced_at=now, declared=DECLARED,
    )
    await store.upsert_instances(
        search_prefix="ws-beta-", object_type_id=type_id, source_id=source_id,
        rows=_rows(1), synced_at=now, declared=DECLARED,
    )
    _, alpha = await store.list_for_type(
        search_prefix="ws-alpha-", object_type_id=type_id, limit=50, offset=0
    )
    _, beta = await store.list_for_type(
        search_prefix="ws-beta-", object_type_id=type_id, limit=50, offset=0
    )
    assert (alpha, beta) == (2, 1)

    from src.services.instance_store import _index_name

    # Two anchors now, not one. The **workspace** is still the prefix (db 0002,
    # this test's original claim), and decision 0006 added the **object type**
    # inside it — so one type's index in one workspace differs from the same
    # type's in another *and* from another type's in the same one.
    other_type = uuid.uuid4()
    assert _index_name("ws-alpha-", type_id) != _index_name("ws-beta-", type_id)
    assert _index_name("ws-alpha-", type_id) != _index_name("ws-alpha-", other_type)


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
                                         display_name)
               VALUES (%s, %s, %s, 'Backfill probe') RETURNING id""",
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


# ---- edit-only properties survive a sync, on *both* stores ------------------
# Foundry `object-link-types` p.113: an edit-only property "is not directly
# mapped to a column in the backing dataset", so a sync's rows never carry it -
# and the store is the only place its value exists.
#
# **One test over two stores, deliberately.** This is where they disagreed:
# OpenSearch's update takes a partial `doc` and merges it, so the value
# survived there, while the Postgres upsert wrote `properties =
# EXCLUDED.properties` and deleted it. Neither raised. Asserting each store
# separately would have let that stand for as long as nobody compared them,
# which is the cross-store rule `OPERATORS` exists to keep - so the claim is
# written once and both stores answer it.
async def _sync_twice(store, *, first: dict, edit: dict, second: dict,
                      declared: list[dict] | None = None) -> dict:
    """Sync a row, apply an edit the dataset knows nothing about, sync again."""
    type_id, source_id = uuid.uuid4(), uuid.uuid4()
    t0 = datetime.now(timezone.utc)
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=[("1", first)], synced_at=t0, declared=declared,
    )
    rows, _ = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=10, offset=0
    )
    await store.update_properties(
        search_prefix=PREFIX, object_type_id=type_id,
        instance_id=str(rows[0]["id"]), properties=edit,
    )
    await store.upsert_instances(
        search_prefix=PREFIX, object_type_id=type_id, source_id=source_id,
        rows=[("1", second)], synced_at=t0 + timedelta(minutes=1), declared=declared,
    )
    rows, _ = await store.list_for_type(
        search_prefix=PREFIX, object_type_id=type_id, limit=10, offset=0
    )
    return dict(rows[0]["properties"])


@pytest.mark.anyio
async def test_a_sync_keeps_what_the_dataset_cannot_say_opensearch(store) -> None:
    got = await _sync_twice(
        store,
        first={"rank": 1},
        edit={"rank": 1, "triage_note": "call the owner"},
        second={"rank": 2},
        # **`triage_note` is declared here even though no column feeds it** —
        # that is exactly what p.113's edit-only property is, and decision
        # 0006's strict mapping is what makes the distinction load-bearing: a
        # property the ontology does not declare cannot be written at all now,
        # so "the dataset cannot say it" and "the ontology does not have it"
        # stopped being the same state.
        declared=[
            {"api_name": "rank", "data_type": "integer"},
            {"api_name": "triage_note", "data_type": "string"},
        ],
    )
    # The mapped property is the dataset's to say, and it changed.
    assert got["rank"] == 2
    # The edit-only one has no column to come back from, so the sync leaves it.
    assert got["triage_note"] == "call the owner"


# The Postgres half of this claim lives in `test_actions.py`, not here: an
# insert into `object_instances` is subject to row-level security, so it needs
# a real workspace, user and source rather than a bare engine connection - and
# the same fixture is what makes the *action* that writes an edit-only property
# testable. Same claim, one place it can actually run.
