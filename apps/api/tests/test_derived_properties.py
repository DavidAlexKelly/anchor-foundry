"""Validating a derived property's question (Foundry `object-link-types`
p.143-148).

Answering it is the store's and is tested through the API. Here: the refusals,
and each is a declaration that would otherwise be a column of blanks or an
error on a page rather than on a save.

p.143's own three examples are the fixture - a department's average employee
salary, a project's lead engineer name, an order's product names - because they
are exactly the three shapes: an aggregate over many, a single value across a
one-to-one hop, and a collection.
"""
from __future__ import annotations

import pytest

from src.services import derived_properties as dp

DEPARTMENT = "11111111-1111-1111-1111-111111111111"
EMPLOYEE = "22222222-2222-2222-2222-222222222222"
PROJECT = "33333333-3333-3333-3333-333333333333"

WORKS_IN = "aaaaaaaa-0000-0000-0000-000000000001"   # Employee -> Department
LEADS = "aaaaaaaa-0000-0000-0000-000000000002"      # Project  -> Employee, 1:1
ASSIGNED = "aaaaaaaa-0000-0000-0000-000000000003"   # Employee -> Project, m:n
UNJOINED = "aaaaaaaa-0000-0000-0000-000000000004"   # defined, not traversable
VENDOR = "44444444-4444-4444-4444-444444444444"
SUPPLIES = "aaaaaaaa-0000-0000-0000-000000000005"   # Vendor -> Project

LINKS = {
    WORKS_IN: {
        "id": WORKS_IN, "display_name": "Works in", "cardinality": "one_to_many",
        "from_object_type_id": EMPLOYEE, "to_object_type_id": DEPARTMENT,
        "from_property": "department", "to_property": "$primary_key",
    },
    LEADS: {
        "id": LEADS, "display_name": "Led by", "cardinality": "one_to_one",
        "from_object_type_id": PROJECT, "to_object_type_id": EMPLOYEE,
        "from_property": "lead", "to_property": "$primary_key",
    },
    ASSIGNED: {
        "id": ASSIGNED, "display_name": "Assigned to", "cardinality": "many_to_many",
        "from_object_type_id": EMPLOYEE, "to_object_type_id": PROJECT,
        "from_property": "project", "to_property": "$primary_key",
    },
    SUPPLIES: {
        "id": SUPPLIES, "display_name": "Supplies", "cardinality": "one_to_many",
        "from_object_type_id": VENDOR, "to_object_type_id": PROJECT,
        "from_property": "project", "to_property": "$primary_key",
    },
    UNJOINED: {
        "id": UNJOINED, "display_name": "Related to", "cardinality": "one_to_many",
        "from_object_type_id": DEPARTMENT, "to_object_type_id": PROJECT,
        "from_property": None, "to_property": None,
    },
}


def parse(raw, *, on=DEPARTMENT, name="derived"):
    return dp.parse(raw, property_name=name, link_types=LINKS, object_type_id=on)


# ---- p.143's three examples -------------------------------------------------
def test_a_departments_average_employee_salary() -> None:
    """"A Department object type could have a derived property for 'Average
    employee salary' that aggregates salary values from all linked Employee
    objects." The hop is inbound - employees name their department - and the
    direction is worked out rather than declared."""
    got = parse({"links": [WORKS_IN], "aggregate": "avg", "property": "salary"})
    assert got == {
        "links": [{"link_type_id": WORKS_IN, "far_type_id": EMPLOYEE}],
        "far_type_id": EMPLOYEE, "aggregate": "avg", "property": "salary",
    }


def test_a_projects_lead_engineer_name_needs_no_aggregation() -> None:
    """"A Project object type could have a derived property for 'Lead engineer
    name' that retrieves the name from a single linked Engineer object."
    p.145 only demands an aggregation when a hop can reach more than one."""
    got = parse({"links": [LEADS], "property": "name"}, on=PROJECT)
    assert "aggregate" not in got
    assert got["far_type_id"] == EMPLOYEE


