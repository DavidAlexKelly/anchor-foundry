"""A property's render hints (§724; `object-link-types` p.248-252; db 0140).

> "Foundry uses render hints to communicate information about the use of
> Ontology properties to Object Storage v1 (Phonograph) and user applications
> in the platform." (p.248)

The list and its one rule are `render_hints.py`'s; what this file holds to is
that the hints are kept everywhere a property is - a save, a restore, an
export and an import - that a property which never heard of them keeps doing
what it did, and that a shared property's override an attached property's
(p.188).
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
from src.services import render_hints  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


DEFAULT = ["selectable", "sortable", "searchable"]


def test_the_table_s_names_in_its_order_and_the_default() -> None:
    assert render_hints.parse(None, property_name="p") == DEFAULT
    assert render_hints.parse([], property_name="p") == []
    # The table's order whatever order they were sent in, and each once.
    assert render_hints.parse(["searchable", "keywords", "identifier", "keywords"],
                              property_name="p") == ["identifier", "keywords", "searchable"]
    assert list(render_hints.HINTS) == [
        "disable_formatting", "identifier", "keywords", "long_text", "low_cardinality",
        "selectable", "sortable", "searchable", "leading_wildcards", "regex"]
    with pytest.raises(ValueError, match="no render hint named 'fast'"):
        render_hints.parse(["fast"], property_name="p")
    for bad in ("searchable", [1]):
        with pytest.raises(ValueError, match="must be a list"):
            render_hints.parse(bad, property_name="p")


@pytest.mark.parametrize("hint", list(render_hints.NEEDS_SEARCHABLE))
def test_each_dependent_hint_needs_searchable(hint: str) -> None:
    """p.250-251: "The Searchable render hint must also be selected along
    with" each of these."""
    with pytest.raises(ValueError, match="needs Searchable"):
        render_hints.parse([hint], property_name="p")
    both = render_hints.parse([hint, "searchable"], property_name="p")
    assert both == [h for h in render_hints.HINTS if h in (hint, "searchable")]


def test_hints_that_need_nothing_stand_alone() -> None:
    standalone = [h for h in render_hints.HINTS
                  if h not in render_hints.NEEDS_SEARCHABLE and h != "searchable"]
    assert standalone == ["disable_formatting", "identifier", "keywords", "long_text"]
    assert render_hints.parse(standalone, property_name="p") == standalone
    with pytest.raises(ValueError, match="Selectable, Sortable need Searchable"):
        render_hints.parse(["selectable", "sortable"], property_name="p")


def new_type(client, fx, tag: str, hints=None) -> dict:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"note_{tag}", "display_name": f"Note {tag}", "title_property": "name",
        "properties": [
            {"api_name": "name", "display_name": "Name", "data_type": "string"},
            {"api_name": "body", "display_name": "Body", "data_type": "string",
             **({"render_hints": hints} if hints is not None else {})}]})
    assert r.status_code == 201, r.text
    return r.json()


def hints_of(client, fx, kind: dict) -> dict:
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    return {p["api_name"]: p["render_hints"] for p in got["properties"]}


def saved(client, fx, kind: dict, hints, field: str = "body"):
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    props = [{k: p.get(k) for k in ("api_name", "display_name", "data_type")}
             | ({"render_hints": hints} if p["api_name"] == field else {})
             for p in got["properties"]]
    return client.patch(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub),
                        json={"display_name": got["display_name"], "properties": props,
                              "title_property": "name"})


def test_a_property_that_names_none_is_searched_aggregated_and_sorted(client, fx) -> None:
    """db 0140's default: p.182's "you can deselect the searchable and sortable
    render hints" is a property that starts with them."""
    kind = new_type(client, fx, uuid.uuid4().hex[:6])
    assert hints_of(client, fx, kind) == {"name": DEFAULT, "body": DEFAULT}


def test_a_property_keeps_its_hints_through_a_save(client, fx) -> None:
    kind = new_type(client, fx, uuid.uuid4().hex[:6], ["long_text", "searchable"])
    assert hints_of(client, fx, kind)["body"] == ["long_text", "searchable"]
    # A save that sends them keeps them; none at all is a property with none.
    assert saved(client, fx, kind, ["keywords"]).status_code == 200
    assert hints_of(client, fx, kind)["body"] == ["keywords"]
    assert saved(client, fx, kind, []).status_code == 200
    assert hints_of(client, fx, kind)["body"] == []


def test_a_dependent_hint_without_searchable_is_refused_by_its_property(client, fx) -> None:
    kind = new_type(client, fx, uuid.uuid4().hex[:6])
    r = saved(client, fx, kind, ["sortable"])
    assert r.status_code == 422, r.text
    assert "'body'" in r.json()["detail"] and "needs Searchable" in r.json()["detail"]


