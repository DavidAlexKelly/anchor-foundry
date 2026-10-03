"""Module branches (§698, db 0136; Foundry `workshop` p.193, p.617-621).

> "When developing on a branch, you may need to rebase before merging your
> Workshop changes into main if main has changed since your last save." (p.193)

What a branch has to guarantee, and what these tests hold it to: a save on a
branch leaves main's document, version and viewers alone; a merge puts the
branch on main as a new version; and a merge is refused while main has moved
past the branch's base, because merging then would drop main's newer changes
without anybody having chosen to.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


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


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/canvas-apps"


def doc(text: str) -> dict:
    return {
        "format": 2, "events": {}, "variables": {},
        "layout": {
            "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "isCanvas": True,
                     "props": {}, "nodes": ["t"], "linkedNodes": {}},
            "t": {"type": {"resolvedName": "CanvasText"}, "props": {"text": text},
                  "parent": "ROOT", "nodes": []},
        },
    }


def text_of(document: dict) -> str:
    return document["layout"]["t"]["props"]["text"]


_n = iter(range(10_000))


def new_module(client: TestClient, fx: Fixture) -> str:
    """A module saved once on main, so every branch has a version to be on."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Branched {fx.tag} {next(_n)}"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    save_main(client, fx, app_id, "main one")
    return app_id


def save_main(client: TestClient, fx: Fixture, app_id: str, text: str) -> dict:
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": doc(text)})
    assert r.status_code == 200, r.text
    return r.json()


def branch(client: TestClient, fx: Fixture, app_id: str, name: str, text: str):
    return client.post(f"{base(fx)}/{app_id}/branches", headers=hdr(fx.editor_sub),
                       json={"name": name, "definition": doc(text)})


def main_of(client: TestClient, fx: Fixture, app_id: str) -> dict:
    r = client.get(f"{base(fx)}/{app_id}", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_save_to_new_branch_leaves_main_alone(client: TestClient, fx: Fixture) -> None:
    """p.617-618's Save to new branch: the builder's document goes to the
    branch, and main - its document and its version - does not move."""
    app_id = new_module(client, fx)
    r = branch(client, fx, app_id, "feature-1", "on the branch")
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["name"] == "feature-1"
    assert made["base_version"] == 1
    assert made["needs_rebase"] is False
    assert text_of(made["definition"]) == "on the branch"

    main = main_of(client, fx, app_id)
    assert main["current_version"] == 1
    assert text_of(main["definition"]) == "main one"


def test_a_branch_save_changes_only_the_branch(client: TestClient, fx: Fixture) -> None:
    app_id = new_module(client, fx)
    assert branch(client, fx, app_id, "work", "first").status_code == 201
    r = client.put(f"{base(fx)}/{app_id}/branches/work/definition",
                   headers=hdr(fx.editor_sub), json={"definition": doc("second")})
    assert r.status_code == 200, r.text
    assert text_of(r.json()["definition"]) == "second"
    assert r.json()["save_count"] == 2

    got = client.get(f"{base(fx)}/{app_id}/branches/work", headers=hdr(fx.viewer_sub))
    assert got.status_code == 200, got.text
    assert text_of(got.json()["definition"]) == "second"
    main = main_of(client, fx, app_id)
    assert (main["current_version"], text_of(main["definition"])) == (1, "main one")


def test_merging_an_up_to_date_branch_makes_the_next_main_version(
    client: TestClient, fx: Fixture,
) -> None:
    """The merge is a main version like any save, described by the branch it
    came from, and the branch is gone afterwards."""
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "ready", "merged text")
    r = client.post(f"{base(fx)}/{app_id}/branches/ready/merge", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 2
    assert text_of(r.json()["definition"]) == "merged text"

    versions = client.get(f"{base(fx)}/{app_id}/versions", headers=hdr(fx.editor_sub)).json()
    assert versions[0]["version_number"] == 2
    assert versions[0]["description"] == "Merged branch ready"
    names = [b["name"] for b in client.get(f"{base(fx)}/{app_id}/branches",
                                           headers=hdr(fx.editor_sub)).json()]
    assert "ready" not in names


def test_a_branch_behind_main_must_be_rebased_before_it_merges(
    client: TestClient, fx: Fixture,
) -> None:
    """p.193: "you may need to rebase before merging … if main has changed since
    your last save". Merging anyway would replace main with a document that
    never saw main's newer change."""
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "behind", "branch text")
    save_main(client, fx, app_id, "main moved on")

    listed = client.get(f"{base(fx)}/{app_id}/branches", headers=hdr(fx.editor_sub)).json()
    [behind] = [b for b in listed if b["name"] == "behind"]
    assert behind["needs_rebase"] is True
    assert behind["base_version"] == 1

    r = client.post(f"{base(fx)}/{app_id}/branches/behind/merge", headers=hdr(fx.editor_sub))
    assert r.status_code == 409, r.text
    assert "rebase" in r.json()["detail"]
    main = main_of(client, fx, app_id)
    assert (main["current_version"], text_of(main["definition"])) == (2, "main moved on")


