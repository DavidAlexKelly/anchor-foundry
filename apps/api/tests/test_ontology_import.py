"""Importing an ontology from JSON (§326; `ontology-manager` p.65-67).

    "Next, select Import, which will recreate the entire working state from the
     JSON file in the application. **You will see the number of changes made in
     the file that need to be saved** in the application header." (p.66)

**The test that matters most is the one that expects nothing to happen.** A
straight re-import of an unedited export must plan zero changes — that is what
says the exporter and the importer agree about what an ontology *is*. A planner
counting every named thing would pass every other test in this file and report
a whole ontology as work to do.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import ontology_import as importer  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("import-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def export(client: TestClient, fx: Fixture) -> dict:
    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def plan(client: TestClient, fx: Fixture, document: dict):
    return client.post(f"{wbase(fx)}/ontology-import/plan",
                       headers=hdr(fx.editor_sub), json={"document": document})


def apply(client: TestClient, fx: Fixture, document: dict):
    return client.post(f"{wbase(fx)}/ontology-import",
                       headers=hdr(fx.editor_sub), json={"document": document})


def one_type(tag: str, **over) -> dict:
    return {
        "api_name": f"imp_{tag}",
        "display_name": f"Imported {tag}",
        "description": "",
        "icon": "cube",
        "colour": "#4f46e5",
        "status": "experimental",
        "deprecation": None,
        "visibility": "normal",
        "title_property": "name",
        "properties": [
            {"api_name": "name", "display_name": "Name", "data_type": "string",
             "required": True, "description": "", "sort_order": 0,
             "visibility": "normal", "value_format": None,
             "conditional_format": None, "edit_only": False,
             "derivation": None, "struct_fields": None,
             "status": "experimental", "deprecation": None},
        ],
        **over,
    }


def a_file(fx: Fixture, *types: dict, origin: dict | None = None) -> dict:
    return {
        "format_version": importer.FORMAT_VERSION,
        "workspace": origin or {"id": str(fx.workspace), "slug": "x", "name": "X"},
        "object_types": list(types),
        "link_types": [],
        "action_types": [],
    }


# ---- what the file has to look like -------------------------------------------
def test_a_file_from_another_version_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.65: "You should not depend on the exported JSON schema as it may
    change over time."

    So a file has to say which shape it is, and one from a shape this platform
    does not read is refused with both numbers — a person editing JSON in a
    text editor can act on "yours says 99, I read 1" and cannot act on "invalid
    file".
    """
    document = a_file(fx)
    document["format_version"] = 99
    r = plan(client, fx, document)
    assert r.status_code == 422, r.text
    assert "99" in r.text and str(importer.FORMAT_VERSION) in r.text


def test_a_file_missing_a_section_is_refused_by_shape(
    client: TestClient, fx: Fixture
) -> None:
    """**Refused by shape, not by what happens when it is used.** A document
    without `link_types` would otherwise fail deep in the planner with a
    `KeyError`, which tells the person who edited the JSON nothing."""
    document = a_file(fx)
    del document["link_types"]
    r = plan(client, fx, document)
    assert r.status_code == 422, r.text
    assert "link_types" in r.text


def test_a_title_property_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """Every name the file uses must be a name the file defines."""
    kind = one_type(uuid.uuid4().hex[:8], title_property="nonexistent")
    r = plan(client, fx, a_file(fx, kind))
    assert r.status_code == 422, r.text
    assert "nonexistent" in r.text


def test_formatting_on_a_property_the_file_does_not_carry_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """**p.67's problem in the shape it takes here.**

        "An exported Ontology working state with conditional formatting rules
         configured on its properties cannot be imported to an Ontology other
         than the one it was exported from." (p.67)

    Foundry refuses because its formatting references rule sets defined outside
    the ontology. This platform's is inline and names sibling properties, so
    there is no external rule set to be missing — but a rule naming a property
    the file does not carry is the same failure, and it is one this file can
    actually contain.
    """
    tag = uuid.uuid4().hex[:8]
    kind = one_type(tag)
    kind["properties"][0]["conditional_format"] = [
        {"kind": "standard", "property": "gone", "comparison": "string",
         "operator": "is_exactly", "value": "x", "colour": "#b91c1c"},
    ]
    r = plan(client, fx, a_file(fx, kind))
    assert r.status_code == 422, r.text
    assert "gone" in r.text


def test_an_action_on_a_type_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """The same rule for the third kind of reference.

    Checked separately from the link above rather than assumed to follow from
    it: they are three loops over three sections, and a sweep found this one
    was the section nothing exercised.
    """
    document = a_file(fx, one_type(uuid.uuid4().hex[:8]))
    document["action_types"] = [
        {"api_name": "orphan", "display_name": "Orphan",
         "object_type": "no_such_type", "parameters": [], "rules": [],
         "criteria": []},
    ]
    r = plan(client, fx, document)
    assert r.status_code == 422, r.text
    assert "no_such_type" in r.text


def test_a_link_joining_a_type_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    document = a_file(fx, one_type(uuid.uuid4().hex[:8]))
    document["link_types"] = [
        {"api_name": "dangling", "display_name": "Dangling",
         "from_object_type": "missing_one", "to_object_type": "missing_two",
         "cardinality": "one_to_many"},
    ]
    r = plan(client, fx, document)
    assert r.status_code == 422, r.text
    assert "missing_one" in r.text


def test_nothing_is_written_by_a_refused_plan(
    client: TestClient, fx: Fixture
) -> None:
    """Checked before anything is applied, which is p.138's rule about batches
    applied to a file: a half-imported ontology is worse than a refused one."""
    tag = uuid.uuid4().hex[:8]
    kind = one_type(tag, title_property="nonexistent")
    assert apply(client, fx, a_file(fx, kind)).status_code == 422
    listed = client.get(f"{wbase(fx)}/object-types?q=imp_{tag}",
                        headers=hdr(fx.editor_sub)).json()
    assert listed["items"] == [], listed


