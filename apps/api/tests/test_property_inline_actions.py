"""A property's inline action (§594; db 0126; `workshop` p.266,
`object-views` p.67, `object-link-types` p.148).

> "To enable inline editing for a property, configure an inline action for the
>  property in the Ontology Manager." (workshop p.266)

The server's half: which action may be a property's inline action, that it
travels with the property through a save, a restore and an export, and that
deleting the action leaves the property simply not editable in place.
"""
from __future__ import annotations

import asyncio
import copy
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import property_inline_actions as inline  # noqa: E402


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


PROPERTIES = [{"api_name": "name", "display_name": "Name", "data_type": "string"},
              {"api_name": "status", "display_name": "Status", "data_type": "string"},
              {"api_name": "priority", "display_name": "Priority", "data_type": "string"}]


def new_type(client, fx, tag: str) -> dict:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"ticket_{tag}", "display_name": f"Ticket {tag}",
        "properties": PROPERTIES, "title_property": "name"})
    assert r.status_code == 201, r.text
    return r.json()


def new_action(client, fx, type_id: str, name: str, editable: list[str]) -> dict:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "api_name": name, "display_name": name.replace("_", " "),
        "editable_properties": editable})
    assert r.status_code == 201, r.text
    return r.json()


def saved(client, fx, kind: dict, **inline_actions):
    """The type saved as the editor saves it, whole, with these inline actions."""
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    props = []
    for p in got["properties"]:
        props.append({k: p.get(k) for k in (
            "api_name", "display_name", "data_type", "required", "description",
            "inline_action_type_id")} | {"inline_action_type_id": inline_actions.get(
                p["api_name"], p.get("inline_action_type_id"))})
    return client.patch(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub),
                        json={"display_name": got["display_name"], "properties": props,
                              "title_property": "name"})


def inline_of(client, fx, kind: dict) -> dict:
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    return {p["api_name"]: p["inline_action_type_id"] for p in got["properties"]}


@pytest.fixture(scope="module")
def world(client, fx) -> dict:
    tag = uuid.uuid4().hex[:6]
    kind = new_type(client, fx, tag)
    return {"tag": tag, "type": kind,
            "status": new_action(client, fx, kind["id"], f"set_status_{tag}", ["status"]),
            "both": new_action(client, fx, kind["id"], f"triage_{tag}", ["status", "priority"])}


def test_a_property_takes_an_action_that_writes_it(client, fx, world) -> None:
    r = saved(client, fx, world["type"], status=world["status"]["id"])
    assert r.status_code == 200, r.text
    assert inline_of(client, fx, world["type"]) == {
        "name": None, "status": world["status"]["id"], "priority": None}
    # One action may be the inline action of each property it writes.
    r = saved(client, fx, world["type"], priority=world["both"]["id"])
    assert r.status_code == 200, r.text
    assert inline_of(client, fx, world["type"])["priority"] == world["both"]["id"]
    # And a save that clears it clears it.
    assert saved(client, fx, world["type"], priority=None).status_code == 200
    assert inline_of(client, fx, world["type"])["priority"] is None


def test_an_action_that_does_not_write_the_property_is_refused(client, fx, world) -> None:
    r = saved(client, fx, world["type"], priority=world["status"]["id"])
    assert r.status_code == 422
    assert "does not write this property from a parameter" in r.json()["detail"]


def test_an_action_on_another_type_is_refused(client, fx, world) -> None:
    other = new_type(client, fx, uuid.uuid4().hex[:6])
    theirs = new_action(client, fx, other["id"], f"other_{world['tag']}", ["status"])
    r = saved(client, fx, world["type"], status=theirs["id"])
    assert r.status_code == 422 and "acts on another object type" in r.json()["detail"]


def test_an_action_that_cannot_back_an_inline_edit_is_refused(client, fx, world) -> None:
    """§238's refusals: one with a parameter a cell cannot hold is not one."""
    action = new_action(client, fx, world["type"]["id"], f"linked_{world['tag']}", ["status"])
    r = client.put(f"{wbase(fx)}/action-types/{action['id']}/definition",
                   headers=hdr(fx.editor_sub), json={
        "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"},
                       {"api_name": "other", "display_name": "Other", "data_type": "object",
                        "object_type_id": world["type"]["id"]}],
        "rules": [{"kind": "modify_object", "config": {"property": "status",
                                                       "parameter": "status"}}],
        "criteria": []})
    assert r.status_code == 200, r.text
    r = saved(client, fx, world["type"], status=action["id"])
    assert r.status_code == 422 and "cannot back an inline edit" in r.json()["detail"]


def test_an_action_that_is_not_there_is_refused(client, fx, world) -> None:
    r = saved(client, fx, world["type"], status=str(uuid.uuid4()))
    assert r.status_code == 422 and "no action type" in r.json()["detail"]


def test_a_new_type_has_no_action_to_name(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"fresh_{world['tag']}", "display_name": "Fresh",
        "properties": [{**PROPERTIES[1], "inline_action_type_id": world["status"]["id"]}]})
    assert r.status_code == 422 and "acts on another object type" in r.json()["detail"]


def test_a_derived_property_has_none() -> None:
    """object-link-types p.148, refused before anything is read."""
    with pytest.raises(ValueError, match="p.148"):
        asyncio.run(inline.apply(None, uuid.uuid4(), uuid.uuid4(), [
            {"api_name": "d", "derivation": {"links": []},
             "inline_action_type_id": str(uuid.uuid4())}]))


def test_which_parameter_writes_the_property() -> None:
    action = {"rules": [
        {"kind": "modify_object", "config": {"property": "a", "parameter": "pa",
                                             "object": "other"}},
        {"kind": "create_object", "config": {"property": "a", "parameter": "px"}},
        {"kind": "modify_object", "config": {"property": "b"}},
        {"kind": "modify_object", "config": {"property": "a", "parameter": "pb"}},
    ]}
    assert inline.parameter_for(action, "a") == "pb"
    assert inline.parameter_for(action, "b") is None
    assert inline.parameter_for({}, "a") is None


