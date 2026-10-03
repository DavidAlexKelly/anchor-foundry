"""Protected modules and branch proposals (§700, db 0137; Foundry `workshop`
p.617-618).

> "When on the main branch, protected Workshop modules show a Save to new
> branch option instead of Save and publish, requiring all changes to be made
> on a branch rather than directly to main." (p.617)
> "When you are ready to merge your changes to main, create a proposal …
> Reviewers can then approve or reject the change" (p.618)

What protection has to guarantee is that main changes only by a reviewed
merge: no direct save, no revert, no merge without an approval, and no
approval that outlives the document it approved or that its own author gave.
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


_n = iter(range(10_000))


def module(client: TestClient, fx: Fixture, *, protect: bool = True) -> str:
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Protected {fx.tag} {next(_n)}"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": doc("main one")})
    assert r.status_code == 200, r.text
    if protect:
        r = client.put(f"{base(fx)}/{app_id}/protection", headers=hdr(fx.admin_sub),
                       json={"protected": True})
        assert r.status_code == 200, r.text
        assert r.json()["protected"] is True
    return app_id


def make_branch(client: TestClient, fx: Fixture, app_id: str, name: str = "change",
                who: str | None = None) -> dict:
    r = client.post(f"{base(fx)}/{app_id}/branches", headers=hdr(who or fx.editor_sub),
                    json={"name": name, "definition": doc(f"{name} text")})
    assert r.status_code == 201, r.text
    return r.json()


def act(client: TestClient, fx: Fixture, app_id: str, what: str, who: str,
        name: str = "change"):
    return client.post(f"{base(fx)}/{app_id}/branches/{name}/{what}", headers=hdr(who))


def test_a_protected_main_refuses_a_direct_save(client: TestClient, fx: Fixture) -> None:
    """p.617: "requiring all changes to be made on a branch rather than
    directly to main"."""
    app_id = module(client, fx)
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": doc("straight to main")})
    assert r.status_code == 409, r.text
    assert "branch" in r.json()["detail"]


def test_a_protected_main_refuses_a_revert(client: TestClient, fx: Fixture) -> None:
    """A revert writes main's next version as surely as a save does."""
    app_id = module(client, fx)
    r = client.post(f"{base(fx)}/{app_id}/versions/1/revert", headers=hdr(fx.editor_sub))
    assert r.status_code == 409, r.text


def test_only_an_admin_protects_a_module(client: TestClient, fx: Fixture) -> None:
    """Protection is the check on editors, so an editor who could switch it off
    would not be checked by it."""
    app_id = module(client, fx, protect=False)
    r = client.put(f"{base(fx)}/{app_id}/protection", headers=hdr(fx.editor_sub),
                   json={"protected": True})
    assert r.status_code == 403, r.text


def test_merging_into_a_protected_main_needs_an_approved_proposal(
    client: TestClient, fx: Fixture,
) -> None:
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    assert act(client, fx, app_id, "merge", fx.editor_sub).status_code == 409

    r = act(client, fx, app_id, "propose", fx.editor_sub)
    assert r.status_code == 200, r.text
    assert r.json()["proposal_status"] == "open"
    assert act(client, fx, app_id, "merge", fx.editor_sub).status_code == 409

    r = act(client, fx, app_id, "approve", fx.admin_sub)
    assert r.status_code == 200, r.text
    assert r.json()["proposal_status"] == "approved"
    r = act(client, fx, app_id, "merge", fx.editor_sub)
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 2


def test_nobody_approves_their_own_changes(client: TestClient, fx: Fixture) -> None:
    """p.618's reviewers are other people. The proposer may not approve, and
    neither may whoever saved the branch last - their changes are what is
    being reviewed, whoever proposed them."""
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    act(client, fx, app_id, "propose", fx.editor_sub)
    assert act(client, fx, app_id, "approve", fx.editor_sub).status_code == 403

    r = client.put(f"{base(fx)}/{app_id}/branches/change/definition",
                   headers=hdr(fx.admin_sub), json={"definition": doc("admin edit")})
    assert r.status_code == 200, r.text
    assert act(client, fx, app_id, "approve", fx.admin_sub).status_code == 403
    assert act(client, fx, app_id, "approve", fx.owner_sub).status_code == 200