# ---- p.66's count -------------------------------------------------------------
def test_re_importing_an_untouched_export_plans_no_changes(
    client: TestClient, fx: Fixture
) -> None:
    """**The test this whole file exists for**, and the one that was vacuous.

    p.66's screen shows "the number of changes made in the file that need to be
    saved", so a file nobody edited must show none. That is also the only
    assertion saying the exporter and the importer agree about what an ontology
    *is*: a planner counting every named thing would pass every other test here
    and report the whole ontology as work to do, and an exporter that dropped a
    field would show it as a change on every re-import.

    **It checked none of that for its first hour alive.** `Fixture()` makes a
    fresh workspace, so the export was an empty document and "no changes" was
    true because there was nothing to change. The mutation sweep found it: a
    planner calling every common name "changed" survived, because there were no
    common names. So the ontology is built here first, and asserted non-empty
    before the claim is made.
    """
    tag = uuid.uuid4().hex[:8]
    built = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"rt_{tag}", "display_name": f"Round trip {tag}",
              "description": "Something to round-trip",
              "properties": [
                  {"api_name": "name", "display_name": "Name",
                   "data_type": "string", "required": True},
                  {"api_name": "score", "display_name": "Score",
                   "data_type": "integer",
                   "conditional_format": [
                       {"kind": "standard", "property": "score",
                        "comparison": "numeric_range", "max": 3,
                        "colour": "#b91c1c"}]},
              ],
              "title_property": "name"},
    )
    assert built.status_code == 201, built.text
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": built.json()["id"], "api_name": f"edit_{tag}",
              "display_name": "Edit", "editable_properties": ["name"]},
    )
    assert action.status_code == 201, action.text

    document = export(client, fx)
    # **The guard that makes the assertion below mean something.** Without it
    # this is a statement about an empty file.
    assert document["object_types"], "nothing to round-trip"
    assert document["action_types"], "nothing to round-trip"

    r = plan(client, fx, document)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changes"] == 0, {
        section: {k: v for k, v in counts.items() if k != "unchanged"}
        for section, counts in body["sections"].items()
    }
    # And every one of them was *seen* rather than missed: `unchanged` is what
    # separates "nothing differs" from "nothing was compared".
    assert f"rt_{tag}" in body["sections"]["object_types"]["unchanged"]
    # Qualified by its object type (§341), because an action's api_name is
    # unique per *type* rather than per workspace.
    assert f"rt_{tag}.edit_{tag}" in body["sections"]["action_types"]["unchanged"]
    assert body["is_round_trip"] is True


def test_a_new_type_in_the_file_is_one_change(
    client: TestClient, fx: Fixture
) -> None:
    document = export(client, fx)
    tag = uuid.uuid4().hex[:8]
    document["object_types"].append(one_type(tag))
    body = plan(client, fx, document).json()
    assert body["changes"] == 1, body["sections"]["object_types"]
    assert body["sections"]["object_types"]["added"] == [f"imp_{tag}"]


def test_an_edited_type_is_a_change_rather_than_an_addition(
    client: TestClient, fx: Fixture
) -> None:
    """The distinction p.66's count rests on: "changed" means *differs*, not
    *mentioned*."""
    tag = uuid.uuid4().hex[:8]
    assert apply(client, fx, a_file(fx, one_type(tag))).status_code == 200

    document = export(client, fx)
    mine = next(t for t in document["object_types"] if t["api_name"] == f"imp_{tag}")
    mine["display_name"] = "Renamed by hand"
    body = plan(client, fx, document).json()
    assert body["sections"]["object_types"]["changed"] == [f"imp_{tag}"]
    assert f"imp_{tag}" not in body["sections"]["object_types"]["added"]


def test_a_type_the_file_leaves_out_is_named_but_not_removed(
    client: TestClient, fx: Fixture
) -> None:
    """**"Recreate the entire working state" stops short of deleting here**, and
    that is a stated divergence rather than an oversight.

    Deleting an object type deletes its objects, immediately and with no
    review — which is the one thing Foundry's staging exists to prevent. So the
    plan names what the file leaves out and §325's cleanup queue is where a
    deletion is decided. An importer that quietly removed them would be a
    file-shaped delete button.
    """
    tag = uuid.uuid4().hex[:8]
    assert apply(client, fx, a_file(fx, one_type(tag))).status_code == 200

    document = export(client, fx)
    document["object_types"] = [
        t for t in document["object_types"] if t["api_name"] != f"imp_{tag}"
    ]
    body = plan(client, fx, document).json()
    assert f"imp_{tag}" in body["sections"]["object_types"]["absent_from_file"]

    applied = apply(client, fx, document)
    assert applied.status_code == 200, applied.text
    assert f"imp_{tag}" in applied.json()["absent_from_file"]
    # Still there: named is not removed.
    listed = client.get(f"{wbase(fx)}/object-types?q=imp_{tag}",
                        headers=hdr(fx.editor_sub)).json()
    assert [t["api_name"] for t in listed["items"]] == [f"imp_{tag}"]


def test_a_file_from_another_workspace_is_not_a_round_trip(
    client: TestClient, fx: Fixture
) -> None:
    """p.65's two workflows, told apart by the one fact the file carries about
    its origin.

    "Nothing changed" is reassuring for an edit-and-put-back and suspicious for
    a copy into a fresh ontology, so the plan says which it is looking at rather
    than leaving the reader to compare two uuids by eye.
    """
    document = export(client, fx)
    document["workspace"] = {"id": str(uuid.uuid4()), "slug": "elsewhere",
                             "name": "Elsewhere"}
    body = plan(client, fx, document).json()
    assert body["is_round_trip"] is False
    assert body["from_workspace"]["slug"] == "elsewhere"