def test_an_orders_product_names_collect_into_a_list() -> None:
    got = parse(
        {"links": [ASSIGNED], "aggregate": "collect_list", "property": "name"},
        on=EMPLOYEE,
    )
    assert got["aggregate"] == "collect_list"
    # p.146: "The default limit is 10 items."
    assert got["limit"] == dp.DEFAULT_LIMIT


# ---- the chain (p.145, p.147) ----------------------------------------------
def test_a_chain_can_be_three_hops_and_no_more() -> None:
    """p.147's "Department → Employee → Project", plus one hop back."""
    got = parse({"links": [WORKS_IN, ASSIGNED], "aggregate": "collect_set",
                 "property": "name"})
    assert [h["far_type_id"] for h in got["links"]] == [EMPLOYEE, PROJECT]
    assert got["far_type_id"] == PROJECT

    three = parse({"links": [WORKS_IN, ASSIGNED, LEADS], "aggregate": "count"})
    assert len(three["links"]) == 3
    with pytest.raises(dp.DerivationError, match=f"at most {dp.MAX_HOPS} links"):
        parse({"links": [WORKS_IN, ASSIGNED, LEADS, WORKS_IN], "aggregate": "count"})


def test_a_chain_that_does_not_join_up_is_refused() -> None:
    """The second link has to touch where the first one landed. Otherwise the
    chain describes a walk nobody could take, and the property would be blank
    on every object rather than wrong on one.

    `Supplies` joins vendors to projects, and this chain has only reached
    employees.
    """
    with pytest.raises(dp.DerivationError, match="link 2: 'Supplies' does not touch"):
        parse({"links": [WORKS_IN, SUPPLIES], "aggregate": "count"})


def test_following_one_link_twice_is_legal_and_lands_back() -> None:
    """The counterpart, and the reason the check above needed a fourth type to
    demonstrate: a department's employees' departments is a real walk, so
    "the same link twice" is not by itself a broken chain."""
    got = parse({"links": [WORKS_IN, WORKS_IN], "aggregate": "count"})
    assert [h["far_type_id"] for h in got["links"]] == [EMPLOYEE, DEPARTMENT]


def test_a_link_that_does_not_touch_this_type_at_all_is_refused() -> None:
    with pytest.raises(dp.DerivationError, match="link 1: 'Led by' does not touch"):
        parse({"links": [LEADS], "property": "name"})


def test_a_link_with_no_join_cannot_be_followed() -> None:
    """A link type can be defined and not traversable (db 0027). There is
    nothing to follow, so there is nothing to derive."""
    with pytest.raises(dp.DerivationError, match="has no join"):
        parse({"links": [UNJOINED], "aggregate": "count"})


def test_a_derivation_needs_at_least_one_link() -> None:
    for empty in (None, [], {"links": []}):
        raw = empty if isinstance(empty, dict) else {"links": empty}
        if empty is None:
            assert parse(None) is None
            continue
        with pytest.raises(dp.DerivationError, match="at least one link"):
            parse(raw)


def test_an_unknown_link_type_is_refused() -> None:
    with pytest.raises(dp.DerivationError, match="no such link type"):
        parse({"links": ["aaaaaaaa-0000-0000-0000-00000000ffff"], "aggregate": "count"})


# ---- aggregation (p.145, p.146) --------------------------------------------
def test_a_many_hop_needs_an_aggregation() -> None:
    """p.145: "If any link in your chain has a 'many' cardinality … you must
    select an Aggregation to combine the values." Without one there is no
    single value to put in the cell - the property would be silently empty on
    exactly the objects it exists for."""
    with pytest.raises(dp.DerivationError, match="needs an aggregation"):
        parse({"links": [WORKS_IN], "property": "salary"})


def test_direction_decides_whether_a_hop_reaches_many() -> None:
    """The same `one_to_many` link, both ways. From the department it reaches
    every employee; from an employee it reaches exactly one department - so
    one direction needs an aggregation and the other does not."""
    with pytest.raises(dp.DerivationError, match="needs an aggregation"):
        parse({"links": [WORKS_IN], "property": "salary"}, on=DEPARTMENT)
    assert parse({"links": [WORKS_IN], "property": "name"}, on=EMPLOYEE)["far_type_id"] == (
        DEPARTMENT
    )


