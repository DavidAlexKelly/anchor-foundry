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

import os

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


#: What each type declares, as `ontology.native_property_types` returns it.
#: p.143's example is "a department's average employee salary", so `salary` is
#: the typed number the arithmetic aggregations need; `title` is the string
#: that must be refused, and `headcount` is a derived property, which p.169
#: excludes by calling the permitted ones **native**.
PROPERTIES = {
    EMPLOYEE: {
        "salary": {"data_type": "integer", "derivation": None},
        "rating": {"data_type": "float", "derivation": None},
        "title": {"data_type": "string", "derivation": None},
        "started": {"data_type": "date", "derivation": None},
        "headcount": {"data_type": "integer",
                      "derivation": {"links": [], "far_type_id": DEPARTMENT}},
    },
    DEPARTMENT: {"name": {"data_type": "string", "derivation": None}},
    PROJECT: {"name": {"data_type": "string", "derivation": None},
              "budget": {"data_type": "float", "derivation": None}},
}


def parse(raw, *, on=DEPARTMENT, name="derived", properties=PROPERTIES):
    return dp.parse(raw, property_name=name, link_types=LINKS, object_type_id=on,
                    far_properties=properties)


# ---- p.143's three examples -------------------------------------------------
def test_a_departments_employee_count() -> None:
    """p.143's first example is "Average employee salary", and **that exact
    one is refused** - see `test_the_numeric_aggregations_are_refused`. This is
    the same chain with an aggregation both stores can answer, and it is here
    to pin the chain itself: the hop is inbound (employees name their
    department) and the direction is worked out rather than declared."""
    got = parse({"links": [WORKS_IN], "aggregate": "count"})
    assert got == {
        "links": [{"link_type_id": WORKS_IN, "far_type_id": EMPLOYEE}],
        "far_type_id": EMPLOYEE, "aggregate": "count",
    }


def test_p143s_own_first_example_works() -> None:
    """"A Department object type could have a derived property for 'Average
    employee salary'" - the spec's opening illustration.

    **This test used to assert the opposite**, and was called
    `test_p143s_own_first_example_is_what_the_blocker_costs`: it existed to
    record that the one shape p.143 leads with was the one shape this platform
    could not answer, because instance properties did not carry their declared
    types. §220 gave them types and §226 answered these four over a set; §406
    is this reading that and removing a refusal nothing had re-read since it
    was written.

    Kept as a test rather than deleted, because the example is the spec's and
    what it asserts is still the interesting fact - only the direction changed.
    """
    got = parse({"links": [WORKS_IN], "aggregate": "avg", "property": "salary"})
    assert got["aggregate"] == "avg"
    assert got["property"] == "salary"
    assert got["far_type_id"] == EMPLOYEE


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


def test_the_aggregations_this_platform_can_answer_are_accepted() -> None:
    for aggregate in dp.AGGREGATES:
        if aggregate in dp.UNSUPPORTED_AGGREGATES:
            continue
        raw = {"links": [WORKS_IN], "aggregate": aggregate}
        if aggregate != "count":
            raw["property"] = "salary"
        assert parse(raw)["aggregate"] == aggregate
    with pytest.raises(dp.DerivationError, match="aggregate must be one of"):
        parse({"links": [WORKS_IN], "aggregate": "median", "property": "salary"})


def test_the_numeric_aggregations_run_on_a_declared_number() -> None:
    """**p.143's own first example, buildable at last** (§406): "a department's
    average employee salary".

    These were refused outright until §406, with a sentence that was true when
    it was written and untrue from §220: "instance properties are stored
    untyped, so this platform cannot promise the same answer on both stores".
    §220 typed them and §226 answered these four over a set, which is the same
    question this asks of a chain's far end.
    """
    for aggregate in dp.NUMERIC_AGGREGATES:
        got = parse({"links": [WORKS_IN], "aggregate": aggregate, "property": "salary"})
        assert got["aggregate"] == aggregate
        assert got["property"] == "salary"
    # A float is as good as an integer; `AGGREGATABLE_TYPES` is the pair.
    assert parse({"links": [WORKS_IN], "aggregate": "avg", "property": "rating"})


def test_arithmetic_over_a_property_that_has_none_is_refused() -> None:
    """The refusal that replaces the blanket one, and it is about *this*
    property rather than about the platform."""
    with pytest.raises(dp.DerivationError, match="is a string property"):
        parse({"links": [WORKS_IN], "aggregate": "sum", "property": "title"})
    # A date has an order but no arithmetic the two stores agree on, which is
    # `object_sets`' own distinction rather than a new one here.
    with pytest.raises(dp.DerivationError, match="is a date property"):
        parse({"links": [WORKS_IN], "aggregate": "avg", "property": "started"})


def test_arithmetic_needs_a_property_and_says_which_mistake_it_is() -> None:
    for raw in ({"links": [WORKS_IN], "aggregate": "sum"},
                {"links": [WORKS_IN], "aggregate": "sum", "property": "  "}):
        with pytest.raises(dp.DerivationError, match="sum needs a property"):
            parse(raw)


def test_arithmetic_is_refused_over_a_property_the_far_type_does_not_have() -> None:
    with pytest.raises(dp.DerivationError, match="no property 'bonus'"):
        parse({"links": [WORKS_IN], "aggregate": "max", "property": "bonus"})