# ---- applying -----------------------------------------------------------------
def test_applying_creates_the_type_the_file_describes(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:8]
    r = apply(client, fx, a_file(fx, one_type(tag)))
    assert r.status_code == 200, r.text
    assert r.json()["added"] == [f"imp_{tag}"]

    listed = client.get(f"{wbase(fx)}/object-types?q=imp_{tag}",
                        headers=hdr(fx.editor_sub)).json()
    assert [t["api_name"] for t in listed["items"]] == [f"imp_{tag}"]


def test_applying_twice_changes_nothing_the_second_time(
    client: TestClient, fx: Fixture
) -> None:
    """An import is a description of a state, so applying it to a workspace
    already in that state is not work. Without this, "apply creates the type"
    is satisfied by an importer that recreates everything on every run — which
    would rewrite every type's version history for a file nobody edited."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    assert apply(client, fx, document).status_code == 200

    again = apply(client, fx, document)
    assert again.status_code == 200, again.text
    assert again.json()["added"] == []
    assert again.json()["updated"] == []


def test_applying_an_edit_updates_the_type(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:8]
    assert apply(client, fx, a_file(fx, one_type(tag))).status_code == 200

    renamed = one_type(tag, display_name="Renamed in the file")
    r = apply(client, fx, a_file(fx, renamed))
    assert r.status_code == 200, r.text
    assert r.json()["updated"] == [f"imp_{tag}"]

    listed = client.get(f"{wbase(fx)}/object-types?q=imp_{tag}",
                        headers=hdr(fx.editor_sub)).json()
    assert listed["items"][0]["display_name"] == "Renamed in the file"


def test_an_action_in_the_file_is_applied(
    client: TestClient, fx: Fixture
) -> None:
    """p.65's action types, written rather than named (§344).

    They were reported as not applied from §326 to §343 — the wait was the
    resolution pass, because an action's parameters and rules name object types
    and link types by id and the file names them by name.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [
        {"api_name": f"act_{tag}", "display_name": "Act",
         "object_type": f"imp_{tag}", "criteria": [],
         "parameters": [{"api_name": "name", "display_name": "Name",
                         "data_type": "string"}],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "name", "parameter": "name"}}]},
    ]
    r = apply(client, fx, document)
    assert r.status_code == 200, r.text
    # **Named by the object type it is on as well as its own name** (§341):
    # `action_types` is unique on (object_type_id, api_name), so a bare name
    # does not identify an action in an ontology that has two of them.
    assert r.json()["actions_added"] == [f"imp_{tag}.act_{tag}"]
    # Checked in the ontology rather than in the report, because the report is
    # the thing that just told you it worked.
    assert an_action(client, fx, tag)["parameters"][0]["api_name"] == "name"


def an_action(client: TestClient, fx: Fixture, tag: str) -> dict:
    listed = client.get(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub))
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    found = next(a for a in (rows["items"] if isinstance(rows, dict) else rows)
                 if a["api_name"] == f"act_{tag}")
    full = client.get(f"{wbase(fx)}/action-types/{found['id']}",
                      headers=hdr(fx.editor_sub))
    assert full.status_code == 200, full.text
    return full.json()


def test_two_actions_sharing_a_name_are_told_apart(
    client: TestClient, fx: Fixture
) -> None:
    """**An action's api_name is not unique in an ontology** (§341).

    `action_types` is unique on (object_type_id, api_name), so `same_name` on
    one type and `same_name` on another are two different actions with one
    name. Keyed by the name alone, a straight round trip reports one of them as
    *changed* — the planner compared an action against the other action — and
    the day the import applies actions it would apply the wrong one.

    Found by a browser test whose workspace happened to hold two, which is why
    this test builds that state on purpose: on a clean database nothing
    collides and the distinction is invisible.
    """
    tag = uuid.uuid4().hex[:8]
    for suffix in ("a", "b"):
        made = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"dup_{tag}{suffix}",
                  "display_name": f"Dup {tag}{suffix}",
                  "properties": [{"api_name": "name", "display_name": "Name",
                                  "data_type": "string"}]},
        )
        assert made.status_code == 201, made.text
        act = client.post(
            f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
            json={"object_type_id": made.json()["id"],
                  "api_name": f"same_{tag}", "display_name": f"Same {suffix}",
                  "editable_properties": ["name"]},
        )
        assert act.status_code == 201, act.text

    document = export(client, fx)
    body = plan(client, fx, document).json()
    # Both are there, told apart, and neither is a change.
    unchanged = body["sections"]["action_types"]["unchanged"]
    assert f"dup_{tag}a.same_{tag}" in unchanged
    assert f"dup_{tag}b.same_{tag}" in unchanged
    assert body["sections"]["action_types"]["changed"] == []


