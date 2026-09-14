"""A parameter's dropdown, written by name (§342; db 0083, 0085, 0086;
`ontology-manager` p.65-67).

    "…copy the working state of one Ontology to another." (p.65)

**Pure, so it is tested here rather than through an export.** The module takes
dictionaries and returns dictionaries, and the interesting cases are the ones a
real workspace makes hard to build: a reference this ontology cannot name. A
sweep is what said so — the "all of it or none of it" rule in `_walk_to_names`
survived every end-to-end test, because an export only ever has ids it can
resolve.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import action_parameter_transfer as transfer  # noqa: E402

TICKET = "11111111-1111-1111-1111-111111111111"
ISSUE = "22222222-2222-2222-2222-222222222222"
RAISED = "aaaaaaaa-0000-0000-0000-000000000001"

TYPES = {TICKET: "ticket", ISSUE: "issue"}
LINKS = {RAISED: "raised_by"}


def names(parameter: dict, *, types=None, links=None) -> dict:
    return transfer.to_names(
        parameter,
        type_names=TYPES if types is None else types,
        link_names=LINKS if links is None else links,
    )


def a_walk(**over) -> dict:
    return {
        "start": {"kind": "parameter", "object_type_id": TICKET,
                  "parameter": "who"},
        "hops": [{"link_type_id": RAISED, "far_type_id": ISSUE}],
        **over,
    }


# ---- what a parameter says it points at ----------------------------------------
def test_a_parameter_pointing_nowhere_says_nothing() -> None:
    """Every parameter written before §330, and most of them after. The keys
    are emitted only when there is something to say, or a round trip invents
    three of them per parameter."""
    assert names({"api_name": "note", "data_type": "string"}) == {}


def test_the_three_fields_become_names() -> None:
    written = names({
        "object_type_id": TICKET,
        "options_from": {"object_type_id": ISSUE, "property": "state"},
        "dropdown_search_around": a_walk(),
    })
    assert written["object_type"] == "ticket"
    assert written["options_from"] == {"object_type": "issue",
                                       "property": "state"}
    assert written["dropdown_search_around"] == {
        "start": {"kind": "parameter", "object_type": "ticket",
                  "parameter": "who"},
        "hops": [{"link_type": "raised_by", "far_object_type": "issue"}],
    }


# ---- a reference this ontology cannot name -------------------------------------
def test_a_type_this_ontology_does_not_have_is_left_out() -> None:
    """**Not written as an id** (§342, and a sweep found it).

    A document carrying an id it could not resolve would *look* portable and
    refuse on the way in. The export's own "nothing in the ontology is
    identified by id" assertion is what makes that a rule, and the case it
    cannot reach is exactly this one: a real export only has ids it can name.
    """
    written = names({"object_type_id": "99999999-9999-9999-9999-999999999999"})
    assert written == {}


def test_an_options_set_this_ontology_does_not_have_is_left_out() -> None:
    written = names({"options_from": {
        "object_type_id": "99999999-9999-9999-9999-999999999999",
        "property": "state"}})
    assert written == {}


def test_a_walk_with_a_link_it_cannot_name_is_left_out_whole() -> None:
    """**All of it or none of it.**

    A walk with one hop translated and one dropped is a *different walk* that
    would import cleanly — the worst of the three outcomes, because the other
    two announce themselves. A walk this ontology cannot fully name is one the
    file leaves out, and the plan then reports the parameter as changed, which
    is true.
    """
    written = names({"dropdown_search_around": a_walk()}, links={})
    assert written == {}


def test_a_walk_with_a_landing_type_it_cannot_name_is_left_out_whole() -> None:
    """The other half of the hop, asserted apart from the link above so neither
    covers for the other."""
    written = names({"dropdown_search_around": a_walk(
        hops=[{"link_type_id": RAISED, "far_type_id": "9" * 8 + "-9999-9999-9999-999999999999"}],
    )})
    assert written == {}


def test_a_walk_from_a_type_it_cannot_name_is_left_out() -> None:
    written = names({"dropdown_search_around": a_walk(
        start={"kind": "object_type",
               "object_type_id": "99999999-9999-9999-9999-999999999999"},
    )})
    assert written == {}


def test_one_unnameable_field_does_not_take_the_others_with_it() -> None:
    """**The negative control for the three above.** Leaving a walk out is not
    licence to leave the parameter out: the type it holds is still nameable and
    still travels, and a version that gave up on the whole parameter would pass
    every test above."""
    written = names({
        "object_type_id": TICKET,
        "dropdown_search_around": a_walk(),
    }, links={})
    assert written == {"object_type": "ticket"}


# ---- p.36's start, which not every walk has ------------------------------------
def test_a_walk_from_a_type_keeps_no_parameter() -> None:
    """p.36's default start reads no parameter, so the key is absent rather
    than null — the document says what the walk is, not what it is not."""
    written = names({"dropdown_search_around": a_walk(
        start={"kind": "object_type", "object_type_id": TICKET},
    )})
    assert written["dropdown_search_around"]["start"] == {
        "kind": "object_type", "object_type": "ticket",
    }


# ---- and back again (§344) -----------------------------------------------------
def ids(parameter: dict, *, types=None, links=None, where="p") -> dict:
    return transfer.to_ids(
        parameter,
        type_ids={v: k for k, v in (TYPES if types is None else types).items()},
        link_ids={v: k for k, v in (LINKS if links is None else links).items()},
        where=where,
    )


def test_a_parameter_survives_the_round_trip() -> None:
    """**The claim both directions exist for**, asserted as one equality rather
    than field by field: a translator that dropped the walk's `parameter` start,
    or a hop's landing type, would pass any list of fields somebody
    remembered."""
    stored = {
        "object_type_id": TICKET,
        "options_from": {"object_type_id": ISSUE, "property": "state"},
        "dropdown_search_around": a_walk(),
    }
    assert ids(names(stored)) == stored


def test_a_walk_from_a_type_survives_too() -> None:
    """p.36's default start reads no parameter, and a round trip must not invent
    one — an empty `parameter` key would make `check_source` look for a
    parameter called `''`."""
    stored = {"dropdown_search_around": a_walk(
        start={"kind": "object_type", "object_type_id": TICKET})}
    assert ids(names(stored)) == stored


def test_a_parameter_pointing_nowhere_gains_nothing() -> None:
    assert ids({"api_name": "note", "data_type": "string"}) == {}


def test_the_landing_type_is_put_back_rather_than_left_to_be_derived() -> None:
    """`check_source` recomputes each hop's far end and **refuses a document
    that declares a different one** — so carrying it back is what makes a
    hand-edited walk that does not join up refuse, instead of importing cleanly
    as a different walk."""
    written = ids(names({"dropdown_search_around": a_walk()}))
    assert written["dropdown_search_around"]["hops"] == [
        {"link_type_id": RAISED, "far_type_id": ISSUE}]


def test_a_hop_with_no_landing_type_is_still_followed() -> None:
    """A file may legitimately not carry one: §342 leaves a walk out whole when
    it cannot name every part, but a hand-written file need not have it at all,
    and `check_source` will supply it."""
    written = ids({"dropdown_search_around": {
        "start": {"kind": "object_type", "object_type": "ticket"},
        "hops": [{"link_type": "raised_by"}]}})
    assert written["dropdown_search_around"]["hops"] == [
        {"link_type_id": RAISED}]


# ---- a name this workspace does not have ---------------------------------------
def test_a_name_this_workspace_lacks_is_refused_rather_than_dropped() -> None:
    """**The asymmetry between the two directions, and the whole reason to say
    it out loud** (§344).

    Outward, a reference this ontology cannot name is *left out*: a document
    carrying an id would look portable and mean nothing anywhere. Inward,
    dropping it would write a parameter with no dropdown and then report the
    file as applied — the file said something and the workspace got something
    else, and nobody would be told.
    """
    for parameter in (
        {"object_type": "nowhere"},
        {"options_from": {"object_type": "nowhere", "property": "state"}},
        {"dropdown_search_around": {
            "start": {"kind": "object_type", "object_type": "nowhere"}}},
        {"dropdown_search_around": {
            "start": {"kind": "object_type", "object_type": "ticket"},
            "hops": [{"link_type": "no_such_link"}]}},
        {"dropdown_search_around": {
            "start": {"kind": "object_type", "object_type": "ticket"},
            "hops": [{"link_type": "raised_by",
                      "far_object_type": "nowhere"}]}},
    ):
        try:
            ids(parameter, where="ticket.rename.pick")
        except ValueError as refusal:
            # Named where it is, because "an object type this workspace does not
            # have" is no use without the field it came from.
            assert "ticket.rename.pick" in str(refusal), parameter
        else:
            raise AssertionError(f"not refused: {parameter}")


def test_a_walk_with_no_hops_is_still_a_walk() -> None:
    """p.36's "changed to any other type" with nothing to follow. An empty hop
    list is a real state and not the same as having no walk, and it has to
    survive both directions or a dropdown narrowed to one type comes back as
    every object of it."""
    stored = {"dropdown_search_around": a_walk(hops=[])}
    assert names(stored)["dropdown_search_around"]["hops"] == []
    assert ids(names(stored)) == stored
