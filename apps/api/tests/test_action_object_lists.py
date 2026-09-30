"""p.36's ObjectReference list parameter (§581; db 0118).

    "The starting set for the query is set to all objects of the object type by
     default, but this can be changed to any other type. The starting set could
     also be set to an ObjectReference list parameter." (p.36)

An array parameter of `object`, naming the type it holds: the one element a
parameter has and a property does not. Its objects are chosen from its whole
type - p.33's filters and walks narrow "single object reference parameters" -
and p.34's check holds each of them. A dropdown's walk may start from it, from
every object it holds at once.

The world is `test_action_search_arounds`' p.37 example: employees, the issues
each raised, and a ticket to act on.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_action_search_arounds import (  # noqa: E402,F401
    EMPLOYEE, ISSUE, LINKS, TYPES, WORKS_ON, _fresh_identity_cache, client, fx, offered,
    pbase, run, wbase, world,
)
from test_api import hdr  # noqa: E402
from src.services import action_search_arounds as around  # noqa: E402
from src.services import action_filters as filters  # noqa: E402
from src.services import object_sets  # noqa: E402


def a_team(**over) -> dict:
    return {"api_name": "team", "display_name": "Team", "data_type": "array",
            "array_of": "object", "object_type_id": EMPLOYEE, **over}


def an_issue(**over) -> dict:
    return {"api_name": "issue", "display_name": "Issue", "data_type": "object",
            "object_type_id": ISSUE, **over}


FROM_TEAM = {"start": {"kind": "parameter", "object_type_id": EMPLOYEE, "parameter": "team"},
             "hops": [{"link_type_id": WORKS_ON}]}


# ---- without a database -------------------------------------------------------------
def test_a_walk_may_start_from_a_list_of_objects() -> None:
    got = around.check_source(
        an_issue(dropdown_search_around=FROM_TEAM), object_type_id=ISSUE,
        link_types=LINKS, object_type_ids=set(TYPES), parameters=[a_team(), an_issue()])
    assert got["start"] == {"kind": "parameter", "object_type_id": EMPLOYEE,
                            "parameter": "team"}


def test_a_list_of_another_element_cannot_be_a_start() -> None:
    with pytest.raises(ValueError, match="holds a array rather than an object"):
        around.check_source(
            an_issue(dropdown_search_around=FROM_TEAM), object_type_id=ISSUE,
            link_types=LINKS, object_type_ids=set(TYPES),
            parameters=[a_team(array_of="string"), an_issue()])


def test_a_list_start_roots_the_walk_at_every_key() -> None:
    built = around.build(an_issue(dropdown_search_around=FROM_TEAM),
                         object_type_id=uuid.UUID(ISSUE), filters=(),
                         start_key=["E2", "E1"])
    root = built.via.base
    assert root.filters == (object_sets.Filter(
        property=object_sets.PRIMARY_KEY_FILTER, op="in", value=["E2", "E1"]),)


def test_an_empty_list_start_is_unresolved() -> None:
    with pytest.raises(filters.Unresolved):
        around.build(an_issue(dropdown_search_around=FROM_TEAM),
                     object_type_id=uuid.UUID(ISSUE), filters=(), start_key=[])


# ---- the declaration ----------------------------------------------------------------
def define(client, fx, world, parameters, rule_parameter="issue"):
    return client.put(
        f"{wbase(fx)}/action-types/{world['action']}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": parameters,
              "rules": [{"kind": "modify_object",
                         "config": {"property": "note", "parameter": rule_parameter}}],
              "criteria": []})


def team(world, **over):
    return a_team(**{"object_type_id": world["employee"], **over})


def issue(world, **over):
    return an_issue(**{"object_type_id": world["issue"], **over})


def walk(world):
    return {"start": {"kind": "parameter", "object_type_id": world["employee"],
                      "parameter": "team"},
            "hops": [{"link_type_id": world["link"]}]}


@pytest.mark.parametrize("over, said", [
    ({"object_type_id": None}, "is a list of objects and does not say of which object type"),
    ({"dropdown_filters": [{"property": "name",
                            "values": [{"kind": "value", "value": "Ada"}]}]},
     "dropdown filters and search arounds narrow a single object reference"),
])
def test_a_list_of_objects_says_of_what_and_is_not_narrowed(client, fx, world, over, said):
    refused = define(client, fx, world, [team(world, **over), issue(world)])
    assert refused.status_code == 422, refused.text
    assert said in refused.text


def test_a_list_of_objects_cannot_be_walked_to(client, fx, world):
    refused = define(client, fx, world, [
        {"api_name": "who", "display_name": "Who", "data_type": "object",
         "object_type_id": world["employee"]},
        team(world, dropdown_search_around={
            "start": {"kind": "object_type", "object_type_id": world["employee"]},
            "hops": []})])
    assert refused.status_code == 422, refused.text
    assert "narrow a single object reference" in refused.text


def test_a_filter_cannot_read_a_property_of_a_list(client, fx, world):
    """p.36's third value kind is "a property of an Object Reference
    parameter": one object's property. A list has no one object to read."""
    refused = define(client, fx, world, [team(world), issue(world, dropdown_filters=[
        {"property": "title", "values": [
            {"kind": "object_property", "parameter": "team", "property": "name"}]}])])
    assert refused.status_code == 422, refused.text
    assert "which is not an object parameter with a declared type" in refused.text


