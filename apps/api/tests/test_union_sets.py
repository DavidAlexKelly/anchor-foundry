"""p.450's union of object sets of different types (§686; `workshop` p.450, p.225).

> "You can use a variable to store a union of multiple object sets of different
> object types and pass it to the Filter List widget." (p.450)

> "The output variable of the Filter List widget can then be used to filter
> the variable containing the unioned object sets and all object types
> instances will be filtered." (p.450)

A union resolves to its parts, side by side: `{"union": [definition, ...]}`.
These tests hold what a union is, what narrowing one does to each part, and
where one is refused because the read on the other end is over one type.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import object_sets  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402

SITES = "11111111-1111-1111-1111-111111111111"
STAFF = "22222222-2222-2222-2222-222222222222"
VANS = "33333333-3333-3333-3333-333333333333"
LINK = "44444444-4444-4444-4444-444444444444"

TYPES = {
    SITES: {"name": "string", "region": "string", "opened": "date"},
    STAFF: {"name": "string", "region": "string", "grade": "integer"},
    VANS: {"plate": "string"},
}
NOTHING = {"property": "$primary_key", "op": "in", "value": []}


def var(vid: str, kind: str = "string", **extra) -> dict:
    return {"id": vid, "kind": kind, "label": extra.pop("label", vid), **extra}


def base(vid: str, type_id: str, filters: list | None = None) -> dict:
    return var(vid, kind="object_set", label=vid,
               object_set={"object_type_id": type_id, "filters": filters or []})


def union(*inputs: str, vid: str = "v_all") -> dict:
    return var(vid, kind="object_set", label="Everything",
               derivation={"transform": "union_set", "inputs": list(inputs)})


def narrowed(of: str = "v_all", by: str = "v_filter") -> dict:
    return var("v_narrowed", kind="object_set", label="Narrowed",
               derivation={"transform": "narrow_set", "inputs": [of, by]})


def document(**extra) -> dict:
    return {
        "v_sites": base("v_sites", SITES, [{"property": "region", "op": "eq", "value": "north"}]),
        "v_staff": base("v_staff", STAFF),
        "v_vans": base("v_vans", VANS),
        "v_all": union("v_sites", "v_staff"),
        **extra,
    }


def resolve(raw: dict, values: dict | None = None, types=TYPES) -> dict:
    return wv.evaluate(wv.parse(raw, property_types=types), values or {}, property_types=types)


# ---- what a union is --------------------------------------------------------
def test_a_union_holds_each_set_as_it_is() -> None:
    resolved = resolve(document())
    assert resolved["v_all"] == {"union": [
        {"object_type_id": SITES, "filters": [{"property": "region", "op": "eq", "value": "north"}]},
        {"object_type_id": STAFF, "filters": []},
    ]}
    # The same key the store refuses by, so the two cannot drift apart.
    assert wv.UNION == object_sets.UNION


def test_a_set_naming_a_type_is_that_type_whatever_else_it_carries() -> None:
    """A stray `union` beside a type is not a union, here or in the store."""
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed(of="v_odd"),
                   v_odd=base("v_odd", VANS))
    variables = wv.parse(raw, property_types=TYPES)
    odd = {"object_type_id": VANS, "filters": [], "union": []}
    clause = {"property": "plate", "op": "eq", "value": "AB1"}
    assert wv._narrow_set(variables["v_narrowed"], odd, [clause], TYPES) == {
        **odd, "filters": [clause]}


def test_a_union_of_a_union_is_flattened() -> None:
    resolved = resolve(document(v_more=union("v_all", "v_vans", vid="v_more")))
    assert [p["object_type_id"] for p in resolved["v_more"]["union"]] == [SITES, STAFF, VANS]


def test_a_union_refuses_two_sets_of_one_type() -> None:
    raw = document(v_north=base("v_north", SITES), v_twice=union("v_sites", "v_north", vid="v_twice"))
    with pytest.raises(wv.VariableError, match="two sets of one object type"):
        resolve(raw)
    # Found through a flattened union as well.
    raw = document(v_north=base("v_north", SITES), v_twice=union("v_all", "v_north", vid="v_twice"))
    with pytest.raises(wv.VariableError, match="two sets of one object type"):
        resolve(raw)


def test_a_union_joins_two_to_ten_sets_each_once() -> None:
    with pytest.raises(wv.VariableError, match="from 2 to 10"):
        wv.parse(document(v_all=union("v_sites")))
    with pytest.raises(wv.VariableError, match="names one set twice"):
        wv.parse(document(v_all=union("v_sites", "v_sites")))
    many = {f"v_{i}": base(f"v_{i}", SITES) for i in range(11)}
    with pytest.raises(wv.VariableError, match="from 2 to 10"):
        wv.parse({**many, "v_all": union(*many)})
    # Ten is allowed; the count after flattening is held to the same bound.
    ten = {f"v_{i}": base(f"v_{i}", f"{i:08d}-0000-0000-0000-000000000000") for i in range(10)}
    wv.parse({**ten, "v_all": union(*ten)})
    eleven = {**ten, "v_x": base("v_x", VANS), "v_all": union(*ten),
              "v_more": union("v_all", "v_x", vid="v_more")}
    with pytest.raises(wv.VariableError, match="joins 11 object sets; a union holds at most 10"):
        wv.evaluate(wv.parse(eleven), {})


def test_a_union_is_an_object_set_of_object_sets() -> None:
    with pytest.raises(wv.VariableError, match="is an object set, not a string"):
        wv.parse(document(v_all=var("v_all", label="Everything", derivation={
            "transform": "union_set", "inputs": ["v_sites", "v_staff"]})))
    with pytest.raises(wv.VariableError, match="'Words' is not an object set"):
        wv.parse(document(v_words=var("v_words", label="Words"),
                          v_all=union("v_sites", "v_words")))


def test_a_union_of_something_that_is_not_a_set_is_refused_at_view() -> None:
    """Held by kind at save; a value arriving shaped wrong is still refused."""
    variables = wv.parse(document())
    with pytest.raises(wv.VariableError, match="joins something that is not an object set"):
        wv._union_set(variables["v_all"], [{"object_type_id": SITES}, "north"])


# ---- narrowing a union narrows every part -----------------------------------
def test_a_common_property_narrows_every_part() -> None:
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    clause = {"property": "region", "op": "eq", "value": "south"}
    parts = resolve(raw, {"v_filter": [clause]})["v_narrowed"]["union"]
    assert parts[0]["filters"] == [{"property": "region", "op": "eq", "value": "north"}, clause]
    assert parts[1]["filters"] == [clause]


def test_a_single_property_leaves_the_other_types_nothing() -> None:
    """p.450's Single property: "a unique property that exists on only one of
    the object types". The other types have no objects with the value asked
    for - and an ordered clause on one type's date is not refused against
    types that have no date."""
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    clause = {"property": "opened", "op": "gte", "value": "2024-01-01"}
    parts = resolve(raw, {"v_filter": [clause]})["v_narrowed"]["union"]
    assert parts[0]["filters"][-1] == clause
    assert parts[1] == {"object_type_id": STAFF, "filters": [NOTHING]}


def test_a_part_keeps_its_place_when_it_keeps_nothing() -> None:
    """A tab does not vanish because a filter emptied it."""
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    parts = resolve(raw, {"v_filter": [{"property": "grade", "op": "eq", "value": 3}]})[
        "v_narrowed"]["union"]
    assert [p["object_type_id"] for p in parts] == [SITES, STAFF]
    assert NOTHING in parts[0]["filters"] and NOTHING not in parts[1]["filters"]


def test_a_selection_in_one_type_narrows_the_others_to_nothing() -> None:
    """A table's selection in one tab names its type (§686), because a key is
    a key only within its own type."""
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    picked = [{"property": "$object_type", "op": "eq", "value": STAFF},
              {"property": "$primary_key", "op": "in", "value": ["S1"]}]
    parts = resolve(raw, {"v_filter": picked})["v_narrowed"]["union"]
    assert parts[0]["filters"][-1] == NOTHING
    assert parts[1]["filters"] == [{"property": "$primary_key", "op": "in", "value": ["S1"]}]


def test_no_clauses_leave_every_part_as_it_was() -> None:
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    resolved = resolve(raw, {"v_filter": []})
    assert resolved["v_narrowed"] == resolved["v_all"]
    assert resolved["v_narrowed"] is not resolved["v_all"]


def test_clauses_that_are_not_a_list_are_refused_for_a_union_too() -> None:
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    with pytest.raises(wv.VariableError, match="expects a list of filter clauses, not str"):
        resolve(raw, {"v_filter": "region=south"})
    with pytest.raises(wv.VariableError, match="expects a list of filter clauses, not int"):
        resolve(raw, {"v_filter": 7})


def test_a_bad_clause_on_a_part_is_refused_rather_than_dropped() -> None:
    raw = document(v_filter=var("v_filter", kind="object_set_filter", label="Filter"),
                   v_narrowed=narrowed())
    with pytest.raises(wv.VariableError, match="Narrowed"):
        resolve(raw, {"v_filter": [{"property": "region", "op": "sounds_like", "value": "x"}]})


def test_without_the_ontology_nothing_is_said_to_be_missing() -> None:
    variables = wv.parse(document(
        v_filter=var("v_filter", kind="object_set_filter", label="Filter"), v_narrowed=narrowed()))
    parts = wv.evaluate(variables, {"v_filter": [{"property": "grade", "op": "eq", "value": 3}]})[
        "v_narrowed"]["union"]
    assert all(p["filters"][-1] == {"property": "grade", "op": "eq", "value": 3} for p in parts)


def test_filter_set_narrows_every_part_too() -> None:
    raw = document(
        v_region=var("v_region", label="Region"),
        v_grade=var("v_grade", label="Grade"),
        v_by_region=var("v_by_region", kind="object_set", label="By region", derivation={
            "transform": "filter_set", "inputs": ["v_all", "v_region"],
            "config": {"property": "region", "op": "eq"}}),
        v_by_grade=var("v_by_grade", kind="object_set", label="By grade", derivation={
            "transform": "filter_set", "inputs": ["v_all", "v_grade"],
            "config": {"property": "grade", "op": "eq"}}),
    )
    resolved = resolve(raw, {"v_region": "south", "v_grade": "3"})
    south = {"property": "region", "op": "eq", "value": "south"}
    assert [p["filters"][-1] for p in resolved["v_by_region"]["union"]] == [south, south]
    by_grade = resolved["v_by_grade"]["union"]
    assert by_grade[0]["filters"][-1] == NOTHING
    assert by_grade[1]["filters"] == [{"property": "grade", "op": "eq", "value": "3"}]
    # Unset is no filter, for every part - not "nothing" for the ones without it.
    resolved = resolve(raw, {})
    assert resolved["v_by_grade"] == resolved["v_all"]


# ---- where a union is refused -----------------------------------------------
def test_a_link_is_not_followed_from_a_union() -> None:
    raw = document(v_far=var("v_far", kind="object_set", label="Far", derivation={
        "transform": "traverse_set", "inputs": ["v_all"],
        "config": {"link_type_id": LINK, "object_type_id": VANS}}))
    with pytest.raises(wv.VariableError, match="follows a link from a union"):
        resolve(raw)


def test_a_union_is_not_aggregated() -> None:
    raw = document(v_count=var("v_count", kind="number", label="Count", derivation={
        "transform": "object_set_aggregation", "inputs": ["v_all"],
        "config": {"aggregation": "count"}}))
    with pytest.raises(wv.VariableError, match="aggregates a union"):
        resolve(raw)


def test_a_read_over_one_type_refuses_a_union_in_a_sentence() -> None:
    definition = {"union": [{"object_type_id": SITES, "filters": []}]}
    for read in (object_sets.parse, object_sets.object_type_id_of):
        with pytest.raises(ValueError, match="union of several object types"):
            read(definition)
    # A definition that names a type is one type, whatever else it carries.
    assert object_sets.object_type_id_of({"object_type_id": SITES, "union": []}).hex
    with pytest.raises(ValueError, match="needs an object_type_id"):
        object_sets.parse({"filters": []})


def test_the_browser_reads_a_union_by_the_same_key() -> None:
    import re

    path = os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "components",
                        "canvas", "union-set.ts")
    with open(path, encoding="utf-8") as handle:
        found = re.search(r'export const UNION = "([^"]+)";', handle.read())
    assert found and found.group(1) == object_sets.UNION
