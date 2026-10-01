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


def periodic(**over) -> dict:
    return {"kind": "periodic", "aggregate": "sum", "window": 2, "unit": "day",
            "align": "2026-01-01T00:00:00", **over}


def test_periodic_windows_start_at_the_alignment_and_do_not_overlap() -> None:
    """p.584: "Output points are generated at equally spaced, non-overlapping
    time intervals … aligned with a user-specified alignment timestamp". Two-day
    windows from the 1st: the 1st and 2nd, the 3rd and 4th, the 5th and 6th."""
    assert run([periodic()]) == [(day(1), 4.0), (day(3), 6.0), (day(5), 10.0)]
    assert run([periodic(aggregate="count")]) == [(day(1), 2.0), (day(3), 1.0), (day(5), 1.0)]


def test_an_end_window_is_stamped_with_its_end_and_takes_what_precedes_it() -> None:
    """p.584: "End means that each output point represents the end of a time
    interval, and is an aggregate over the input points that precede it". A
    point on the boundary ends a window rather than starting one."""
    assert run([periodic(window_type="end")]) == [(day(1), 1.0), (day(3), 3.0), (day(5), 16.0)]


def test_moving_the_alignment_moves_the_windows() -> None:
    assert run([periodic(align="2026-01-02T00:00:00")]) == [
        (datetime(2025, 12, 31), 1.0), (day(2), 3.0), (day(4), 16.0)]
    # A zone is read as the instant it names: midnight in UTC+1 is 23:00 UTC.
    assert run([periodic(align="2026-01-02T00:00:00+01:00", window=1)])[0][0] == datetime(2025, 12, 31, 23)


def test_without_an_alignment_windows_line_up_on_1970() -> None:
    """1 January 1970 was a Thursday, and so was 1 January 2026: one week-long
    window from it holds all four readings."""
    assert run([{"kind": "periodic", "aggregate": "sum", "window": 1, "unit": "week"}]) == [
        (day(1), 20.0)]


@pytest.mark.parametrize("method, expected", [
    # Gaps of one, two and one days, under 1-3, 3-6 and 6-10.
    ("linear", [0, 2, 11, 19]),
    ("left", [0, 1, 7, 13]),
    ("right", [0, 3, 15, 25]),
])
def test_an_integral_is_the_area_so_far(method, expected) -> None:
    """p.585: "the cumulative area under the input time series", with p.585's
    three ways to take the height between two points."""
    assert values([{"kind": "integral", "unit": "day", "method": method}]) == expected


def test_an_integral_is_in_the_unit_chosen() -> None:
    """p.585's kilowatt-hours: the same area per hour is twenty-four times the
    area per day."""
    assert values([{"kind": "integral", "unit": "hour"}]) == [0, 48, 264, 456]


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
     "transform 1: the kind must be one of cumulative, periodic, rolling, derivative, integral, shift, range, formula, filter, sample, combine, event_statistics"),
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
    ([{"kind": "periodic", "window": 2, "unit": "day"}],
     "transform 1: the aggregate must be one of sum, avg, min, max, count, stddev"),
    ([{"kind": "periodic", "aggregate": "sum", "window": 0, "unit": "day"}],
     "transform 1: the window must be from 1 to 100000"),
    ([{"kind": "periodic", "aggregate": "sum", "window": 2, "unit": "month"}],
     "transform 1: the unit must be one of second, minute, hour, day, week"),
    ([{"kind": "periodic", "aggregate": "sum", "window": 2, "unit": "day", "window_type": "middle"}],
     "transform 1: the window type must be one of start, end"),
    ([{"kind": "periodic", "aggregate": "sum", "window": 2, "unit": "day", "align": "noon"}],
     "transform 1: the alignment 'noon' is not a date and time"),
    ([{"kind": "integral", "unit": "day", "method": "simpson"}],
     "transform 1: the method must be one of linear, left, right"),
    ([{"kind": "integral"}], "transform 1: the unit must be one of second, minute, hour, day, week"),
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
    # A periodic window starts its windows at 1970 unless told otherwise, and
    # an integral is linear unless told otherwise.
    assert ts.parse_transforms([{"kind": "periodic", "aggregate": "avg", "window": 2, "unit": "week"},
                                {"kind": "integral", "unit": "hour"}]) == [
        {"kind": "periodic", "aggregate": "avg", "window": 2, "unit": "week",
         "align": "1970-01-01T00:00:00", "window_type": "start"},
        {"kind": "integral", "unit": "hour", "method": "linear"}]
    assert ts.parse_transforms([periodic(window_type="end", align="")])[0]["align"] == ts.EPOCH


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
                                 "cumulative, periodic, rolling, derivative, integral, shift, range, formula, filter, sample, combine, event_statistics")


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
    assert f"export const WINDOW_TYPES = [{listed(ts.WINDOW_TYPES)}] as const;" in source
    assert f"export const INTEGRATION_METHODS = [{listed(ts.INTEGRATION_METHODS)}] as const;" in source
    assert f"export const FORMULA_FUNCTIONS = [{listed(ts.FORMULA_FUNCTIONS)}] as const;" in source
    assert f"export const MAX_FORMULA = {ts.MAX_FORMULA};" in source
    assert f"export const MAX_FORMULA_INPUTS = {ts.MAX_FORMULA_INPUTS};" in source
    assert f"export const MAX_SPAN = {ts.MAX_SPAN:_};" in source
    # §648's two.
    assert f"export const FILTER_OPERATORS = [{listed(ts.FILTER_OPERATORS)}] as const;" in source
    assert f"export const SAMPLE_METHODS = [{listed(ts.SAMPLE_METHODS)}] as const;" in source
    assert f"export const COMBINE_AGGREGATES = [{listed(ts.COMBINE_AGGREGATES)}] as const;" in source