# ---- applying an action type (§344) ---------------------------------------------
def a_configured_ontology(client: TestClient, fx: Fixture, tag: str) -> dict:
    """One action with every feature §328-§343 gave a parameter, built through
    the API so the workspace holds what a real one would.

    Nothing here is incidental: the type a parameter holds, the set a
    multiple-choice one reads, the walk that reaches it, the filters that narrow
    it, the section the form puts it in, the override that changes it and the
    rule that writes a link are each a field some pass has to carry, and a
    fixture missing one asks its question of an absent value (§341's lesson,
    three times over).
    """
    near = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"near_{tag}", "display_name": "Near",
              "properties": [{"api_name": "name", "display_name": "Name",
                              "data_type": "string", "required": True}],
              "title_property": "name"})
    assert near.status_code == 201, near.text
    far = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"far_{tag}", "display_name": "Far",
              "properties": [
                  {"api_name": "name", "display_name": "Name",
                   "data_type": "string"},
                  {"api_name": "near_id", "display_name": "Near",
                   "data_type": "string"}],
              "title_property": "name"})
    assert far.status_code == 201, far.text
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"joins_{tag}", "display_name": "Joins",
              "from_type_id": far.json()["id"], "to_type_id": near.json()["id"],
              "cardinality": "one_to_many",
              "from_property": "near_id", "to_property": "$primary_key"})
    assert link.status_code == 201, link.text
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": near.json()["id"], "api_name": f"act_{tag}",
              "display_name": "Act", "editable_properties": ["name"]})
    assert action.status_code == 201, action.text
    saved = client.put(
        f"{wbase(fx)}/action-types/{action.json()['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  # **A real default, not an absent one.** A sweep found the
                  # round trip below could drop `default_value` and still be
                  # equal, because no parameter here had one — §341's mistake,
                  # for the fourth time across these units.
                  {"api_name": "tier", "display_name": "Tier",
                   "data_type": "string", "default_value": "bronze"},
                  {"api_name": "who", "display_name": "Who",
                   "data_type": "object", "object_type_id": near.json()["id"],
                   "dropdown_filters": [
                       {"property": "name",
                        "values": [{"kind": "value", "value": "keep"}]}]},
                  {"api_name": "name", "display_name": "Name",
                   "data_type": "string",
                   "options_from": {"object_type_id": far.json()["id"],
                                    "property": "name"},
                   "dropdown_search_around": {
                       "start": {"kind": "parameter",
                                 "object_type_id": near.json()["id"],
                                 "parameter": "who"},
                       "hops": [{"link_type_id": link.json()["id"]}]},
                   "overrides": [
                       {"set_default": "see the ticket", "set_required": True,
                        "conditions": [{
                            "left": {"kind": "parameter", "parameter": "tier"},
                            "operator": "is",
                            "right": {"kind": "value", "value": "gold"}}]}]},
              ],
              "rules": [
                  {"kind": "modify_object",
                   "config": {"property": "name", "parameter": "name"}},
                  {"kind": "create_link",
                   "config": {"link_type": link.json()["id"],
                              "object": "who"}},
              ],
              "criteria": [
                  {"message": "Only gold tiers may rename",
                   "config": {"operator": "is",
                              "left": {"kind": "parameter", "parameter": "tier"},
                              "right": {"kind": "value", "value": "gold"}}}]})
    assert saved.status_code == 200, saved.text
    sectioned = client.put(
        f"{wbase(fx)}/action-types/{action.json()['id']}/sections",
        headers=hdr(fx.editor_sub),
        json={"sections": [{"title": "Why", "description": "What changed",
                            "parameters": ["name"]}]})
    assert sectioned.status_code == 200, sectioned.text
    return {"action_id": action.json()["id"], "link_id": link.json()["id"]}


def the_action(document: dict, tag: str) -> dict:
    return next(a for a in document["action_types"]
                if a["api_name"] == f"act_{tag}")


def test_a_deleted_action_comes_back_exactly_as_it_left(
    client: TestClient, fx: Fixture
) -> None:
    """**The test §344 exists for.** Export a fully configured action, delete
    it, import the file, and the document the workspace produces is the document
    it was given.

    Equality over the whole action sub-document, not a field list: a writer that
    dropped the walk, or the filters, or the section membership, or the second
    rule would pass any assertion naming the fields somebody remembered. The
    document is id-free (§326, §342, §343), so it compares across two different
    rows of the same action — which is the only reason this can be an `==`.
    """
    tag = uuid.uuid4().hex[:8]
    built = a_configured_ontology(client, fx, tag)
    before = the_action(export(client, fx), tag)

    gone = client.delete(f"{wbase(fx)}/action-types/{built['action_id']}",
                         headers=hdr(fx.editor_sub))
    assert gone.status_code in (200, 204), gone.text

    document = export(client, fx)
    document["action_types"].append(before)
    applied = apply(client, fx, document)
    assert applied.status_code == 200, applied.text
    assert applied.json()["actions_added"] == [f"near_{tag}.act_{tag}"]

    assert the_action(export(client, fx), tag) == before


def test_re_importing_a_configured_action_plans_no_changes(
    client: TestClient, fx: Fixture
) -> None:
    """**Idempotence, which is the other half of the claim above.** The first
    import can be right about every field and still be a change every time, if
    apply and export disagree about anything — and a reader pressing Apply twice
    is exactly what p.66's screen invites."""
    tag = uuid.uuid4().hex[:8]
    a_configured_ontology(client, fx, tag)
    document = export(client, fx)
    assert the_action(document, tag)["parameters"], "nothing to round-trip"

    applied = apply(client, fx, document)
    assert applied.status_code == 200, applied.text
    body = plan(client, fx, export(client, fx)).json()
    assert f"near_{tag}.act_{tag}" in body["sections"]["action_types"]["unchanged"]
    assert body["sections"]["action_types"]["changed"] == []


def test_an_edited_action_is_updated_rather_than_duplicated(
    client: TestClient, fx: Fixture
) -> None:
    """`action_types` is unique on (object_type_id, api_name), so a second
    insert would be refused outright — which means a pass that did not look for
    the existing row could not update an action at all."""
    tag = uuid.uuid4().hex[:8]
    a_configured_ontology(client, fx, tag)
    document = export(client, fx)
    the_action(document, tag)["display_name"] = "Renamed in the file"

    applied = apply(client, fx, document)
    assert applied.status_code == 200, applied.text
    assert applied.json()["actions_updated"] == [f"near_{tag}.act_{tag}"]
    assert applied.json()["actions_added"] == []
    assert the_action(export(client, fx), tag)["display_name"] \
        == "Renamed in the file"


