"""Workshop's string and boolean comparisons on variables (§566;
`workshop` p.142).

    "Contains: Runs a boolean check on if the second given string value(s)
     or variable(s) is a substring of the first given string value or
     variable. … Is false (NOT): Runs a boolean check on if a given boolean
     variable is false. Is null: Runs a boolean check on if a given variable
     is null." (p.142)
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_checks as vc  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402


def run(transform: str, *values):
    return vc.apply(transform, list(values), {}, "Match")


@pytest.mark.parametrize("transform, values, expected", [
    ("string_is", ("Paris", "Paris"), True),
    ("string_is", ("Paris", "Paris", "paris"), False),
    ("string_is_not", ("Paris", "Lyon", "Nice"), True),
    ("string_is_not", ("Paris", "Lyon", "Paris"), False),
    ("string_contains", ("Paris, France", "Paris", "France"), True),
    ("string_contains", ("Paris, France", "Paris", "Spain"), False),
    ("string_contains", ("Paris", "paris"), False),
    ("string_does_not_contain", ("Paris", "Lyon", "Nice"), True),
    ("string_does_not_contain", ("Paris", "Lyon", "ari"), False),
    ("string_starts_with", ("Paris", "Pa"), True),
    ("string_starts_with", ("Paris", "ar"), False),
    ("string_ends_with", ("Paris", "is"), True),
    ("string_ends_with", ("Paris", "Par"), False),
    ("string_contains", ("Paris", ""), True),
])
def test_string_comparisons_are_the_first_against_each_of_the_rest(transform, values, expected) -> None:
    assert run(transform, *values) is expected


def test_a_string_comparison_with_nothing_yet_is_nothing() -> None:
    assert run("string_is", None, "Paris") is None
    assert run("string_contains", "Paris", None) is None


def test_a_string_comparison_over_something_else_is_refused() -> None:
    with pytest.raises(vc.CheckError) as caught:
        run("string_contains", "12", 1)
    assert str(caught.value) == ("'Match' compares 1, which is not text - convert it with a "
                                 "cast first")


@pytest.mark.parametrize("value, is_true, is_false, is_null", [
    (True, True, False, False),
    (False, False, True, False),
    (None, False, False, True),
])
def test_boolean_checks(value, is_true, is_false, is_null) -> None:
    assert run("is_true", value) is is_true
    assert run("is_false", value) is is_false
    assert run("is_null", value) is is_null
    assert run("is_not_null", value) is (not is_null)


def test_is_null_takes_any_kind_of_value() -> None:
    assert run("is_null", "") is False
    assert run("is_not_null", 0) is True
    assert run("is_null", []) is False


def test_is_true_over_something_else_is_refused() -> None:
    with pytest.raises(vc.CheckError) as caught:
        run("is_true", "yes")
    assert str(caught.value) == "'Match' checks 'yes', which is not true or false"


def test_a_boolean_variables_typed_text_is_its_boolean() -> None:
    assert vc.of_boolean_variable("true") is True
    assert vc.of_boolean_variable(" False ") is False
    assert vc.of_boolean_variable("yes") == "yes"
    assert vc.of_boolean_variable(None) is None


# ---- the derivation ------------------------------------------------------------------
def derived(vid: str, transform: str, inputs: list[str], kind="boolean") -> dict:
    return {"id": vid, "kind": kind, "label": vid,
            "derivation": {"transform": transform, "inputs": inputs, "config": {}}}


def test_a_derivation_evaluates_checks() -> None:
    parsed = wv.parse({
        "city": {"id": "city", "kind": "string", "label": "City", "default": "Paris, France"},
        "want": {"id": "want", "kind": "string", "label": "Want", "default": "France"},
        "flag": {"id": "flag", "kind": "boolean", "label": "Flag", "default": "false"},
        "unset": {"id": "unset", "kind": "string", "label": "Unset"},
        "has": derived("has", "string_contains", ["city", "want"]),
        "off": derived("off", "is_false", ["flag"]),
        "none": derived("none", "is_null", ["unset"]),
    })
    got = wv.evaluate(parsed, {})
    assert (got["has"], got["off"], got["none"]) == (True, True, True)


def test_if_else_reads_a_boolean_variables_typed_false_as_false() -> None:
    """Found building §566: a boolean default typed in the panel is the text
    "false", which `if_else` read as a value present, so as true."""
    parsed = wv.parse({
        "flag": {"id": "flag", "kind": "boolean", "label": "Flag", "default": "false"},
        "yes": {"id": "yes", "kind": "string", "label": "Yes", "default": "shown"},
        "no": {"id": "no", "kind": "string", "label": "No", "default": "hidden"},
        "pick": derived("pick", "if_else", ["flag", "yes", "no"], kind="string"),
    })
    assert wv.evaluate(parsed, {})["pick"] == "hidden"
    assert wv.evaluate(parsed, {"flag": True})["pick"] == "shown"


@pytest.mark.parametrize("transform, inputs, said", [
    ("string_is", ["city"], "string_is needs at least 2 inputs"),
    ("is_true", ["city", "city"], "is_true takes 1 input"),
    ("string_contains", ["city"] * 21, "string_contains takes at most 20 inputs"),
])
def test_a_derivation_that_cannot_run_is_refused_at_save(transform, inputs, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"city": {"id": "city", "kind": "string", "label": "City"},
                  "x": derived("x", transform, inputs)})
    assert str(caught.value) == f"variable 'x': {said}"


def test_only_a_boolean_variables_text_is_read_as_a_boolean() -> None:
    """A string variable holding "true" is the word, to be compared as text."""
    parsed = wv.parse({
        "a": {"id": "a", "kind": "string", "label": "A", "default": "true"},
        "b": {"id": "b", "kind": "string", "label": "B", "default": "true"},
        "same": derived("same", "string_is", ["a", "b"]),
    })
    assert wv.evaluate(parsed, {})["same"] is True


def test_a_derivation_over_the_wrong_kind_says_which_variable() -> None:
    parsed = wv.parse({
        "n": {"id": "n", "kind": "number", "label": "N", "default": 3},
        "t": {"id": "t", "kind": "string", "label": "T", "default": "3"},
        "same": {**derived("same", "string_is", ["t", "n"]), "label": "Same"},
    })
    with pytest.raises(wv.VariableError) as caught:
        wv.evaluate(parsed, {})
    assert str(caught.value) == "'Same' compares 3, which is not text - convert it with a cast first"
