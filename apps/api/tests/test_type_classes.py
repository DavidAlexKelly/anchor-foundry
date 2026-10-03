"""A property's type classes (§671; db 0133; `object-link-types` p.91).

> "Type classes: Apply type classes as additional metadata that can be
>  interpreted by applications." (p.91)

The server's half: the `kind:name` shape, each once, kept through a save, a
restore and an export, and cleared by a save that sends none. What reads them
- p.222's hubble:icon in the Object Table - is the web's.
"""
from __future__ import annotations

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
from src.services import type_classes  # noqa: E402


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


def test_the_shape_is_kind_name_each_once() -> None:
    assert type_classes.parse(None, property_name="p") == []
    assert type_classes.parse([" hubble:icon ", "scenarios:scenario-name", "hubble:icon"],
                              property_name="p") == ["hubble:icon", "scenarios:scenario-name"]
    assert type_classes.parse(["a.b:c_d-1"], property_name="p") == ["a.b:c_d-1"]
    for bad in (["icon"], ["hubble:"], [":icon"], ["a:b:c"], ["a b:c"], [5], "hubble:icon",
                ["a:" + "x" * 100]):
        with pytest.raises(ValueError, match="'p'"):
            type_classes.parse(bad, property_name="p")
    # One class not in a list is refused as not a list, rather than read
    # character by character.
    with pytest.raises(ValueError, match="must be a list"):
        type_classes.parse("hubble:icon", property_name="p")
    many = [f"k:n{i}" for i in range(type_classes.MAX_CLASSES)]
    assert len(type_classes.parse(many, property_name="p")) == type_classes.MAX_CLASSES
    with pytest.raises(ValueError, match="more than"):
        type_classes.parse(many + ["k:more"], property_name="p")
    # Just under the length cap is kept.
    assert type_classes.parse(["a:" + "x" * 98], property_name="p") == ["a:" + "x" * 98]


def new_type(client, fx, tag: str, classes=None) -> dict:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"part_{tag}", "display_name": f"Part {tag}", "title_property": "name",
        "properties": [
            {"api_name": "name", "display_name": "Name", "data_type": "string"},
            {"api_name": "picture", "display_name": "Picture", "data_type": "string",
             **({"type_classes": classes} if classes is not None else {})}]})
    assert r.status_code == 201, r.text
    return r.json()


def classes_of(client, fx, kind: dict) -> dict:
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    return {p["api_name"]: p["type_classes"] for p in got["properties"]}


def saved(client, fx, kind: dict, classes):
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    props = [{k: p.get(k) for k in ("api_name", "display_name", "data_type")}
             | ({"type_classes": classes} if p["api_name"] == "picture" else {})
             for p in got["properties"]]
    return client.patch(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub),
                        json={"display_name": got["display_name"], "properties": props,
                              "title_property": "name"})


def test_a_property_keeps_its_type_classes(client, fx) -> None:
    kind = new_type(client, fx, uuid.uuid4().hex[:6], ["hubble:icon", "hubble:icon"])
    assert classes_of(client, fx, kind) == {"name": [], "picture": ["hubble:icon"]}
    assert saved(client, fx, kind, ["hubble:icon", "team:photo"]).status_code == 200
    assert classes_of(client, fx, kind)["picture"] == ["hubble:icon", "team:photo"]
    # A save that sends none clears them.
    assert saved(client, fx, kind, None).status_code == 200
    assert classes_of(client, fx, kind)["picture"] == []


def test_a_property_of_its_own_keeps_the_count_of_twenty(client, fx) -> None:
    """The parse allows forty, for an attached property's union (§723); a
    property with no shared property is still held to twenty."""
    kind = new_type(client, fx, uuid.uuid4().hex[:6])
    many = [f"k:n{i}" for i in range(type_classes.MAX_CLASSES + 1)]
    r = saved(client, fx, kind, many)
    assert r.status_code == 422 and "more than 20" in r.text, r.text


