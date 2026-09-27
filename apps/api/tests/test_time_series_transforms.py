"""Time series transforms (§524; `workshop` p.583-586).

    "A time series transform performs a mathematical operation on input time
     series data to yield a new output time series. These input time series
     can be time series properties or the outputs from other transforms, which
     allows multiple transforms to be chained together." (p.583)

**The arithmetic is checked against a real DuckDB**, over a table shaped like
the dataset `points_sql` reads: a SQL string that looks right and computes the
wrong rolling window is the failure worth catching, and only running it
catches it. The endpoint tests then check that the transforms reach that SQL.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_time_series import (  # noqa: E402,F401
    _fresh_identity_cache, client, declare, fx, instance, ontology, pbase, points, wbase,
)
from src.services import time_series as ts  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402

#: S1 reads 1, 3, 6, 10 on the 1st, 2nd, 4th and 5th; S2 is another sensor
#: whose readings must never leak into S1's.
ROWS = [
    ("S1", "2026-01-01 00:00:00", 1.0),
    ("S1", "2026-01-02 00:00:00", 3.0),
    ("S1", "2026-01-04 00:00:00", 6.0),
    ("S1", "2026-01-05 00:00:00", 10.0),
    ("S2", "2026-01-03 00:00:00", 1000.0),
]


def run(transforms: list[dict], **kw) -> list[tuple[datetime, float]]:
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE dataset (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO dataset VALUES (?, ?, ?)", kw.pop("rows", ROWS))
        sql = ts.points_sql(key_column="sensor", timestamp_column="taken", value_column="reading",
                            series_id="S1", interval=kw.pop("interval", "none"),
                            aggregate=kw.pop("aggregate", "avg"),
                            transforms=ts.parse_transforms(transforms), **kw)
        return [(r[0], None if r[1] is None else float(r[1])) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def values(transforms: list[dict], **kw) -> list[float]:
    return [v for _, v in run(transforms, **kw)]


def day(n: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, n, hour)


# ---- the arithmetic --------------------------------------------------------------
def test_no_transforms_is_the_series_itself() -> None:
    assert run([]) == [(day(1), 1.0), (day(2), 3.0), (day(4), 6.0), (day(5), 10.0)]


@pytest.mark.parametrize("aggregate, expected", [
    ("sum", [1, 4, 10, 20]),
    ("avg", [1, 2, 10 / 3, 5]),
    ("min", [1, 1, 1, 1]),
    ("max", [1, 3, 6, 10]),
    ("count", [1, 2, 3, 4]),
])
def test_cumulative_aggregates_everything_so_far(aggregate, expected) -> None:
    """p.584: "aggregating over all earlier points, including the input point
    itself"."""
    assert values([{"kind": "cumulative", "aggregate": aggregate}]) == pytest.approx(expected)


def test_a_cumulative_standard_deviation_starts_undefined() -> None:
    """The sample standard deviation, which one point does not have."""
    got = values([{"kind": "cumulative", "aggregate": "stddev"}])
    three = ((1 - 10 / 3) ** 2 + (3 - 10 / 3) ** 2 + (6 - 10 / 3) ** 2) / 2
    assert got[0] is None
    assert got[1:] == pytest.approx([math.sqrt(2), math.sqrt(three), math.sqrt(46 / 3)])


def test_rolling_aggregates_a_window_of_time_not_of_points() -> None:
    """p.584: "the points that fall in a fixed-size temporal window preceding
    it, including the input point itself". Two days back from the 4th reaches
    the 2nd but not the 1st; from the 5th it reaches the 4th and not the 2nd."""
    assert values([{"kind": "rolling", "aggregate": "sum", "window": 2, "unit": "day"}]) == [
        1, 4, 9, 16]
    assert values([{"kind": "rolling", "aggregate": "count", "window": 1, "unit": "day"}]) == [
        1, 2, 1, 2]
    assert values([{"kind": "rolling", "aggregate": "max", "window": 36, "unit": "hour"}]) == [
        1, 3, 6, 10]
    assert values([{"kind": "rolling", "aggregate": "avg", "window": 1, "unit": "week"}]) == (
        pytest.approx([1, 2, 10 / 3, 5]))


def test_a_derivative_is_the_rate_per_the_unit_chosen() -> None:
    """p.585: daily readings, read as a rate per week, are scaled by seven.
    The first point has nothing to change from and is left out."""
    per_day = run([{"kind": "derivative", "unit": "day"}])
    assert per_day == [(day(2), 2.0), (day(4), 1.5), (day(5), 4.0)]
    assert values([{"kind": "derivative", "unit": "week"}]) == [14.0, 10.5, 28.0]
    assert values([{"kind": "derivative", "unit": "hour"}]) == pytest.approx([2 / 24, 1.5 / 24, 4 / 24])


