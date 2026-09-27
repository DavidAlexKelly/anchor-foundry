"""An object set filter's default whose values are variables (§592;
`workshop` p.146-148).

> "The values can be specified inline, or as variables." (p.146)
> "To accomplish this, you can specify a default filter variable state using
>  variables for property values, and turn on Update used variables on filter
>  value changes." (p.148)

The server's half: a default filter reads its variables when nothing has set
the filter, and the references are checked. The write-back is the browser's
(`filter-default.ts`), since it is the viewer's filter that changes.
"""
from __future__ import annotations

import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import workshop_variables as wv  # noqa: E402
from test_workshop_variables import TYPE_ID, object_set_var, var  # noqa: E402

RANGE = [{"property": "ppg", "op": "gte", "value": {"variable": "v_low"}},
         {"property": "ppg", "op": "lte", "value": {"variable": "v_high"}}]


TYPES = {TYPE_ID: {"ppg": "integer", "team": "string", "tags": "string", "name": "string",
                   "active": "boolean", "where": "geopoint"}}


def evaluate(variables, values, **kw):
    return wv.evaluate(variables, values, property_types=TYPES, **kw)


def module(default=RANGE, *, low: dict | None = None, **extra) -> dict[str, wv.Variable]:
    return wv.parse({
        "v_players": object_set_var("v_players", label="Players",
                                    object_set={"object_type_id": TYPE_ID, "filters": []}),
        "v_filter": var("v_filter", kind="object_set_filter", label="Player filter",
                        default=json.dumps(default) if isinstance(default, list) else default,
                        **extra),
        "v_low": low or var("v_low", kind="number", label="Low", default="10"),
        "v_high": var("v_high", kind="number", label="High"),
        "v_shown": object_set_var(
            "v_shown", label="Shown",
            derivation={"transform": "narrow_set", "inputs": ["v_players", "v_filter"]}),
    })


def test_a_default_reads_its_variables_as_they_are_now() -> None:
    variables = module()
    # The panel's typed "10" is the number it spells; an unset High is no
    # upper bound rather than a bound of nothing.
    assert evaluate(variables, {})["v_filter"] == [
        {"property": "ppg", "op": "gte", "value": 10}]
    got = evaluate(variables, {"v_low": 12, "v_high": "30"})
    assert got["v_filter"] == [{"property": "ppg", "op": "gte", "value": 12},
                               {"property": "ppg", "op": "lte", "value": 30}]
    assert got["v_shown"]["filters"] == got["v_filter"]


def test_a_filter_somebody_set_is_not_the_default() -> None:
    chosen = [{"property": "ppg", "op": "gte", "value": 1}]
    assert evaluate(module(), {"v_filter": chosen, "v_low": 99})["v_filter"] == chosen


def test_inline_values_stay_and_an_empty_one_drops_its_clause() -> None:
    default = [{"property": "team", "op": "eq", "value": "north"},
               {"property": "tags", "op": "in", "value": {"variable": "v_low"}},
               {"property": "name", "op": "eq", "value": {"variable": "v_high"}}]
    variables = module(default, low=var("v_low", kind="array", label="Tags", default='["a", "b"]'))
    assert evaluate(variables, {"v_high": ""})["v_filter"] == [
        {"property": "team", "op": "eq", "value": "north"},
        {"property": "tags", "op": "in", "value": ["a", "b"]}]
    assert evaluate(variables, {"v_low": "[]", "v_high": "x"})["v_filter"] == [
        {"property": "team", "op": "eq", "value": "north"},
        {"property": "name", "op": "eq", "value": "x"}]


def test_a_boolean_is_read_as_one() -> None:
    default = [{"property": "active", "op": "eq", "value": {"variable": "v_low"}}]
    variables = module(default, low=var("v_low", kind="boolean", label="Active", default="false"))
    assert evaluate(variables, {})["v_filter"] == [
        {"property": "active", "op": "eq", "value": False}]