def test_a_class_not_kind_name_is_refused_by_its_property(client, fx) -> None:
    kind = new_type(client, fx, uuid.uuid4().hex[:6])
    r = saved(client, fx, kind, ["icon"])
    assert r.status_code == 422, r.text
    assert "'picture'" in r.json()["detail"] and "kind:name" in r.json()["detail"]


def test_a_restore_and_an_export_keep_them(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    kind = new_type(client, fx, tag, ["hubble:icon"])
    versions = client.get(f"{wbase(fx)}/object-types/{kind['id']}/versions",
                          headers=hdr(fx.editor_sub)).json()
    with_them = max(v["version_number"] for v in versions)
    assert saved(client, fx, kind, []).status_code == 200
    r = client.post(f"{wbase(fx)}/object-types/{kind['id']}/versions/{with_them}/restore",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    assert classes_of(client, fx, kind)["picture"] == ["hubble:icon"]

    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [t for t in document["object_types"] if t["api_name"] == f"part_{tag}"]
    assert {p["api_name"]: p["type_classes"] for p in exported["properties"]} == {
        "name": [], "picture": ["hubble:icon"]}
    # An untouched export plans nothing; a copy under a new name lands with them.
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": document})
    assert f"part_{tag}" in r.json()["sections"]["object_types"]["unchanged"]
    fresh = uuid.uuid4().hex[:6]
    copied = {**copy.deepcopy(exported), "api_name": f"copy_{fresh}"}
    file = {**document, "object_types": [copied], "link_types": [], "action_types": []}
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub), json={"document": file})
    assert r.status_code == 200, r.text
    again = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [landed] = [t for t in again["object_types"] if t["api_name"] == f"copy_{fresh}"]
    assert {p["api_name"]: p["type_classes"] for p in landed["properties"]}["picture"] == ["hubble:icon"]


# ---- §730: link types and action types (p.235) -------------------------------
def _pair(client, fx, tag: str) -> tuple[str, str]:
    ids = []
    for side in ("hub", "spoke"):
        r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
            "api_name": f"{side}_{tag}", "display_name": f"{side} {tag}", "title_property": "name",
            "properties": [{"api_name": "name", "data_type": "string"}]})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    return ids[0], ids[1]


def test_a_link_type_carries_type_classes(client, fx) -> None:
    """p.235: "Type classes can be applied to properties, link types, and
    action types." p.237's `hierarchy:parent` is one a link takes."""
    tag = uuid.uuid4().hex[:6]
    hub, spoke = _pair(client, fx, tag)
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"parent_{tag}", "display_name": "Parent", "from_type_id": spoke,
        "to_type_id": hub, "cardinality": "one_to_many",
        "type_classes": [" hierarchy:parent ", "hierarchy:parent"]})
    assert r.status_code == 201, r.text
    link = r.json()
    assert link["type_classes"] == ["hierarchy:parent"]
    url = f"{wbase(fx)}/link-types/{link['id']}"
    # An edit that does not mention them keeps them; one that does replaces.
    assert client.patch(url, headers=hdr(fx.editor_sub), json={"to_side_name": "Children"}
                        ).json()["type_classes"] == ["hierarchy:parent"]
    assert client.patch(url, headers=hdr(fx.editor_sub), json={"type_classes": ["team:x"]}
                        ).json()["type_classes"] == ["team:x"]
    assert client.patch(url, headers=hdr(fx.editor_sub), json={"type_classes": []}
                        ).json()["type_classes"] == []
    r = client.patch(url, headers=hdr(fx.editor_sub), json={"type_classes": ["parent"]})
    assert r.status_code == 422 and "kind:name" in r.text, r.text


