"""p.66's "recreate the entire working state", deletions included (§799;
`ontology-manager` p.65-67).

An import removes what its file leaves out only when the person applying it
asks, having seen the plan name each one. The removals go actions first,
then link types, then object types, and p.256's refusal of an active
resource refuses the whole import. Its own workspace, because the point is
deleting whatever the file does not carry.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402


@pytest.fixture
def fx() -> Fixture:
    """A fresh workspace per test: each one deletes what its file leaves out."""
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("import-delete"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def make_type(client, fx, name: str) -> str:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": name, "display_name": name,
        "properties": [{"api_name": "name", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def world(client, fx) -> dict:
    keep, drop = make_type(client, fx, "keep"), make_type(client, fx, "drop")
    link = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": "keep_drop", "display_name": "Keep drop", "from_type_id": keep,
        "to_type_id": drop, "cardinality": "one_to_many", "from_property": "name",
        "to_property": "name"})
    assert link.status_code == 201, link.text
    action = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": drop, "api_name": "touch", "display_name": "Touch",
        "editable_properties": ["name"]})
    assert action.status_code == 201, action.text
    return {"keep": keep, "drop": drop}


def leaving_out_drop(client, fx) -> dict:
    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    document = r.json()
    document["object_types"] = [t for t in document["object_types"] if t["api_name"] != "drop"]
    document["link_types"] = []
    document["action_types"] = [a for a in document["action_types"]
                                if a["object_type"] != "drop"]
    return document


def names(client, fx) -> tuple[list[str], list[str], list[str]]:
    exported = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    return (sorted(t["api_name"] for t in exported["object_types"]),
            sorted(lt["api_name"] for lt in exported["link_types"]),
            sorted(f"{a['object_type']}.{a['api_name']}" for a in exported["action_types"]))


def apply(client, fx, document: dict, **flags):
    return client.post(f"{wbase(fx)}/ontology-import", headers=hdr(fx.editor_sub),
                       json={"document": document, **flags})


def test_left_out_is_left_alone_unless_asked(client, fx) -> None:
    world(client, fx)
    document = leaving_out_drop(client, fx)
    planned = client.post(f"{wbase(fx)}/ontology-import/plan", headers=hdr(fx.editor_sub),
                          json={"document": document}).json()["sections"]
    assert (planned["object_types"]["absent_from_file"], planned["link_types"]["absent_from_file"],
            planned["action_types"]["absent_from_file"]) == (["drop"], ["keep_drop"],
                                                              ["drop.touch"])
    r = apply(client, fx, document)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == {"object_types": [], "link_types": [], "action_types": []}
    assert names(client, fx) == (["drop", "keep"], ["keep_drop"], ["drop.touch"])


def test_asked_it_recreates_the_working_state(client, fx) -> None:
    world(client, fx)
    r = apply(client, fx, leaving_out_drop(client, fx), delete_absent=True)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == {"object_types": ["drop"], "link_types": ["keep_drop"],
                                   "action_types": ["drop.touch"]}
    assert names(client, fx) == (["keep"], [], [])


def test_an_active_resource_refuses_the_whole_import(client, fx) -> None:
    """p.256: an active object type cannot be deleted - so nothing is, the
    link and the action included."""
    ids = world(client, fx)
    r = client.post(f"{wbase(fx)}/object-types/bulk-status", headers=hdr(fx.editor_sub),
                    json={"object_type_ids": [ids["drop"]], "status": "active"})
    assert r.status_code == 200, r.text
    r = apply(client, fx, leaving_out_drop(client, fx), delete_absent=True)
    assert r.status_code in (409, 422), r.text
    assert "active" in r.text
    assert names(client, fx) == (["drop", "keep"], ["keep_drop"], ["drop.touch"])


def test_a_type_with_no_actions_or_links_left_out(client, fx) -> None:
    """Only object types absent: the action and link passes have nothing."""
    make_type(client, fx, "keep")
    make_type(client, fx, f"spare_{uuid.uuid4().hex[:4]}")
    r = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    r["object_types"] = [t for t in r["object_types"] if t["api_name"] == "keep"]
    got = apply(client, fx, r, delete_absent=True)
    assert got.status_code == 200, got.text
    assert names(client, fx) == (["keep"], [], [])


def test_a_link_and_an_action_left_out_go_while_their_types_stay(client, fx) -> None:
    """Not only through a type's delete: a file keeping both types and dropping
    the link and one action removes exactly those. An action is named by its
    type too - `keep.touch` shares the dropped action's name and stays."""
    ids = world(client, fx)
    kept = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": ids["keep"], "api_name": "touch",
        "display_name": "Touch keep", "editable_properties": ["name"]})
    assert kept.status_code == 201, kept.text
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    document["link_types"] = []
    document["action_types"] = [a for a in document["action_types"] if a["object_type"] != "drop"]
    r = apply(client, fx, document, delete_absent=True)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == {"object_types": [], "link_types": ["keep_drop"],
                                   "action_types": ["drop.touch"]}
    assert names(client, fx) == (["drop", "keep"], [], ["keep.touch"])

