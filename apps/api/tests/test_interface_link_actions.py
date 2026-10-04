"""p.63-64's Create and Delete interface link rules (§761; decision 0024 §3;
db 0149; Foundry `action-types` p.63-64).

> "'Create interface link' rules allow you to create links using an interface
> link constraint defined on an interface." (p.63)
> "If there are multiple concrete link implementations on the object type for
> the link constraint, the action will fail." (p.63) / "… the action will
> attempt to delete all the concrete link implementations." (p.64)

The fixture is one interface, `Seated`, whose link to a Desk two types keep
in the two ways a key can lie: an Office holds the desk's key (the near
side), and a Desk holds a Room's (the far side). One action reaches both.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import actions as actions_service  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


# ---- the rename, without a database ---------------------------------------------
LINKS = {
    "near": {"from_object_type_id": "office", "to_object_type_id": "desk",
             "from_property": "desk_ref", "to_property": "$primary_key"},
    "far": {"from_object_type_id": "desk", "to_object_type_id": "room",
            "from_property": "room_ref", "to_property": "$primary_key"},
    "join": {"from_object_type_id": "office", "to_object_type_id": "desk",
             "join_from_column": "office", "join_to_column": "desk"},
}
CREATE = {"kind": "create_interface_link", "position": 0,
          "config": {"link": "desk", "object": "the_desk"}}
DELETE = {**CREATE, "kind": "delete_interface_link"}
DESK = {"primary_key": "D1", "properties": {"room_ref": None}}


def rename(rules, mapping, *, type_id="office", subject=None, destinations=None):
    return actions_service.interface_link_rules(
        rules, link_mapping=mapping, link_types=LINKS, subject_type_id=type_id,
        subject=subject or {"primary_key": "O1", "properties": {"desk_ref": None}},
        destinations={"the_desk": DESK} if destinations is None else destinations)


def test_a_key_on_this_object_is_written_with_the_destinations_key() -> None:
    rules, values = rename([CREATE], {"desk": ["near"]})
    assert rules == [{"kind": "create_link", "position": 0,
                      "config": {"link_type": "near", "target": "__interface_link_0"}}]
    assert values == {"__interface_link_0": "D1"}


def test_a_key_on_the_destination_names_it() -> None:
    rules, values = rename([CREATE], {"desk": ["far"]}, type_id="room",
                           subject={"primary_key": "R1", "properties": {}})
    assert rules == [{"kind": "create_link", "position": 0,
                      "config": {"link_type": "far", "object": "the_desk"}}]
    assert values == {}


def test_a_join_table_names_the_destination_from_either_end() -> None:
    rules, _ = rename([CREATE], {"desk": ["join"]})
    assert rules[0]["config"] == {"link_type": "join", "object": "the_desk"}


def test_other_rules_pass_through_untouched() -> None:
    other = {"kind": "modify_object", "config": {"property": "x", "parameter": "y"}}
    rules, _ = rename([other, CREATE], {"desk": ["near"]})
    assert rules[0] is other


def test_none_or_several_is_refused_where_p63_says() -> None:
    with pytest.raises(actions_service.InterfaceSubjectError, match="no link type"):
        rename([CREATE], {})
    with pytest.raises(actions_service.InterfaceSubjectError, match="several"):
        rename([CREATE], {"desk": ["near", "join"]})
    with pytest.raises(actions_service.InterfaceSubjectError, match="no value"):
        rename([CREATE], {"desk": ["near"]},
               destinations={"the_desk": {"primary_key": None, "properties": {}}})


def test_delete_takes_each_concrete_link_that_joins_these_two() -> None:
    linked = {"primary_key": "O1", "properties": {"desk_ref": "D1"}}
    rules, _ = rename([DELETE], {"desk": ["near", "join"]}, subject=linked)
    assert [r["config"] for r in rules] == [
        {"link_type": "near"}, {"link_type": "join", "object": "the_desk"}]
    assert {r["kind"] for r in rules} == {"delete_link"}
    # A key pointing at some other desk is some other link: left alone.
    elsewhere = {"primary_key": "O1", "properties": {"desk_ref": "D9"}}
    rules, _ = rename([DELETE], {"desk": ["near"]}, subject=elsewhere)
    assert rules == []
    # And from the far side, only where the desk points at this room.
    room = {"primary_key": "R1", "properties": {}}
    rules, _ = rename([DELETE], {"desk": ["far"]}, type_id="room", subject=room,
                      destinations={"the_desk": {"primary_key": "D1",
                                                 "properties": {"room_ref": "R1"}}})
    assert [r["config"] for r in rules] == [{"link_type": "far", "object": "the_desk"}]
    rules, _ = rename([DELETE], {"desk": ["far"]}, type_id="room", subject=room,
                      destinations={"the_desk": {"primary_key": "D1",
                                                 "properties": {"room_ref": "R2"}}})
    assert rules == []


# ---- through the API ------------------------------------------------------------
def _type(client, fx, name: str, props: list[str]) -> str:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"{name}{fx.tag}", "display_name": f"{name} {fx.tag}",
        "properties": [{"api_name": p, "data_type": "string"} for p in props],
        "title_property": props[0]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sync(client, fx, type_id: str, csv: bytes, key: str, mappings: dict) -> dict[str, str]:
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"d {uuid.uuid4().hex[:6]}"},
                    files={"file": ("d.csv", io.BytesIO(csv), "text/csv")})
    assert r.status_code == 201, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "dataset_id": r.json()["id"],
        "primary_key_column": key, "column_mappings": mappings})
    assert r.status_code == 201, r.text
    assert client.post(f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
                       headers=hdr(fx.editor_sub)).status_code == 200
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {i["primary_key"]: i["id"] for i in items}


def _link(client, fx, from_id, to_id, prop) -> str:
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"l_{uuid.uuid4().hex[:6]}", "display_name": "L", "from_type_id": from_id,
        "to_type_id": to_id, "cardinality": "one_to_many",
        "from_property": prop, "to_property": "$primary_key"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def world(client, fx) -> dict:
    desk = _type(client, fx, "Desk", ["desk_code", "room_ref"])
    office = _type(client, fx, "Office", ["office_code", "desk_ref"])
    room = _type(client, fx, "Room", ["room_code"])
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Seated{fx.tag}", "display_name": f"Seated {fx.tag}",
        "properties": [{"api_name": "code", "data_type": "string"}],
        "link_constraints": [{"api_name": "desk", "target_object_type_id": desk}]})
    assert r.status_code == 201, r.text
    seated = r.json()["id"]
    near = _link(client, fx, office, desk, "desk_ref")
    far = _link(client, fx, desk, room, "room_ref")
    for type_id, link, code in ((office, near, "office_code"), (room, far, "room_code")):
        r = client.put(f"{wbase(fx)}/object-types/{type_id}/interfaces",
                       headers=hdr(fx.editor_sub),
                       json=[{"interface_id": seated, "property_mapping": {"code": code},
                              "link_mapping": {"desk": [link]}}])
        assert r.status_code == 200, r.text
    desks = _sync(client, fx, desk, b"desk_code,room_ref\nD1,\nD2,\n", "desk_code",
                  {"desk_code": "desk_code", "room_ref": "room_ref"})
    offices = _sync(client, fx, office, b"office_code,desk_ref\nO1,\n", "office_code",
                    {"office_code": "office_code", "desk_ref": "desk_ref"})
    rooms = _sync(client, fx, room, b"room_code\nR1\n", "room_code", {"room_code": "room_code"})
    return {"desk": desk, "office": office, "room": room, "seated": seated,
            "near": near, "far": far, "desks": desks, "offices": offices, "rooms": rooms}


def _action(client, fx, world, kind: str) -> dict:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "interface_id": world["seated"], "api_name": f"a_{uuid.uuid4().hex[:8]}",
        "display_name": "Seat", "editable_properties": ["code"]})
    assert r.status_code == 201, r.text
    action = r.json()
    r = client.put(f"{wbase(fx)}/action-types/{action['id']}/definition",
                   headers=hdr(fx.editor_sub), json={
        "parameters": [{"api_name": "the_desk", "display_name": "Desk", "data_type": "object",
                        "object_type_id": world["desk"]}],
        "rules": [{"kind": kind, "config": {"link": "desk", "object": "the_desk"}}],
        "criteria": []})
    assert r.status_code == 200, r.text
    return action


def _run(client, fx, action, instance, desk):
    return client.post(f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": instance, "values": {"the_desk": desk}})


def _props(client, fx, type_id, instance) -> dict:
    return client.get(f"{wbase(fx)}/object-types/{type_id}/instances/{instance}",
                      headers=hdr(fx.viewer_sub)).json()["properties"]


def test_one_action_creates_the_link_on_either_side_of_the_key(client, fx, world) -> None:
    create = _action(client, fx, world, "create_interface_link")
    r = _run(client, fx, create, world["offices"]["O1"], world["desks"]["D1"])
    assert r.status_code == 200, r.text
    assert _props(client, fx, world["office"], world["offices"]["O1"])["desk_ref"] == "D1"
    r = _run(client, fx, create, world["rooms"]["R1"], world["desks"]["D2"])
    assert r.status_code == 200, r.text
    assert _props(client, fx, world["desk"], world["desks"]["D2"])["room_ref"] == "R1"

    delete = _action(client, fx, world, "delete_interface_link")
    # Not linked to D2, so nothing of O1's is cleared.
    _run(client, fx, delete, world["offices"]["O1"], world["desks"]["D2"])
    assert _props(client, fx, world["office"], world["offices"]["O1"])["desk_ref"] == "D1"
    r = _run(client, fx, delete, world["offices"]["O1"], world["desks"]["D1"])
    assert r.status_code == 200, r.text
    assert not _props(client, fx, world["office"], world["offices"]["O1"])["desk_ref"]
    r = _run(client, fx, delete, world["rooms"]["R1"], world["desks"]["D2"])
    assert r.status_code == 200, r.text
    assert not _props(client, fx, world["desk"], world["desks"]["D2"])["room_ref"]


def test_several_concrete_links_refuse_a_create(client, fx, world) -> None:
    hall = _type(client, fx, f"Hall{uuid.uuid4().hex[:4]}", ["hall_code", "a_ref", "b_ref"])
    a = _link(client, fx, hall, world["desk"], "a_ref")
    b = _link(client, fx, hall, world["desk"], "b_ref")
    r = client.put(f"{wbase(fx)}/object-types/{hall}/interfaces", headers=hdr(fx.editor_sub),
                   json=[{"interface_id": world["seated"], "property_mapping": {"code": "hall_code"},
                          "link_mapping": {"desk": [a, b]}}])
    assert r.status_code == 200, r.text
    halls = _sync(client, fx, hall, b"hall_code,a_ref,b_ref\nH1,,\n", "hall_code",
                  {"hall_code": "hall_code", "a_ref": "a_ref", "b_ref": "b_ref"})
    create = _action(client, fx, world, "create_interface_link")
    r = _run(client, fx, create, halls["H1"], world["desks"]["D1"])
    assert r.status_code == 422, r.text
    assert "several link types" in r.text
    assert not _props(client, fx, hall, halls["H1"])["a_ref"]


def test_a_rule_is_refused_where_it_cannot_run(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["office"], "api_name": f"o_{uuid.uuid4().hex[:8]}",
        "display_name": "On a type", "editable_properties": ["desk_ref"]})
    action = r.json()
    bad = {"parameters": [{"api_name": "the_desk", "display_name": "Desk",
                           "data_type": "object", "object_type_id": world["desk"]}],
           "rules": [{"kind": "create_interface_link",
                      "config": {"link": "desk", "object": "the_desk"}}], "criteria": []}
    r = client.put(f"{wbase(fx)}/action-types/{action['id']}/definition",
                   headers=hdr(fx.editor_sub), json=bad)
    assert r.status_code == 422 and "action on an interface" in r.text, r.text

    seat = _action(client, fx, world, "create_interface_link")
    for rule_config, params, says in [
        ({"link": "chair", "object": "the_desk"}, bad["parameters"], "does not declare"),
        ({"link": "desk"}, bad["parameters"], "needs an `object`"),
        ({"link": "desk", "object": "the_desk"},
         [{"api_name": "the_desk", "display_name": "Desk", "data_type": "object",
           "object_type_id": world["room"]}], "object reference to that type"),
        ({"link": "desk", "object": "the_desk"},
         [{"api_name": "the_desk", "display_name": "Desk", "data_type": "string"}],
         "object reference to that type"),
    ]:
        r = client.put(f"{wbase(fx)}/action-types/{seat['id']}/definition",
                       headers=hdr(fx.editor_sub), json={
            "parameters": params,
            "rules": [{"kind": "create_interface_link", "config": rule_config}],
            "criteria": []})
        assert r.status_code == 422, (rule_config, r.text)
        assert says in r.text, r.text


def test_a_link_to_an_interface_takes_a_reference_to_it(client, fx, world) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Paired{tag}", "display_name": f"Paired {tag}",
        "properties": [{"api_name": "code", "data_type": "string"}],
        "link_constraints": [{"api_name": "mate", "target_interface_id": world["seated"]}]})
    paired = r.json()["id"]
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "interface_id": paired, "api_name": f"p_{tag}", "display_name": "Pair",
        "editable_properties": ["code"]})
    action = r.json()

    def define(param: dict):
        return client.put(f"{wbase(fx)}/action-types/{action['id']}/definition",
                          headers=hdr(fx.editor_sub), json={
            "parameters": [{"api_name": "mate", "display_name": "Mate", "data_type": "object",
                            **param}],
            "rules": [{"kind": "create_interface_link", "config": {"link": "mate",
                                                                    "object": "mate"}}],
            "criteria": []})

    assert define({"interface_id": world["seated"]}).status_code == 200
    r = define({"object_type_id": world["office"]})
    assert r.status_code == 422 and "interface reference to that interface" in r.text, r.text