def test_p169_allows_arithmetic_only_over_native_properties() -> None:
    """p.169: "Aggregations may only be calculated on the linked object type's
    **native** properties."

    A derived property at the far end is itself a chain, so aggregating one
    would be an aggregation over a per-object walk - there is no column to
    push it into. p.170 lets an *aggregation* derived property feed column
    math, and nothing lets one feed an aggregation.
    """
    with pytest.raises(dp.DerivationError, match="itself a derived property"):
        parse({"links": [WORKS_IN], "aggregate": "sum", "property": "headcount"})


def test_a_caller_that_resolved_no_types_gets_a_refusal_not_a_pass() -> None:
    """§221's rule, one layer out: absence of a declaration is a refusal.

    A caller that has not read the ontology has checked no property's type, so
    letting it through would put the arithmetic on the reader's screen instead
    of on the save - which is the whole reason this module exists.
    """
    with pytest.raises(dp.DerivationError, match="resolved none"):
        parse({"links": [WORKS_IN], "aggregate": "sum", "property": "salary"},
              properties=None)
    # And the aggregations that need no declaration are unaffected by it.
    assert parse({"links": [WORKS_IN], "aggregate": "count"}, properties=None)


def test_approximate_cardinality_is_refused_for_its_own_reason() -> None:
    """Not the untyped-property blocker: OpenSearch's cardinality aggregation
    is approximate and Postgres' COUNT(DISTINCT) is exact, so "approximate"
    would be a promise one store keeps and the other exceeds. The exact one is
    the same question with an answer both can give.

    **The regex used to be "both stores", which both refusals contained** - so
    this could not have failed if the wrong reason had been given. Now it names
    the approximation, which is the half that is only true of this one.
    """
    with pytest.raises(dp.DerivationError, match="approximates where Postgres is exact"):
        parse({"links": [WORKS_IN], "aggregate": "approx_cardinality",
               "property": "salary"})
    assert parse({"links": [WORKS_IN], "aggregate": "exact_cardinality",
                  "property": "salary"})["aggregate"] == "exact_cardinality"


def test_count_takes_no_property_and_everything_else_needs_one() -> None:
    """p.146: "For Count aggregation, you do not need to select a property as
    objects are automatically counted." Carrying one anyway is two intentions."""
    assert "property" not in parse({"links": [WORKS_IN], "aggregate": "count"})
    with pytest.raises(dp.DerivationError, match="a count needs no property"):
        parse({"links": [WORKS_IN], "aggregate": "count", "property": "salary"})
    with pytest.raises(dp.DerivationError, match="choose which property"):
        parse({"links": [WORKS_IN], "aggregate": "collect_list"})


# ---- the collection limit (p.146) ------------------------------------------
def test_a_limit_applies_only_to_the_aggregations_that_collect() -> None:
    got = parse({"links": [WORKS_IN], "aggregate": "collect_set",
                 "property": "name", "limit": 3})
    assert got["limit"] == 3
    with pytest.raises(dp.DerivationError, match="only aggregations that collect"):
        parse({"links": [WORKS_IN], "aggregate": "exact_cardinality",
               "property": "salary", "limit": 3})
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


def test_the_normalised_form_can_be_saved_back_unchanged() -> None:
    """**Read-modify-write has to work.** `parse` returns `far_type_id`, so an
    editor that reads a derivation, changes the aggregation and saves it sends
    that field back - and an API that refused its own output would make every
    client strip fields it did not choose to add. Found by the browser test,
    which is exactly the round trip a person makes.
    """
    first = parse({"links": [WORKS_IN], "aggregate": "count"})
    assert parse(first) == first


def test_a_declared_landing_type_that_disagrees_with_the_chain_is_refused() -> None:
    """Accepted back, never trusted: the chain decides where it lands."""
    with pytest.raises(dp.DerivationError, match="lands on a different object type"):
        parse({"links": [WORKS_IN], "aggregate": "count", "far_type_id": PROJECT})


def test_the_browser_and_the_server_agree_on_which_aggregations_exist() -> None:
    """**The guard §410 added, and the gap it would have caught.**

    §406 removed four aggregations from `UNSUPPORTED_AGGREGATES` and added them
    to the editor's dropdown — and left `Derivation["aggregate"]` in
    `packages/types` naming the old four. Nothing failed, because the editor
    wrote `aggregate as "count"` to satisfy the union: a cast that names one
    member to smuggle four others through.

    So there were three lists of aggregations and only two of them were
    compared. This is the third: the TypeScript union must be exactly what this
    module accepts, which is `AGGREGATES` minus the ones it refuses.

    Read out of the source rather than imported, for the reason §190's
    panel-drift test gives: the two are in different languages and neither is
    derived from the other, so the only honest comparison is to go and look.
    """
    import re

    types_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))),
        "packages", "types", "src", "index.ts",
    )
    source = open(types_file).read()
    block = re.search(r"export interface Derivation \{(.*?)\n\}", source, re.S)
    assert block, "Derivation not found in packages/types - has it been renamed?"
    field = re.search(r"aggregate\?:([^;]+);", block.group(1), re.S)
    assert field, "Derivation has no `aggregate` field - has it been renamed?"
    declared = set(re.findall(r'"([a-z_]+)"', field.group(1)))
    assert declared, "the union parsed as empty - the scan broke, not the type"

    accepted = set(dp.AGGREGATES) - set(dp.UNSUPPORTED_AGGREGATES)
    assert declared == accepted, (
        f"the browser's Derivation union and the server's accepted list have "
        f"drifted: only in TypeScript {sorted(declared - accepted)}, "
        f"only on the server {sorted(accepted - declared)}"
    )
