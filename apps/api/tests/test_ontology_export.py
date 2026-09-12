"""Exporting an ontology as JSON (§326; `ontology-manager` p.65-67).

    "Ontology schema definitions are stored in a JSON file. An Ontology JSON
     file can be exported and edited with a code editor or text editor before
     being imported back into Foundry." (p.65)

    "You should not depend on the exported JSON schema as it may change over
     time." (p.65)

**The tests are about p.65's second workflow**, "copy the working state of one
Ontology to another", because it is the one that constrains the shape. A file
that round-trips into its own workspace can be full of uuids and nobody
notices; a file meant for a *different* workspace cannot contain a single one.
So most of what is checked below is that nothing identifies anything by id.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import ontology_export as export  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402

UUID_LIKE = __import__("re").compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("export-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


@pytest.fixture(scope="module")
def exported(client: TestClient, fx: Fixture) -> dict:
    """One ontology with something of every kind in it, exported once.

    Module-scoped because the export is a read: every test below asks a
    different question of the same document, and re-exporting per test would
    make each one pay for a whole workspace's ontology.
    """
    tag = uuid.uuid4().hex[:8]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"exp_{tag}", "display_name": f"Exported {tag}",
              "description": "A type that gets exported",
              "properties": [
                  {"api_name": "name", "display_name": "Name",
                   "data_type": "string", "required": True},
                  {"api_name": "score", "display_name": "Score",
                   "data_type": "integer",
                   # The one field p.67 is about, and the one that names a
                   # sibling property rather than carrying an id.
                   "conditional_format": [
                       {"kind": "standard", "property": "score",
                        "comparison": "numeric_range", "max": 10,
                        "colour": "#b91c1c"},
                   ]},
              ],
              "title_property": "name"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]

    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": f"rename_{tag}",
              "display_name": "Rename", "editable_properties": ["name"]},
    )
    assert action.status_code == 201, action.text

    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return {"doc": r.json(), "api_name": f"exp_{tag}",
            "action": f"rename_{tag}", "type_id": type_id}


def a_type(doc: dict, api_name: str) -> dict | None:
    return next((t for t in doc["object_types"] if t["api_name"] == api_name), None)


def test_the_file_says_which_shape_it_is(exported: dict) -> None:
    """p.65: "You should not depend on the exported JSON schema as it may
    change over time."

    Which is licence to change it, and a reason to stamp it: a file that did
    not say which shape it was would leave the importer guessing on the day the
    shape moves.
    """
    assert exported["doc"]["format_version"] == export.FORMAT_VERSION


def test_the_file_says_which_ontology_it_came_from(exported: dict) -> None:
    """p.65's two workflows differ in exactly this: edit-and-put-back goes home,
    copy-to-another does not. The importer cannot tell them apart unless the
    file says where it started.

    The slug as well as the id, because a person reading the file in a text
    editor — which is p.65's whole premise — needs to recognise it, and a uuid
    tells them nothing.
    """
    origin = exported["doc"]["workspace"]
    assert origin["id"] and origin["slug"] and origin["name"]


def test_an_object_type_brings_its_properties(exported: dict) -> None:
    found = a_type(exported["doc"], exported["api_name"])
    assert found is not None
    assert [p["api_name"] for p in found["properties"]] == ["name", "score"]
    assert found["description"] == "A type that gets exported"


def test_properties_keep_the_order_somebody_put_them_in(
    client: TestClient, fx: Fixture
) -> None:
    """**Named against the alphabet on purpose.**

    A property's `sort_order` is how it was arranged, and an export that lost it
    would reorder every form and table built from the file. The type above
    happens to be in alphabetical order too — "name" before "score" — so the
    mutation sweep dropped `sort_order` from the statement and nothing noticed.
    Here the first property sorts last by name, so the two orders disagree and
    only one of them can be right.
    """
    tag = uuid.uuid4().hex[:8]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"ord_{tag}", "display_name": f"Ordered {tag}",
              "properties": [
                  {"api_name": "zulu", "display_name": "Zulu",
                   "data_type": "string"},
                  {"api_name": "alpha", "display_name": "Alpha",
                   "data_type": "string"},
              ]},
    )
    assert r.status_code == 201, r.text

    doc = client.get(f"{wbase(fx)}/ontology-export",
                     headers=hdr(fx.editor_sub)).json()
    found = a_type(doc, f"ord_{tag}")
    assert found is not None
    assert [p["api_name"] for p in found["properties"]] == ["zulu", "alpha"], (
        "the file keeps the order somebody arranged, not the alphabet"
    )


def test_a_jsonb_column_arriving_as_text_is_parsed(exported: dict) -> None:
    """**The branch the driver's configuration hides.**

    `psycopg` hands `jsonb` back as Python objects here, so `_json`'s
    `isinstance(value, str)` arm never runs against this database — a mutant
    removing it survived, and correctly. The arm is not dead though: the same
    column arrives as text under a different driver setting, and a file whose
    `conditional_format` was the *string* `"[{...}]"` would import as a
    meaningless scalar rather than a list of rules.

    So it is checked directly rather than through a query, which is the only
    way to reach it — and the pairing below is the point: a field outside
    `JSON_FIELDS` must be handed back untouched, or the blanket parse that
    broke this module's first draft comes back.
    """
    row = {"conditional_format": '[{"kind": "always", "colour": "#000"}]',
           "display_name": "Not JSON at all"}
    picked = export._pick(row, ("conditional_format", "display_name"))
    assert picked["conditional_format"] == [{"kind": "always", "colour": "#000"}]
    assert picked["display_name"] == "Not JSON at all"


def test_the_title_property_travels_as_a_name(exported: dict) -> None:
    """**The claim the whole file rests on.** `title_property_id` is a uuid, and
    a uuid means nothing in the workspace this file might be imported into — so
    it goes out as the property's api_name.

    Checked here rather than left to the sweep of uuids below, because that
    sweep would pass just as well if the field were dropped entirely.
    """
    found = a_type(exported["doc"], exported["api_name"])
    assert found is not None
    assert found["title_property"] == "name"


def test_an_action_type_names_its_object_type_by_name(exported: dict) -> None:
    action = next(a for a in exported["doc"]["action_types"]
                  if a["api_name"] == exported["action"])
    assert action["object_type"] == exported["api_name"]
    # The definition travels too, or the copy is an action that does nothing.
    assert [p["api_name"] for p in action["parameters"]] == ["name"]
    assert [r["kind"] for r in action["rules"]] == ["modify_object"]


def test_conditional_formatting_travels_whole(exported: dict) -> None:
    """**p.67's rule has no cause here, and that is worth writing down.**

        "An exported Ontology working state with conditional formatting rules
         configured on its properties cannot be imported to an Ontology other
         than the one it was exported from." (p.67)

    Foundry's formatting references *rule sets* defined outside the ontology,
    which is why they cannot travel. This platform's are inline jsonb on the
    property and name only sibling properties by api_name — so they are
    self-contained and the refusal p.67 describes would be a check that can
    never be right (§214).

    What *is* real is the same class of problem: a rule naming a property the
    file does not carry. That is checked below.
    """
    found = a_type(exported["doc"], exported["api_name"])
    assert found is not None
    score = next(p for p in found["properties"] if p["api_name"] == "score")
    assert score["conditional_format"], score
    assert score["conditional_format"][0]["property"] == "score"


def test_every_formatting_rule_names_a_property_the_file_carries(
    exported: dict
) -> None:
    """p.67's problem in the shape it actually takes here.

    A conditional format names a property by api_name; if the export dropped
    that property — or a rule referred to one from another type — the imported
    ontology would draw a colour off a column that does not exist. Asserted over
    the whole document rather than the one type this suite made, because the
    claim is about the file rather than about the fixture.
    """
    for kind in exported["doc"]["object_types"]:
        theirs = {p["api_name"] for p in kind["properties"]}
        for prop in kind["properties"]:
            for rule in prop.get("conditional_format") or []:
                named = rule.get("property")
                if named is None:
                    continue  # an `always` rule colours regardless
                assert named in theirs, (
                    f"{kind['api_name']}.{prop['api_name']} formats on "
                    f"{named!r}, which the file does not carry"
                )


def test_a_link_type_brings_its_join(client: TestClient, fx: Fixture) -> None:
    """A link type without `from_property` and `to_property` is a link that
    cannot traverse — the join *is* the link, not decoration on it."""
    tag = uuid.uuid4().hex[:8]
    ids = []
    for side in ("left", "right"):
        r = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"lnk_{side}_{tag}",
                  "display_name": f"Link {side} {tag}",
                  "properties": [{"api_name": "key", "data_type": "string"}]},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    made = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"joins_{tag}", "display_name": f"Joins {tag}",
              "from_type_id": ids[0], "to_type_id": ids[1],
              "cardinality": "one_to_many",
              "from_property": "key", "to_property": "key"},
    )
    assert made.status_code == 201, made.text

    doc = client.get(f"{wbase(fx)}/ontology-export",
                     headers=hdr(fx.editor_sub)).json()
    link = next(x for x in doc["link_types"] if x["api_name"] == f"joins_{tag}")
    assert link["from_object_type"] == f"lnk_left_{tag}"
    assert link["to_object_type"] == f"lnk_right_{tag}"
    assert link["from_property"] == "key"
    assert link["to_property"] == "key"


def test_nothing_in_the_ontology_is_identified_by_id(exported: dict) -> None:
    """**p.65's second workflow, as one assertion**: "copy the working state of
    one Ontology to another".

    An id from this workspace means nothing in the workspace the file is
    imported into, so the ontology half of the document must contain none. The
    `workspace` block is exempt and named as such — it describes where the file
    *came from*, which is the one thing that is allowed to be about this copy.
    """
    ontology = {k: v for k, v in exported["doc"].items() if k != "workspace"}
    stray = UUID_LIKE.findall(json.dumps(ontology))
    assert stray == [], f"the ontology names things by id: {stray[:3]}"


def test_the_export_does_not_claim_authorship(exported: dict) -> None:
    """`created_by`, `created_at` and `resource_id` are facts about this copy,
    not about the ontology. Carrying them would make an import claim somebody
    else's authorship and a resource id that already belongs to another row."""
    found = a_type(exported["doc"], exported["api_name"])
    assert found is not None
    for absent in ("id", "created_by", "created_at", "resource_id",
                   "workspace_id"):
        assert absent not in found, absent


def test_a_viewer_cannot_export_the_ontology(
    client: TestClient, fx: Fixture
) -> None:
    """p.65 frames the file as something you edit and import back, so this is
    the read half of a write — and the whole shape of a workspace's ontology in
    one document is more than a viewer needs in order to read one type."""
    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403, r.text


def test_an_outsider_gets_nothing(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text