def test_it_is_kept_by_a_restore_and_dropped_with_its_action(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    kind = new_type(client, fx, tag)
    action = new_action(client, fx, kind["id"], f"set_status_{tag}", ["status"])
    assert saved(client, fx, kind, status=action["id"]).status_code == 200
    versions = client.get(f"{wbase(fx)}/object-types/{kind['id']}/versions",
                          headers=hdr(fx.editor_sub)).json()
    with_it = max(v["version_number"] for v in versions)
    assert saved(client, fx, kind, status=None).status_code == 200
    r = client.post(f"{wbase(fx)}/object-types/{kind['id']}/versions/{with_it}/restore",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    assert inline_of(client, fx, kind)["status"] == action["id"]
    # Deleted, the property is simply not editable in place (db 0126).
    r = client.delete(f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text
    assert inline_of(client, fx, kind)["status"] is None
    # And the version that named it still restores.
    r = client.post(f"{wbase(fx)}/object-types/{kind['id']}/versions/{with_it}/restore",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    assert inline_of(client, fx, kind)["status"] is None


def test_it_travels_in_an_export_by_name(client, fx, world) -> None:
    assert saved(client, fx, world["type"], status=world["status"]["id"]).status_code == 200
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [kind] = [t for t in document["object_types"] if t["api_name"] == f"ticket_{world['tag']}"]
    by_name = {p["api_name"]: p for p in kind["properties"]}
    assert by_name["status"]["inline_action"] == f"set_status_{world['tag']}"
    assert by_name["name"]["inline_action"] is None
    # An untouched export plans nothing.
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": document})
    assert r.status_code == 200, r.text
    assert f"ticket_{world['tag']}" in r.json()["sections"]["object_types"]["unchanged"]


def test_an_import_sets_it_after_the_actions_it_names(client, fx, world) -> None:
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [kind] = [t for t in document["object_types"] if t["api_name"] == f"ticket_{world['tag']}"]
    [action] = [a for a in document["action_types"]
                if a["api_name"] == f"set_status_{world['tag']}"
                and a["object_type"] == f"ticket_{world['tag']}"]
    # The same type and action under new names, as a copy into a new place.
    fresh = uuid.uuid4().hex[:6]
    copied = copy.deepcopy(kind)
    copied["api_name"] = f"copy_{fresh}"
    # The action keeps its name: an action's name is unique only on its type,
    # so the one on the original type must not be the one found.
    for p in copied["properties"]:
        p["inline_action"] = action["api_name"] if p["api_name"] == "status" else None
    moved = {**copy.deepcopy(action), "object_type": f"copy_{fresh}"}
    file = {**document, "object_types": [copied], "link_types": [], "action_types": [moved]}
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert r.status_code == 200, r.text
    again = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [landed] = [t for t in again["object_types"] if t["api_name"] == f"copy_{fresh}"]
    assert {p["api_name"]: p["inline_action"] for p in landed["properties"]}["status"] == \
        action["api_name"]
    # And the type's latest version holds it, so a restore of it keeps it.
    type_id = next(t["id"] for t in client.get(
        f"{wbase(fx)}/object-types?q=copy_{fresh}", headers=hdr(fx.editor_sub)).json()["items"]
        if t["api_name"] == f"copy_{fresh}")
    versions = client.get(f"{wbase(fx)}/object-types/{type_id}/versions",
                          headers=hdr(fx.editor_sub)).json()
    latest = max(versions, key=lambda v: v["version_number"])
    assert {p["api_name"]: p.get("inline_action_type_id") for p in latest["properties"]}[
        "status"] is not None
    # Re-applied, nothing changes: the version taken after the fourth pass
    # holds it too.
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert f"copy_{fresh}" in r.json()["sections"]["object_types"]["unchanged"]


def test_an_import_naming_an_action_it_does_not_define_is_refused(client, fx, world) -> None:
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [kind] = [t for t in document["object_types"] if t["api_name"] == f"ticket_{world['tag']}"]
    kind = copy.deepcopy(kind)
    for p in kind["properties"]:
        if p["api_name"] == "name":
            p["inline_action"] = f"set_status_{world['tag']}"
        if p["api_name"] == "status":
            p["inline_action"] = "nothing_here"
    file = {**document, "object_types": [kind], "link_types": [], "action_types": []}
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert r.status_code == 422, r.text
    assert "inline action" in r.json()["detail"]


def test_an_import_whose_action_does_not_write_the_property_is_refused(client, fx, world) -> None:
    """The fourth pass checks as the Ontology Manager does, and a refusal
    there leaves nothing of the file written."""
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [kind] = [t for t in document["object_types"] if t["api_name"] == f"ticket_{world['tag']}"]
    [action] = [a for a in document["action_types"]
                if a["api_name"] == f"set_status_{world['tag']}"
                and a["object_type"] == f"ticket_{world['tag']}"]
    fresh = uuid.uuid4().hex[:6]
    copied = copy.deepcopy(kind)
    copied["api_name"] = f"wrong_{fresh}"
    for p in copied["properties"]:
        p["inline_action"] = action["api_name"] if p["api_name"] == "priority" else None
    moved = {**copy.deepcopy(action), "object_type": f"wrong_{fresh}"}
    file = {**document, "object_types": [copied], "link_types": [], "action_types": [moved]}
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert r.status_code == 422, r.text
    assert "does not write this property" in r.json()["detail"]
    again = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    assert f"wrong_{fresh}" not in {t["api_name"] for t in again["object_types"]}
