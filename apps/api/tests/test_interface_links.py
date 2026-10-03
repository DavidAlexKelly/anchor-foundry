"""Link constraints on interfaces (§759; decision 0024; db 0148; Foundry
`ontology` p.60, `action-types` p.63-64).

> "If the link constraint is between two interfaces … If the link constraint
> is between an interface and an object type …" (action-types p.63)
> "If there are multiple concrete link implementations on the object type for
> the link constraint …" (p.64)

An interface promises that every implementing object type links to
something; an implementation keeps the promise with one or more of its own
link types. As with properties, most of what matters is a refusal.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_interfaces import client, fx, implement, make_type, wbase  # noqa: E402,F401
from src.services import interfaces as svc  # noqa: E402
from src.services.interfaces import InterfaceError  # noqa: E402

I_TEAM, I_PERSON, T_DESK = "i-team", "i-person", "t-desk"


# ---- the shape, without a database --------------------------------------------
def test_a_link_constraint_points_at_exactly_one_thing() -> None:
    ok = svc.parse_link_constraints([
        {"api_name": "members", "target_interface_id": str(uuid.UUID(int=1))},
        {"api_name": "desk", "display_name": " Desk ", "required": False,
         "target_object_type_id": str(uuid.UUID(int=2))},
    ])
    assert ok == [
        {"api_name": "members", "display_name": "members", "description": "",
         "target_interface_id": str(uuid.UUID(int=1)), "target_object_type_id": None,
         "required": True},
        {"api_name": "desk", "display_name": "Desk", "description": "",
         "target_interface_id": None, "target_object_type_id": str(uuid.UUID(int=2)),
         "required": False},
    ]
    assert svc.parse_link_constraints(None) == []
    for bad, says in [
        ([{"api_name": "x"}], "one interface or one object type"),
        ([{"api_name": "x", "target_interface_id": str(uuid.UUID(int=1)),
           "target_object_type_id": str(uuid.UUID(int=2))}], "one interface or one object type"),
        ([{"api_name": "Bad", "target_interface_id": str(uuid.UUID(int=1))}], "invalid"),
        ([{"api_name": "x", "target_interface_id": "nope"}], "not an id"),
        ([{"api_name": "x", "target_object_type_id": "nope"}], "not an id"),
        ([{"api_name": "x", "target_interface_id": str(uuid.UUID(int=1))}] * 2, "twice"),
        ("x", "must be a list"),
        (["x"], "must be an object"),
        ([{"api_name": f"l{i}", "target_interface_id": str(uuid.UUID(int=1))}
          for i in range(svc.MAX_LINK_CONSTRAINTS + 1)], "at most"),
    ]:
        with pytest.raises(InterfaceError, match=says):
            svc.parse_link_constraints(bad)


def link(name: str, *, interface: str | None = None, type_: str | None = None,
         required: bool = True) -> dict:
    return {"api_name": name, "display_name": name, "target_interface_id": interface,
            "target_object_type_id": type_, "required": required}


def test_link_constraints_are_inherited_and_a_contradiction_is_refused() -> None:
    own = {"child": [link("desk", type_=T_DESK)], "parent": [link("team", interface=I_TEAM)],
           "other": [link("desk", interface=I_TEAM)]}
    assert [c["api_name"] for c in svc.effective_link_constraints(
        "child", own=own, extends={"child": ["parent"]})] == ["desk", "team"]
    # The same name to the same thing is agreement.
    agree = {**own, "parent": [link("desk", type_=T_DESK)]}
    assert [c["api_name"] for c in svc.effective_link_constraints(
        "child", own=agree, extends={"child": ["parent"]})] == ["desk"]
    with pytest.raises(InterfaceError, match="different targets"):
        svc.effective_link_constraints("child", own=own, extends={"child": ["other"]})
    with pytest.raises(InterfaceError, match="circle"):
        svc.effective_link_constraints("a", own={}, extends={"a": ["b"], "b": ["a"]})


def test_ancestors_follow_every_extension() -> None:
    assert svc.ancestors("a", {"a": ["b", "c"], "b": ["d"]}) == {"a", "b", "c", "d"}
    assert svc.ancestors("a", {"a": ["b"], "b": ["a"]}) == {"a", "b"}


LINKS = {
    "l-staff": {"api_name": "staffs", "from": "t-office", "to": "t-person"},
    "l-desk": {"api_name": "sits_at", "from": "t-person", "to": T_DESK},
    "l-chair": {"api_name": "chair", "from": "t-chair", "to": "t-office"},
    "l-self": {"api_name": "partner", "from": "t-office", "to": "t-office"},
    "l-else": {"api_name": "elsewhere", "from": "t-a", "to": "t-b"},
    "l-annex": {"api_name": "annex", "from": "t-annex", "to": "t-office"},
}
IMPLEMENTS = {"t-person": {I_PERSON}, "t-office": {I_TEAM}, "t-annex": {I_TEAM}}
NAMES = {"t-person": "Person", "t-chair": "Chair", T_DESK: "Desk", I_PERSON: "Personlike",
         "t-office": "Office", I_TEAM: "Teamlike"}


def check(required: list[dict], mapping: dict, type_id: str = "t-office") -> None:
    svc.check_link_implementation(
        interface_name="Teamlike", required=required, type_id=type_id, links=LINKS,
        implements=IMPLEMENTS, names=NAMES, mapping=mapping)


def test_a_link_type_keeps_a_constraint_to_an_interface() -> None:
    check([link("members", interface=I_PERSON)], {"members": ["l-staff"]})
    # From the other end too, and a self-link to an interface it implements.
    check([link("desk", type_=T_DESK)], {"desk": ["l-desk"]}, type_id="t-person")
    check([link("peer", interface=I_TEAM)], {"peer": ["l-self"]})
    # p.64's several.
    check([link("peer", interface=I_TEAM)], {"peer": ["l-self", "l-annex"]})


def test_a_constraint_is_refused_each_way_it_can_be_broken() -> None:
    members = [link("members", interface=I_PERSON)]
    for mapping, says in [
        ({}, "requires the link 'members'"),
        ({"members": ["l-gone"]}, "does not have"),
        ({"members": ["l-else"]}, "does not link this object type"),
        ({"members": ["l-chair"]}, "Chair, which does not implement Personlike"),
        ({"members": ["l-staff", "l-staff"]}, "twice"),
        ({"members": ["l-staff"], "boss": ["l-staff"]}, "declares no link boss"),
    ]:
        with pytest.raises(InterfaceError, match=says):
            check(members, mapping)
    with pytest.raises(InterfaceError, match="links to Person, and 'desk' links to Desk"):
        check([link("desk", type_=T_DESK)], {"desk": ["l-staff"]})
    # Optional and unkept is fine.
    check([link("members", interface=I_PERSON, required=False)], {})


# ---- through the API ------------------------------------------------------------
def make_interface(client: TestClient, fx: Fixture, name: str, **over) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"{name}{tag}", "display_name": f"{name} {tag}", **over})
    assert r.status_code == 201, r.text
    return r.json()


def make_link(client: TestClient, fx: Fixture, from_id: str, to_id: str) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"l_{tag}", "display_name": f"Link {tag}", "from_type_id": from_id,
        "to_type_id": to_id, "cardinality": "one_to_many",
        "from_property": "ref", "to_property": "$primary_key"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture()
def world(client, fx) -> dict:
    """Teamlike promises its implementations link to Personlike objects, and
    to one Desk type."""
    person_i = make_interface(client, fx, "Personlike")
    desk = make_type(client, fx, [])
    team_i = make_interface(client, fx, "Teamlike", link_constraints=[
        {"api_name": "members", "display_name": "Members",
         "target_interface_id": person_i["id"]},
        {"api_name": "desk", "target_object_type_id": desk["id"], "required": False}])
    person = make_type(client, fx, [])
    office = make_type(client, fx, [{"api_name": "ref", "display_name": "Ref",
                                     "data_type": "string"}])
    assert implement(client, fx, person["id"], [{"interface_id": person_i["id"]}]).status_code == 200
    staff = make_link(client, fx, office["id"], person["id"])
    return {"person_i": person_i, "team_i": team_i, "desk": desk, "person": person,
            "office": office, "staff": staff}


def test_an_interface_keeps_its_link_constraints(client, fx, world) -> None:
    got = client.get(f"{wbase(fx)}/interfaces/{world['team_i']['id']}",
                     headers=hdr(fx.viewer_sub)).json()
    assert [(c["api_name"], c["target_interface_id"], c["target_object_type_id"], c["required"])
            for c in got["link_constraints"]] == [
        ("members", world["person_i"]["id"], None, True),
        ("desk", None, world["desk"]["id"], False)]
    assert got["effective_link_constraints"] == got["link_constraints"]
    # An update that does not mention them leaves them as they were.
    r = client.put(f"{wbase(fx)}/interfaces/{world['team_i']['id']}", headers=hdr(fx.editor_sub),
                   json={"display_name": "Renamed"})
    assert r.status_code == 200, r.text
    assert len(r.json()["link_constraints"]) == 2
    # One that does replaces them.
    r = client.put(f"{wbase(fx)}/interfaces/{world['team_i']['id']}", headers=hdr(fx.editor_sub),
                   json={"display_name": "Renamed", "link_constraints": []})
    assert r.json()["link_constraints"] == []


def test_a_child_interface_inherits_them(client, fx, world) -> None:
    child = make_interface(client, fx, "Squadlike", extends=[world["team_i"]["id"]])
    assert [c["api_name"] for c in child["effective_link_constraints"]] == ["members", "desk"]
    assert child["link_constraints"] == []


def test_an_implementation_keeps_them_with_its_link_types(client, fx, world) -> None:
    team = world["team_i"]["id"]
    r = implement(client, fx, world["office"]["id"], [{"interface_id": team}])
    assert r.status_code == 422, r.text
    assert "requires the link 'members'" in r.text
    r = implement(client, fx, world["office"]["id"], [
        {"interface_id": team, "link_mapping": {"members": [world["staff"]["id"]]}}])
    assert r.status_code == 200, r.text
    assert r.json()[0]["link_mapping"] == {"members": [world["staff"]["id"]]}
    # Saved again without saying, it keeps what it had.
    r = implement(client, fx, world["office"]["id"], [{"interface_id": team}])
    assert r.status_code == 200, r.text
    assert r.json()[0]["link_mapping"] == {"members": [world["staff"]["id"]]}


def test_a_link_to_a_type_that_does_not_implement_the_target_is_refused(
    client, fx, world
) -> None:
    stranger = make_type(client, fx, [])
    wrong = make_link(client, fx, world["office"]["id"], stranger["id"])
    r = implement(client, fx, world["office"]["id"], [
        {"interface_id": world["team_i"]["id"], "link_mapping": {"members": [wrong["id"]]}}])
    assert r.status_code == 422, r.text
    assert "does not implement" in r.text


def test_an_interface_linking_to_itself_is_kept_by_what_is_being_saved(client, fx) -> None:
    """A link back to the same interface is kept by the type's *new* list:
    the check reads what is being saved, not what was."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Node{tag}", "display_name": f"Node {tag}"})
    node = r.json()
    r = client.put(f"{wbase(fx)}/interfaces/{node['id']}", headers=hdr(fx.editor_sub), json={
        "display_name": node["display_name"],
        "link_constraints": [{"api_name": "next", "target_interface_id": node["id"]}]})
    assert r.status_code == 200, r.text
    step = make_type(client, fx, [{"api_name": "ref", "display_name": "Ref",
                                   "data_type": "string"}])
    loop = make_link(client, fx, step["id"], step["id"])
    r = implement(client, fx, step["id"], [
        {"interface_id": node["id"], "link_mapping": {"next": [loop["id"]]}}])
    assert r.status_code == 200, r.text
    # And it can still be deleted, its own constraint with it.
    assert implement(client, fx, step["id"], []).status_code == 200
    r = client.delete(f"{wbase(fx)}/interfaces/{node['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text


def test_what_a_constraint_points_at_cannot_be_deleted_from_under_it(client, fx, world) -> None:
    r = client.delete(f"{wbase(fx)}/interfaces/{world['person_i']['id']}",
                      headers=hdr(fx.editor_sub))
    assert r.status_code in (409, 422), r.text
    assert "linked to by" in r.text
    r = client.delete(f"{wbase(fx)}/object-types/{world['desk']['id']}",
                      headers=hdr(fx.editor_sub))
    assert r.status_code == 409, r.text
    assert ".desk" in r.text


def test_a_link_type_keeping_a_constraint_cannot_be_deleted(client, fx, world) -> None:
    assert implement(client, fx, world["office"]["id"], [
        {"interface_id": world["team_i"]["id"],
         "link_mapping": {"members": [world["staff"]["id"]]}}]).status_code == 200
    r = client.delete(f"{wbase(fx)}/link-types/{world['staff']['id']}",
                      headers=hdr(fx.editor_sub))
    assert r.status_code == 409, r.text
    assert "keeps an interface's link" in r.text
    assert ".members" in r.text


def test_a_constraint_must_point_inside_the_workspace(client, fx) -> None:
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Lost{uuid.uuid4().hex[:6]}", "display_name": "Lost",
        "link_constraints": [{"api_name": "x", "target_interface_id": str(uuid.uuid4())}]})
    assert r.status_code == 422, r.text
    assert "does not have" in r.text