def test_a_restore_an_export_and_an_import_keep_them(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    kind = new_type(client, fx, tag, ["identifier", "searchable"])
    versions = client.get(f"{wbase(fx)}/object-types/{kind['id']}/versions",
                          headers=hdr(fx.editor_sub)).json()
    with_them = max(v["version_number"] for v in versions)
    assert saved(client, fx, kind, DEFAULT).status_code == 200
    r = client.post(f"{wbase(fx)}/object-types/{kind['id']}/versions/{with_them}/restore",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    assert hints_of(client, fx, kind)["body"] == ["identifier", "searchable"]

    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [t for t in document["object_types"] if t["api_name"] == f"note_{tag}"]
    assert {p["api_name"]: p["render_hints"] for p in exported["properties"]} == {
        "name": DEFAULT, "body": ["identifier", "searchable"]}
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": document})
    assert f"note_{tag}" in r.json()["sections"]["object_types"]["unchanged"]
    fresh = uuid.uuid4().hex[:6]
    copied = {**copy.deepcopy(exported), "api_name": f"copy_{fresh}"}
    file = {**document, "object_types": [copied], "link_types": [], "action_types": []}
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert r.status_code == 200, r.text
    again = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [landed] = [t for t in again["object_types"] if t["api_name"] == f"copy_{fresh}"]
    assert {p["api_name"]: p["render_hints"] for p in landed["properties"]}["body"] == [
        "identifier", "searchable"]


def test_a_file_from_before_hints_keeps_the_workspace_s(client, fx) -> None:
    """A file exported before db 0140 names no hints. Reading that as the
    default would turn back on a hint somebody had turned off - so planning
    it changes nothing and applying it keeps what the workspace has."""
    tag = uuid.uuid4().hex[:6]
    kind = new_type(client, fx, tag, ["long_text"])
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [t for t in document["object_types"] if t["api_name"] == f"note_{tag}"]
    older = copy.deepcopy(exported)
    for prop in older["properties"]:
        del prop["render_hints"]
    file = {**document, "object_types": [older], "link_types": [], "action_types": []}
    r = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert f"note_{tag}" in r.json()["sections"]["object_types"]["unchanged"], r.json()
    # Changed in some other way, so it is applied - and the hints stay.
    older["description"] = "Edited in the file"
    r = client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                    json={"document": file})
    assert r.status_code == 200, r.text
    assert hints_of(client, fx, kind)["body"] == ["long_text"]


# ---- a shared property's (p.182, p.188) -------------------------------------
def make_shared(client, fx, **over) -> dict:
    r = client.post(f"{wbase(fx)}/shared-properties", headers=hdr(fx.editor_sub), json={
        "api_name": f"body_{uuid.uuid4().hex[:6]}", "display_name": "Body",
        "data_type": "string", **over})
    assert r.status_code == 201, r.text
    return r.json()


def test_a_shared_property_s_hints_override_the_property_s(client, fx) -> None:
    """p.188: "If the shared property you use has different render hint
    configuration values than the selected property, using the shared property
    will override the configuration values of the selected property." """
    shared = make_shared(client, fx, render_hints=["long_text", "searchable"])
    assert shared["render_hints"] == ["long_text", "searchable"]
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"memo_{tag}", "display_name": f"Memo {tag}", "title_property": "name",
        "properties": [
            {"api_name": "name", "data_type": "string"},
            {"api_name": "body", "data_type": "string", "shared_property_id": shared["id"],
             "render_hints": ["keywords"]}]})
    assert r.status_code == 201, r.text
    kind = r.json()
    assert hints_of(client, fx, kind)["body"] == ["long_text", "searchable"]
    # Edited in one place, seen everywhere (p.178).
    r = client.patch(f"{wbase(fx)}/shared-properties/{shared['id']}",
                     headers=hdr(fx.editor_sub),
                     json={"display_name": "Body", "data_type": "string",
                           "render_hints": ["keywords"]})
    assert r.status_code == 200, r.text
    assert hints_of(client, fx, kind)["body"] == ["keywords"]
    # And, like the other inherited fields, not edited on the property.
    got = client.get(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub)).json()
    props = [{k: p.get(k) for k in ("api_name", "display_name", "data_type",
                                    "shared_property_id", "description", "visibility")}
             for p in got["properties"]]

    def send(extra: dict):
        body = [{**p, **(extra if p["api_name"] == "body" else {})} for p in props]
        return client.patch(f"{wbase(fx)}/object-types/{kind['id']}", headers=hdr(fx.editor_sub),
                            json={"display_name": got["display_name"], "properties": body,
                                  "title_property": "name"})

    r = send({"render_hints": DEFAULT})
    assert r.status_code == 422 and "render_hints is inherited" in r.text, r.text
    # What it read is accepted back, and none at all is not an edit.
    assert send({"render_hints": ["keywords"]}).status_code == 200
    r = send({})
    assert r.status_code == 200, r.text
    assert hints_of(client, fx, kind)["body"] == ["keywords"]


def test_a_shared_property_s_hints_follow_the_same_rule(client, fx) -> None:
    r = client.post(f"{wbase(fx)}/shared-properties", headers=hdr(fx.editor_sub), json={
        "api_name": f"bad_{uuid.uuid4().hex[:6]}", "display_name": "Bad",
        "data_type": "string", "render_hints": ["regex"]})
    assert r.status_code == 422 and "needs Searchable" in r.text, r.text
    assert make_shared(client, fx)["render_hints"] == DEFAULT
    # Left out of an edit, they are kept - from something other than the
    # default, or keeping and resetting would look the same.
    shared = make_shared(client, fx, render_hints=["keywords"])
    r = client.patch(f"{wbase(fx)}/shared-properties/{shared['id']}",
                     headers=hdr(fx.editor_sub),
                     json={"display_name": "Renamed", "data_type": "string"})
    assert r.json()["render_hints"] == ["keywords"]
