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
    assert f"edit_{tag}" in body["sections"]["action_types"]["unchanged"]
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


def test_link_and_action_types_are_reported_as_not_applied(
    client: TestClient, fx: Fixture
) -> None:
    """**Named rather than silently skipped** (§214).

    Applying links and actions needs its own resolution pass — a link joins two
    types that may both be new in the same file, and an action's rules name
    parameters that may be — so it is ○ here. A reader whose file carried three
    link types and got no word of them would believe they arrived.
    """
    tag = uuid.uuid4().hex[:8]
    document = a_file(fx, one_type(tag))
    document["link_types"] = [
        {"api_name": f"lnk_{tag}", "display_name": "Link",
         "from_object_type": f"imp_{tag}", "to_object_type": f"imp_{tag}",
         "cardinality": "one_to_many"},
    ]
    r = apply(client, fx, document)
    assert r.status_code == 200, r.text
    assert r.json()["not_applied"]["link_types"] == [f"lnk_{tag}"]


# ---- who may -------------------------------------------------------------------
def test_a_viewer_cannot_plan_or_apply(client: TestClient, fx: Fixture) -> None:
    document = a_file(fx)
    for path in ("/ontology-import/plan", "/ontology-import"):
        r = client.post(f"{wbase(fx)}{path}", headers=hdr(fx.viewer_sub),
                        json={"document": document})
        assert r.status_code == 403, (path, r.text)
