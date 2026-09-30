"""Selecting objects inside a polygon (§571; `workshop` p.301-302).

    "Draw options: Configure which shape drawing tools will be available in
     the toolbar. … selecting intersecting objects" (p.301)

    "Enable shaped-based selection: Enable a tool to select objects on the
     map that intersect a drawn shape." (p.302)

`within_box` (§230) answers a rectangle. A polygon is its own operator, for
the box's reason: one answered as its bounding box would select objects
outside what was drawn. **`object_sets.in_polygon` is the one definition**,
and both stores are held to it here - Postgres through the API, OpenSearch
through the fixture server - over the same rows `test_object_sets` holds the
box to.
"""
from __future__ import annotations

import os
import sys
import urllib.request
import uuid
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_object_sets import (  # noqa: E402,F401
    GEO_DECLARED, GEO_ROWS, GEO_TYPES, _fresh_identity_cache, anyio_backend, client, evaluate,
    fx, geo, opensearch,
)
from src.services import instance_store, object_sets  # noqa: E402


def corners(*pairs) -> dict:
    return {"points": [{"lat": lat, "lon": lon} for lat, lon in pairs]}


# A triangle round row 1 (52, 5) that leaves out row 2 (55, 10), which the
# triangle's bounding box would take in - the reason this is not a box.
TRIANGLE = corners((50, 0), (54, 0), (50, 12))
# A concave outline: an L whose upper arm holds row 1 (52, 5) and whose notch
# holds row 3 (20, 5), which the outline's bounding box would take in.
ELL = corners((10, -5), (60, -5), (60, 8), (30, 8), (30, 2), (10, 2))
# Round the antimeridian's east side only: row 5 (0, -175) and not row 4.
EAST_OF_SEAM = corners((-5, -179), (5, -179), (5, -170), (-5, -170))


def members(polygon: dict) -> set[str]:
    parsed = object_sets.parse_polygon(polygon)
    return {key for key, props in GEO_ROWS if object_sets.in_polygon(props.get("where"), parsed)}


# ---- the one definition ---------------------------------------------------------
def test_a_polygon_takes_in_what_it_outlines_and_not_its_bounding_box() -> None:
    assert members(TRIANGLE) == {"1"}


def test_a_concave_polygon_leaves_its_notch_out() -> None:
    assert members(ELL) == {"1"}
    # The same outline's box would take the notch's row in.
    box = object_sets.parse_box({"north": 60, "south": 10, "east": 8, "west": -5})
    assert object_sets.in_box({"lat": 20, "lon": 5}, box)


def test_a_polygon_either_side_of_the_seam() -> None:
    assert members(EAST_OF_SEAM) == {"5"}


@pytest.mark.parametrize("start", [0, 1, 2])
def test_the_corners_may_start_anywhere(start) -> None:
    """The edge back to the first corner counts like any other, whichever
    corner the outline starts from."""
    pairs = [(50, 0), (54, 0), (50, 12)]
    assert members(corners(*(pairs[start:] + pairs[:start]))) == {"1"}


def test_a_point_level_with_a_corner_is_counted_once() -> None:
    """Row 1 (52, 5) is level with the diamond's east and west corners, so a
    ray from it passes through a corner, which must count once."""
    assert members(corners((48, 5), (52, 12), (56, 5), (52, -2))) == {"1"}


def test_matching_a_definition_uses_the_one_definition() -> None:
    definition = object_sets.parse(
        {"object_type_id": str(uuid.uuid4()),
         "filters": [{"property": "where", "op": "within_polygon", "value": TRIANGLE}]},
        property_types=GEO_TYPES)
    assert {key for key, props in GEO_ROWS
            if object_sets.matches(props, definition.filters)} == {"1"}


def test_a_row_with_no_coordinate_is_in_no_polygon() -> None:
    parsed = object_sets.parse_polygon(TRIANGLE)
    assert object_sets.in_polygon(None, parsed) is False
    assert object_sets.in_polygon("somewhere", parsed) is False


def test_the_closing_corner_may_be_given_or_not() -> None:
    closed = corners((50, 0), (54, 0), (50, 12), (50, 0))
    assert object_sets.parse_polygon(closed) == object_sets.parse_polygon(TRIANGLE)


@pytest.mark.parametrize("raw, said", [
    ([], "must be an object with a list of points"),
    ({"points": "x"}, "must be an object with a list of points"),
    (corners((1, 1), (2, 2)), "at least three corners"),
    (corners((1, 1), (2, 2), (1, 1)), "at least three corners"),
    ({"points": [{"lat": 1, "lon": 1}, {"lat": 2}, {"lat": 3, "lon": 3}]},
     "point 2 needs a number for 'lon'"),
    ({"points": [{"lat": True, "lon": 1}] * 3}, "point 1 needs a number for 'lat'"),
    ({"points": ["x", "y", "z"]}, "point 1 must be an object with lat and lon"),
    (corners((91, 0), (0, 1), (1, 0)), "point 1's lat must be between -90 and 90"),
    (corners((0, 181), (0, 1), (1, 0)), "point 1's lon must be between -180 and 180"),
    (corners((0, -100), (1, 0), (0, 100)), "wider than half the world"),
    (corners(*[(n / 10, n / 10) for n in range(101)]), "at most 100 corners"),
])
def test_a_polygon_that_says_too_little_is_refused(raw, said) -> None:
    with pytest.raises(ValueError) as caught:
        object_sets.parse_polygon(raw)
    assert said in str(caught.value)


def test_a_polygon_needs_a_geopoint_behind_it() -> None:
    with pytest.raises(ValueError) as caught:
        object_sets.parse({"object_type_id": str(uuid.uuid4()), "filters": [
            {"property": "where", "op": "within_polygon", "value": TRIANGLE}]},
            property_types={"where": "string"})
    assert "within_polygon needs a geopoint" in str(caught.value)


# ---- both stores, held to it -------------------------------------------------------
POLYGONS = [TRIANGLE, ELL, EAST_OF_SEAM]
IDS = ["triangle", "concave", "seam"]


@pytest.mark.anyio
@pytest.mark.parametrize("polygon", POLYGONS, ids=IDS)
async def test_opensearch_answers_a_polygon_as_the_definition_does(opensearch: str, polygon) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-poly", object_type_id=type_id, source_id=source_id,
            rows=GEO_ROWS, synced_at=datetime.now(timezone.utc), declared=GEO_DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id),
             "filters": [{"property": "where", "op": "within_polygon", "value": polygon}]},
            property_types=GEO_TYPES,
        )
        rows, total = await store.evaluate_object_set(
            search_prefix="ws-poly", object_type_id=type_id,
            filters=definition.filters, limit=50, offset=0,
        )
        assert {r["primary_key"] for r in rows} == members(polygon)
        assert total == len(members(polygon))
    finally:
        await store.close()


@pytest.mark.parametrize("polygon", POLYGONS, ids=IDS)
def test_postgres_answers_a_polygon_as_the_definition_does(client, fx, geo, polygon) -> None:
    page = evaluate(client, fx, {"object_type_id": geo, "filters": [
        {"property": "where", "op": "within_polygon", "value": polygon}]})
    assert {i["primary_key"] for i in page["instances"]} == members(polygon)
    assert page["total"] == len(members(polygon))