def test_an_override_reading_a_parameter_the_file_puts_above_it(
    client: TestClient, fx: Fixture
) -> None:
    """**Why `set_definition` is handed the sections it is about to be given**
    (§344).

    p.45 lets an override read only the parameters above it "in the form
    hierarchy", and the hierarchy is §328's sections — which do not exist when a
    new action's definition is saved. Declared order here puts the reader first
    and the read second; the file's sections put them the other way round. So
    this action is legal where it was exported and, without the sections in
    hand, refused where it is imported.

    Measured before it was built: `check_references` accepts this document with
    the sections and refuses it without them.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [{
        "api_name": f"act_{tag}", "display_name": "Act",
        "object_type": f"imp_{tag}", "criteria": [], "rules": [],
        "parameters": [
            {"api_name": "note", "display_name": "Note", "data_type": "string",
             "overrides": [{"set_required": True, "conditions": [{
                 "left": {"kind": "parameter", "parameter": "tier"},
                 "operator": "is",
                 "right": {"kind": "value", "value": "gold"}}]}]},
            {"api_name": "why", "display_name": "Why", "data_type": "string"},
            {"api_name": "tier", "display_name": "Tier", "data_type": "string"},
        ],
        # **Three sections, and the middle one is the point.** With two, a
        # `form_order` that collapsed every id-less section onto one key still
        # happened to put `tier` above `note` — so the test passed over the
        # broken version and a sweep is what said so. Three is where the wrong
        # answer separates from the right one.
        "sections": [{"title": "First", "parameters": ["tier"]},
                     {"title": "Second", "parameters": ["why"]},
                     {"title": "Third", "parameters": ["note"]}],
    }]
    applied = apply(client, fx, document)
    assert applied.status_code == 200, applied.text
    # And the arrangement that made it legal is the one the workspace now has.
    found = an_action(client, fx, tag)
    sections = client.get(
        f"{wbase(fx)}/action-types/{found['id']}/sections",
        headers=hdr(fx.editor_sub)).json()
    assert [s["title"] for s in sections] == ["First", "Second", "Third"]
    assert sections[2]["parameters"] == ["note"]


def test_an_action_that_never_modifies_its_subject_is_applied(
    client: TestClient, fx: Fixture
) -> None:
    """**Why the import creates a shell rather than going through p.30's
    screen** (§344). `create_action_type` converts editable properties into
    parameters and `modify_object` rules, and `editable_properties_of` returns
    nothing for an action whose only rule creates an object — so that path
    refuses a perfectly legal action with "an action must make at least one
    property editable"."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [{
        "api_name": f"act_{tag}", "display_name": "Act",
        "object_type": f"imp_{tag}", "criteria": [], "sections": [],
        "parameters": [{"api_name": "name", "display_name": "Name",
                        "data_type": "string"}],
        "rules": [{"kind": "create_object",
                   "config": {"primary_key": "name",
                              "properties": {"name": "name"}}}],
    }]
    applied = apply(client, fx, document)
    assert applied.status_code == 200, applied.text
    assert [r["kind"] for r in an_action(client, fx, tag)["rules"]] \
        == ["create_object"]


def test_an_actions_status_travels(client: TestClient, fx: Fixture) -> None:
    """p.253's status and p.154's revert toggle are statements *about* the
    action rather than part of what it does, so they are written by their own
    call — and a pass that forgot them would import every action as
    `experimental` with revert on, silently."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [{
        "api_name": f"act_{tag}", "display_name": "Act",
        "object_type": f"imp_{tag}", "criteria": [], "sections": [],
        "status": "active", "allow_revert": False,
        "parameters": [{"api_name": "name", "display_name": "Name",
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "name", "parameter": "name"}}],
    }]
    assert apply(client, fx, document).status_code == 200
    found = an_action(client, fx, tag)
    assert found["status"] == "active"
    assert found["allow_revert"] is False


def test_a_rule_whose_link_the_file_dropped_is_refused_by_name(
    client: TestClient, fx: Fixture
) -> None:
    """§343 drops a reference this ontology cannot name rather than writing it
    as an id, and said the refusal would arrive "the day action types are
    applied". This is that day: `_validate_definition` names the field, which is
    the truth about the rule as it stands."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [{
        "api_name": f"act_{tag}", "display_name": "Act",
        "object_type": f"imp_{tag}", "criteria": [], "sections": [],
        "parameters": [{"api_name": "who", "display_name": "Who",
                        "data_type": "object"}],
        "rules": [{"kind": "create_link", "config": {"object": "who"}}],
    }]
    refused = apply(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "link type" in refused.text


@pytest.mark.parametrize("name", ["", "x" * 201])
@pytest.mark.parametrize("existing", [False, True])
def test_a_display_name_the_column_would_refuse_is_refused_by_name(
    client: TestClient, fx: Fixture, name: str, existing: bool
) -> None:
    """**p.65's premise is a hand-edited file**, and db 0013 checks
    `length(display_name) BETWEEN 1 AND 200` — which fires as an integrity
    error, a 500 with nothing in it about which field is wrong. Same shape as
    the 500 §340 shipped for a link's missing `cardinality`.

    Both paths and both ends of the range, because a sweep found the guard
    unreachable four ways at once: the route's own schema refuses these before
    the service sees them, so the import is the only caller that can reach it —
    and the first draft defaulted an empty name to the api_name, which put an
    action into the ontology under a name nobody chose and meant the empty case
    could not arrive at all.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [{
        "api_name": f"act_{tag}", "display_name": "Fine for now",
        "object_type": f"imp_{tag}", "criteria": [], "sections": [],
        "parameters": [{"api_name": "name", "display_name": "Name",
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "name", "parameter": "name"}}],
    }]
    if existing:
        # The rename path rather than the create path: the action is already
        # there and the file changes what it is called.
        assert apply(client, fx, document).status_code == 200
    document["action_types"][0]["display_name"] = name

    refused = apply(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "display name" in refused.text, refused.text


def test_nothing_is_written_when_an_action_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """A refused import writes nothing at all, including the object types that
    were legal — and that is `user_connection`'s single transaction rather than
    an ordering, which is the correction §340 had to make about its own version
    of this sentence."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [{
        "api_name": f"act_{tag}", "display_name": "Act",
        "object_type": f"imp_{tag}", "criteria": [], "sections": [],
        "parameters": [],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "name", "parameter": "gone"}}],
    }]
    assert apply(client, fx, document).status_code == 422
    listed = client.get(f"{wbase(fx)}/object-types?q=imp_{tag}",
                        headers=hdr(fx.editor_sub)).json()
    assert listed["items"] == []