def test_an_interface_only_a_constraint_points_at_still_cannot_be_deleted(client, fx) -> None:
    lonely = make_interface(client, fx, "Lonely")
    make_interface(client, fx, "Pointer", link_constraints=[
        {"api_name": "to_lonely", "target_interface_id": lonely["id"]}])
    r = client.delete(f"{wbase(fx)}/interfaces/{lonely['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code in (409, 422), r.text
    assert "linked to by" in r.text and "Pointer" in r.text


def test_a_target_implemented_through_extension_keeps_the_constraint(client, fx, world) -> None:
    """A type implementing `Childlike extends Personlike` is a Personlike, so a
    link to it keeps a constraint to Personlike's objects."""
    child_i = make_interface(client, fx, "Childlike", extends=[world["person_i"]["id"]])
    kid = make_type(client, fx, [])
    assert implement(client, fx, kid["id"], [{"interface_id": child_i["id"]}]).status_code == 200
    to_kid = make_link(client, fx, world["office"]["id"], kid["id"])
    r = implement(client, fx, world["office"]["id"], [
        {"interface_id": world["team_i"]["id"], "link_mapping": {"members": [to_kid["id"]]}}])
    assert r.status_code == 200, r.text


def test_a_constraint_listed_with_nothing_is_not_kept_at_all(client, fx, world) -> None:
    r = implement(client, fx, world["office"]["id"], [
        {"interface_id": world["team_i"]["id"],
         "link_mapping": {"members": [world["staff"]["id"]], "desk": []}}])
    assert r.status_code == 200, r.text
    assert r.json()[0]["link_mapping"] == {"members": [world["staff"]["id"]]}


def test_the_panel_is_offered_exactly_the_link_types_the_save_takes(client, fx, world) -> None:
    """§760: `link-candidates` asks the save's own rule, per constraint."""
    stranger = make_type(client, fx, [])
    wrong = make_link(client, fx, world["office"]["id"], stranger["id"])
    to_desk = make_link(client, fx, world["office"]["id"], world["desk"]["id"])
    r = client.get(f"{wbase(fx)}/interfaces/{world['team_i']['id']}/link-candidates",
                   headers=hdr(fx.viewer_sub), params={"object_type_id": world["office"]["id"]})
    assert r.status_code == 200, r.text
    got = {name: [c["id"] for c in cands] for name, cands in r.json().items()}
    assert got == {"members": [world["staff"]["id"]], "desk": [to_desk["id"]]}
    member = r.json()["members"][0]
    assert member["other_type"] == world["person"]["display_name"]
    assert wrong["id"] not in got["members"]
    # Each one offered is one the save keeps.
    r = implement(client, fx, world["office"]["id"], [
        {"interface_id": world["team_i"]["id"],
         "link_mapping": {"members": got["members"], "desk": got["desk"]}}])
    assert r.status_code == 200, r.text


def test_a_link_back_to_the_interface_being_implemented_is_offered(client, fx) -> None:
    """The panel asks before the type implements the interface: the
    candidates read it as implementing it, as the save will."""
    tag = uuid.uuid4().hex[:6]
    node = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Chain{tag}", "display_name": f"Chain {tag}"}).json()
    client.put(f"{wbase(fx)}/interfaces/{node['id']}", headers=hdr(fx.editor_sub), json={
        "display_name": node["display_name"],
        "link_constraints": [{"api_name": "next", "target_interface_id": node["id"]}]})
    step = make_type(client, fx, [{"api_name": "ref", "display_name": "Ref",
                                   "data_type": "string"}])
    loop = make_link(client, fx, step["id"], step["id"])
    r = client.get(f"{wbase(fx)}/interfaces/{node['id']}/link-candidates",
                   headers=hdr(fx.viewer_sub), params={"object_type_id": step["id"]})
    assert [c["id"] for c in r.json()["next"]] == [loop["id"]]


def test_a_candidate_names_the_type_at_its_other_end_from_either_end(client, fx, world) -> None:
    # A link whose *from* end is the desk, so the office is its "to" end.
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"faces_{uuid.uuid4().hex[:6]}", "display_name": "Faces",
        "from_type_id": world["desk"]["id"], "to_type_id": world["office"]["id"],
        "cardinality": "one_to_many", "from_property": "id", "to_property": "$primary_key"})
    assert r.status_code == 201, r.text
    back = r.json()
    r = client.get(f"{wbase(fx)}/interfaces/{world['team_i']['id']}/link-candidates",
                   headers=hdr(fx.viewer_sub), params={"object_type_id": world["office"]["id"]})
    desk = {c["id"]: c["other_type"] for c in r.json()["desk"]}
    assert desk[back["id"]] == world["desk"]["display_name"]
