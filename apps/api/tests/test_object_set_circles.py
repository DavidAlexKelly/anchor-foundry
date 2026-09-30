"""Selecting objects within a distance of a point (§572; `workshop` p.301-302).

    "Draw options: Configure which shape drawing tools will be available in
     the toolbar. … selecting intersecting objects" (p.301)

    "Enable shaped-based selection: Enable a tool to select objects on the
     map that intersect a drawn shape." (p.302)

A circle is a centre and a radius in metres on the ground: great-circle
distance on the mean Earth, the radius OpenSearch's `geo_distance` measures
with. **`object_sets.in_circle` is the one definition**, and both stores are
held to it here - Postgres through the API, OpenSearch through the fixture
server - over the rows `test_object_sets` holds the box to.
"""
from __future__ import annotations

import math
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

R = object_sets.EARTH_RADIUS_M


def circle(lat, lon, km) -> dict:
    return {"lat": lat, "lon": lon, "radius": km * 1000}


# Row 2 (55, 10) is 469.5 km from row 1 (52, 5).
TAKES_ROW_2 = circle(52, 5, 470)
LEAVES_ROW_2 = circle(52, 5, 469)
# Rows 4 (0, 175) and 5 (0, -175) are each 556 km from the antimeridian.
ON_THE_SEAM = circle(0, 180, 600)
# 4 degrees from row 5 and 6 from row 4, across the seam.
EAST_OF_SEAM = circle(0, -179, 600)
# Round the pole: everything north of about 51.3 degrees, whatever its meridian.
ROUND_THE_POLE = circle(90, 0, 4300)
# The widest circle, centred a hair off row 2's far side, where both stores
# round the haversine term to 1 + 2**-52.
FAR_SIDE = circle(-54.9999999, -170, 20_000)
# Row 6 (0, 0) exactly on the edge: this radius is the distance both stores
# compute, to the bit, from (0, 1).
ON_THE_EDGE = {"lat": 0, "lon": 1, "radius": 111195.07973436874}
# 8 cm short of it, which a store measuring on a rounder 6,371 km Earth
# would take in.
JUST_SHORT = {"lat": 0, "lon": 1, "radius": 111195.0}


def members(raw: dict) -> set[str]:
    parsed = object_sets.parse_circle(raw)
    return {key for key, props in GEO_ROWS if object_sets.in_circle(props.get("where"), parsed)}


# ---- the one definition ---------------------------------------------------------
@pytest.mark.parametrize("a, b, metres", [
    ((0, 0), (0, 1), R * math.pi / 180),     # a degree of the Equator
    ((0, 0), (1, 0), R * math.pi / 180),     # a degree of a meridian
    ((0, 0), (90, 0), R * math.pi / 2),      # the Equator to the pole
    ((0, 0), (0, 180), R * math.pi),         # the far side of the world
    ((10, 20), (10, 20), 0.0),
    ((0, 179.5), (0, -179.5), R * math.pi / 180),  # across the seam, not round the world
    ((-87.5, 0), (87.5, -180), R * math.pi),  # a haversine term of 1 + 2**-52
])
def test_distance_is_on_the_ground(a, b, metres) -> None:
    assert object_sets.distance_m(*a, *b) == pytest.approx(metres, abs=1e-6)
    assert object_sets.distance_m(*b, *a) == pytest.approx(metres, abs=1e-6)


def test_the_radius_is_the_mean_earths() -> None:
    """The radius OpenSearch measures `geo_distance` with, so both stores
    draw one circle."""
    assert R == 6371008.7714


def test_a_circle_takes_in_what_is_within_its_radius() -> None:
    assert members(TAKES_ROW_2) == {"1", "2"}
    assert members(LEAVES_ROW_2) == {"1"}


def test_a_point_on_the_edge_is_in() -> None:
    edge = object_sets.parse_circle({"lat": 0, "lon": 0, "radius": R * math.pi / 180})
    assert object_sets.in_circle({"lat": 0, "lon": 1}, edge)
    inside = object_sets.parse_circle({"lat": 0, "lon": 0, "radius": R * math.pi / 180 - 1})
    assert not object_sets.in_circle({"lat": 0, "lon": 1}, inside)


def test_a_row_exactly_on_the_edge_is_in() -> None:
    assert members(ON_THE_EDGE) == {"6"}
    assert members(JUST_SHORT) == set()