# ---- §532: p.586's formula ---------------------------------------------------------
def formula(expression: str) -> dict:
    return {"kind": "formula", "expression": expression}


def test_a_formula_is_p586s_arithmetic_on_the_series() -> None:
    """p.586: "The example below scales the input time series by a factor of
    two, and adds five to the result." S1 reads 1, 3, 6, 10."""
    assert values([formula("x * 2 + 5")]) == [7, 11, 17, 25]
    assert values([formula("(x + 1) / 2")]) == [1, 2, 3.5, 5.5]
    assert values([formula("-x ** 2")]) == [-1, -9, -36, -100]
    assert values([formula("x - 3")]) == [-2, 0, 3, 7]
    assert values([formula("+x")]) == [1, 3, 6, 10]


def test_a_formula_calls_its_functions() -> None:
    assert values([formula("sqrt(x)")]) == pytest.approx([1, math.sqrt(3), math.sqrt(6), math.sqrt(10)])
    assert values([formula("round(ln(x) * 100)")]) == [0, 110, 179, 230]
    assert values([formula("log10(x * 10)")]) == pytest.approx([1, math.log10(30), math.log10(60), 2])
    assert values([formula("abs(x - 5)")]) == [4, 2, 1, 5]
    assert values([formula("floor(x / 4)")]) == [0, 0, 1, 2]
    assert values([formula("ceil(x / 4)")]) == [1, 1, 2, 3]
    assert values([formula("exp(x - x)")]) == [1, 1, 1, 1]


def test_where_a_formula_has_no_answer_is_a_gap() -> None:
    """A division by zero, a square root of a negative, a logarithm of
    nothing and a fractional power of a negative are gaps, not a failed read;
    and so is an overflow, since infinity is not a reading."""
    assert values([formula("1 / (x - 3)")]) == [-0.5, None, pytest.approx(1 / 3), pytest.approx(1 / 7)]
    assert values([formula("sqrt(x - 3)")]) == [None, 0, pytest.approx(math.sqrt(3)), pytest.approx(math.sqrt(7))]
    assert values([formula("ln(x - 3)")]) == [None, None, pytest.approx(math.log(3)), pytest.approx(math.log(7))]
    assert values([formula("log10(x - 3)")])[:2] == [None, None]
    assert values([formula("(x - 3) ** 0.5")]) == [None, 0, pytest.approx(math.sqrt(3)), pytest.approx(math.sqrt(7))]
    assert values([formula("(x - 3) ** 2")]) == [4, 0, 9, 49]
    assert values([formula("exp(x * 1000)")]) == [None, None, None, None]


def test_an_undefined_point_does_not_poison_the_rest_of_the_formula() -> None:
    """Infinity and NaN pass through a later function without failing it,
    and the point is a gap at the end."""
    assert values([formula("sqrt(1 / (x - 3)) + ln(0 - 1 / (x - 3))")])[1] is None
    assert values([formula("floor(1 / (x - 3))")]) == [-1, None, 0, 0]


def test_a_formula_chains_like_any_transform() -> None:
    assert values([{"kind": "cumulative", "aggregate": "sum"}, formula("x / 10")]) == [0.1, 0.4, 1, 2]


