"""Object sets (roadmap phase 2, item 1.2).

Two things are under test and the second is the important one.

First, that a set means what it says: filters narrow, the total is the size of
the *set* rather than of the page, and a filter that cannot be satisfied
refuses rather than quietly widening.

Second, **that both stores agree**. Postgres evaluates in SQL and OpenSearch in
its query DSL, and a set that meant two things depending on which store a
deployment happens to run would be invisible until somebody compared two
environments. So the same rows and the same filters go through
`object_sets.matches`, the Postgres path, and the OpenSearch path, and all
three have to produce the same answer.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import instance_store, object_sets  # noqa: E402

PORT = 9209
BASE = f"http://127.0.0.1:{PORT}"

# One fixed population, used by every layer below, so a disagreement is a
# disagreement about semantics rather than about test data.
ROWS = [
    ("1", {"region": "north", "status": "open", "capacity": 10}),
    ("2", {"region": "north", "status": "closed", "capacity": 250}),
    ("3", {"region": "south", "status": "open", "capacity": 40}),
    ("4", {"region": "south", "status": "open", "capacity": 7}),
    ("5", {"region": "east", "status": "open", "capacity": "n/a"}),
]

CASES = [
    {"filters": [{"property": "region", "op": "eq", "value": "north"}]},
    {"filters": [{"property": "region", "op": "neq", "value": "north"}]},
    {"filters": [{"property": "region", "op": "in", "value": ["north", "east"]}]},
    {"filters": [{"property": "status", "op": "starts_with", "value": "clos"}]},
    {
        "filters": [
            {"property": "region", "op": "eq", "value": "south"},
            {"property": "status", "op": "eq", "value": "open"},
        ]
    },
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


# ---- the definition ----------------------------------------------------------
def test_a_definition_without_a_type_is_refused() -> None:
    with pytest.raises(ValueError, match="object_type_id"):
        object_sets.parse({"filters": []})


def test_an_unknown_operator_names_the_ones_that_exist() -> None:
    with pytest.raises(ValueError, match="startswith.*supported|supported"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "region", "op": "startswith", "value": "n"}],
            }
        )


def test_a_filter_with_no_value_is_refused_rather_than_ignored() -> None:
    """The failure decision 0002 documented, caught at the door. A filter bound
    to a variable nobody has set must not silently widen the set - that is how
    a map came to show *more* rows than it should. The caller drops the filter;
    it does not send an empty one."""
    with pytest.raises(ValueError, match="omit the filter"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "region", "op": "eq", "value": None}],
            }
        )


def test_list_and_scalar_operators_refuse_each_other() -> None:
    type_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="non-empty list"):
        object_sets.parse(
            {"object_type_id": type_id, "filters": [{"property": "r", "op": "in", "value": "north"}]}
        )
    with pytest.raises(ValueError, match="single value"):
        object_sets.parse(
            {"object_type_id": type_id, "filters": [{"property": "r", "op": "eq", "value": ["a"]}]}
        )


def test_ordered_comparison_is_refused_and_says_why() -> None:
    """The finding this item's cross-store test was written to produce.

    Properties are stored untyped, so `capacity > 40` reads as 250 > 40 on
    Postgres (which can cast) and as "250" < "40" on OpenSearch (which compares
    indexed text). The first implementation shipped both and the two stores
    disagreed on the first run. Refused rather than picked: a numeric-only
    reading breaks dates and codes, a lexicographic one is indefensible to
    anyone filtering a number, and doing it properly means honouring the
    declared property type - a mapping change with a backfill behind it."""
    for op in object_sets.ORDERED_OPERATORS:
        with pytest.raises(ValueError, match="not supported yet"):
            object_sets.parse(
                {
                    "object_type_id": str(uuid.uuid4()),
                    "filters": [{"property": "capacity", "op": op, "value": 40}],
                }
            )


def test_comparison_is_on_the_text_of_a_value() -> None:
    """The same rule links use: two independently-mapped sources can disagree
    about whether a code is a string or a number."""
    definition = object_sets.parse(
        {
            "object_type_id": str(uuid.uuid4()),
            "filters": [{"property": "code", "op": "eq", "value": 7}],
        }
    )
    assert object_sets.matches({"code": "7"}, definition.filters)


# ---- the two stores agree ----------------------------------------------------
@pytest.fixture(scope="module")
def opensearch() -> str:
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "opensearch_fixture_server.py"
    )
    proc = subprocess.Popen(
        [sys.executable, script, str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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


@pytest.mark.anyio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["filters"][0]["op"])
async def test_opensearch_and_the_reference_semantics_agree(opensearch: str, case: dict) -> None:
    """The check that stops a set meaning two things.

    `object_sets.matches` is the written-down definition; the store has to
    reach the same conclusion through an entirely different mechanism.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-set-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
        )
        definition = object_sets.parse({"object_type_id": str(type_id), **case})

        expected = {key for key, props in ROWS if object_sets.matches(props, definition.filters)}
        rows, total = await store.evaluate_object_set(
            search_prefix="ws-set-test",
            object_type_id=type_id,
            filters=definition.filters,
            limit=50,
            offset=0,
        )
        assert {r["primary_key"] for r in rows} == expected, case
        assert total == len(expected)
    finally:
        await store.close()