# ---- what a parameter's dropdown names (§342) -----------------------------------
def an_action_naming(tag: str, **parameter) -> dict:
    return {"api_name": f"act_{tag}", "display_name": "Act",
            "object_type": f"imp_{tag}", "rules": [], "criteria": [],
            "parameters": [{"api_name": "pick", "display_name": "Pick",
                            "data_type": "object", **parameter}]}


def test_a_parameter_naming_a_type_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """**The same rule as a link's two ends, one resource further in** (§342).

    db 0083's column is an id in the database and an api_name in the file, so a
    name the document does not carry cannot be resolved on the way in — and a
    dropdown stored against nothing is the state §339 spent a unit making
    unreachable by deletion.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_naming(tag, object_type="nowhere")]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "nowhere" in refused.text and "object type" in refused.text
    # Named where it is, so a reader editing JSON can find it.
    assert f"imp_{tag}.act_{tag}.pick" in refused.text


def test_an_options_set_naming_a_type_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """db 0086's document names a type too, and a sweep found this one was the
    only reference nothing checked — the other two tests each covered their own
    field and left this one to be covered by neither."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_naming(
        tag, options_from={"object_type": "nowhere", "property": "name"})]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "nowhere" in refused.text and "object type" in refused.text


def test_a_walk_naming_a_link_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """db 0085's hops name link types, which the file must also carry. Asserted
    apart from the type above because one check covering both would pass with
    either half deleted."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_naming(
        tag,
        object_type=f"imp_{tag}",
        dropdown_search_around={
            "start": {"kind": "object_type", "object_type": f"imp_{tag}"},
            "hops": [{"link_type": "no_such_link"}]},
    )]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "no_such_link" in refused.text and "link type" in refused.text


def test_a_parameter_naming_what_the_file_does_define_is_accepted(
    client: TestClient, fx: Fixture
) -> None:
    """**The negative control**, without which every assertion above passes for
    a build that refuses any action carrying a dropdown at all."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag), one_type(tag, api_name=f"imp_{tag}b"))
    document["link_types"] = [a_link(tag)]
    document["action_types"] = [an_action_naming(
        tag,
        object_type=f"imp_{tag}b",
        options_from={"object_type": f"imp_{tag}", "property": "name"},
        dropdown_search_around={
            "start": {"kind": "object_type", "object_type": f"imp_{tag}"},
            "hops": [{"link_type": f"lnk_{tag}"}]},
    )]
    accepted = plan(client, fx, document)
    assert accepted.status_code == 200, accepted.text


# ---- what a rule names (§343) ---------------------------------------------------
def an_action_ruled(tag: str, *rules: dict) -> dict:
    return {"api_name": f"act_{tag}", "display_name": "Act",
            "object_type": f"imp_{tag}", "criteria": [], "parameters": [],
            "rules": [{"kind": k, "config": c, "sort_order": i}
                      for i, (k, c) in enumerate(rules)]}


def test_a_rule_naming_a_type_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """**The same rule as a parameter's dropdown, one table over** (§343).

    p.75's object rules name the type they create, change or delete, and that
    name was a uuid in the file until this unit — so nothing checked it and
    nothing could.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_ruled(
        tag, ("create_object", {"object_type": "nowhere",
                                "primary_key": "name"}))]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "nowhere" in refused.text and "object type" in refused.text
    # Named by its position, because a rule has no name of its own.
    assert f"imp_{tag}.act_{tag} rule 1" in refused.text


def test_a_rule_naming_a_link_the_file_does_not_define_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """Asserted apart from the type above so neither covers for the other —
    they are two tables in `action_rule_transfer` and a check reading only one
    of them passes the other's test."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_ruled(
        tag, ("create_link", {"link_type": "no_such_link", "object": "who"}))]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "no_such_link" in refused.text and "link type" in refused.text


def test_a_notify_rules_recipient_type_is_checked_too(
    client: TestClient, fx: Fixture
) -> None:
    """p.96's object-property recipient names its type one level deeper than
    the five beside it, which is exactly the shape a check written as a flat
    scan of `config` would miss."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_ruled(tag, ("notify", {
        "recipients": {"kind": "object_property", "parameter": "who",
                       "object_type": "nowhere", "property": "owner_id"},
        "subject": "Hi"}))]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "nowhere" in refused.text and "object type" in refused.text


def test_a_rule_naming_what_the_file_does_define_is_accepted(
    client: TestClient, fx: Fixture
) -> None:
    """**The negative control**, without which every assertion above passes for
    a build that refuses any action carrying a rule at all."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag), one_type(tag, api_name=f"imp_{tag}b"))
    document["link_types"] = [a_link(tag)]
    document["action_types"] = [an_action_ruled(
        tag,
        ("modify_object", {"object_type": f"imp_{tag}b", "object": "who",
                           "property": "name", "parameter": "name"}),
        ("create_link", {"link_type": f"lnk_{tag}", "object": "who"}),
    )]
    accepted = plan(client, fx, document)
    assert accepted.status_code == 200, accepted.text


