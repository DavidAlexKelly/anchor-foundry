"""Required properties (parity `docs/parity/ontology.md` §1.2; Foundry
`object-link-types` p.116).

> "Required properties are object type properties that must have a value. You
> can use this object type property to validate that there are no objects that
> have a null value for this property, or an empty array if it is an array
> property. This validation applies to data from the backing datasource and
> edits via actions." (p.116)

**The column has existed since migration 0003 and meant nothing.** The
Ontology Manager displayed it, the API accepted it, and no write path read it -
which is the shape of gap this repo's standard is written against: a flag that
looks configured and enforces nothing is worse than an absent feature, because
somebody will believe it.

The two enforcement points behave differently, and that is p.116's own
arrangement rather than a compromise: **sync reports, actions refuse.**
"""
from __future__ import annotations

import pytest

from src.services import actions as actions_service
from src.services import instances as instances_service
from src.services import ontology as ontology_service


# ---- what counts as absent ---------------------------------------------------
@pytest.mark.parametrize("value", [None, "", "   ", [], {}])
def test_these_are_all_missing(value) -> None:
    """p.116 names null and the empty array. The empty string is ours, and it
    is the one that matters in practice: a form posts `""` for a box somebody
    cleared, so treating it as a value would let the one path a person
    actually uses walk straight past the rule."""
    assert ontology_service.is_missing(value) is True


@pytest.mark.parametrize("value", [0, 0.0, False, "north", ["a"], {"a": 1}])
def test_these_are_values(value) -> None:
    """`0` and `false` are the classic false negative in a check written with
    `if not value`, and a required numeric property whose only legal reading is
    zero is an ordinary thing."""
    assert ontology_service.is_missing(value) is False


def test_required_properties_reads_the_flag() -> None:
    properties = [
        {"api_name": "name", "required": True},
        {"api_name": "note", "required": False},
        {"api_name": "other"},
    ]
    assert ontology_service.required_properties(properties) == {"name"}


# ---- actions refuse (p.116, "validated at apply time") -----------------------
def test_an_action_that_clears_a_required_property_is_refused() -> None:
    with pytest.raises(ValueError, match="'name' is required and this action would clear it"):
        actions_service.check_required({"name": ""}, required={"name"})


def test_an_action_that_does_not_touch_it_is_allowed() -> None:
    """**The spec's own line, and the one that keeps this usable.** A required
    property that was already empty is indexing's business - p.116 puts that
    check there, where it *reports*. Refusing here as well would make an object
    that predates the rule uneditable by the one action that could fix it."""
    actions_service.check_required({"note": "hello"}, required={"name"})


def test_an_action_that_fills_it_is_allowed() -> None:
    actions_service.check_required({"name": "north"}, required={"name"})


def test_an_empty_array_fails_a_required_array_property() -> None:
    """p.116: "Setting an array property to required ensures the presence of at
    least one item"."""
    with pytest.raises(ValueError, match="would clear it"):
        actions_service.check_required({"tags": []}, required={"tags"})
    actions_service.check_required({"tags": ["a"]}, required={"tags"})


def test_a_create_must_supply_every_required_property() -> None:
    """There is no "already" for a new object, so absence and emptiness are the
    same failure - the one path where an untouched property is still a fault."""
    with pytest.raises(ValueError, match="would create an object without one"):
        actions_service.check_required({"note": "x"}, required={"name"}, creating=True)
    actions_service.check_required({"name": "north"}, required={"name"}, creating=True)


def test_the_refusal_names_the_property() -> None:
    """Two required properties and one of them wrong: a message naming neither
    would leave somebody checking every field on the form."""
    with pytest.raises(ValueError, match="'status'"):
        actions_service.check_required(
            {"name": "north", "status": None}, required={"name", "status"}
        )


def test_nothing_required_means_nothing_refused() -> None:
    actions_service.check_required({"name": None, "tags": []}, required=set())


# ---- sync reports (p.116, "happens as backing datasources are indexed") ------
def rows(*properties: dict) -> list[tuple[str, dict]]:
    return [(str(i), p) for i, p in enumerate(properties)]


def test_sync_counts_the_rows_that_do_not_comply() -> None:
    counts = instances_service.missing_required(
        rows({"name": "north"}, {"name": None}, {"name": ""}), {"name"}
    )
    assert counts == {"name": 2}


def test_a_property_that_complies_everywhere_is_absent_from_the_count() -> None:
    """So a caller can ask "is anything wrong" by asking whether the answer is
    empty, rather than by scanning for zeros."""
    assert instances_service.missing_required(rows({"name": "north"}), {"name"}) == {}


def test_a_required_property_nobody_mapped_fails_every_row() -> None:
    """The most complete failure there is and the easiest to miss, because
    nothing about the rows looks wrong - the column simply is not there."""
    counts = instances_service.missing_required(
        rows({"other": 1}, {"other": 2}), {"name"}
    )
    assert counts == {"name": 2}


def test_sync_counts_rather_than_raising() -> None:
    """p.116: "the ontology modification itself will succeed if the column
    backing a required property contains null values". A sync that refused
    would leave an object type that will not load, and no way to see why -
    and the fix is upstream in the dataset, out of reach from here."""
    counts = instances_service.missing_required(rows({"name": None}), {"name"})
    assert counts == {"name": 1}, "counted, not raised"


def test_the_two_ends_agree_about_what_missing_means() -> None:
    """One predicate, two call sites. Two opinions about whether `""` counts
    would make a row the sync flagged and an action accepted - or the reverse,
    which is worse."""
    for value in (None, "", []):
        assert instances_service.missing_required(rows({"name": value}), {"name"})
        with pytest.raises(ValueError):
            actions_service.check_required({"name": value}, required={"name"})
