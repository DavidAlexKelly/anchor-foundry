"""Workshop's math operations and numeric comparisons on variables (§564;
`workshop` p.140-141).

    "Add: Returns the sum of given numeric values or variables. … Round Up
     (Ceil): Returns the rounded up value to a specified precision of a given
     numeric value or variable. … Max: Returns the maximum value from a
     collection of numeric, date, or timestamp values or variables." (p.140)

    "Less than: Runs a boolean check on if the first given numeric value or
     variable is less than the second given numeric value(s) or
     variable(s)." (p.141)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_math as vm  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402


def run(transform: str, *values, **config):
    return vm.apply(transform, list(values), config, "Result")


# ---- p.140's math operations ---------------------------------------------------
def test_the_four_operations() -> None:
    assert run("add", 2, 3, 4) == 9
    assert run("add", 7) == 7
    assert run("add", 0.1, 0.2) == pytest.approx(0.3)
    assert run("subtract", 10, 3, 2) == 5
    assert run("multiply", 2, 3, 4) == 24
    assert run("divide", 7, 2) == 3.5
    assert run("divide", 6, 3) == 2
    assert isinstance(run("divide", 6, 3), int)


def test_a_division_by_zero_is_nothing_rather_than_infinity() -> None:
    assert run("divide", 1, 0) is None
    assert run("divide", 0, 0) is None
    # And so is a result too large to be a number.
    assert run("multiply", 1e308, 10) is None


def test_a_small_value_between_two_large_ones_is_kept() -> None:
    """Added in order, 1e16 + 1 is 1e16 and the 1 is lost; a sum that keeps
    what it has dropped does not lose it."""
    assert run("add", 1e16, 1.0, -1e16) == 1


def test_absolute_and_negate() -> None:
    assert run("absolute", -4.5) == 4.5
    assert run("negate", 3) == -3
    assert run("negate", -3) == 3


@pytest.mark.parametrize("transform, value, precision, expected", [
    ("round_up", 2.121, 2, 2.13),
    ("round_up", -2.129, 2, -2.12),
    ("round_down", 2.129, 2, 2.12),
    ("round_down", -2.121, 2, -2.13),
    ("round_nearest", 2.675, 2, 2.68),
    ("round_nearest", 2.5, 0, 3),
    ("round_nearest", -2.5, 0, -3),
    ("round_up", 7.1, 0, 8),
    ("round_down", 1234, -2, 1200),
    ("round_up", 1201, -2, 1300),
])
def test_rounding_to_a_precision(transform, value, precision, expected) -> None:
    assert run(transform, value, precision=precision) == expected


def test_rounding_defaults_to_whole_numbers() -> None:
    assert run("round_nearest", 2.4) == 2


def test_max_and_min_over_numbers_leave_gaps_out() -> None:
    assert run("max", 3, 9, 4) == 9
    assert run("min", 3, 9, 4) == 3
    assert run("max", None, 2, None) == 2
    assert run("min", None, None) is None


def test_max_and_min_over_dates_and_timestamps() -> None:
    assert run("max", "2026-01-05", "2026-03-01", "2025-12-31") == "2026-03-01"
    assert run("min", "2026-01-05", "2026-03-01", "2025-12-31") == "2025-12-31"
    # Compared as instants, returned as given: 09:00 in London is after 09:30
    # in Paris.
    assert run("max", "2026-01-01T09:30:00+01:00", "2026-01-01T09:00:00Z") == "2026-01-01T09:00:00Z"


@pytest.mark.parametrize("values, said", [
    (("2026-01-01", 3), "one kind at a time"),
    (("2026-01-01", "2026-01-01T00:00:00Z"), "one kind at a time"),
    (("soon", "later"), "one kind at a time"),
    (("2026-01-01T00:00:00", "2026-01-01T00:00:00Z"), "with and without a time zone"),
])
def test_max_over_mixed_kinds_is_refused(values, said) -> None:
    with pytest.raises(vm.MathError) as caught:
        run("max", *values)
    assert said in str(caught.value)


# ---- p.141's comparisons ---------------------------------------------------------
@pytest.mark.parametrize("transform, values, expected", [
    ("equal_to", (3, 3), True),
    ("equal_to", (3, 3.0, 3), True),
    ("equal_to", (3, 4), False),
    ("not_equal_to", (3, 4, 5), True),
    ("not_equal_to", (3, 4, 3), False),
    ("less_than", (1, 2, 3), True),
    ("less_than", (2, 2), False),
    ("less_or_equal", (2, 2, 3), True),
    ("less_or_equal", (3, 2), False),
    ("greater_than", (5, 2, 4), True),
    ("greater_than", (5, 2, 5), False),
    ("greater_or_equal", (5, 5), True),
    ("greater_or_equal", (4, 5), False),
])
def test_the_first_against_each_of_the_rest(transform, values, expected) -> None:
    assert run(transform, *values) is expected


# ---- nothing yet, and not a number ---------------------------------------------------
@pytest.mark.parametrize("transform", ["add", "subtract", "divide", "negate", "less_than",
                                       "round_nearest"])
def test_an_input_with_nothing_yet_is_nothing(transform) -> None:
    values = (None, 2) if vm.ARITY[transform][1] != 1 else (None,)
    assert run(transform, *values) is None


@pytest.mark.parametrize("value", ["12", True, [1], {"a": 1}])
def test_something_that_is_not_a_number_is_refused(value) -> None:
    with pytest.raises(vm.MathError) as caught:
        run("add", 1, value)
    assert str(caught.value) == (
        f"'Result' does arithmetic on {value!r}, which is not a number - convert it with a "
        "cast first")


# ---- the derivation ---------------------------------------------------------------------
def number(vid: str, default=None) -> dict:
    return {"id": vid, "kind": "number", "label": vid,
            **({"default": default} if default is not None else {})}


def derived(vid: str, transform: str, inputs: list[str], kind="number", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid,
            "derivation": {"transform": transform, "inputs": inputs, "config": config}}


def test_a_derivation_evaluates_its_operation() -> None:
    parsed = wv.parse({
        "a": number("a", 12), "b": number("b", 5),
        "sum": derived("sum", "add", ["a", "b"]),
        "ratio": derived("ratio", "divide", ["a", "b"]),
        "rounded": derived("rounded", "round_nearest", ["ratio"], precision=1),
        "big": derived("big", "greater_than", ["sum", "a"], kind="boolean"),
    })
    got = wv.evaluate(parsed, {})
    assert (got["sum"], got["ratio"], got["rounded"], got["big"]) == (17, 2.4, 2.4, True)
    got = wv.evaluate(parsed, {"a": 3})
    assert (got["sum"], got["rounded"], got["big"]) == (8, 0.6, True)


def test_a_derivation_over_text_says_which_variable() -> None:
    parsed = wv.parse({
        "a": {"id": "a", "kind": "string", "label": "Typed", "default": "12"},
        "b": number("b", 1),
        "sum": {**derived("sum", "add", ["a", "b"]), "label": "Total"},
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert "'Total' does arithmetic on '12'" in str(caught.value)


@pytest.mark.parametrize("transform, inputs, config, said", [
    ("subtract", ["a"], {}, "subtract needs at least 2 inputs"),
    ("add", [], {}, "add needs at least 1 input"),
    ("divide", ["a", "b", "a"], {}, "divide takes 2 inputs"),
    ("negate", ["a", "b"], {}, "negate takes 1 input"),
    ("less_than", ["a"], {}, "less_than needs at least 2 inputs"),
    ("round_up", ["a"], {"precision": 11}, "round_up's precision must be a whole number of "
                                           "decimal places from -10 to 10"),
    ("round_up", ["a"], {"precision": -11}, "precision must be a whole number"),
    ("round_up", ["a"], {"precision": 1.5}, "precision must be a whole number"),
    ("round_up", ["a"], {"precision": True}, "precision must be a whole number"),
    ("add", ["a"] * 21, {}, "add takes at most 20 inputs"),
])
def test_a_derivation_that_cannot_run_is_refused_at_save(transform, inputs, config, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"a": number("a", 1), "b": number("b", 2),
                  "x": derived("x", transform, inputs, **config)})
    assert said in str(caught.value)
    assert str(caught.value).startswith("variable 'x': ")


def test_a_number_variables_typed_default_is_its_number() -> None:
    """The panel keeps a typed default as text; a number variable's text is
    the number it spells, and a string variable's is still refused above."""
    parsed = wv.parse({
        "a": {"id": "a", "kind": "number", "label": "a", "default": "12"},
        "b": {"id": "b", "kind": "number", "label": "b", "default": " 2.5 "},
        "c": {"id": "c", "kind": "number", "label": "c", "default": "lots"},
        "sum": derived("sum", "add", ["a", "b"]),
        "bad": derived("bad", "add", ["a", "c"]),
    })
    assert wv.evaluate(parsed, {}, only=frozenset({"sum", "a", "b"}))["sum"] == 14.5
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert "on 'lots'" in str(caught.value)
    assert vm.of_number_variable("7") == 7 and isinstance(vm.of_number_variable("7"), int)
    assert vm.of_number_variable("inf") == "inf"
    assert vm.of_number_variable(3) == 3
