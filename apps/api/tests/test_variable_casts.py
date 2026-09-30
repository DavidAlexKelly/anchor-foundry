"""The rest of Workshop's casts, and Object RID (§569; `workshop` p.138-139).

    "String → Date: … For example, if passing in a string variable with the
     value 06/26/24, select M/dd/yyyy as the corresponding parser format to
     cast to a date type." (p.138)

    "if passing in a string variable with value 2024 06 26 12:50 AM, select
     yyyy M dd hh:mm aa as the corresponding parser format to cast to a
     timestamp type." (p.139)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_casts as vc  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402


def cast(value, target, **config):
    return vc.cast(value, target, config, "When")


# ---- p.138-139's own examples ---------------------------------------------------
def test_p138s_date_example() -> None:
    assert cast("06/26/24", "date", format="M/dd/yyyy") == "2024-06-26"


def test_p139s_timestamp_example() -> None:
    assert cast("2024 06 26 12:50 AM", "timestamp", format="yyyy M dd hh:mm aa") == \
        "2024-06-26T00:50:00Z"
    assert cast("2024 06 26 12:50 PM", "timestamp", format="yyyy M dd hh:mm aa") == \
        "2024-06-26T12:50:00Z"


# ---- parsers ------------------------------------------------------------------------
@pytest.mark.parametrize("value, parser, expected", [
    ("26 June 2024", "d MMMM yyyy", "2024-06-26"),
    ("26-Jun-2024", "dd-MMM-yyyy", "2024-06-26"),
    ("2024.06.26", "yyyy.MM.dd", "2024-06-26"),
    ("Day 26 of 06, 2024", "'Day' d 'of' MM, yyyy", "2024-06-26"),
    ("  06/26/2024 ", "MM/dd/yyyy", "2024-06-26"),
    # Quoted text is matched as written, even where it means something to a
    # regular expression.
    ("(26) Jun 2024", "'('d')' MMM yyyy", "2024-06-26"),
])
def test_a_date_by_its_parser(value, parser, expected) -> None:
    assert cast(value, "date", format=parser) == expected


def test_a_timestamp_by_its_parser_in_its_time_zone() -> None:
    assert cast("2024-06-26 14:05:09.250", "timestamp", format="yyyy-MM-dd HH:mm:ss.SSS",
                timezone="Europe/Paris") == "2024-06-26T12:05:09.250000Z"
    assert cast("2024-01-26 14:05", "timestamp", format="yyyy-MM-dd HH:mm",
                timezone="Europe/Paris") == "2024-01-26T13:05:00Z"


@pytest.mark.parametrize("value, parser, said", [
    ("06-26-24", "M/dd/yyyy", "does not match the parser"),
    ("02/30/24", "M/dd/yyyy", "is not a real date"),
    ("26 Juno 2024", "d MMMM yyyy", "'Juno' is not a month"),
    ("2024 06 26 13:50 PM", "yyyy M dd hh:mm aa", "13 is not an hour on a 12-hour clock"),
])
def test_a_value_its_parser_cannot_read_is_refused(value, parser, said) -> None:
    with pytest.raises(vc.CastError) as caught:
        cast(value, "date" if "h" not in parser else "timestamp", format=parser)
    assert said in str(caught.value)


@pytest.mark.parametrize("target, parser, said", [
    ("date", "MM/yyyy", "a parser to a date needs the day"),
    ("date", "dd/yyyy", "a parser to a date needs the month"),
    ("timestamp", "yyyy-MM-dd", "a parser to a timestamp needs the hour"),
    ("timestamp", "yyyy-MM-dd hh:mm", "a parser with a 12-hour clock (h) needs AM or PM (a)"),
    ("date", "yyyy-MM-dd EEE", "uses 'E', which is not a date or time letter"),
    ("date", "yyyy-MM-dd 'at", "opens a quote it does not close"),
    ("date", "yyyy-MM-dd yy", "names the year twice"),
    ("date", "d" * 61, "at most 60 characters"),
])
def test_a_parser_that_cannot_read_a_value_is_refused_at_save(target, parser, said) -> None:
    assert said in vc.check(target, {"format": parser})


def test_a_good_parser_passes() -> None:
    assert vc.check("timestamp", {"format": "yyyy M dd hh:mm aa"}) is None
    assert vc.check("date", {"format": "d MMM yyyy"}) is None
    assert vc.check("string", {}) is None


# ---- dates and timestamps, in a time zone -------------------------------------------
def test_timestamp_to_date_is_its_day_in_the_zone() -> None:
    assert cast("2024-06-26T23:30:00Z", "date") == "2024-06-26"
    assert cast("2024-06-26T23:30:00Z", "date", timezone="Europe/Paris") == "2024-06-27"
    assert cast("2024-06-26T23:30:00", "date", timezone="Asia/Tokyo") == "2024-06-27"
    assert cast("2024-06-26", "date") == "2024-06-26"


def test_date_to_timestamp_is_the_start_of_its_day_in_the_zone() -> None:
    assert cast("2024-06-26", "timestamp") == "2024-06-26T00:00:00Z"
    assert cast("2024-06-26", "timestamp", timezone="Europe/Paris") == "2024-06-25T22:00:00Z"
    assert cast("2024-06-26T10:00:00", "timestamp", timezone="Europe/Paris") == "2024-06-26T08:00:00Z"
    assert cast("2024-06-26T10:00:00+02:00", "timestamp") == "2024-06-26T08:00:00Z"


@pytest.mark.parametrize("value, target", [("soon", "date"), ("soon", "timestamp"),
                                           ("2024-13-01", "timestamp"), (5, "date")])
def test_something_that_is_not_a_date_or_time_is_refused(value, target) -> None:
    with pytest.raises(vc.CastError):
        cast(value, target)


def test_a_time_zone_is_named() -> None:
    assert "is not a time zone" in vc.check("date", {"timezone": "Mars/Olympus"})
    assert "is not a time zone" in vc.check("date", {"timezone": 5})
    assert vc.check("date", {"timezone": "UTC"}) is None


# ---- geopoints and geoshapes ----------------------------------------------------------
def test_string_to_geopoint_and_geoshape() -> None:
    assert cast("40.782142,-73.96596", "geopoint") == {"lat": 40.782142, "lon": -73.96596}
    ring = [[-73.958, 40.800], [-73.981, 40.768], [-73.973, 40.764], [-73.958, 40.800]]
    shape = cast('{"type":"Polygon","coordinates":[' + str(ring) + "]}", "geoshape")
    assert shape["type"] == "Polygon"
    with pytest.raises(vc.CastError):
        cast("somewhere", "geopoint")
    with pytest.raises(vc.CastError):
        cast("{}", "geoshape")


# ---- Object RID ---------------------------------------------------------------------------
def test_object_rid() -> None:
    assert vc.object_rid({"id": "abc", "object_type_id": "t"}, "Id") == "abc"
    assert vc.object_rid(None, "Id") is None
    with pytest.raises(vc.CastError):
        vc.object_rid("abc", "Id")
    with pytest.raises(vc.CastError):
        vc.object_rid({"object_type_id": "t"}, "Id")


# ---- the derivation ------------------------------------------------------------------------
def test_a_derivation_casts_with_its_parser_and_zone() -> None:
    parsed = wv.parse({
        "typed": {"id": "typed", "kind": "string", "label": "Typed", "default": "06/26/24"},
        "day": {"id": "day", "kind": "date", "label": "Day", "derivation": {
            "transform": "cast", "inputs": ["typed"], "config": {"to": "date", "format": "M/dd/yyyy"}}},
        "start": {"id": "start", "kind": "timestamp", "label": "Start", "derivation": {
            "transform": "cast", "inputs": ["day"],
            "config": {"to": "timestamp", "timezone": "Europe/Paris"}}},
        "picked": {"id": "picked", "kind": "single_object", "label": "Picked"},
        "rid": {"id": "rid", "kind": "string", "label": "Rid", "derivation": {
            "transform": "object_rid", "inputs": ["picked"], "config": {}}},
    })
    got = wv.evaluate(parsed, {"picked": {"id": "i-1", "object_type_id": "t"}})
    assert (got["day"], got["start"], got["rid"]) == ("2024-06-26", "2024-06-25T22:00:00Z", "i-1")


def test_a_cast_that_fails_says_which_variable() -> None:
    parsed = wv.parse({
        "typed": {"id": "typed", "kind": "string", "label": "Typed", "default": "later"},
        "day": {"id": "day", "kind": "date", "label": "Day", "derivation": {
            "transform": "cast", "inputs": ["typed"], "config": {"to": "date"}}},
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert str(caught.value).startswith("'Day' cannot convert 'later' to date: ")


@pytest.mark.parametrize("config, said", [
    ({"to": "date", "format": "MM/yyyy"}, "variable 'x': a parser to a date needs the day"),
    ({"to": "timestamp", "timezone": "Nowhere"}, "variable 'x': 'Nowhere' is not a time zone - "
                                                 "name one such as Europe/Paris"),
    ({"to": "shape"}, "variable 'x': cast target 'shape'; expected one of string, number, boolean, "
                      "date, timestamp, geopoint, geoshape"),
])
def test_a_cast_that_cannot_run_is_refused_at_save(config, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"a": {"id": "a", "kind": "string", "label": "A"},
                  "x": {"id": "x", "kind": "string", "label": "X",
                        "derivation": {"transform": "cast", "inputs": ["a"], "config": config}}})
    assert str(caught.value) == said


def test_object_rid_takes_one_object() -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"a": {"id": "a", "kind": "single_object", "label": "A"},
                  "x": {"id": "x", "kind": "string", "label": "X",
                        "derivation": {"transform": "object_rid", "inputs": ["a", "a"], "config": {}}}})
    assert "object_rid needs exactly one input" in str(caught.value)


def test_the_builder_offers_every_cast_target_the_server_takes() -> None:
    import re

    source = open(os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "components",
                               "canvas", "VariablesPanel.tsx")).read()
    line = re.search(r"const CAST_TARGETS = \[(.*?)\] as const;", source)
    assert line, "CAST_TARGETS not found in VariablesPanel.tsx"
    assert re.findall(r'"([^"]+)"', line.group(1)) == list(wv.CAST_TARGETS)


def test_string_concatenation_joins_an_arrays_elements() -> None:
    """p.138: "If an array variable is inputted, the operation will
    concatenate and cast elements within the array into string. Builders may
    optionally specify a separate input to be added between elements.\""""
    parsed = wv.parse({
        "tags": {"id": "tags", "kind": "array", "label": "Tags", "default": ["red", 2, True, None]},
        "name": {"id": "name", "kind": "string", "label": "Name", "default": "Kit"},
        "line": {"id": "line", "kind": "string", "label": "Line", "derivation": {
            "transform": "concat", "inputs": ["name", "tags"], "config": {"separator": ", "}}},
    })
    assert wv.evaluate(parsed, {})["line"] == "Kit, red, 2, true, "


def test_a_time_zone_can_come_from_a_variable() -> None:
    """p.139: "set dynamically using a string reference or variable"."""
    parsed = wv.parse({
        "day": {"id": "day", "kind": "date", "label": "Day", "default": "2024-06-26"},
        "zone": {"id": "zone", "kind": "string", "label": "Zone", "default": "Asia/Tokyo"},
        "start": {"id": "start", "kind": "timestamp", "label": "Start", "derivation": {
            "transform": "cast", "inputs": ["day", "zone"],
            "config": {"to": "timestamp", "timezone": "Europe/Paris"}}},
    })
    assert wv.evaluate(parsed, {})["start"] == "2024-06-25T15:00:00Z"
    # Nothing named falls back to the cast's own zone.
    assert wv.evaluate(parsed, {"zone": ""})["start"] == "2024-06-25T22:00:00Z"
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {"zone": "Moon/Base"})
    assert "'Moon/Base' is not a time zone" in str(caught.value)


def test_only_a_date_or_timestamp_cast_takes_a_zone_variable() -> None:
    def parse(to: str):
        return wv.parse({
            "a": {"id": "a", "kind": "string", "label": "A"},
            "z": {"id": "z", "kind": "string", "label": "Z"},
            "x": {"id": "x", "kind": "string", "label": "X", "derivation": {
                "transform": "cast", "inputs": ["a", "z"], "config": {"to": to}}},
        })
    assert parse("date")
    with pytest.raises(wv.VariableError) as caught:
        parse("number")
    assert str(caught.value) == "variable 'x': cast needs exactly one input"
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({
            "a": {"id": "a", "kind": "string", "label": "A"},
            "x": {"id": "x", "kind": "string", "label": "X", "derivation": {
                "transform": "cast", "inputs": ["a", "a", "a"], "config": {"to": "date"}}},
        })
    assert str(caught.value) == ("variable 'x': cast needs exactly one input, and a second "
                                 "naming its time zone at most")