@pytest.mark.parametrize("expression, said", [
    ("y + 1", "transform 1: a formula knows only x, not 'y'"),
    ("__import__('os')", "transform 1: a formula may call only abs, sqrt, ln, log10, exp, floor, ceil, round"),
    ("x.real", "transform 1: a formula is numbers, x, + - * / **, brackets and abs, sqrt, ln, log10, exp, floor, ceil, round"),
    ("'text'", "transform 1: a formula is numbers, x, + - * / **, brackets and abs, sqrt, ln, log10, exp, floor, ceil, round"),
    ("x < 2", "transform 1: a formula is numbers, x, + - * / **, brackets and abs, sqrt, ln, log10, exp, floor, ceil, round"),
    ("True + x", "transform 1: a formula is numbers, x, + - * / **, brackets and abs, sqrt, ln, log10, exp, floor, ceil, round"),
    ("x % 2", "transform 1: a formula uses only + - * / and **"),
    ("abs(x, 2)", "transform 1: abs takes one argument"),
    ("abs(x=1)", "transform 1: abs takes one argument"),
    ("abs(x, key=1)", "transform 1: abs takes one argument"),
    ("x.__class__(1)", "transform 1: a formula may call only abs, sqrt, ln, log10, exp, floor, ceil, round"),
    ("1e400 * x", "transform 1: inf is too large a number for a formula"),
    ("x +", "transform 1: 'x +' is not a formula"),
    ("   ", "transform 1: a formula needs an expression"),
    ("x" + " + x" * 60, "transform 1: a formula is at most 200 characters"),
])
def test_a_formula_that_is_not_arithmetic_is_refused(expression, said) -> None:
    with pytest.raises(ValueError) as caught:
        ts.parse_transforms([formula(expression)])
    assert str(caught.value) == said


def test_a_formula_without_an_expression_is_refused() -> None:
    with pytest.raises(ValueError, match="transform 1: a formula needs an expression"):
        ts.parse_transforms([{"kind": "formula"}])
    assert ts.parse_transforms([formula("  x * 2  ")]) == [formula("x * 2")]


# ---- p.393's Filter time series and Sample (§648) -----------------------------------
@pytest.mark.parametrize("op, value, keep, expected", [
    ("gt", 3, True, [6, 10]),
    ("gte", 3, True, [3, 6, 10]),
    ("lt", 6, True, [1, 3]),
    ("lte", 6, True, [1, 3, 6]),
    ("eq", 6, True, [6]),
    ("neq", 6, True, [1, 3, 10]),
    ("gt", 3, False, [1, 3]),
    ("eq", 6.0, False, [1, 3, 10]),
])
def test_a_filter_keeps_or_removes_what_matches(op, value, keep, expected) -> None:
    """p.393: "Keep or remove points in a time series based on a time range or
    mathematical condition." The time range is `range`; this is the condition."""
    assert values([{"kind": "filter", "op": op, "value": value, "keep": keep}]) == expected


def test_a_filter_keeps_by_default_and_drops_a_gap_either_way() -> None:
    gappy = ROWS + [("S1", "2026-01-06 00:00:00", None)]
    assert values([{"kind": "filter", "op": "gt", "value": 5}], rows=gappy) == [6, 10]
    assert values([{"kind": "filter", "op": "gt", "value": 5, "keep": False}], rows=gappy) == [1, 3]


def test_a_sample_takes_the_reading_at_or_before_each_step() -> None:
    """p.393: "Resample a time series at a constant frequency to fill gaps".
    The 3rd has no reading, so it takes the 2nd's."""
    assert run([{"kind": "sample", "every": 1, "unit": "day"}]) == [
        (day(1), 1.0), (day(2), 3.0), (day(3), 3.0), (day(4), 6.0), (day(5), 10.0)]


def test_a_linear_sample_draws_the_line_between_readings() -> None:
    assert run([{"kind": "sample", "every": 12, "unit": "hour", "method": "linear"}]) == [
        (day(1), 1.0), (day(1, 12), 2.0), (day(2), 3.0), (day(2, 12), 3.75), (day(3), 4.5),
        (day(3, 12), 5.25), (day(4), 6.0), (day(4, 12), 8.0), (day(5), 10.0)]


def test_a_sample_fills_a_gap_and_changes_the_rate() -> None:
    gappy = ROWS[:2] + [("S1", "2026-01-03 00:00:00", None)] + ROWS[2:]
    # Every other day: the 3rd has no reading, so it takes the 2nd's.
    assert values([{"kind": "sample", "every": 2, "unit": "day"}], rows=gappy) == [1, 3, 10]


