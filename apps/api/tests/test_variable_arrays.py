"""Workshop's array operations and checks on variables (§567; `workshop`
p.142-143).

    "Compose: Returns an array containing all values of the given arrays.
     Intersection: Returns an array containing only common values between
     the given arrays. Update element at … Get element at … Length …"
     (p.142-143)

    "Contains: Runs a boolean check for the presence of given values within
     a given array. … Is subset of: Runs a boolean check on if a given array
     is a subset of another given array." (p.143)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_arrays as va  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402


def run(transform: str, *values, **config):
    return va.apply(transform, list(values), config, "Tags")


def test_compose_joins_the_arrays_in_order() -> None:
    assert run("array_compose", ["a", "b"], ["b", "c"], []) == ["a", "b", "b", "c"]
    assert run("array_compose", ["a"]) == ["a"]


def test_intersection_keeps_what_every_array_has_once_in_the_firsts_order() -> None:
    assert run("array_intersection", ["c", "a", "b", "a"], ["a", "b", "c"], ["b", "a"]) == ["a", "b"]
    assert run("array_intersection", [1, "1"], ["1"]) == ["1"]


def test_get_and_update_an_element_by_its_position_from_zero() -> None:
    assert run("array_get_element", ["a", "b", "c"], index=1) == "b"
    assert run("array_get_element", ["a", "b", "c"]) == "a"
    assert run("array_get_element", ["a"], index=3) is None
    original = ["a", "b", "c"]
    assert run("array_update_element", original, "z", index=2) == ["a", "b", "z"]
    assert original == ["a", "b", "c"]
    assert run("array_update_element", original, "z", index=3) == ["a", "b", "c"]
    assert run("array_update_element", original, "z", index=3) is not original


def test_length() -> None:
    assert run("array_length", ["a", "b"]) == 2
    assert run("array_length", []) == 0


@pytest.mark.parametrize("values, contains, lacks", [
    (("a",), True, False),
    (("a", "c"), True, False),
    (("a", "z"), False, False),
    (("y", "z"), False, True),
    ((["a", "c"],), True, False),
    ((["y", "c"],), False, False),
])
def test_contains_and_does_not_contain_each_given_value(values, contains, lacks) -> None:
    array = ["a", "b", "c"]
    assert run("array_contains", array, *values) is contains
    assert run("array_does_not_contain", array, *values) is lacks


def test_subset() -> None:
    assert run("array_is_subset_of", ["a", "c"], ["a", "b", "c"]) is True
    assert run("array_is_subset_of", [], ["a"]) is True
    assert run("array_is_subset_of", ["a", "z"], ["a", "b"]) is False


def test_nothing_yet_is_nothing() -> None:
    assert run("array_length", None) is None
    assert run("array_compose", ["a"], None) is None
    assert run("array_is_subset_of", ["a"], None) is None
    assert run("array_contains", ["a"], None) is None
    assert run("array_contains", ["a"], None, "a") is True


def test_something_that_is_not_an_array_is_refused() -> None:
    with pytest.raises(va.ArrayError) as caught:
        run("array_length", "abc")
    assert str(caught.value) == "'Tags' takes an array, and was given 'abc'"
    with pytest.raises(va.ArrayError):
        run("array_compose", ["a"], "b")


def test_an_array_variables_typed_json_is_its_list() -> None:
    assert va.of_array_variable('["a", 2]') == ["a", 2]
    assert va.of_array_variable('{"a": 1}') == '{"a": 1}'
    assert va.of_array_variable("a, b") == "a, b"
    assert va.of_array_variable(["x"]) == ["x"]


# ---- the derivation ------------------------------------------------------------------
def derived(vid: str, transform: str, inputs: list[str], kind="array", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": transform, "inputs": inputs, "config": config}}


def test_a_derivation_evaluates_array_operations() -> None:
    parsed = wv.parse({
        "a": {"id": "a", "kind": "array", "label": "A", "default": '["red", "green"]'},
        "b": {"id": "b", "kind": "array", "label": "B", "default": ["green", "blue"]},
        "both": derived("both", "array_compose", ["a", "b"]),
        "common": derived("common", "array_intersection", ["a", "b"]),
        "second": derived("second", "array_get_element", ["both"], kind="string", index=1),
        "count": derived("count", "array_length", ["both"], kind="number"),
        "has": derived("has", "array_contains", ["both", "a"], kind="boolean"),
    })
    got = wv.evaluate(parsed, {})
    assert got["both"] == ["red", "green", "green", "blue"]
    assert (got["common"], got["second"], got["count"], got["has"]) == (["green"], "green", 4, True)


def test_a_derivation_over_the_wrong_kind_says_which_variable() -> None:
    parsed = wv.parse({
        "a": {"id": "a", "kind": "string", "label": "A", "default": "red"},
        "count": derived("count", "array_length", ["a"], kind="number"),
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert str(caught.value) == "'Count' takes an array, and was given 'red'"


@pytest.mark.parametrize("transform, inputs, config, said", [
    ("array_contains", ["a"], {}, "array_contains needs at least 2 inputs"),
    ("array_length", ["a", "a"], {}, "array_length takes 1 input"),
    ("array_is_subset_of", ["a", "a", "a"], {}, "array_is_subset_of takes 2 inputs"),
    ("array_get_element", ["a"], {"index": -1}, "array_get_element's index must be a whole number "
                                                "from 0 to 10000"),
    ("array_get_element", ["a"], {"index": 10_001}, "index must be a whole number"),
    ("array_update_element", ["a", "a"], {"index": "2"}, "index must be a whole number"),
    ("array_update_element", ["a", "a"], {"index": True}, "index must be a whole number"),
    ("array_compose", ["a"] * 21, {}, "array_compose takes at most 20 inputs"),
])
def test_a_derivation_that_cannot_run_is_refused_at_save(transform, inputs, config, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"a": {"id": "a", "kind": "array", "label": "A"},
                  "x": derived("x", transform, inputs, **config)})
    assert said in str(caught.value)
    assert str(caught.value).startswith("variable 'x': ")


def test_only_an_array_variables_text_is_read_as_a_list() -> None:
    parsed = wv.parse({
        "a": {"id": "a", "kind": "string", "label": "A", "default": '["red"]'},
        "count": derived("count", "array_length", ["a"], kind="number"),
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert str(caught.value) == """'Count' takes an array, and was given '["red"]'"""
