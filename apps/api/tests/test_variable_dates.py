"""Workshop's date and time math and comparisons on variables (§565;
`workshop` p.140-141).

    "Relative date: Returns a calculated date given a numeric value or
     variable, specifying the number of days, weeks, months or years to add
     or subtract, and a date value or variable. … Between dates: Returns the
     numeric difference between two given date values or variables. …
     Current date: Returns the current date." (p.140)

    "Date comparisons: Is on or after: Runs a boolean check on if the first
     given date value or variable is on or after the second given date value
     or variable." (p.140)
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_dates as vd  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402


def run(transform: str, *values, today=None, **config):
    return vd.apply(transform, list(values), config, "Due", today=today)


# ---- p.140's date/time math ---------------------------------------------------
@pytest.mark.parametrize("value, amount, unit, direction, expected", [
    ("2026-01-10", 5, "days", "add", "2026-01-15"),
    ("2026-01-10", 2, "weeks", "add", "2026-01-24"),
    ("2026-01-10", 10, "days", "subtract", "2025-12-31"),
    ("2026-01-31", 1, "months", "add", "2026-02-28"),
    ("2024-01-31", 1, "months", "add", "2024-02-29"),
    ("2026-03-31", 1, "months", "subtract", "2026-02-28"),
    ("2026-11-15", 3, "months", "add", "2027-02-15"),
    ("2024-02-29", 1, "years", "add", "2025-02-28"),
    ("2026-05-01", -2, "days", "add", "2026-04-29"),
])
def test_a_relative_date(value, amount, unit, direction, expected) -> None:
    assert run("relative_date", value, amount, unit=unit, direction=direction) == expected


@pytest.mark.parametrize("value, amount, unit, expected", [
    ("2026-01-10T12:00:00Z", 90, "minutes", "2026-01-10T13:30:00Z"),
    ("2026-01-10T12:00:00", 1.5, "hours", "2026-01-10T13:30:00Z"),
    ("2026-01-10T12:00:00+02:00", 30, "seconds", "2026-01-10T10:00:30Z"),
    ("2026-01-31T08:00:00Z", 1, "months", "2026-02-28T08:00:00Z"),
    ("2026-01-10T12:00:00Z", 1, "years", "2027-01-10T12:00:00Z"),
    ("2026-01-10T12:00:00Z", 1, "weeks", "2026-01-17T12:00:00Z"),
])
def test_a_relative_time(value, amount, unit, expected) -> None:
    assert run("relative_time", value, amount, unit=unit) == expected


def test_a_relative_time_subtracts() -> None:
    assert run("relative_time", "2026-01-10T00:00:00Z", 1, unit="days",
               direction="subtract") == "2026-01-09T00:00:00Z"


@pytest.mark.parametrize("first, second, unit, expected", [
    ("2026-01-01", "2026-01-15", "days", 14),
    ("2026-01-15", "2026-01-01", "days", -14),
    ("2026-01-01", "2026-01-15", "weeks", 2),
    ("2026-01-01", "2026-01-14", "weeks", 1),
    ("2026-01-14", "2026-01-01", "weeks", -1),
    ("2026-01-31", "2026-02-28", "months", 0),
    ("2026-01-31", "2026-03-01", "months", 1),
    ("2026-01-15", "2026-03-15", "months", 2),
    ("2026-03-15", "2026-01-16", "months", -1),
    ("2024-02-29", "2025-02-28", "years", 0),
    ("2024-02-28", "2026-03-01", "years", 2),
    # Toward zero: fourteen months back is one whole year back, not two.
    ("2026-03-01", "2025-01-15", "years", -1),
])
def test_between_dates_counts_whole_units(first, second, unit, expected) -> None:
    assert run("between_dates", first, second, unit=unit) == expected


@pytest.mark.parametrize("first, second, unit, expected", [
    ("2026-01-01T00:00:00Z", "2026-01-01T01:30:00Z", "hours", 1),
    ("2026-01-01T00:00:00Z", "2026-01-01T01:30:00Z", "minutes", 90),
    ("2026-01-01T01:30:00Z", "2026-01-01T00:00:00Z", "hours", -1),
    ("2026-01-01T00:00:00+01:00", "2026-01-01T00:00:00Z", "hours", 1),
    ("2026-01-31T10:00:00Z", "2026-02-28T09:00:00Z", "months", 0),
    ("2026-01-15T10:00:00Z", "2026-02-15T10:00:00Z", "months", 1),
    ("2026-02-15T10:00:00Z", "2026-01-15T11:00:00Z", "months", 0),
    ("2025-01-01T00:00:00Z", "2027-06-01T00:00:00Z", "years", 2),
])
def test_between_times_counts_whole_units(first, second, unit, expected) -> None:
    assert run("between_times", first, second, unit=unit) == expected


def test_the_current_date() -> None:
    from datetime import datetime, timezone

    assert run("current_date", today=date(2026, 9, 27)) == "2026-09-27"
    assert run("current_date") == datetime.now(timezone.utc).date().isoformat()


# ---- p.140-141's comparisons ----------------------------------------------------
@pytest.mark.parametrize("transform, first, second, expected", [
    ("date_is_on_or_after", "2026-01-02", "2026-01-02", True),
    ("date_is_on_or_after", "2026-01-01", "2026-01-02", False),
    ("date_is_after", "2026-01-02", "2026-01-02", False),
    ("date_is_after", "2026-01-03", "2026-01-02", True),
    ("date_is_on_or_before", "2026-01-02", "2026-01-02", True),
    ("date_is_before", "2026-01-02", "2026-01-02", False),
    ("date_is_before", "2026-01-01", "2026-01-02", True),
    ("date_is_equal", "2026-01-02", "2026-01-02", True),
    ("time_is_after", "2026-01-01T10:00:00Z", "2026-01-01T10:30:00+01:00", True),
    ("time_is_equal", "2026-01-01T09:30:00Z", "2026-01-01T10:30:00+01:00", True),
    ("time_is_equal", "2026-01-01T09:30:00", "2026-01-01T09:30:00Z", True),
    ("time_is_on_or_before", "2026-01-01T09:30:00Z", "2026-01-01T09:30:00Z", True),
    ("time_is_before", "2026-01-01T09:30:00Z", "2026-01-01T09:30:00Z", False),
    ("time_is_on_or_after", "2026-01-01T09:29:00Z", "2026-01-01T09:30:00Z", False),
])
def test_comparisons(transform, first, second, expected) -> None:
    assert run(transform, first, second) is expected


# ---- nothing yet, and the wrong kind of value -----------------------------------
@pytest.mark.parametrize("transform, values", [
    ("relative_date", (None, 1)), ("relative_date", ("2026-01-01", None)),
    ("between_times", ("2026-01-01T00:00:00Z", None)), ("date_is_before", (None, "2026-01-01")),
])
def test_an_input_with_nothing_yet_is_nothing(transform, values) -> None:
    assert run(transform, *values) is None


@pytest.mark.parametrize("transform, values, config, said", [
    ("relative_date", ("2026-01-01T00:00:00Z", 1), {}, "takes a date, as YYYY-MM-DD"),
    ("relative_time", ("2026-01-01", 1), {}, "takes a timestamp"),
    ("date_is_before", ("2026-13-01", "2026-01-01"), {}, "takes a date"),
    ("date_is_before", ("20260101", "2026-01-01"), {}, "takes a date, as YYYY-MM-DD"),
    ("time_is_before", ("soon", "2026-01-01T00:00:00Z"), {}, "takes a timestamp"),
    ("relative_date", ("2026-01-01", "3"), {}, "which is not a number"),
    ("relative_date", ("2026-01-01", True), {}, "which is not a number"),
    ("relative_date", ("2026-01-01", 1.5), {}, "only whole days can be counted"),
    ("relative_time", ("2026-01-01T00:00:00Z", 0.5), {"unit": "months"}, "only whole months"),
])
def test_the_wrong_kind_of_value_is_refused(transform, values, config, said) -> None:
    with pytest.raises(vd.DateError) as caught:
        run(transform, *values, **config)
    assert said in str(caught.value)
    assert str(caught.value).startswith("'Due' ")


# ---- the derivation ------------------------------------------------------------------
def derived(vid: str, transform: str, inputs: list[str], kind="date", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid,
            "derivation": {"transform": transform, "inputs": inputs, "config": config}}


def test_a_derivation_evaluates_date_math() -> None:
    parsed = wv.parse({
        "start": {"id": "start", "kind": "date", "label": "Start", "default": "2026-01-31"},
        "n": {"id": "n", "kind": "number", "label": "N", "default": "1"},
        "due": derived("due", "relative_date", ["start", "n"], unit="months"),
        "gap": derived("gap", "between_dates", ["start", "due"], kind="number"),
        "late": derived("late", "date_is_after", ["due", "start"], kind="boolean"),
        "today": derived("today", "current_date", []),
    })
    got = wv.evaluate(parsed, {})
    assert (got["due"], got["gap"], got["late"]) == ("2026-02-28", 28, True)
    assert len(got["today"]) == 10


def test_a_derivation_over_the_wrong_kind_says_which_variable() -> None:
    parsed = wv.parse({
        "start": {"id": "start", "kind": "string", "label": "Start", "default": "soon"},
        "n": {"id": "n", "kind": "number", "label": "N", "default": 1},
        "due": {**derived("due", "relative_date", ["start", "n"]), "label": "Due"},
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert str(caught.value) == "'Due' takes a date, as YYYY-MM-DD, and was given 'soon'"


@pytest.mark.parametrize("transform, inputs, config, said", [
    ("relative_date", ["start"], {}, "relative_date takes 2 inputs"),
    ("current_date", ["start"], {}, "current_date takes 0 inputs"),
    ("relative_date", ["start", "start"], {"unit": "hours"},
     "relative_date's unit must be one of days, weeks, months, years"),
    ("between_times", ["start", "start"], {"unit": "fortnights"}, "between_times's unit must be"),
    ("relative_time", ["start", "start"], {"direction": "back"},
     "relative_time's direction must be add or subtract"),
])
def test_a_derivation_that_cannot_run_is_refused_at_save(transform, inputs, config, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"start": {"id": "start", "kind": "date", "label": "Start"},
                  "x": derived("x", transform, inputs, **config)})
    assert str(caught.value) == f"variable 'x': {said}" or said in str(caught.value)