def test_a_sample_is_bounded_inside_the_query() -> None:
    """A step of a second over four days would be 345,601 samples; the grid
    stops at MAX_SAMPLES rather than being built and then capped."""
    got = run([{"kind": "sample", "every": 1, "unit": "second"}], limit=ts.MAX_POINTS)
    assert len(got) == ts.MAX_POINTS
    sql = ts.points_sql(key_column="sensor", timestamp_column="taken", value_column="reading",
                        series_id="S1", interval="none", aggregate="avg",
                        transforms=ts.parse_transforms([{"kind": "sample", "every": 1,
                                                          "unit": "second"}]))
    assert f"INTERVAL ({ts.MAX_SAMPLES - 1}) SECOND" in sql


def test_a_page_of_series_is_filtered_and_sampled_each_on_its_own() -> None:
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE dataset (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO dataset VALUES (?, ?, ?)", ROWS + [
            ("S2", "2026-01-05 00:00:00", 2000.0)])
        for transforms, expected in (
            ([{"kind": "filter", "op": "gte", "value": 6}],
             {"S1": [6.0, 10.0], "S2": [1000.0, 2000.0]}),
            ([{"kind": "sample", "every": 1, "unit": "day"}],
             {"S1": [1.0, 3.0, 3.0, 6.0, 10.0], "S2": [1000.0, 1000.0, 2000.0]}),
            ([{"kind": "sample", "every": 1, "unit": "day", "method": "linear"}],
             {"S1": [1.0, 3.0, 4.5, 6.0, 10.0], "S2": [1000.0, 1500.0, 2000.0]}),
        ):
            sql = ts.points_for_many_sql(
                key_column="sensor", timestamp_column="taken", value_column="reading",
                series_ids=["S1", "S2"], interval="none", aggregate="avg",
                transforms=ts.parse_transforms(transforms))
            got: dict[str, list[float]] = {}
            for series, _, value in con.execute(sql).fetchall():
                got.setdefault(series, []).append(value)
            assert got == expected, transforms
    finally:
        con.close()


@pytest.mark.parametrize("raw, said", [
    ({"kind": "filter", "op": "near", "value": 1}, "the comparison must be one of"),
    ({"kind": "filter", "op": "gt", "value": "1"}, "compares with a number"),
    ({"kind": "filter", "op": "gt", "value": True}, "compares with a number"),
    ({"kind": "filter", "op": "gt", "value": float("inf")}, "compares with a number"),
    ({"kind": "filter", "op": "gt", "value": 1, "keep": "yes"}, "keep is true"),
    ({"kind": "sample", "every": 0, "unit": "day"}, "the step must be from 1"),
    ({"kind": "sample", "every": 1, "unit": "fortnight"}, "the unit must be one of"),
    ({"kind": "sample", "every": 1, "unit": "day", "method": "cubic"}, "the method must be one of"),
])
def test_a_filter_or_sample_that_says_too_little_is_refused(raw, said) -> None:
    with pytest.raises(ValueError) as caught:
        ts.parse_transforms([raw])
    assert said in str(caught.value)


def test_a_filter_and_a_sample_parse_with_their_defaults() -> None:
    assert ts.parse_transforms([{"kind": "filter", "op": "lt", "value": 2}]) == [
        {"kind": "filter", "op": "lt", "value": 2.0, "keep": True}]
    assert ts.parse_transforms([{"kind": "sample", "every": 3, "unit": "hour"}]) == [
        {"kind": "sample", "every": 3, "unit": "hour", "method": "previous"}]