def test_a_host_s_value_is_read_for_a_bound_variable() -> None:
    """p.127: a mapped variable's own default is not used."""
    got = evaluate(module(), {}, bound=frozenset({"v_low"}))
    assert got["v_filter"] == []
    got = evaluate(module(), {"v_low": 4}, bound=frozenset({"v_low"}))
    assert got["v_filter"] == [{"property": "ppg", "op": "gte", "value": 4}]


def test_a_default_with_no_references_is_itself() -> None:
    inline = [{"property": "team", "op": "eq", "value": "north"}]
    assert evaluate(module(inline), {})["v_filter"] == inline
    # And no default is no filter.
    assert evaluate(module(""), {})["v_filter"] is None


@pytest.mark.parametrize("default, low, said", [
    ([{"property": "p", "op": "eq", "value": {"variable": "v_gone"}}], None,
     "reads 'v_gone', which this module does not declare"),
    ([{"property": "p", "op": "eq", "value": {"variable": "v_low"}}],
     var("v_low", label="Derived", derivation={"transform": "concat", "inputs": ["v_high"]}),
     "reads 'Derived'; a filter value is read from a variable somebody sets"),
    ([{"property": "p", "op": "eq", "value": {"variable": "v_low"}}],
     object_set_var("v_low", label="A set", object_set={"object_type_id": TYPE_ID, "filters": []}),
     "reads 'A set'"),
    ([{"property": "p", "op": "eq", "value": {"variable": "v_filter"}}], None,
     "reads 'Player filter'"),
    ([{"property": "p", "op": "eq", "value": {"variable": "v_low", "and": 1}}], None,
     'is {"variable": "<id>"} and nothing else'),
    ([{"property": "p", "op": "eq", "value": {"variable": 3}}], None,
     'is {"variable": "<id>"} and nothing else'),
])
def test_a_reference_that_cannot_be_read_is_refused(default, low, said) -> None:
    with pytest.raises(wv.VariableError, match=re.escape(said)):
        module(default, low=low)


def test_a_value_that_merely_holds_a_dict_is_inline() -> None:
    box = [{"property": "where", "op": "within_box", "value": {"north": 1, "south": 0, "east": 1, "west": 0}}]
    assert evaluate(module(box), {})["v_filter"] == box


def test_update_used_variables_is_for_a_filter_that_uses_some() -> None:
    """p.148's toggle, on the variable it describes."""
    assert module(update_used_variables=True)["v_filter"].update_used is True
    assert module()["v_filter"].update_used is False
    with pytest.raises(wv.VariableError, match="it uses none"):
        module([{"property": "team", "op": "eq", "value": "north"}], update_used_variables=True)
    with pytest.raises(wv.VariableError, match="true or false"):
        module(update_used_variables="yes")
    with pytest.raises(wv.VariableError, match="is not an object set filter"):
        wv.parse({"v_a": var("v_a", update_used_variables=True)})


def test_a_variable_a_default_reads_is_in_use() -> None:
    """Deleting it would leave the default naming nothing."""
    found = wv.usages({}, module())
    assert found["v_low"] == [{"node": "v_filter", "prop": "default"}]
    assert found["v_high"] == [{"node": "v_filter", "prop": "default"}]
    # An array's default is not a filter default, whatever it holds.
    assert wv.usages({}, wv.parse({
        "v_a": var("v_a", kind="array", label="A", default=json.dumps(RANGE)),
        "v_low": var("v_low", kind="number", label="Low"),
    }))["v_low"] == []
    twice = [RANGE[0], {**RANGE[1], "value": {"variable": "v_low"}}]
    assert wv.usages({}, module(twice))["v_low"] == [{"node": "v_filter", "prop": "default"}]


def test_the_browser_offers_the_kinds_a_value_may_read() -> None:
    path = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "components",
                        "canvas", "filter-default.ts")
    source = open(path).read()
    block = source[source.index("export const FILTER_REF_KINDS"):]
    block = block[:block.index("];")]
    assert tuple(re.findall(r'"(\w+)"', block)) == wv.FILTER_REF_KINDS