def test_a_rebase_save_moves_the_base_only_to_mains_current_version(
    client: TestClient, fx: Fixture,
) -> None:
    """The save that finishes a rebase (§699) names the main version it merged
    against. Naming any other is a rebase against the wrong ancestor."""
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "rebasing", "branch text")
    save_main(client, fx, app_id, "main two")

    stale = client.put(f"{base(fx)}/{app_id}/branches/rebasing/definition",
                       headers=hdr(fx.editor_sub),
                       json={"definition": doc("merged"), "base_version": 1})
    assert stale.status_code == 409, stale.text

    r = client.put(f"{base(fx)}/{app_id}/branches/rebasing/definition",
                   headers=hdr(fx.editor_sub),
                   json={"definition": doc("merged"), "base_version": 2})
    assert r.status_code == 200, r.text
    assert (r.json()["base_version"], r.json()["needs_rebase"]) == (2, False)
    merged = client.post(f"{base(fx)}/{app_id}/branches/rebasing/merge",
                         headers=hdr(fx.editor_sub))
    assert merged.status_code == 200, merged.text
    assert text_of(merged.json()["definition"]) == "merged"


def test_a_plain_branch_save_keeps_its_base(client: TestClient, fx: Fixture) -> None:
    """Only a rebase moves the base. A save without one is still a branch of the
    version it was taken from, however many times it is saved."""
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "steady", "one")
    save_main(client, fx, app_id, "main two")
    r = client.put(f"{base(fx)}/{app_id}/branches/steady/definition",
                   headers=hdr(fx.editor_sub), json={"definition": doc("two")})
    assert r.status_code == 200, r.text
    assert (r.json()["base_version"], r.json()["needs_rebase"]) == (1, True)


@pytest.mark.parametrize("name", ["main", "Main", "-dash", "has space", "x" * 64, ""])
def test_a_branch_name_has_to_be_a_branch_name(
    client: TestClient, fx: Fixture, name: str,
) -> None:
    """`main` is the other head's name, so a branch called it would make every
    merge into main ambiguous."""
    app_id = new_module(client, fx)
    r = branch(client, fx, app_id, name, "x")
    assert r.status_code == 422, r.text


def test_two_branches_cannot_share_a_name(client: TestClient, fx: Fixture) -> None:
    app_id = new_module(client, fx)
    assert branch(client, fx, app_id, "twin", "a").status_code == 201
    r = branch(client, fx, app_id, "twin", "b")
    assert r.status_code == 409, r.text


def test_a_branch_is_held_to_mains_save_rules(client: TestClient, fx: Fixture) -> None:
    """A branch that accepted a document main's Save refuses would be a way to
    put that document on main by merging it."""
    app_id = new_module(client, fx)
    unknown = doc("x")
    unknown["layout"]["t"]["type"] = {"resolvedName": "NoSuchWidget"}
    assert branch(client, fx, app_id, "bad", "x").status_code == 201
    r = client.post(f"{base(fx)}/{app_id}/branches", headers=hdr(fx.editor_sub),
                    json={"name": "worse", "definition": unknown})
    assert r.status_code == 422, r.text
    r = client.put(f"{base(fx)}/{app_id}/branches/bad/definition",
                   headers=hdr(fx.editor_sub), json={"definition": unknown})
    assert r.status_code == 422, r.text


def test_a_viewer_can_read_branches_and_not_write_them(client: TestClient, fx: Fixture) -> None:
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "look", "x")
    assert client.get(f"{base(fx)}/{app_id}/branches",
                      headers=hdr(fx.viewer_sub)).status_code == 200
    for method, path, body in [
        ("post", "/branches", {"name": "nope", "definition": doc("x")}),
        ("put", "/branches/look/definition", {"definition": doc("y")}),
        ("post", "/branches/look/merge", None),
        ("delete", "/branches/look", None),
    ]:
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(f"{base(fx)}/{app_id}{path}",
                                    headers=hdr(fx.viewer_sub), **kwargs)
        assert r.status_code == 403, (method, path, r.text)