# ---- p.392's Time series search (§651) ----------------------------------------------
def events(op: str, value: float, transforms: list[dict] | None = None, rows=None) -> list[tuple]:
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE dataset (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO dataset VALUES (?, ?, ?)", rows or ROWS)
        sql = ts.events_sql(key_column="sensor", timestamp_column="taken", value_column="reading",
                            series_id="S1", interval="none", aggregate="avg",
                            transforms=ts.parse_transforms(transforms or []), op=op, value=value)
        return [(r[0], r[1], r[2]) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def test_an_event_is_a_run_of_readings_that_meet_the_threshold() -> None:
    """p.392: "identifying time ranges that match a specified pattern or
    threshold". S1 reads 1, 3, 6, 10: above 2 is one run, from the 2nd to the
    5th; S2's 1000 is another series."""
    assert events("gt", 2) == [(day(2), day(5), 3)]
    assert events("lt", 5) == [(day(1), day(2), 2)]
    assert events("gt", 100) == []


def test_a_reading_that_misses_closes_the_run_and_a_gap_does_not() -> None:
    rows = [("S1", "2026-01-01", 5.0), ("S1", "2026-01-02", 1.0), ("S1", "2026-01-03", 6.0),
            ("S1", "2026-01-04", None), ("S1", "2026-01-05", 7.0)]
    assert events("gte", 5, rows=rows) == [(day(1), day(1), 1), (day(3), day(5), 2)]


def test_a_search_reads_the_series_through_its_transforms() -> None:
    """A running sum of 1, 3, 6, 10 is 1, 4, 10, 20: above 5 from the 4th."""
    assert events("gt", 5, [{"kind": "cumulative", "aggregate": "sum"}]) == [(day(4), day(5), 2)]


def test_a_search_is_capped_one_past_the_limit_so_the_cut_can_be_said() -> None:
    sql = ts.events_sql(key_column="k", timestamp_column="t", value_column="v", series_id="S1",
                        interval="none", aggregate="avg", transforms=[], op="eq", value=1)
    assert sql.endswith(f"LIMIT {ts.MAX_EVENTS + 1}")


@pytest.mark.parametrize("kw, said", [
    ({"op": "near", "value": 1}, "the comparison must be one of"),
    ({"op": "gt", "value": float("nan")}, "compares with a number"),
    ({"op": "gt", "value": True}, "compares with a number"),
    ({"op": "gt", "value": 1, "interval": "year"}, "unknown interval"),
    ({"op": "gt", "value": 1, "aggregate": "median"}, "unknown aggregate"),
])
def test_a_search_that_says_too_little_is_refused(kw, said) -> None:
    with pytest.raises(ValueError) as caught:
        ts.events_sql(key_column="k", timestamp_column="t", value_column="v", series_id="S1",
                      interval=kw.pop("interval", "none"), aggregate=kw.pop("aggregate", "avg"),
                      transforms=[], **kw)
    assert said in str(caught.value)


def test_the_events_endpoint_searches_one_object_s_series(client, fx, ontology, instance) -> None:
    assert declare(client, fx, ontology).status_code == 200
    url = (f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}"
           "/series/readings/events")
    readings = points(client, fx, ontology).json()["points"]
    r = client.get(url, headers=hdr(fx.viewer_sub), params={"op": "gte", "value": 20})
    assert r.status_code == 200, r.text
    assert r.json() == {"property_api_name": "readings", "truncated": False, "events": [
        {"start": readings[1]["at"], "end": readings[-1]["at"], "points": len(readings) - 1}]}
    # Through a transform, and refused in a sentence for a comparison it lacks.
    running = json.dumps([{"kind": "cumulative", "aggregate": "sum"}])
    r = client.get(url, headers=hdr(fx.viewer_sub),
                   params={"op": "gt", "value": 50, "transforms": running})
    assert [e["points"] for e in r.json()["events"]] == [1]
    r = client.get(url, headers=hdr(fx.viewer_sub), params={"op": "near", "value": 1})
    assert r.status_code == 422 and "comparison" in r.text
    assert client.get(url, headers=hdr(fx.outsider_sub),
                      params={"op": "gt", "value": 1}).status_code == 404


def test_a_search_past_the_cap_says_it_was_cut(client, fx, ontology, instance, monkeypatch) -> None:
    """S1 reads 10, 20, 30: not equal to 20 is two runs, and with room for
    one the answer says there were more."""
    assert declare(client, fx, ontology).status_code == 200
    url = (f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}"
           "/series/readings/events")
    body = client.get(url, headers=hdr(fx.viewer_sub), params={"op": "neq", "value": 20}).json()
    assert [e["points"] for e in body["events"]] == [1, 1] and body["truncated"] is False
    monkeypatch.setattr(ts, "MAX_EVENTS", 1)
    body = client.get(url, headers=hdr(fx.viewer_sub), params={"op": "neq", "value": 20}).json()
    assert len(body["events"]) == 1 and body["truncated"] is True


def test_an_object_with_no_series_id_has_no_events(client, fx, ontology, instance) -> None:
    import psycopg

    from test_api import ADMIN_DSN

    assert declare(client, fx, ontology).status_code == 200
    url = (f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}"
           "/series/readings/events")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE object_instances SET properties = properties - 'readings' "
                     "WHERE id = %s", (instance,))
        try:
            r = client.get(url, headers=hdr(fx.viewer_sub), params={"op": "gt", "value": 0})
        finally:
            conn.execute("UPDATE object_instances SET properties = jsonb_set(properties, "
                         "'{readings}', to_jsonb(primary_key)) WHERE id = %s", (instance,))
    assert r.status_code == 200, r.text
    assert r.json() == {"property_api_name": "readings", "events": [], "truncated": False}
