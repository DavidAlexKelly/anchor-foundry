"""Ontology resource statuses (parity `docs/parity/ontology.md` §1.3; Foundry
`object-link-types` p.253-259).

**A status is a promise about stability, and the refusals are what make it
one.** p.256 turns `active` into "cannot be deleted" and "cannot be renamed";
p.257 turns an experimental object type into an experimental link type. A
status column with none of that behind it would be a label somebody would
believe — the shape of gap this repo's standard exists to catch.

The rules are pure, so this file needs no database. That is deliberate: p.257's
propagation is a table, and a table is exactly the sort of thing that is easy
to implement in a way that looks right on the two cases somebody tried.
"""
from __future__ import annotations

import pytest

from src.services import ontology_status as st


# ---- the values themselves (p.254) -------------------------------------------
def test_the_five_statuses_are_p254s_five() -> None:
    assert set(st.STATUSES) == {
        "promoted", "active", "experimental", "deprecated", "example",
    }


def test_a_new_resource_is_experimental() -> None:
    """p.256: "By default, any new ontological resource will be given the
    `experimental` status." Not `active` - a resource nobody has finished is
    not something applications should be told to rely on."""
    assert st.DEFAULT_STATUS == "experimental"


def test_promoted_is_for_object_types_only() -> None:
    """p.255: it "applies only to object types. It is not available for
    properties, link types, action types or interfaces"."""
    assert st.check_status("promoted", kind="object_type") == "promoted"
    for kind in ("property", "link_type", "action_type"):
        with pytest.raises(st.StatusError, match="only to object types"):
            st.check_status("promoted", kind=kind)


def test_an_unknown_status_is_refused_by_name() -> None:
    with pytest.raises(st.StatusError, match="invalid status"):
        st.check_status("retired", kind="object_type")


# ---- deletion (p.256) --------------------------------------------------------
@pytest.mark.parametrize("status", ["experimental", "deprecated"])
def test_an_experimental_or_deprecated_resource_can_be_deleted(status) -> None:
    """p.256 names exactly these two."""
    st.check_deletable(status, kind="object_type", name="Thing")


@pytest.mark.parametrize("status", ["active", "promoted", "example"])
def test_everything_else_cannot_be_deleted(status) -> None:
    """`active` is p.256's own case. `promoted` "inherits similar operational
    protections of the active status, such as restrictions on deletion"
    (p.255). `example` is simply not on p.256's list - and an example somebody
    can delete by accident is a training environment that stops working."""
    with pytest.raises(st.StatusError, match="cannot be deleted"):
        st.check_deletable(status, kind="object_type", name="Thing")


def test_the_refusal_says_what_to_do_about_it() -> None:
    """"Cannot delete" without "mark it deprecated first" is a dead end rather
    than a step."""
    with pytest.raises(st.StatusError, match="mark it deprecated"):
        st.check_deletable("active", kind="object_type", name="Thing")


# ---- the ordering p.257's table is made of -----------------------------------
def test_weakest_picks_the_least_production_ready() -> None:
    """p.257's grid of link statuses by object type statuses is, in every cell,
    "whichever of the two is lower" - an `active` type joined to an
    `experimental` one gives "experimental only". Writing the grid out would be
    writing an ordering out twice."""
    assert st.weakest("active", "experimental") == "experimental"
    assert st.weakest("promoted", "deprecated") == "deprecated"
    assert st.weakest("active", "active") == "active"
    assert st.weakest("experimental", "example") == "example"
    assert st.weakest("example", "deprecated") == "deprecated"


def test_deprecated_is_the_lowest_of_all() -> None:
    """p.257: "If at least one object type in a link type is changed to
    `deprecated`, the link type will automatically be changed to
    `deprecated`" - even against `example`, which is otherwise the other
    not-for-production state."""
    for other in st.STATUSES:
        assert st.weakest("deprecated", other) == "deprecated"


# ---- propagation into properties (p.256, p.258) ------------------------------
@pytest.mark.parametrize("status", ["experimental", "example", "deprecated"])
def test_a_type_going_down_takes_its_properties(status) -> None:
    """p.256: "if an object type is changed from `active` to `experimental`,
    all of its properties will be marked `experimental` as well.\""""
    properties = [{"api_name": "a", "status": "active"},
                  {"api_name": "b", "status": "active"}]
    st.propagate_to_properties(status, properties)
    assert [p["status"] for p in properties] == [status, status]


def test_a_type_going_up_does_not_take_its_properties() -> None:
    """**The asymmetry, and p.258 is explicit about it**: applying `active` to
    all properties is "the option to also apply", not a consequence. A property
    deliberately still experimental on an otherwise finished type stays that
    way - otherwise finishing a type would silently declare every half-built
    field on it production-ready."""
    properties = [{"api_name": "a", "status": "experimental"}]
    st.propagate_to_properties("active", properties)
    assert properties[0]["status"] == "experimental"
    st.propagate_to_properties("promoted", properties)
    assert properties[0]["status"] == "experimental"


def test_propagation_never_raises_a_property_that_is_already_lower() -> None:
    """A `deprecated` property on a type becoming `experimental` stays
    deprecated: the type's status is a ceiling, not an assignment."""
    properties = [{"api_name": "a", "status": "deprecated"}]
    st.propagate_to_properties("experimental", properties)
    assert properties[0]["status"] == "deprecated"


def test_a_property_with_no_status_is_treated_as_the_default() -> None:
    properties = [{"api_name": "a"}]
    st.propagate_to_properties("example", properties)
    assert properties[0]["status"] == "example"