# ---- p.67's refusal, which turns out to have a cause here (§343) ----------------
def a_rule_reaching_outside(kind: str) -> tuple[str, dict]:
    if kind == "webhook":
        return ("webhook", {"webhook": str(uuid.uuid4()), "mode": "writeback"})
    return ("notify", {"recipients": {"kind": "static",
                                      "user_ids": [str(uuid.uuid4())]},
                       "subject": "Hi"})


@pytest.mark.parametrize("kind", ["webhook", "notify"])
def test_a_copy_carrying_a_rule_that_reaches_outside_is_refused(
    client: TestClient, fx: Fixture, kind: str
) -> None:
    """**p.67, for the class §326 said had no cause here.**

        "An exported Ontology working state with conditional formatting rules
         configured on its properties cannot be imported to an Ontology other
         than the one it was exported from." (p.67)

    That reading was right about formatting — this platform's is inline jsonb
    naming sibling properties, so p.67's own example genuinely cannot happen —
    and wrong about the class. A webhook rule names a webhook, scoped to a
    workspace and a project; a static notify rule names people, scoped to an
    organisation. Neither is in the file and neither can be.

    Both kinds are asserted, because a refusal reading one of them would leave
    the other silently importable into a workspace where it means nothing.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag),
                      origin={"id": str(uuid.uuid4()), "slug": "elsewhere",
                              "name": "Elsewhere"})
    document["action_types"] = [an_action_ruled(
        tag, a_rule_reaching_outside(kind))]
    refused = plan(client, fx, document)
    assert refused.status_code == 422, refused.text
    # p.67's own remedy: the sentence names the rule to delete from the file.
    assert f"imp_{tag}.act_{tag} rule 1" in refused.text
    assert "cannot be transferred over" in refused.text


@pytest.mark.parametrize("kind", ["webhook", "notify"])
def test_the_same_file_going_back_where_it_came_from_is_not_refused(
    client: TestClient, fx: Fixture, kind: str
) -> None:
    """**The other half of p.67's sentence**: "other than the one it was
    exported from".

    A round trip is putting the ontology back where those ids already mean what
    they say, so refusing it would be refusing p.65's first workflow for a
    reason that does not apply to it — and this is what tells the check apart
    from one that simply refuses every webhook and every notification.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_ruled(
        tag, a_rule_reaching_outside(kind))]
    accepted = plan(client, fx, document)
    assert accepted.status_code == 200, accepted.text


def test_a_hand_edited_rule_that_is_not_an_object_is_not_a_server_fault(
    client: TestClient, fx: Fixture
) -> None:
    """p.65's premise is somebody editing this JSON in a text editor, and both
    of §343's readers run over every rule in the document — so a `config` that
    is a string would turn a typo into a 500 with nothing in it. §340 shipped
    exactly that defect for a link's missing `cardinality`; this is the same
    mistake, refused in advance."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["action_types"] = [an_action_ruled(
        tag, ("create_link", "link_type: no_such_link"))]
    read = plan(client, fx, document)
    assert read.status_code == 200, read.text


def test_a_copy_whose_notify_rule_reads_a_property_is_not_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.96's other recipient kind names an object type and a property, both of
    which are in the file. Without this, a refusal that stopped every `notify`
    rule from being copied would pass the two above."""
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag),
                      origin={"id": str(uuid.uuid4()), "slug": "elsewhere",
                              "name": "Elsewhere"})
    document["action_types"] = [an_action_ruled(tag, ("notify", {
        "recipients": {"kind": "object_property", "parameter": "who",
                       "object_type": f"imp_{tag}", "property": "name"},
        "subject": "Hi"}))]
    accepted = plan(client, fx, document)
    assert accepted.status_code == 200, accepted.text


# ---- p.65's link types, applied (§340) -----------------------------------------
def a_link(tag: str, **over) -> dict:
    """A link from the file's first type to its second, joined on `name`."""
    return {
        "api_name": f"lnk_{tag}",
        "display_name": "Belongs to",
        "cardinality": "one_to_many",
        "from_object_type": f"imp_{tag}",
        "to_object_type": f"imp_{tag}b",
        "from_property": "name",
        "to_property": "$primary_key",
        "from_side_name": "Members",
        "to_side_name": "Owner",
        "status": "experimental",
        "deprecation": None,
        **over,
    }


def two_types_and_a_link(fx: Fixture, tag: str, **over) -> dict:
    document = a_file(fx, one_type(tag), one_type(tag, api_name=f"imp_{tag}b"))
    document["link_types"] = [a_link(tag, **over)]
    return document


def links_of(client: TestClient, fx: Fixture) -> dict[str, dict]:
    return {row["api_name"]: row for row in export(client, fx)["link_types"]}


def test_a_link_whose_two_ends_are_both_new_in_the_file_is_applied(
    client: TestClient, fx: Fixture
) -> None:
    """**The reason this was ○, stated as the test.** p.65's second workflow is
    "copy the working state of one Ontology to another", where every type in the
    file is new — so a link resolved before the object-type pass would name two
    types that do not exist yet. Both ends are new here, which is the case a
    single-pass importer cannot do at all.
    """
    tag = uuid.uuid4().hex[:8]
    r = apply(client, fx, two_types_and_a_link(fx, tag))
    assert r.status_code == 200, r.text
    assert r.json()["links_added"] == [f"lnk_{tag}"]

    made = links_of(client, fx)[f"lnk_{tag}"]
    assert made["from_object_type"] == f"imp_{tag}"
    assert made["to_object_type"] == f"imp_{tag}b"
    assert made["cardinality"] == "one_to_many"
    # The join and the side names travel with it, or the link is defined and
    # not traversable (db 0027) — which looks identical in a listing and is a
    # different ontology.
    assert made["from_property"] == "name"
    assert made["to_property"] == "$primary_key"
    assert made["from_side_name"] == "Members"
    assert made["to_side_name"] == "Owner"