def test_an_outsider_sees_no_branches(client: TestClient, fx: Fixture) -> None:
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "secret", "x")
    r = client.get(f"{base(fx)}/{app_id}/branches/secret", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404, r.text


def test_deleting_a_branch_leaves_main(client: TestClient, fx: Fixture) -> None:
    app_id = new_module(client, fx)
    branch(client, fx, app_id, "gone", "x")
    r = client.delete(f"{base(fx)}/{app_id}/branches/gone", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text
    assert client.get(f"{base(fx)}/{app_id}/branches/gone",
                      headers=hdr(fx.editor_sub)).status_code == 404
    assert text_of(main_of(client, fx, app_id)["definition"]) == "main one"


def embedding(*module_ids: str) -> dict:
    return {
        "format": 2, "variables": {}, "events": {},
        "layout": {
            "ROOT": {"type": {"resolvedName": "CanvasContainer"}, "isCanvas": True,
                     "props": {}, "nodes": [f"e{i}" for i in range(len(module_ids))],
                     "linkedNodes": {}},
            **{f"e{i}": {"type": {"resolvedName": "CanvasEmbeddedModule"},
                         "props": {"moduleId": mid}, "parent": "ROOT", "nodes": []}
               for i, mid in enumerate(module_ids)},
        },
    }


def test_a_merge_checks_the_branch_against_main_as_it_is_now(
    client: TestClient, fx: Fixture,
) -> None:
    """The branch was valid when saved; what it is merged into may not still
    accept it. Here A's branch embeds B, which was fine - and then B was saved
    embedding A, so A's main embedding B would close a cycle."""
    a, b = new_module(client, fx), new_module(client, fx)
    r = client.post(f"{base(fx)}/{a}/branches", headers=hdr(fx.editor_sub),
                    json={"name": "embeds-b", "definition": embedding(b)})
    assert r.status_code == 201, r.text
    r = client.put(f"{base(fx)}/{b}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": embedding(a)})
    assert r.status_code == 200, r.text

    r = client.post(f"{base(fx)}/{a}/branches/embeds-b/merge", headers=hdr(fx.editor_sub))
    assert r.status_code == 422, r.text
    assert main_of(client, fx, a)["current_version"] == 1


def test_variables_resolve_against_the_branch_being_edited(
    client: TestClient, fx: Fixture,
) -> None:
    """A branch may declare a variable main does not have; the builder editing
    that branch has to get its value, not main's absence of one."""
    app_id = new_module(client, fx)
    document = doc("x")
    document["variables"] = {"v_note": {"id": "v_note", "kind": "string",
                                        "label": "Note", "default": "from the branch"}}
    r = client.post(f"{base(fx)}/{app_id}/branches", headers=hdr(fx.editor_sub),
                    json={"name": "noted", "definition": document})
    assert r.status_code == 201, r.text

    on_branch = client.post(f"{base(fx)}/{app_id}/variables/evaluate",
                            headers=hdr(fx.viewer_sub), json={"branch": "noted"})
    assert on_branch.status_code == 200, on_branch.text
    assert on_branch.json()["values"]["v_note"] == "from the branch"
    on_main = client.post(f"{base(fx)}/{app_id}/variables/evaluate",
                          headers=hdr(fx.viewer_sub), json={})
    assert "v_note" not in on_main.json()["values"]
    missing = client.post(f"{base(fx)}/{app_id}/variables/evaluate",
                          headers=hdr(fx.viewer_sub), json={"branch": "nope"})
    assert missing.status_code == 404, missing.text


# ---- §701: the builder resolves the variables it is editing -------------------
def note_variable(default: str) -> dict:
    return {"v_note": {"id": "v_note", "kind": "string", "label": "Note", "default": default}}


def test_an_editor_resolves_their_working_variables(client: TestClient, fx: Fixture) -> None:
    """p.621's "evaluate outcomes in real time": a variable in the builder's
    draft - configured a moment ago, or brought in by a rebase not saved yet -
    has a value before anybody saves."""
    app_id = new_module(client, fx)
    r = client.post(f"{base(fx)}/{app_id}/variables/evaluate", headers=hdr(fx.editor_sub),
                    json={"working": {"variables": note_variable("drafted"), "events": {}}})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["v_note"] == "drafted"


def test_a_viewers_draft_is_not_theirs_to_resolve(client: TestClient, fx: Fixture) -> None:
    """A viewer's module is the saved one: they cannot edit it, so there is no
    draft of theirs to resolve."""
    app_id = new_module(client, fx)
    r = client.post(f"{base(fx)}/{app_id}/variables/evaluate", headers=hdr(fx.viewer_sub),
                    json={"working": {"variables": note_variable("drafted"), "events": {}}})
    assert r.status_code == 200, r.text
    assert "v_note" not in r.json()["values"]


def test_a_draft_that_does_not_validate_resolves_as_saved(client: TestClient, fx: Fixture) -> None:
    """A variable half-configured in its panel must not blank the canvas under
    the person configuring it: the saved document resolves until the draft is
    whole."""
    app_id = new_module(client, fx)
    saved = doc("x")
    saved["variables"] = note_variable("saved")
    client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
               json={"definition": saved})
    broken = {"v_bad": {"id": "v_bad", "kind": "string", "label": "Bad",
                        "derivation": {"transform": "concat", "inputs": ["v_missing"]}}}
    r = client.post(f"{base(fx)}/{app_id}/variables/evaluate", headers=hdr(fx.editor_sub),
                    json={"working": {"variables": broken, "events": {}}})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["v_note"] == "saved"
