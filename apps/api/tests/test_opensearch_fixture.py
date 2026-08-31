"""The OpenSearch fixture's own fidelity (decision 0006 §7).

**Why a fixture has tests.** `opensearch_fixture_server.py` is what every
OpenSearch-side claim in this repo rests on, and it has twice been the reason a
check passed for the wrong reason: an aggregation with `size: 0` that a real
cluster rejects came back empty and cheerful, and a nested aggregation that
counted the wrong documents would have looked identical to one that counted the
right ones. A load-bearing fake needs its own evidence.

**What decision 0006 asked for**, and what is asserted here:

1. a mapping is accepted and remembered from `indices.create`;
2. values are compared *according to it* - an `integer` numerically, a
   `keyword` as bytes, a `geo_point` by bounding box;
3. a document whose value contradicts the mapping is refused, as a real cluster
   refuses it, so the reindex failure in §5 is reachable in a test.

Point 2 is the one that matters most, and the reason is worth stating plainly:
until the mapping was remembered, **every field here was text**. A store that
mapped `capacity` as an integer and one that left it alone produced identical
answers - so the disagreement typed properties exist to remove was invisible to
the only test that could have seen it.

What this still does not prove is that a real cluster agrees. It narrows the
unproven claim from "does any of this work" to "does OpenSearch behave like the
mapping it was given".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

PORT = 9213  # its own: 9209 and 9211 are taken
BASE = f"http://127.0.0.1:{PORT}"

TYPED_MAPPING = {
    "mappings": {
        "properties": {
            "primary_key": {"type": "keyword"},
            "capacity": {"type": "integer"},
            "ratio": {"type": "float"},
            "opened": {"type": "date"},
            "active": {"type": "boolean"},
            "location": {"type": "geo_point"},
            "label": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        },
        "dynamic_templates": [
            {
                "property_strings": {
                    "path_match": "properties.*",
                    "mapping": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                }
            }
        ],
    }
}


@pytest.fixture(scope="module")
def server():
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


def call(method: str, path: str, body=None, raw: str | None = None):
    """Returns (status, parsed body). Errors are values here rather than
    exceptions, because refusing is what half these tests are about."""
    data = raw.encode() if raw is not None else (
        json.dumps(body).encode() if body is not None else None
    )
    request = urllib.request.Request(
        f"{BASE}{path}", method=method, data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            payload = response.read()
            return response.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        return exc.code, (json.loads(payload) if payload else None)


def index(name: str, mapping: dict = TYPED_MAPPING) -> str:
    call("POST", "/__reset")
    call("PUT", f"/{name}", mapping)
    return name


def put(name: str, doc_id: str, doc: dict):
    body = (json.dumps({"update": {"_index": name, "_id": doc_id}}) + "\n"
            + json.dumps({"doc": doc, "doc_as_upsert": True}) + "\n")
    return call("POST", "/_bulk", raw=body)


def search(name: str, query: dict):
    return call("POST", f"/{name}/_search", {"query": query, "size": 50})


def keys(response) -> list[str]:
    return sorted(hit["_source"]["primary_key"] for hit in response["hits"]["hits"])


# ---- 1. the mapping is remembered -------------------------------------------
def test_a_field_with_no_mapping_is_still_accepted(server):
    """Enforcement is not strictness for its own sake. An index created without
    a mapping - which several tests do - must behave as it always did, or this
    change would be a rewrite of every existing test rather than an addition."""
    name = index("plain", {})
    status, _ = put(name, "1", {"primary_key": "a", "anything": "at all"})
    assert status == 200
    assert keys(search(name, {"match_all": {}})[1]) == ["a"]


# ---- 3. a document that contradicts the mapping is refused -------------------
@pytest.mark.parametrize(
    "field,value",
    [
        ("capacity", "n/a"),
        ("capacity", "12.5"),
        ("ratio", "high"),
        ("opened", "not a date"),
        ("active", "perhaps"),
        ("location", "nowhere"),
    ],
)
def test_a_value_that_contradicts_its_type_is_refused(server, field, value):
    """The failure decision 0006 §5 turns on: a reindex that meets a value the
    declared type cannot hold must fail loudly. A fixture that stored it as a
    string would let that reindex look like it had worked, and leave the
    disagreement to be found on a real deployment."""
    name = index("typed")
    status, body = put(name, "1", {"primary_key": "a", field: value})
    assert status == 200, "a bulk reports per item, not per request"
    item = body["items"][0]["update"]
    assert item["status"] == 400, item
    assert item["error"]["type"] == "mapper_parsing_exception"
    assert field in item["error"]["reason"]
    # And nothing was stored: a cluster refuses the document, not the field.
    assert search(name, {"match_all": {}})[1]["hits"]["total"]["value"] == 0


def test_a_value_the_type_can_hold_is_stored_as_that_type(server):
    name = index("typed")
    assert put(name, "1", {"primary_key": "a", "capacity": "40", "ratio": "0.5",
                           "active": "true"})[0] == 200
    source = call("GET", f"/{name}/_doc/1")[1]["_source"]
    # Coerced on the way in, the way a cluster stores the parsed value.
    assert source["capacity"] == 40 and isinstance(source["capacity"], int)
    assert source["ratio"] == 0.5
    assert source["active"] is True


# ---- 2. comparison follows the mapping --------------------------------------
def test_an_integer_field_compares_numerically(server):
    """**The whole point.** `capacity >= 40` is true of 250 on an integer field
    and false on a text one, because "250" sorts before "40". Until the mapping
    was remembered this fixture could only ever give the second answer - so a
    typed range that worked on Postgres and not on OpenSearch would have passed
    here."""
    name = index("typed")
    put(name, "1", {"primary_key": "small", "capacity": 10})
    put(name, "2", {"primary_key": "big", "capacity": 250})
    put(name, "3", {"primary_key": "mid", "capacity": 40})

    assert keys(search(name, {"range": {"capacity": {"gte": 40}}})[1]) == ["big", "mid"]
    assert keys(search(name, {"range": {"capacity": {"lt": 40}}})[1]) == ["small"]


def test_a_keyword_field_compares_as_text(server):
    """The other half of the same coin, and the reason
    `object_sets.ORDERED_OPERATORS` refuses to choose: on a keyword field "250"
    really does come before "40", and that is not a bug in the fixture."""
    name = index("typed", {"mappings": {"properties": {
        "primary_key": {"type": "keyword"}, "capacity": {"type": "keyword"}}}})
    put(name, "1", {"primary_key": "small", "capacity": "10"})
    put(name, "2", {"primary_key": "big", "capacity": "250"})
    put(name, "3", {"primary_key": "mid", "capacity": "40"})

    assert keys(search(name, {"range": {"capacity": {"gte": "40"}}})[1]) == ["mid"]


def test_a_date_field_compares_chronologically_not_alphabetically(server):
    name = index("typed")
    put(name, "1", {"primary_key": "early", "opened": "2024-01-05T00:00:00+00:00"})
    put(name, "2", {"primary_key": "late", "opened": "2024-11-30T00:00:00+00:00"})
    # Offsets and Z are the same instant; a text comparison would disagree.
    put(name, "3", {"primary_key": "zulu", "opened": "2024-06-01T00:00:00Z"})

    assert keys(search(name, {"range": {"opened": {"gte": "2024-06-01T00:00:00+00:00"}}})[1]) \
        == ["late", "zulu"]


def test_a_term_query_matches_by_type_not_by_spelling(server):
    """`40` and `"40"` are the same integer, and a store that sent one where it
    meant the other must not silently miss."""
    name = index("typed")
    put(name, "1", {"primary_key": "a", "capacity": 40})
    assert keys(search(name, {"term": {"capacity": 40}})[1]) == ["a"]
    assert keys(search(name, {"term": {"capacity": "40"}})[1]) == ["a"]


def test_a_query_value_the_type_cannot_hold_is_refused_not_answered_empty(server):
    """Silently empty is the worst available answer: a wrong query that looks
    like a true one. A real cluster returns 400."""
    name = index("typed")
    put(name, "1", {"primary_key": "a", "capacity": 40})
    status, body = search(name, {"term": {"capacity": "n/a"}})
    assert status == 400, body
    assert "capacity" in body["error"]["reason"]


# ---- 2 (continued). geo_point answers a bounding box ------------------------
def test_a_bounding_box_selects_by_area(server):
    """Decision 0006 §3. The map's area selection is a `geo_bounding_box`
    rather than four ordered comparisons, and the fixture answers it properly
    so a store reaching for comparisons instead would be visibly wrong here
    rather than merely slower."""
    name = index("typed")
    put(name, "1", {"primary_key": "london", "location": {"lat": 51.5, "lon": -0.12}})
    put(name, "2", {"primary_key": "edinburgh", "location": {"lat": 55.95, "lon": -3.19}})
    put(name, "3", {"primary_key": "paris", "location": "48.86,2.35"})

    box = {"geo_bounding_box": {"location": {
        "top_left": {"lat": 56.0, "lon": -4.0},
        "bottom_right": {"lat": 51.0, "lon": 0.0},
    }}}
    assert keys(search(name, box)[1]) == ["edinburgh", "london"]


def test_a_bounding_box_across_the_antimeridian_is_a_union_not_an_interval(server):
    """The case four ordered comparisons get wrong, silently, for exactly the
    customers whose data crosses it - which is why decision 0006 names the
    bounding box rather than leaving it to be assembled from comparisons."""
    name = index("typed")
    put(name, "1", {"primary_key": "fiji", "location": {"lat": -17.7, "lon": 178.0}})
    put(name, "2", {"primary_key": "samoa", "location": {"lat": -13.8, "lon": -172.0}})
    put(name, "3", {"primary_key": "kenya", "location": {"lat": -1.3, "lon": 36.8}})

    crossing = {"geo_bounding_box": {"location": {
        "top_left": {"lat": 0.0, "lon": 170.0},
        "bottom_right": {"lat": -20.0, "lon": -170.0},
    }}}
    assert keys(search(name, crossing)[1]) == ["fiji", "samoa"]


def test_a_bounding_box_on_a_field_that_is_not_a_geo_point_is_refused(server):
    name = index("typed")
    put(name, "1", {"primary_key": "a", "capacity": 40})
    status, body = search(name, {"geo_bounding_box": {"capacity": {
        "top_left": {"lat": 1.0, "lon": -1.0},
        "bottom_right": {"lat": -1.0, "lon": 1.0}}}})
    assert status == 400, body


# ---- the dynamic template, which is what the platform actually declares ------
def test_the_keyword_subfield_comes_from_the_template_not_from_luck(server):
    """`instance_store._ensure_index` maps every `properties.*` as text with a
    keyword subfield, and link traversal depends on that subfield existing. The
    fixture resolves it through the template rather than treating any dotted
    path as the same value."""
    name = index("typed")
    put(name, "1", {"primary_key": "a", "properties": {"dept": "Ops"}})
    assert keys(search(name, {"term": {"properties.dept.keyword": "Ops"}})[1]) == ["a"]
    # A template-mapped field is text, so a *number* in one is still text and
    # compares as such - the untyped behaviour every property has today.
    put(name, "2", {"primary_key": "b", "properties": {"dept": 250}})
    assert keys(search(name, {"term": {"properties.dept.keyword": "250"}})[1]) == ["b"]


# ---- 6. what one index per object type needs (decision 0006 §1) --------------
STRICT_MAPPING = {
    "mappings": {
        "properties": {
            "object_type_id": {"type": "keyword"},
            "primary_key": {"type": "keyword"},
            "properties": {
                "type": "object",
                "dynamic": "strict",
                "properties": {"capacity": {"type": "long"}},
            },
        }
    }
}


def test_a_property_the_mapping_does_not_declare_is_refused(server):
    """`dynamic: "strict"` is the point of declaring types at all: left
    dynamic, the first document carrying an undeclared property decides its
    type for every document after it. A fixture that stored it anyway would
    make the declaration look like it was working while the cluster it stands
    in for refused the write."""
    name = index("strict", STRICT_MAPPING)
    status, body = put(name, "1", {"primary_key": "a", "properties": {"capacity": 10}})
    assert status == 200 and not body["errors"]

    status, body = put(name, "2", {"primary_key": "b",
                                   "properties": {"capacity": 10, "surprise": "x"}})
    assert status == 200, "a bulk reports per item rather than failing the call"
    assert body["errors"], "the undeclared property was accepted"
    assert "strict" in body["items"][0]["update"]["error"]["reason"]
    # And the document is not half-stored: a cluster refuses the whole thing.
    assert keys(search(name, {"match_all": {}})[1]) == ["a"]


def test_creating_an_index_that_exists_is_refused(server):
    """What a real cluster answers, with `resource_already_exists_exception`.
    The fixture used to overwrite it - so a store that had lost its
    exists-check passed here and would have destroyed a live mapping against a
    domain."""
    name = index("twice", STRICT_MAPPING)
    status, body = call("PUT", f"/{name}", {"mappings": {}})
    assert status == 400
    assert body["error"]["type"] == "resource_already_exists_exception"
    # The mapping it already had is intact, which is the thing the refusal
    # protects: a silent overwrite would leave the index accepting anything.
    _, mapping = call("GET", f"/{name}/_mapping")
    assert "capacity" in mapping[name]["mappings"]["properties"]["properties"]["properties"]


def test_a_pattern_reaches_only_the_indices_it_names(server):
    """The workspace explorer searches `{prefix}objects-*`, and the prefix is
    the workspace boundary (db 0002). A pattern that reached further would make
    the explorer return another tenant's objects - structural isolation being
    the whole reason the index is named from the prefix at all."""
    call("POST", "/__reset")
    for name in ("ws-a-objects-1", "ws-a-objects-2", "ws-b-objects-1",
                 "ws-a-object-instances"):
        call("PUT", f"/{name}", {})
        put(name, "1", {"primary_key": name, "properties": {}})

    _, found = search("ws-a-objects-*", {"match_all": {}})
    assert keys(found) == ["ws-a-objects-1", "ws-a-objects-2"], (
        "the pattern crossed a workspace, or swept in the index it replaces"
    )


def test_a_hit_reports_the_index_it_came_from(server):
    """Not the pattern it was asked for. A search across several indices whose
    hits all named the pattern would look single-index in every assertion - and
    `_index` is the only thing on a hit that says which type's index answered."""
    call("POST", "/__reset")
    for name in ("ws-a-objects-1", "ws-a-objects-2"):
        call("PUT", f"/{name}", {})
        put(name, "1", {"primary_key": name, "properties": {}})

    _, found = search("ws-a-objects-*", {"match_all": {}})
    assert {hit["_index"] for hit in found["hits"]["hits"]} == {
        "ws-a-objects-1", "ws-a-objects-2"
    }