def test_a_save_after_approval_needs_reviewing_again(client: TestClient, fx: Fixture) -> None:
    """The approval was of a document that no longer exists."""
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    act(client, fx, app_id, "propose", fx.editor_sub)
    act(client, fx, app_id, "approve", fx.admin_sub)
    r = client.put(f"{base(fx)}/{app_id}/branches/change/definition",
                   headers=hdr(fx.editor_sub), json={"definition": doc("after approval")})
    assert r.status_code == 200, r.text
    assert r.json()["proposal_status"] == "open"
    assert act(client, fx, app_id, "merge", fx.editor_sub).status_code == 409


def test_a_rejected_proposal_cannot_merge(client: TestClient, fx: Fixture) -> None:
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    act(client, fx, app_id, "propose", fx.editor_sub)
    r = act(client, fx, app_id, "reject", fx.admin_sub)
    assert r.status_code == 200, r.text
    assert r.json()["proposal_status"] == "rejected"
    assert r.json()["reviewed_by_name"]
    assert act(client, fx, app_id, "merge", fx.editor_sub).status_code == 409


def test_a_review_needs_a_proposal(client: TestClient, fx: Fixture) -> None:
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    assert act(client, fx, app_id, "approve", fx.admin_sub).status_code == 409


def test_an_unprotected_module_merges_without_a_proposal(client: TestClient, fx: Fixture) -> None:
    """Proposals are p.618's merge requirement for a *protected* module; on any
    other, merging is what §698 made it."""
    app_id = module(client, fx, protect=False)
    make_branch(client, fx, app_id)
    assert act(client, fx, app_id, "merge", fx.editor_sub).status_code == 200


def test_the_branch_says_whether_this_reader_may_review_it(
    client: TestClient, fx: Fixture,
) -> None:
    """The builder shows Approve and Reject to the people who may press them."""
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    act(client, fx, app_id, "propose", fx.editor_sub)
    mine = client.get(f"{base(fx)}/{app_id}/branches/change", headers=hdr(fx.editor_sub))
    theirs = client.get(f"{base(fx)}/{app_id}/branches/change", headers=hdr(fx.admin_sub))
    viewer = client.get(f"{base(fx)}/{app_id}/branches/change", headers=hdr(fx.viewer_sub))
    assert mine.json()["can_review"] is False
    assert theirs.json()["can_review"] is True
    assert viewer.json()["can_review"] is False


def test_a_viewer_cannot_propose_or_review(client: TestClient, fx: Fixture) -> None:
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    assert act(client, fx, app_id, "propose", fx.viewer_sub).status_code == 403
    act(client, fx, app_id, "propose", fx.editor_sub)
    assert act(client, fx, app_id, "approve", fx.viewer_sub).status_code == 403


def test_whoever_made_the_branch_counts_as_its_author(client: TestClient, fx: Fixture) -> None:
    """Somebody else proposing a branch does not make its changes theirs: the
    person who created it saved it, and may not approve it."""
    app_id = module(client, fx)
    make_branch(client, fx, app_id)  # created, and so last saved, by the editor
    assert act(client, fx, app_id, "propose", fx.admin_sub).status_code == 200
    assert act(client, fx, app_id, "approve", fx.editor_sub).status_code == 403
    # Nor may whoever proposed it, though they saved none of it.
    assert act(client, fx, app_id, "approve", fx.admin_sub).status_code == 403
    assert act(client, fx, app_id, "approve", fx.owner_sub).status_code == 200


def test_a_decided_proposal_is_not_offered_for_review(client: TestClient, fx: Fixture) -> None:
    app_id = module(client, fx)
    make_branch(client, fx, app_id)
    act(client, fx, app_id, "propose", fx.editor_sub)
    act(client, fx, app_id, "approve", fx.admin_sub)
    r = client.get(f"{base(fx)}/{app_id}/branches/change", headers=hdr(fx.owner_sub))
    assert r.json()["can_review"] is False