def test_a_list_of_objects_is_kept_with_its_type(client, fx, world):
    define(client, fx, world, [team(world), issue(world)]).raise_for_status()
    got = client.get(f"{wbase(fx)}/action-types/{world['action']}",
                     headers=hdr(fx.viewer_sub)).json()
    held = {p["api_name"]: (p["data_type"], p["array_of"], p["object_type_id"])
            for p in got["parameters"]}
    assert held["team"] == ("array", "object", world["employee"])


# ---- the choices --------------------------------------------------------------------
def test_a_list_is_offered_its_whole_type(client, fx, world):
    define(client, fx, world, [team(world), issue(world)]).raise_for_status()
    keys = {c["primary_key"] for c in offered(client, fx, world)["team"]["items"]}
    assert keys == {"E1", "E2"}


@pytest.mark.parametrize("chosen, reached", [
    (["E1"], {"I1", "I2"}),
    (["E2"], {"I3", "I4"}),
    (["E1", "E2"], {"I1", "I2", "I3", "I4"}),
])
def test_a_walk_starts_from_every_object_in_the_list(client, fx, world, chosen, reached):
    define(client, fx, world, [team(world), issue(world, dropdown_search_around=walk(world))]
           ).raise_for_status()
    shown = offered(client, fx, world, {"team": [world["employees"][k] for k in chosen]})
    assert {c["primary_key"] for c in shown["issue"]["items"]} == reached


def test_an_empty_list_offers_nothing_and_names_the_box(client, fx, world):
    define(client, fx, world, [team(world), issue(world, dropdown_search_around=walk(world))]
           ).raise_for_status()
    shown = offered(client, fx, world, {"team": []})["issue"]
    assert shown["items"] == []
    assert shown["waiting_for"] == "team"


# ---- the submission -----------------------------------------------------------------
def test_each_object_in_the_list_is_checked(client, fx, world):
    define(client, fx, world, [team(world), issue(world, dropdown_search_around=walk(world))]
           ).raise_for_status()
    ghost = str(uuid.uuid4())
    refused = run(client, fx, world, {"team": [world["employees"]["E1"], ghost],
                                      "issue": world["issues"]["I1"]})
    assert refused.status_code == 422, refused.text
    assert f"(item 2 of 'team') is not an object of the type it asks for" in refused.text
    # An object of another type is not one of the list's either.
    refused = run(client, fx, world, {"team": [world["issues"]["I1"]],
                                      "issue": world["issues"]["I1"]})
    assert refused.status_code == 422, refused.text
    assert "item 1 of 'team'" in refused.text


def test_a_list_of_objects_must_be_a_list(client, fx, world):
    define(client, fx, world, [team(world), issue(world)]).raise_for_status()
    refused = run(client, fx, world, {"team": world["employees"]["E1"],
                                      "issue": world["issues"]["I1"]})
    assert refused.status_code == 422, refused.text
    assert "'team' is a list of objects" in refused.text


def test_a_submission_is_held_to_the_walk_from_the_list(client, fx, world):
    define(client, fx, world, [team(world), issue(world, dropdown_search_around=walk(world))]
           ).raise_for_status()
    ada = [world["employees"]["E1"]]
    refused = run(client, fx, world, {"team": ada, "issue": world["issues"]["I3"]})
    assert refused.status_code == 422, refused.text
    ok = run(client, fx, world, {"team": ada, "issue": world["issues"]["I2"]})
    assert ok.status_code == 200, ok.text
    both = [world["employees"]["E1"], world["employees"]["E2"]]
    ok = run(client, fx, world, {"team": both, "issue": world["issues"]["I3"]})
    assert ok.status_code == 200, ok.text