# ---- through the API (Postgres store, the local-dev default) -----------------
@pytest.fixture(scope="module")
def seeded(client: TestClient, fx: Fixture) -> str:
    """The fixture population, landed the way real instances land: a dataset
    upload, an object type, a source mapping, a sync.

    Inserting into `object_instances` directly would have been shorter and
    would have tested a table rather than the thing under test - and it is not
    even possible, since an instance has to belong to a source.
    """
    tag = uuid.uuid4().hex[:8]
    csv = b"key,region,status,capacity\n" + b"".join(
        f"{key},{p['region']},{p['status']},{p['capacity']}\n".encode() for key, p in ROWS
    )
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.owner_sub),
        data={"name": f"Sites {tag}"},
        files={"file": ("sites.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types",
        headers=hdr(fx.owner_sub),
        json={
            "api_name": f"Site{tag}",
            "display_name": f"Site {tag}",
            "properties": [
                {"api_name": p, "data_type": "string"}
                for p in ("region", "status", "capacity")
            ],
        },
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.owner_sub),
        json={
            "object_type_id": type_id,
            "dataset_id": dataset_id,
            "primary_key_column": "key",
            "column_mappings": {"region": "region", "status": "status", "capacity": "capacity"},
        },
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources/{source_id}/sync",
        headers=hdr(fx.owner_sub),
    )
    assert r.status_code == 200, r.text
    return type_id


def evaluate(client: TestClient, fx: Fixture, definition: dict, **kw) -> dict:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["filters"][0]["op"])
def test_the_postgres_store_and_the_reference_semantics_agree(
    client: TestClient, fx: Fixture, seeded: str, case: dict
) -> None:
    type_id = seeded
    definition = object_sets.parse({"object_type_id": type_id, **case})
    expected = {key for key, props in ROWS if object_sets.matches(props, definition.filters)}

    body = evaluate(client, fx, {"object_type_id": type_id, **case})
    assert {i["primary_key"] for i in body["instances"]} == expected, case
    assert body["total"] == len(expected)


