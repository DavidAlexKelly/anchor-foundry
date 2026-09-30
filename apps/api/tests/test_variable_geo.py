"""Workshop's geospatial operations on variables (§568; `workshop` p.142).

    "Geohash from geopoint: Converts a given geopoint into a geohash value as
     a string. Latitude from geopoint … Longitude from geopoint … MGRS from
     geopoint: Converts a given geopoint into an MGRS value as a string."
     (p.142)

**The MGRS references were computed by GeoTrans** (the `mgrs` package, which
wraps it) and are held here as fixed data, not recomputed: a projection that
looks right and is a hundred metres out is the failure worth catching, and
only an independent implementation can catch it. They include Norway's and
Svalbard's zone exceptions, both hemispheres, both edges of the grid and the
Equator at the prime meridian.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_geo as vg  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402

GEOTRANS = [
    ((48.8583, 2.2945), "31UDQ4825111943"),
    ((40.6892, -74.0445), "18TWL8073504695"),
    ((-33.8568, 151.2153), "56HLH3490052288"),
    ((64.1466, -21.9426), "27WVM5413813689"),
    ((60.0, 5.0), "32VKM7697958157"),
    ((78.2232, 15.6267), "33XWG1427883355"),
    ((-79.9, 0.1), "31CDM4324728161"),
    ((0.0, 0.0), "31NAA6602100000"),
    ((83.9, -30), "26XMU6442417856"),
    ((56.5, 3.5), "32VJH6162275290"),
    ((72.5, 9.5), "33XUA1563353151"),
    # Svalbard's other three zones.
    ((75, 5), "31XED5777024580"),
    ((75, 25), "35XMD4222924580"),
    ((75, 35), "37XCD8451927502"),
    # 180°E is zone 1, both sides of the Equator; just west of it is zone 60.
    ((10, 180), "01PAM7107106908"),
    ((-10, 180), "01LAJ7107193091"),
    ((10, 179.9), "60PZS1795506810"),
    # A northing within 0.00002 m of a whole metre, where the meridian arc's
    # smallest term decides which metre it is.
    ((40.00045, 10.0), "32TNK8535928286"),
]


def run(transform: str, value, **config):
    return vg.apply(transform, [value], config, "Where")


@pytest.mark.parametrize("point, expected", GEOTRANS)
def test_mgrs_agrees_with_geotrans(point, expected) -> None:
    assert run("mgrs", {"lat": point[0], "lon": point[1]}) == expected


def test_mgrs_refuses_the_poles() -> None:
    for lat in (-80.5, 84.5):
        with pytest.raises(vg.GeoError) as caught:
            run("mgrs", {"lat": lat, "lon": 0})
        assert "80°S to 84°N" in str(caught.value)


def test_the_geohash() -> None:
    # Wikipedia's own example.
    assert run("geohash", {"lat": 57.64911, "lon": 10.40744}, precision=11) == "u4pruydqqvj"
    # To twelve by default, as pygeohash also gives it.
    assert run("geohash", {"lat": 57.64911, "lon": 10.40744}) == "u4pruydqqvj8"
    assert run("geohash", {"lat": 57.64911, "lon": 10.40744}, precision=1) == "u"
    assert run("geohash", {"lat": -90, "lon": -180}, precision=3) == "000"
    assert run("geohash", {"lat": 90, "lon": 180}, precision=3) == "zzz"
    # A point on an edge belongs to the upper half, as pygeohash has it.
    assert run("geohash", {"lat": 0, "lon": 0}, precision=6) == "s00000"
    assert run("geohash", {"lat": -45, "lon": 90}, precision=6) == "q00000"


def test_latitude_and_longitude() -> None:
    assert run("latitude", {"lat": 51.5, "lon": -0.12}) == 51.5
    assert run("longitude", {"lat": 51.5, "lon": -0.12}) == -0.12


def test_a_geopoint_as_text_is_read_as_a_property_reads_it() -> None:
    assert run("latitude", "51.5,-0.12") == 51.5
    assert run("longitude", "51.5, -0.12") == -0.12


def test_nothing_yet_is_nothing() -> None:
    assert run("mgrs", None) is None


@pytest.mark.parametrize("value", ["somewhere", "95,-0.12", {"lat": 1}])
def test_something_that_is_not_a_geopoint_is_refused(value) -> None:
    with pytest.raises(vg.GeoError) as caught:
        run("latitude", value)
    assert str(caught.value).startswith("'Where' takes a geopoint: ")


def test_a_derivation_evaluates_geospatial_operations() -> None:
    parsed = wv.parse({
        "at": {"id": "at", "kind": "string", "label": "At", "default": "48.8583,2.2945"},
        "grid": {"id": "grid", "kind": "string", "label": "Grid",
                 "derivation": {"transform": "mgrs", "inputs": ["at"], "config": {}}},
        "hash": {"id": "hash", "kind": "string", "label": "Hash",
                 "derivation": {"transform": "geohash", "inputs": ["at"], "config": {"precision": 5}}},
        "lat": {"id": "lat", "kind": "number", "label": "Lat",
                "derivation": {"transform": "latitude", "inputs": ["at"], "config": {}}},
    })
    got = wv.evaluate(parsed, {})
    assert (got["grid"], got["hash"], got["lat"]) == ("31UDQ4825111943", "u09tu", 48.8583)


def test_a_derivation_over_something_else_says_which_variable() -> None:
    parsed = wv.parse({
        "at": {"id": "at", "kind": "string", "label": "At", "default": "Paris"},
        "lat": {"id": "lat", "kind": "number", "label": "Lat",
                "derivation": {"transform": "latitude", "inputs": ["at"], "config": {}}},
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert str(caught.value).startswith("'Lat' takes a geopoint: ")


@pytest.mark.parametrize("transform, inputs, config, said", [
    ("latitude", [], {}, "variable 'x': latitude takes 1 input"),
    ("mgrs", ["at", "at"], {}, "variable 'x': mgrs takes 1 input"),
    ("geohash", ["at"], {"precision": 13}, "variable 'x': geohash's precision must be a whole "
                                           "number of characters from 1 to 12"),
    ("geohash", ["at"], {"precision": 0}, None),
    ("geohash", ["at"], {"precision": True}, None),
])
def test_a_derivation_that_cannot_run_is_refused_at_save(transform, inputs, config, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"at": {"id": "at", "kind": "string", "label": "At"},
                  "x": {"id": "x", "kind": "string", "label": "X",
                        "derivation": {"transform": transform, "inputs": inputs, "config": config}}})
    if said:
        assert str(caught.value) == said
    else:
        assert "precision must be a whole number" in str(caught.value)