def test_an_action_type_carries_type_classes(client, fx) -> None:
    """p.239's `actions:generate_uuid` and its neighbours are classes an
    action type takes; written beside its name (p.7's Overview)."""
    tag = uuid.uuid4().hex[:6]
    hub, _ = _pair(client, fx, tag)
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": hub, "api_name": f"edit_{tag}", "display_name": "Edit",
        "editable_properties": ["name"]})
    assert r.status_code == 201, r.text
    action = r.json()
    assert action["type_classes"] == []
    url = f"{wbase(fx)}/action-types/{action['id']}"
    got = client.patch(url, headers=hdr(fx.editor_sub),
                       json={"type_classes": ["actions:generate_uuid", "hubble-oe:hide-action"]})
    assert got.status_code == 200, got.text
    assert got.json()["type_classes"] == ["actions:generate_uuid", "hubble-oe:hide-action"]
    # Kept by a rename, as the rename keeps the description.
    assert client.patch(url, headers=hdr(fx.editor_sub), json={"display_name": "Edit it"}
                        ).json()["type_classes"] == ["actions:generate_uuid", "hubble-oe:hide-action"]
    r = client.patch(url, headers=hdr(fx.editor_sub), json={"type_classes": ["a:b:c"]})
    assert r.status_code == 422 and "kind:name" in r.text, r.text


def test_link_and_action_classes_travel_through_an_export_and_an_older_file_keeps_them(
    client, fx,
) -> None:
    tag = uuid.uuid4().hex[:6]
    hub, spoke = _pair(client, fx, tag)
    link = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"tie_{tag}", "display_name": "Tie", "from_type_id": spoke,
        "to_type_id": hub, "cardinality": "one_to_many", "type_classes": ["hierarchy:parent"]}
    ).json()
    action = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": hub, "api_name": f"poke_{tag}", "display_name": "Poke",
        "editable_properties": ["name"]}).json()
    client.patch(f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.editor_sub),
                 json={"type_classes": ["actions:prefill_current_user"]})
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported_link] = [lt for lt in document["link_types"] if lt["api_name"] == f"tie_{tag}"]
    [exported_action] = [a for a in document["action_types"] if a["api_name"] == f"poke_{tag}"]
    assert exported_link["type_classes"] == ["hierarchy:parent"]
    assert exported_action["type_classes"] == ["actions:prefill_current_user"]
    # A file from before db 0141 names none, and planning it changes nothing.
    older = copy.deepcopy(document)
    for row in older["link_types"] + older["action_types"]:
        row.pop("type_classes", None)
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": older})
    assert f"tie_{tag}" in r.json()["sections"]["link_types"]["unchanged"], r.json()
    assert any(k.endswith(f"poke_{tag}") for k in r.json()["sections"]["action_types"]["unchanged"])
    # A file that changes them is applied, and they land.
    newer = copy.deepcopy(document)
    for row in newer["link_types"]:
        if row["api_name"] == f"tie_{tag}":
            row["type_classes"] = ["team:links"]
    for row in newer["action_types"]:
        if row["api_name"] == f"poke_{tag}":
            row["type_classes"] = ["team:actions"]
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": newer})
    assert r.status_code == 200, r.text
    links = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub)).json()
    assert next(lt for lt in links if lt["id"] == link["id"])["type_classes"] == ["team:links"]
    # An action the import creates lands with its classes too.
    fresh = uuid.uuid4().hex[:6]
    [source] = [a for a in document["action_types"] if a["api_name"] == f"poke_{tag}"]
    copied = {**copy.deepcopy(source), "api_name": f"copy_{fresh}"}
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": {**document, "link_types": [], "action_types": [copied],
                                       "object_types": [t for t in document["object_types"]
                                                        if t["api_name"] == f"hub_{tag}"]}})
    assert r.status_code == 200, r.text
    actions = client.get(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub)).json()
    assert next(a for a in actions if a["api_name"] == f"copy_{fresh}")["type_classes"] == [
        "actions:prefill_current_user"]
    assert client.get(f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.editor_sub)
                      ).json()["type_classes"] == ["team:actions"]