# ---- propagation into link types (p.257) -------------------------------------
def test_a_link_is_dragged_down_by_either_object_type() -> None:
    """p.257's table, both rows of it."""
    assert st.link_status("active", from_status="experimental", to_status="active") == (
        "experimental"
    )
    assert st.link_status("active", from_status="active", to_status="experimental") == (
        "experimental"
    )
    assert st.link_status("active", from_status="active", to_status="deprecated") == (
        "deprecated"
    )
    assert st.link_status("active", from_status="example", to_status="active") == (
        "example"
    )


def test_a_link_between_two_active_types_may_be_active() -> None:
    """The cell that would be missing if this only ever lowered things."""
    assert st.link_status("active", from_status="active", to_status="active") == "active"


def test_a_link_is_dragged_down_by_its_foreign_key_property() -> None:
    """p.257: "The same requirements are true of foreign keys of a link type.\""""
    assert st.link_status(
        "active", from_status="active", to_status="active",
        from_property_status="experimental",
    ) == "experimental"
    assert st.link_status(
        "active", from_status="active", to_status="active",
        to_property_status="deprecated",
    ) == "deprecated"


def test_an_active_foreign_key_does_not_promote_its_link() -> None:
    """**p.257 states this in its own words** and it is the reason propagation
    is one-directional: "it is valid for a foreign key property to be in
    production, while the link type and its backing datasource are still in
    development".

    A link type declared experimental stays experimental however finished its
    ends are.
    """
    assert st.link_status(
        "experimental", from_status="active", to_status="promoted",
        from_property_status="active", to_property_status="active",
    ) == "experimental"


def test_a_link_may_always_be_less_ready_than_its_ends() -> None:
    """The declaration is a ceiling its dependencies lower, never a floor they
    raise."""
    assert st.link_status(
        "deprecated", from_status="active", to_status="active"
    ) == "deprecated"


# ---- deprecation metadata (p.254) --------------------------------------------
def test_a_deprecation_records_why_when_and_what_instead() -> None:
    """p.254's three fields."""
    out = st.parse_deprecation(
        {"reason": "Replaced by Contact", "deadline": "2026-12-31",
         "replacement_id": "abc"},
        "deprecated",
    )
    assert out == {"reason": "Replaced by Contact", "deadline": "2026-12-31",
                   "replacement_id": "abc"}


def test_deprecation_details_are_refused_on_anything_else() -> None:
    """A deadline on an `active` object type is a date nothing will ever act
    on, and somebody reading it would reasonably believe otherwise."""
    with pytest.raises(st.StatusError, match="only to a deprecated resource"):
        st.parse_deprecation({"reason": "why"}, "active")


def test_moving_away_from_deprecated_clears_the_details() -> None:
    """Un-deprecating something should not leave it explaining why it was going
    to be deleted."""
    assert st.parse_deprecation(None, "active") is None


def test_a_deprecation_may_be_recorded_before_the_details_are_known() -> None:
    """p.256 prompts for them; it does not require them. A deprecation somebody
    could not record because they had not picked a date yet is a deprecation
    that does not get recorded."""
    assert st.parse_deprecation(None, "deprecated") is None
    assert st.parse_deprecation({"reason": "why"}, "deprecated") == {"reason": "why"}


def test_a_deadline_that_is_not_a_date_is_refused() -> None:
    with pytest.raises(st.StatusError, match="ISO 8601"):
        st.parse_deprecation({"deadline": "next spring"}, "deprecated")


# ---- p.255's permission and visibility sentences (§175) ---------------------
def test_only_the_ontology_level_may_apply_promoted() -> None:
    """p.255: "Only users with the `Ontology Owner` role on the ontology level
    can directly apply the `promoted` status." A workspace is this platform's
    ontology (db 0003), so that role is `admin`."""
    with pytest.raises(st.StatusError, match="admin"):
        st.check_promotion(
            "promoted", current_status="active", workspace_role="editor"
        )
    st.check_promotion("promoted", current_status="active", workspace_role="admin")


def test_promotion_is_gated_on_the_transition_not_the_value() -> None:
    """**The trap.** The type editor sends the whole definition on every save,
    so an editor pressing Save on an already-promoted type sends `promoted`
    without asking for anything. Gating on the value would make the most
    important object types uneditable by the people who build them."""
    st.check_promotion(
        "promoted", current_status="promoted", workspace_role="editor"
    )


def test_every_other_status_is_ungated() -> None:
    """p.255 restricts one status. Anything that refused the other four would
    be a permission model nobody wrote down."""
    for status in ("active", "experimental", "deprecated", "example"):
        st.check_promotion(status, current_status="promoted", workspace_role="viewer")


def test_promoting_sets_the_visibility_prominent() -> None:
    """p.255: "Setting an object type's status to `promoted` will
    automatically set its visibility to `prominent`."""
    assert st.visibility_for("promoted", "normal") == "prominent"
    assert st.visibility_for("promoted", "prominent") == "prominent"


def test_visibility_raises_and_never_lowers() -> None:
    """The same asymmetry propagation has: p.255 says what promoting does and
    nothing about demoting undoing it. A type somebody deliberately made
    prominent should not quietly stop being so."""
    assert st.visibility_for("active", "prominent") == "prominent"
    assert st.visibility_for("deprecated", "prominent") == "prominent"
    assert st.visibility_for("active", "normal") == "normal"