def test_the_total_is_the_size_of_the_set_not_the_page(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """"127 sites match" is the answer a Workshop app needs, and the one a page
    of rows cannot give - which is the whole reason this is server-side."""
    type_id = seeded
    body = evaluate(
        client, fx, {"object_type_id": type_id, "filters": []}, limit=2, offset=0
    )
    assert len(body["instances"]) == 2
    assert body["total"] == len(ROWS)


def test_paging_a_filtered_set_does_not_repeat_a_row(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    type_id = seeded
    definition = {"object_type_id": type_id, "filters": [{"property": "status", "op": "eq", "value": "open"}]}
    first = evaluate(client, fx, definition, limit=2, offset=0)
    second = evaluate(client, fx, definition, limit=2, offset=2)
    keys = [i["primary_key"] for i in first["instances"] + second["instances"]]
    assert len(keys) == len(set(keys)), "a row appeared on two pages"
    open_rows = sum(1 for _, props in ROWS if props["status"] == "open")
    assert first["total"] == second["total"] == open_rows


def test_a_type_from_another_workspace_is_not_evaluable(
    client: TestClient, fx: Fixture
) -> None:
    """An id in a request body is never trusted to be in scope."""
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": str(uuid.uuid4()), "filters": []}},
    )
    assert r.status_code == 404, r.text


def test_a_bad_definition_is_refused_in_a_sentence(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": str(uuid.uuid4()),
                             "filters": [{"property": "r", "op": "nope", "value": 1}]}},
    )
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)
    assert "nope" in r.json()["detail"]


# ---- aggregating a set (roadmap 1.5, what a Metric Card shows) ----------------
def aggregate(client: TestClient, fx: Fixture, definition: dict, **kw):
    return client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/aggregate",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )


def test_a_count_is_the_size_of_the_set_not_of_a_page(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The whole reason this is not a flag on `/evaluate`: a card that got its
    number by paging would be wrong the moment a set outgrew a page, which is
    exactly when the number starts mattering."""
    definition = {"object_type_id": seeded, "filters": []}
    page = evaluate(client, fx, definition, limit=2)
    assert len(page["instances"]) == 2

    r = aggregate(client, fx, definition, aggregation="count")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == len(ROWS)


def test_a_count_honours_the_set_s_filters(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "region", "op": "eq", "value": "north"}],
    }
    expected = sum(1 for _, p in ROWS if p["region"] == "north")
    r = aggregate(client, fx, definition, aggregation="count")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == expected
    # And it agrees with what the table beside it would show.
    assert evaluate(client, fx, definition)["total"] == expected


def test_count_distinct_counts_values_not_rows(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    definition = {"object_type_id": seeded, "filters": []}
    expected = len({p["region"] for _, p in ROWS})
    r = aggregate(client, fx, definition, aggregation="count_distinct", property="region")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == expected
    assert expected < len(ROWS), "the fixture must have repeats or this proves nothing"


def test_count_distinct_without_a_property_says_what_is_missing(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = aggregate(client, fx, {"object_type_id": seeded, "filters": []},
                  aggregation="count_distinct")
    assert r.status_code == 422, r.text
    assert "needs a property" in r.json()["detail"]


def test_a_numeric_aggregation_is_refused_with_the_reason(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """Same refusal as ordered operators, for the same cause: properties are
    stored untyped, so a sum means one thing on Postgres and nothing at all on
    OpenSearch. A card whose number is right on one deployment and absent on
    another is worse than one that says the platform cannot answer yet."""
    r = aggregate(client, fx, {"object_type_id": seeded, "filters": []},
                  aggregation="sum", property="capacity")
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "untyped" in detail
    assert "count and count_distinct" in detail


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        {"aggregation": "count", "property": None, "filters": []},
        {"aggregation": "count", "property": None,
         "filters": [{"property": "region", "op": "eq", "value": "north"}]},
        {"aggregation": "count_distinct", "property": "region", "filters": []},
        {"aggregation": "count_distinct", "property": "status",
         "filters": [{"property": "region", "op": "eq", "value": "north"}]},
    ],
    ids=["count", "count-filtered", "distinct", "distinct-filtered"],
)
async def test_both_stores_aggregate_a_set_the_same_way(opensearch: str, case: dict) -> None:
    """The check that stops a Metric Card meaning two things.

    Postgres counts distinct `jsonb_extract_path_text`; OpenSearch runs a
    cardinality aggregation on the `.keyword` subfield. Different mechanisms,
    and the number has to be the same or an app's headline figure depends on
    which store the deployment happens to run.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-agg-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), "filters": case["filters"]}
        )
        in_set = [p for _, p in ROWS if object_sets.matches(p, definition.filters)]
        expected = (
            len(in_set)
            if case["aggregation"] == "count"
            else len({str(p[case["property"]]) for p in in_set if p.get(case["property"]) is not None})
        )
        value = await store.aggregate_object_set(
            search_prefix="ws-agg-test",
            object_type_id=type_id,
            filters=definition.filters,
            aggregation=case["aggregation"],
            property_name=case["property"],
        )
        assert value == expected, case
    finally:
        await store.close()