def test_two_readings_at_one_instant_have_no_rate() -> None:
    """Not infinity: a rate over no time is not a number to draw."""
    rows = [("S1", "2026-01-01 00:00:00", 1.0), ("S1", "2026-01-01 00:00:00", 5.0),
            ("S1", "2026-01-02 00:00:00", 7.0)]
    got = values([{"kind": "derivative", "unit": "day"}], rows=rows)
    assert len(got) == 1 and all(math.isfinite(v) for v in got), got


def test_a_shift_moves_every_point_and_keeps_its_value() -> None:
    assert run([{"kind": "shift", "by": 3, "unit": "hour"}]) == [
        (day(1, 3), 1.0), (day(2, 3), 3.0), (day(4, 3), 6.0), (day(5, 3), 10.0)]
    assert [at for at, _ in run([{"kind": "shift", "by": -1, "unit": "week"}])][0] == datetime(2025, 12, 25)


def test_a_range_keeps_the_points_inside_it_ends_included() -> None:
    assert values([{"kind": "range", "start": "2026-01-02T00:00:00", "end": "2026-01-04T00:00:00"}]) == [3, 6]
    assert values([{"kind": "range", "start": "2026-01-04T00:00:00"}]) == [6, 10]
    assert values([{"kind": "range", "end": "2026-01-01T00:00:00"}]) == [1]


def test_transforms_chain_in_the_order_given() -> None:
    """p.583: "the outputs from other transforms … chained together"."""
    # Cumulative, then its rate: the rate of a running total is the reading
    # spread over the gap.
    assert values([{"kind": "cumulative", "aggregate": "sum"},
                   {"kind": "derivative", "unit": "day"}]) == [3.0, 3.0, 10.0]
    # The same two, the other way round, are a different series.
    assert values([{"kind": "derivative", "unit": "day"},
                   {"kind": "cumulative", "aggregate": "sum"}]) == [2.0, 3.5, 7.5]
    # A shift then a range sees the shifted times.
    assert values([{"kind": "shift", "by": 1, "unit": "day"},
                   {"kind": "range", "start": "2026-01-05T00:00:00"}]) == [6, 10]


def test_transforms_run_on_the_bucketed_series() -> None:
    # Weeks start on Monday: the 1st to the 4th are one week, the 5th the next.
    assert values([{"kind": "cumulative", "aggregate": "sum"}], interval="week", aggregate="sum") == [
        10.0, 20.0]


def test_the_cap_comes_after_the_transforms() -> None:
    """A range over a capped read would find nothing past the cap; over
    every point it finds the late ones, and then the cap applies."""
    assert values([{"kind": "range", "start": "2026-01-04T00:00:00"}], limit=1) == [6]
    assert values([{"kind": "cumulative", "aggregate": "sum"}], limit=3) == [1, 4, 10]
    assert values([], limit=2) == [1, 3]


# ---- what a transform may say -----------------------------------------------------
@pytest.mark.parametrize("raw, said", [
    ({"kind": "cumulative"}, "transforms must be a list"),
    ([{"kind": "cumulative", "aggregate": "sum"}] * 11, "a series takes at most 10 transforms"),
    (["cumulative"], "transform 1: must be an object"),
    ([{"kind": "smooth"}],
     "transform 1: the kind must be one of cumulative, rolling, derivative, shift, range"),
    ([{"kind": "cumulative", "aggregate": "median"}],
     "transform 1: the aggregate must be one of sum, avg, min, max, count, stddev"),
    ([{"kind": "rolling", "aggregate": "sum", "window": 0, "unit": "day"}],
     "transform 1: the window must be from 1 to 100000"),
    ([{"kind": "rolling", "aggregate": "sum", "window": 100001, "unit": "day"}],
     "transform 1: the window must be from 1 to 100000"),
    ([{"kind": "rolling", "aggregate": "sum", "window": "2", "unit": "day"}],
     "transform 1: the window must be a whole number"),
    ([{"kind": "rolling", "aggregate": "sum", "window": True, "unit": "day"}],
     "transform 1: the window must be a whole number"),
    ([{"kind": "rolling", "aggregate": "sum", "window": 2, "unit": "fortnight"}],
     "transform 1: the unit must be one of second, minute, hour, day, week"),
    ([{"kind": "derivative"}], "transform 1: the unit must be one of second, minute, hour, day, week"),
    ([{"kind": "shift", "by": 0, "unit": "day"}],
     "transform 1: the shift must be non-zero and at most 100000 either way"),
    ([{"kind": "shift", "by": -100001, "unit": "day"}],
     "transform 1: the shift must be non-zero and at most 100000 either way"),
    ([{"kind": "range"}], "transform 1: a time range needs a start, an end or both"),
    ([{"kind": "range", "start": "", "end": None}], "transform 1: a time range needs a start, an end or both"),
    ([{"kind": "range", "start": "soon"}], "transform 1: the start 'soon' is not a date and time"),
    ([{"kind": "range", "end": "later"}], "transform 1: the end 'later' is not a date and time"),
    ([{"kind": "range", "start": "2026-01-05", "end": "2026-01-01"}], "transform 1: the start is after the end"),
    ([{"kind": "derivative", "unit": "day"}, {"kind": "shift", "by": 1}],
     "transform 2: the unit must be one of second, minute, hour, day, week"),
])
def test_a_transform_that_could_not_run_is_refused(raw, said) -> None:
    with pytest.raises(ValueError) as caught:
        ts.parse_transforms(raw)
    assert str(caught.value) == said