def test_many_to_many_reaches_many_in_both_directions() -> None:
    for start in (EMPLOYEE, PROJECT):
        with pytest.raises(dp.DerivationError, match="needs an aggregation"):
            parse({"links": [ASSIGNED], "property": "name"}, on=start)


def test_every_aggregation_p145_lists_is_accepted() -> None:
    for aggregate in dp.AGGREGATES:
        raw = {"links": [WORKS_IN], "aggregate": aggregate}
        if aggregate != "count":
            raw["property"] = "salary"
        assert parse(raw)["aggregate"] == aggregate
    with pytest.raises(dp.DerivationError, match="aggregate must be one of"):
        parse({"links": [WORKS_IN], "aggregate": "median", "property": "salary"})


def test_count_takes_no_property_and_everything_else_needs_one() -> None:
    """p.146: "For Count aggregation, you do not need to select a property as
    objects are automatically counted." Carrying one anyway is two intentions."""
    assert "property" not in parse({"links": [WORKS_IN], "aggregate": "count"})
    with pytest.raises(dp.DerivationError, match="a count needs no property"):
        parse({"links": [WORKS_IN], "aggregate": "count", "property": "salary"})
    with pytest.raises(dp.DerivationError, match="choose which property"):
        parse({"links": [WORKS_IN], "aggregate": "sum"})


# ---- the collection limit (p.146) ------------------------------------------
def test_a_limit_applies_only_to_the_aggregations_that_collect() -> None:
    got = parse({"links": [WORKS_IN], "aggregate": "collect_set",
                 "property": "name", "limit": 3})
    assert got["limit"] == 3
    with pytest.raises(dp.DerivationError, match="only aggregations that collect"):
        parse({"links": [WORKS_IN], "aggregate": "sum", "property": "salary", "limit": 3})
    for bad in (0, -1, 2.5, True, "3"):
        with pytest.raises(dp.DerivationError, match="limit must be"):
            parse({"links": [WORKS_IN], "aggregate": "collect_list",
                   "property": "name", "limit": bad})
    with pytest.raises(dp.DerivationError, match=f"at most {dp.MAX_LIMIT}"):
        parse({"links": [WORKS_IN], "aggregate": "collect_list",
               "property": "name", "limit": dp.MAX_LIMIT + 1})


# ---- p.148's list -----------------------------------------------------------
def test_a_derived_property_cannot_be_required() -> None:
    """p.148. Nothing writes one, so nothing could ever satisfy the rule - the
    sync report and the action check would both be asking an unanswerable
    question."""
    with pytest.raises(dp.DerivationError, match="cannot be required"):
        dp.check_compatible(
            {"required": True, "derivation": {}}, property_name="total"
        )


def test_a_derived_property_cannot_carry_formatting() -> None:
    """p.148: "Derived properties cannot have rule set bindings or base
    formatters.\""""
    with pytest.raises(dp.DerivationError, match="cannot carry formatting"):
        dp.check_compatible(
            {"value_format": {"kind": "number", "style": "plain"}}, property_name="total"
        )
    with pytest.raises(dp.DerivationError, match="cannot carry formatting"):
        dp.check_compatible(
            {"conditional_format": [{"kind": "always", "colour": "#abc"}]},
            property_name="total",
        )


def test_a_property_cannot_be_both_edit_only_and_derived() -> None:
    """Ours rather than p.148's, and the same kind of contradiction: edit-only
    means "written by an action, stored on the instance", derived means
    "written by nothing, stored nowhere"."""
    with pytest.raises(dp.DerivationError, match="both edit-only and derived"):
        dp.check_compatible({"edit_only": True}, property_name="total")


def test_a_plain_property_passes_every_compatibility_check() -> None:
    """Presence beside absence: the checks above would all pass on an empty
    dict too, so this pins that they are looking at the right fields."""
    dp.check_compatible(
        {"required": False, "value_format": None, "conditional_format": None,
         "edit_only": False},
        property_name="total",
    )


def test_an_unknown_option_is_refused_rather_than_dropped() -> None:
    with pytest.raises(dp.DerivationError, match="unknown derivation option agregate"):
        parse({"links": [WORKS_IN], "agregate": "count"})
