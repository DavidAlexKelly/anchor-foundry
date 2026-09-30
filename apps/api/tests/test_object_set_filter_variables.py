"""The object set filter variable kind (§590; `workshop` p.75, p.146, p.199,
p.205).

> "Object set filter: Stores a set of property type / property value pairs
>  used to filter object set variables." (p.75)
> "An object set filter variable is used to track the filter state of an
>  object set... Object set filters can then be applied to object set
>  variables, or used to filter object sets in widget configurations." (p.146)

Filter state had travelled as an element-less `array`. The kind is the same
clauses under their own name, so what reads clauses reads either - and a
module saved with arrays keeps working, which the last test holds.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import workshop_variables as wv  # noqa: E402
from test_workshop_variables import TYPE_ID, object_set_var, var  # noqa: E402

NORTH = [{"property": "region", "op": "eq", "value": "north"}]


def module(kind: str = "object_set_filter", **extra) -> dict[str, wv.Variable]:
    return wv.parse({
        "v_sites": object_set_var("v_sites", label="All sites",
                                  object_set={"object_type_id": TYPE_ID, "filters": []}),
        "v_filter": var("v_filter", kind=kind, label="Site filter", **extra),
        "v_visible": object_set_var(
            "v_visible", label="Visible",
            derivation={"transform": "narrow_set", "inputs": ["v_sites", "v_filter"]}),
        "v_region": var("v_region", label="Region", derivation={
            "transform": "filter_value", "inputs": ["v_filter"],
            "config": {"property": "region"}}),
    })


def test_it_is_a_kind() -> None:
    assert "object_set_filter" in wv.KINDS
    assert wv.CLAUSE_KINDS == ("object_set_filter", "array")


def test_it_narrows_a_set_as_a_filter_array_did() -> None:
    """p.146: "applied to object set variables"."""
    resolved = wv.evaluate(module(), {"v_filter": NORTH})
    assert resolved["v_visible"]["filters"] == NORTH


def test_its_values_can_be_read_back_out() -> None:
    """p.146's filter value extraction: "you want to extract their chosen
    alert type into a string variable"."""
    assert wv.evaluate(module(), {"v_filter": NORTH})["v_region"] == "north"


def test_its_default_is_a_starting_filter() -> None:
    """p.146: "A default state for the filter can also be specified by
    selecting object types, property types, values" - typed by the panel as
    JSON, as an array's is."""
    import json

    variables = module(default=json.dumps(NORTH))
    assert variables["v_filter"].default == NORTH
    assert wv.evaluate(variables, {})["v_visible"]["filters"] == NORTH
    assert module(default="")["v_filter"].default is None


@pytest.mark.parametrize("default, said", [
    ('{"property": "region"}', "its default is a list of filter clauses"),
    ('[{"value": "north"}]', "each default filter names a property"),
    ('["north"]', "each default filter names a property"),
])
def test_a_default_that_is_not_filters_is_refused(default, said) -> None:
    with pytest.raises(wv.VariableError, match=said):
        module(default=default)


def test_it_cannot_be_in_the_url() -> None:
    """p.199 excludes "Object set filter variables" from URL parameters."""
    with pytest.raises(wv.VariableError, match="p.199 excludes"):
        module(url_behavior="always", external_id="f", interface=True)


def test_it_can_be_saved_in_a_state() -> None:
    """p.205 lists "Object Set Filter" among the kinds a state preserves."""
    assert "object_set_filter" in wv.SAVABLE_KINDS


def test_a_filter_array_still_works() -> None:
    """Every module saved before §590 holds its filters in an array."""
    assert wv.evaluate(module(kind="array"), {"v_filter": NORTH})["v_visible"]["filters"] == NORTH