def test_what_a_transform_may_say() -> None:
    assert ts.parse_transforms(None) == []
    assert ts.parse_transforms([{"kind": "shift", "by": -100000, "unit": "second", "extra": 1}]) == [
        {"kind": "shift", "by": -100000, "unit": "second"}]
    assert ts.parse_transforms([{"kind": "rolling", "aggregate": "stddev", "window": 100000,
                                 "unit": "minute"}])[0]["window"] == 100000
    # A range's ends are normalised, and one end is enough.
    assert ts.parse_transforms([{"kind": "range", "start": "2026-01-01", "end": "2026-01-01"}]) == [
        {"kind": "range", "start": "2026-01-01T00:00:00", "end": "2026-01-01T00:00:00"}]
    assert len(ts.parse_transforms([{"kind": "derivative", "unit": "day"}] * 10)) == 10


# ---- where they are kept and read -----------------------------------------------
def test_a_series_variable_carries_its_transforms() -> None:
    parsed = wv.parse({
        "v_object": {"id": "v_object", "kind": "single_object", "label": "Picked"},
        "v_series": {"id": "v_series", "kind": "time_series_set", "label": "Readings",
                     "derivation": {"transform": "object_series", "inputs": ["v_object"],
                                    "config": {"property": "readings", "transforms": [
                                        {"kind": "cumulative", "aggregate": "sum", "x": 1}]}}},
    })
    resolved = wv.evaluate(parsed, {"v_object": {"object_type_id": "t", "id": "i"}})
    assert resolved["v_series"]["transforms"] == [{"kind": "cumulative", "aggregate": "sum"}]


def test_a_series_variable_refuses_a_transform_that_could_not_run() -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({
            "v_object": {"id": "v_object", "kind": "single_object", "label": "Picked"},
            "v_series": {"id": "v_series", "kind": "time_series_set", "label": "Readings",
                         "derivation": {"transform": "object_series", "inputs": ["v_object"],
                                        "config": {"property": "readings",
                                                   "transforms": [{"kind": "smooth"}]}}},
        })
    assert str(caught.value) == ("variable 'v_series': transform 1: the kind must be one of "
                                 "cumulative, rolling, derivative, shift, range")


def test_the_points_endpoints_apply_transforms(client, fx, ontology, instance) -> None:
    assert declare(client, fx, ontology).status_code == 200
    cumulative = json.dumps([{"kind": "cumulative", "aggregate": "sum"}])
    r = points(client, fx, ontology, transforms=cumulative)
    assert [p["value"] for p in r.json()["points"]] == [10, 30, 60]
    r = client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}/series/readings/points",
        headers=hdr(fx.viewer_sub), params={"transforms": cumulative, "interval": "day",
                                            "aggregate": "sum"})
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["points"]] == [30, 60]
    # Empty is none.
    assert [p["value"] for p in points(client, fx, ontology, transforms="").json()["points"]] == [
        10, 20, 30]


def test_the_points_endpoints_refuse_what_is_not_a_transform(client, fx, ontology, instance) -> None:
    assert declare(client, fx, ontology).status_code == 200
    r = points(client, fx, ontology, transforms="[{")
    assert (r.status_code, r.json()["detail"]) == (422, "transforms must be a JSON list")
    r = points(client, fx, ontology, transforms=json.dumps([{"kind": "smooth"}]))
    assert r.status_code == 422
    assert r.json()["detail"].startswith("transform 1: the kind must be one of")
    r = client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}/series/readings/points",
        headers=hdr(fx.viewer_sub), params={"transforms": json.dumps({"kind": "range"})})
    assert (r.status_code, r.json()["detail"]) == (422, "transforms must be a list")


def test_the_browser_offers_what_the_server_takes() -> None:
    source = open(os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "components",
                               "canvas", "series-transforms.ts")).read()

    def listed(values) -> str:
        return ", ".join(f'"{v}"' for v in values)

    assert f"export const TRANSFORM_KINDS = [{listed(ts.TRANSFORM_KINDS)}] as const;" in source
    assert f"export const WINDOW_AGGREGATES = [{listed(ts.WINDOW_AGGREGATES)}] as const;" in source
    assert f"export const TIME_UNITS = [{listed(ts.TIME_UNITS)}] as const;" in source
    assert f"export const MAX_TRANSFORMS = {ts.MAX_TRANSFORMS};" in source
    assert f"export const MAX_SPAN = {ts.MAX_SPAN:_};" in source