def test_re_importing_the_link_plans_no_changes(
    client: TestClient, fx: Fixture
) -> None:
    """The round trip §326 is built around, now that links are in it. A link
    applied and then re-read has to compare equal to its own export, or every
    later import reports work that is already done."""
    tag = uuid.uuid4().hex[:8]
    apply(client, fx, two_types_and_a_link(fx, tag)).raise_for_status()
    again = plan(client, fx, two_types_and_a_link(fx, tag))
    assert again.status_code == 200, again.text
    assert again.json()["sections"]["link_types"]["changed"] == []
    assert again.json()["sections"]["link_types"]["added"] == []


def test_an_edited_join_is_applied_to_an_existing_link(
    client: TestClient, fx: Fixture
) -> None:
    """The half `set_link_join` calls mutable, which is what an import of an
    existing link can carry."""
    tag = uuid.uuid4().hex[:8]
    apply(client, fx, two_types_and_a_link(fx, tag)).raise_for_status()
    r = apply(client, fx, two_types_and_a_link(fx, tag, to_side_name="Holder"))
    assert r.status_code == 200, r.text
    assert r.json()["links_updated"] == [f"lnk_{tag}"]
    assert links_of(client, fx)[f"lnk_{tag}"]["to_side_name"] == "Holder"


def test_a_file_that_moves_an_end_of_an_existing_link_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """`set_link_join`'s own rule, which an import is not an exception to:
    changing an endpoint "would make it a different relationship wearing the
    same name". Applying the mutable half and leaving the ends would produce a
    link matching neither the file nor the workspace."""
    tag = uuid.uuid4().hex[:8]
    apply(client, fx, two_types_and_a_link(fx, tag)).raise_for_status()
    moved = two_types_and_a_link(fx, tag, to_object_type=f"imp_{tag}")
    refused = apply(client, fx, moved)
    assert refused.status_code == 422, refused.text
    assert "different relationship wearing the same name" in refused.text


def test_a_file_that_changes_an_existing_links_cardinality_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """The same rule for the other immutable field — and asserted separately,
    because one check covering both would pass with either clause deleted."""
    tag = uuid.uuid4().hex[:8]
    apply(client, fx, two_types_and_a_link(fx, tag)).raise_for_status()
    refused = apply(
        client, fx, two_types_and_a_link(fx, tag, cardinality="many_to_many"))
    assert refused.status_code == 422, refused.text
    assert "cardinality" in refused.text


def test_nothing_is_written_when_a_link_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """**A refused import writes nothing, including the half that was legal.**

    The file carries a legal new object type *and* an illegal link change, and
    the type is not there afterwards.

    What makes that true is `user_connection`: the whole request is one
    transaction, so a refusal anywhere rolls back everything the import had
    written. The first draft of this test claimed it was proving the *position*
    of `check_immutable_links` — and a sweep showed that moving that call to
    after the object-type pass changes nothing here. The behaviour is worth
    pinning; the reason it holds is the transaction, and this test is now
    written as a test of that.
    """
    tag = uuid.uuid4().hex[:8]
    apply(client, fx, two_types_and_a_link(fx, tag)).raise_for_status()
    document = two_types_and_a_link(fx, tag, cardinality="many_to_many")
    document["object_types"].append(one_type(tag, api_name=f"imp_{tag}c"))
    refused = apply(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert f"imp_{tag}c" not in {t["api_name"] for t in export(client, fx)["object_types"]}


def test_a_link_with_no_cardinality_is_refused_by_name(
    client: TestClient, fx: Fixture
) -> None:
    """**p.65's premise is a hand-edited file**, so a key somebody deleted has
    to come back as a sentence about that key.

    Before §340 nothing read `cardinality`, and the first thing that did turned
    a file missing it into a 500 — an error that says nothing about the file and
    nothing the reader can act on.
    """
    tag = uuid.uuid4().hex[:8]
    document = two_types_and_a_link(fx, tag)
    del document["link_types"][0]["cardinality"]
    refused = apply(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "cardinality" in refused.text
    assert "one_to_many" in refused.text


def test_a_link_with_no_api_name_is_refused_by_name(
    client: TestClient, fx: Fixture
) -> None:
    """The other field a link cannot be created without.

    **Refused a layer down**, and `ontology_import` has no check of its own for
    it: `create_link_type` matches the api_name against a regex and names the
    field, and since a request is one transaction the earlier refusal changed
    neither the outcome nor what was written. The test stays because the
    behaviour matters; the check it was written against is gone (§213).
    """
    tag = uuid.uuid4().hex[:8]
    document = two_types_and_a_link(fx, tag)
    document["link_types"][0]["api_name"] = ""
    refused = apply(client, fx, document)
    assert refused.status_code == 422, refused.text
    assert "api_name" in refused.text


def test_a_link_between_types_that_already_exist_is_still_applied(
    client: TestClient, fx: Fixture
) -> None:
    """The negative control for the two-pass ordering: the ends being new is
    what makes the ordering necessary, not what makes the link get applied."""
    tag = uuid.uuid4().hex[:8]
    types_only = a_file(fx, one_type(tag), one_type(tag, api_name=f"imp_{tag}b"))
    apply(client, fx, types_only).raise_for_status()
    r = apply(client, fx, two_types_and_a_link(fx, tag))
    assert r.status_code == 200, r.text
    assert r.json()["links_added"] == [f"lnk_{tag}"]


# ---- who may -------------------------------------------------------------------
def test_a_viewer_cannot_plan_or_apply(client: TestClient, fx: Fixture) -> None:
    document = a_file(fx)
    for path in ("/ontology-import/plan", "/ontology-import"):
        r = client.post(f"{wbase(fx)}{path}", headers=hdr(fx.viewer_sub),
                        json={"document": document})
        assert r.status_code == 403, (path, r.text)
