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
