"""Selecting objects inside any one of several shapes (§639; `workshop` p.301).

    "Drawn shapes: A bidirectional string variable that reflects the shapes
     drawn within the map interface as a GeoJSON string." (p.301)

    "Enable single draw mode: Limit users to only draw one shape at a time on
     the map interface, automatically removing the previous shape when a new
     one is drawn." (p.301)

Without single draw mode a Map keeps several shapes, and the objects it
selects are those inside any of them. A set's filters are all required, so
`within_box`, `within_polygon` and `within_distance` (§230, §571, §572) could
not say it. `within_any` does, and each shape keeps its own operator's one
definition - held to here on both stores, over the rows `test_object_sets`
holds the box to.
"""
from __future__ import annotations

import os
import sys
import urllib.request
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_object_set_polygons import TRIANGLE, corners  # noqa: E402
from test_object_sets import (  # noqa: E402,F401
    BOX, GEO_DECLARED, GEO_ROWS, GEO_TYPES, _fresh_identity_cache, anyio_backend, client,
    evaluate, fx, geo, opensearch,
)
from src.services import instance_store, object_sets  # noqa: E402

# Row 5 (0, -175), and nothing else within 100 km.
NEAR_FIVE = {"lat": 0.5, "lon": -175, "radius": 100_000}
# Row 3 (20, 5), as a box.
ROUND_THREE = {"north": 25, "south": 15, "east": 10, "west": 0}
# Row 4 (0, 175), as a box across the seam.
ACROSS_SEAM = {"north": 5, "south": -5, "east": -179, "west": 170}

# One of each kind: a polygon, a circle and a box, each round its own row.
ONE_OF_EACH = [TRIANGLE, NEAR_FIVE, ROUND_THREE]
# Two shapes over the same row (1): it is one object, counted once.
OVERLAPPING = [BOX, TRIANGLE]
# A wrapping box among others keeps its wrap.
WITH_THE_SEAM = [ACROSS_SEAM, ROUND_THREE]


def members(shapes: list) -> set[str]:
    parsed = object_sets.parse_shapes(shapes)
    return {key for key, props in GEO_ROWS
            if any(object_sets.in_shape(props.get("where"), shape) for shape in parsed)}


def filtered(shapes) -> dict:
    return {"property": "where", "op": "within_any", "value": shapes}


# ---- the one definition ---------------------------------------------------------
def test_any_one_shape_is_enough() -> None:
    assert members(ONE_OF_EACH) == {"1", "3", "5"}
    assert members(OVERLAPPING) == {"1", "2"}
    assert members(WITH_THE_SEAM) == {"3", "4"}


def test_each_shape_is_read_as_its_own_operator_reads_it() -> None:
    assert object_sets.parse_shapes(ONE_OF_EACH) == (
        object_sets.parse_polygon(TRIANGLE),
        object_sets.parse_circle(NEAR_FIVE),
        object_sets.parse_box(ROUND_THREE),
    )


def test_matching_a_definition_uses_the_one_definition() -> None:
    definition = object_sets.parse(
        {"object_type_id": str(uuid.uuid4()), "filters": [filtered(ONE_OF_EACH)]},
        property_types=GEO_TYPES)
    assert {key for key, props in GEO_ROWS
            if object_sets.matches(props, definition.filters)} == {"1", "3", "5"}


def test_a_row_with_no_coordinate_is_in_no_shape() -> None:
    for shape in object_sets.parse_shapes(ONE_OF_EACH):
        assert object_sets.in_shape(None, shape) is False


@pytest.mark.parametrize("raw, said", [
    ([], "must be a non-empty list of shapes"),
    (TRIANGLE, "must be a non-empty list of shapes"),
    ([ROUND_THREE] * 21, "at most 20 shapes"),
    ([ROUND_THREE, corners((1, 1), (2, 2))], "shape 2: a polygon needs at least three corners"),
    ([{**NEAR_FIVE, "radius": 0}], "shape 1: a circle's radius is metres"),
    ([ROUND_THREE, {"north": 1}], "shape 2: a box needs a number for 'south'"),
    (["here"], "shape 1: a within_box value must be an object"),
])
def test_shapes_that_say_too_little_are_refused(raw, said) -> None:
    with pytest.raises(ValueError) as caught:
        object_sets.parse_shapes(raw)
    assert said in str(caught.value)


def test_twenty_shapes_are_allowed() -> None:
    assert len(object_sets.parse_shapes([ROUND_THREE] * 20)) == 20


def test_the_shapes_need_a_geopoint_behind_them() -> None:
    with pytest.raises(ValueError) as caught:
        object_sets.parse({"object_type_id": str(uuid.uuid4()), "filters": [
            filtered(ONE_OF_EACH)]}, property_types={"where": "string"})
    assert "within_any needs a geopoint" in str(caught.value)


# ---- both stores, held to it -------------------------------------------------------
SHAPES = [ONE_OF_EACH, OVERLAPPING, WITH_THE_SEAM]
IDS = ["one-of-each", "overlapping", "seam"]


@pytest.mark.anyio
@pytest.mark.parametrize("shapes", SHAPES, ids=IDS)
async def test_opensearch_answers_the_shapes_as_the_definition_does(opensearch: str, shapes) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-any", object_type_id=type_id, source_id=source_id,
            rows=GEO_ROWS, synced_at=datetime.now(timezone.utc), declared=GEO_DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), "filters": [filtered(shapes)]},
            property_types=GEO_TYPES,
        )
        rows, total = await store.evaluate_object_set(
            search_prefix="ws-any", object_type_id=type_id,
            filters=definition.filters, limit=50, offset=0,
        )
        assert {r["primary_key"] for r in rows} == members(shapes)
        assert total == len(members(shapes))
    finally:
        await store.close()


@pytest.mark.parametrize("shapes", SHAPES, ids=IDS)
def test_postgres_answers_the_shapes_as_the_definition_does(client, fx, geo, shapes) -> None:
    page = evaluate(client, fx, {"object_type_id": geo, "filters": [filtered(shapes)]})
    assert {i["primary_key"] for i in page["instances"]} == members(shapes)
    assert page["total"] == len(members(shapes))


def test_postgres_takes_the_shapes_alongside_another_filter(client, fx, geo) -> None:
    """The shapes are one filter among a set's others: their OR is bracketed,
    so it does not swallow the filter beside it."""
    page = evaluate(client, fx, {"object_type_id": geo, "filters": [
        filtered(ONE_OF_EACH),
        {"property": "$primary_key", "op": "neq", "value": "3"},
    ]})
    assert {i["primary_key"] for i in page["instances"]} == {"1", "5"}