# ---- grouping a set (roadmap 1.5, what a chart over a set plots) -------------
def group(client: TestClient, fx: Fixture, definition: dict, **kw):
    return client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/group",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )


def test_grouping_counts_each_value_and_orders_biggest_first(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = group(client, fx, {"object_type_id": seeded, "filters": []}, property="region")
    assert r.status_code == 200, r.text
    body = r.json()
    expected: dict[str, int] = {}
    for _, p in ROWS:
        expected[p["region"]] = expected.get(p["region"], 0) + 1
    assert {g["value"]: g["count"] for g in body["groups"]} == expected
    counts = [g["count"] for g in body["groups"]]
    assert counts == sorted(counts, reverse=True), "biggest bar first"
    assert body["distinct_total"] == len(expected)
    assert body["truncated"] is False


def test_grouping_honours_the_set_s_filters(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The point of grouping a *set* rather than a type: the chart and the
    table beside it are looking at the same rows."""
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "region", "op": "eq", "value": "north"}],
    }
    r = group(client, fx, definition, property="status")
    assert r.status_code == 200, r.text
    expected: dict[str, int] = {}
    for _, p in ROWS:
        if p["region"] == "north":
            expected[p["status"]] = expected.get(p["status"], 0) + 1
    assert {g["value"]: g["count"] for g in r.json()["groups"]} == expected
    assert sum(g["count"] for g in r.json()["groups"]) == evaluate(
        client, fx, definition
    )["total"]


def test_truncation_is_reported_rather_than_silent(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """A chart drawing the top N of many without saying so is the same trap as
    a preview that sampled and did not mention it. Derived from the distinct
    total, not from "did we fill the page", which would be wrong on a set with
    exactly `limit` groups."""
    r = group(client, fx, {"object_type_id": seeded, "filters": []},
              property="region", limit=1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["groups"]) == 1
    assert body["truncated"] is True
    assert body["distinct_total"] > 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        {"property": "region", "filters": []},
        {"property": "status", "filters": []},
        {"property": "status",
         "filters": [{"property": "region", "op": "eq", "value": "north"}]},
    ],
    ids=["region", "status", "status-filtered"],
)
async def test_both_stores_group_a_set_the_same_way(opensearch: str, case: dict) -> None:
    """Postgres groups with SQL, OpenSearch with a terms aggregation. Same
    buckets, same counts, **same order** - ties included, which is why both
    sides ask for count-descending-then-value-ascending explicitly."""
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-group-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), "filters": case["filters"]}
        )
        in_set = [p for _, p in ROWS if object_sets.matches(p, definition.filters)]
        tally: dict[str, int] = {}
        for p in in_set:
            value = p.get(case["property"])
            if value is not None:
                tally[str(value)] = tally.get(str(value), 0) + 1
        expected = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))

        buckets, distinct_total = await store.group_object_set(
            search_prefix="ws-group-test",
            object_type_id=type_id,
            filters=definition.filters,
            property_name=case["property"],
            limit=object_sets.MAX_GROUPS,
        )
        assert buckets == expected, case
        assert distinct_total == len(tally)
    finally:
        await store.close()