def test_a_circle_has_no_seam() -> None:
    assert members(ON_THE_SEAM) == {"4", "5"}
    assert members(EAST_OF_SEAM) == {"5"}


def test_a_circle_round_the_pole_takes_in_every_meridian() -> None:
    assert members(ROUND_THE_POLE) == {"1", "2"}


def test_the_widest_circle_leaves_out_only_its_far_side() -> None:
    assert members(FAR_SIDE) == {"1", "3", "4", "5", "6"}


def test_matching_a_definition_uses_the_one_definition() -> None:
    definition = object_sets.parse(
        {"object_type_id": str(uuid.uuid4()),
         "filters": [{"property": "where", "op": "within_distance", "value": TAKES_ROW_2}]},
        property_types=GEO_TYPES)
    assert {key for key, props in GEO_ROWS
            if object_sets.matches(props, definition.filters)} == {"1", "2"}


def test_a_row_with_no_coordinate_is_in_no_circle() -> None:
    parsed = object_sets.parse_circle(TAKES_ROW_2)
    assert object_sets.in_circle(None, parsed) is False
    assert object_sets.in_circle("somewhere", parsed) is False


@pytest.mark.parametrize("raw, said", [
    ([], "must be an object with lat, lon and radius"),
    ({"lat": 1, "lon": 1}, "a circle needs a number for 'radius', got None"),
    ({"lat": True, "lon": 1, "radius": 5}, "a circle needs a number for 'lat', got True"),
    ({"lat": 1, "lon": "1", "radius": 5}, "a circle needs a number for 'lon'"),
    (circle(91, 0, 1), "a circle's lat must be between -90 and 90"),
    (circle(0, -181, 1), "a circle's lon must be between -180 and 180"),
    (circle(0, 0, 0), "a circle's radius is metres, more than 0 and at most 20,000,000"),
    (circle(0, 0, -1), "radius is metres"),
    (circle(0, 0, 20_000.001), "radius is metres"),
])
def test_a_circle_that_says_too_little_is_refused(raw, said) -> None:
    with pytest.raises(ValueError) as caught:
        object_sets.parse_circle(raw)
    assert said in str(caught.value)


def test_the_widest_circle_is_allowed() -> None:
    assert object_sets.parse_circle(circle(-90, 180, 20_000)).radius == 20_000_000


def test_a_circle_needs_a_geopoint_behind_it() -> None:
    with pytest.raises(ValueError) as caught:
        object_sets.parse({"object_type_id": str(uuid.uuid4()), "filters": [
            {"property": "where", "op": "within_distance", "value": TAKES_ROW_2}]},
            property_types={"where": "string"})
    assert "within_distance needs a geopoint" in str(caught.value)


# ---- both stores, held to it -------------------------------------------------------
CIRCLES = [TAKES_ROW_2, LEAVES_ROW_2, ON_THE_SEAM, EAST_OF_SEAM, ROUND_THE_POLE, FAR_SIDE,
           ON_THE_EDGE, JUST_SHORT]
IDS = ["takes-row-2", "leaves-row-2", "seam", "east-of-seam", "pole", "far-side", "on-the-edge",
       "just-short"]


@pytest.mark.anyio
@pytest.mark.parametrize("raw", CIRCLES, ids=IDS)
async def test_opensearch_answers_a_circle_as_the_definition_does(opensearch: str, raw) -> None:
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-circle", object_type_id=type_id, source_id=source_id,
            rows=GEO_ROWS, synced_at=datetime.now(timezone.utc), declared=GEO_DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id),
             "filters": [{"property": "where", "op": "within_distance", "value": raw}]},
            property_types=GEO_TYPES,
        )
        rows, total = await store.evaluate_object_set(
            search_prefix="ws-circle", object_type_id=type_id,
            filters=definition.filters, limit=50, offset=0,
        )
        assert {r["primary_key"] for r in rows} == members(raw)
        assert total == len(members(raw))
    finally:
        await store.close()


@pytest.mark.parametrize("raw", CIRCLES, ids=IDS)
def test_postgres_answers_a_circle_as_the_definition_does(client, fx, geo, raw) -> None:
    page = evaluate(client, fx, {"object_type_id": geo, "filters": [
        {"property": "where", "op": "within_distance", "value": raw}]})
    assert {i["primary_key"] for i in page["instances"]} == members(raw)
    assert page["total"] == len(members(raw))
