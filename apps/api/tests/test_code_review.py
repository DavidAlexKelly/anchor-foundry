"""Review-gated promotion (ROADMAP Code item 4, migration 0031).

The item asks for "a PR-like review step before a change takes effect on
whichever branch/environment is considered live", and there are no branches
here by decision (`docs/decisions/0001-where-code-lives.md`) - `models.code`
*is* live. So what these tests protect is the gate itself and the ways round
it that a review system has to refuse: approving your own work, approving code
and then swapping it, and applying an approval against a file somebody else
has since changed.
"""
from __future__ import annotations

import io
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

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("code-review-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def cbase(fx: Fixture) -> str:
    return f"{pbase(fx)}/code"


@pytest.fixture(scope="module")
def source(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Review rows {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def model(client: TestClient, fx: Fixture, source: str) -> str:
    r = client.post(
        f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Gated {uuid.uuid4().hex[:6]}", "code": "SELECT id FROM raw",
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(autouse=True)
def _review_off(client: TestClient, fx: Fixture):
    """Each test starts from the default (review off) whatever the last one
    left behind - the policy is project-wide state."""
    yield
    client.put(f"{cbase(fx)}/review-policy", headers=hdr(fx.owner_sub),
               json={"require_code_review": False})


def propose(client: TestClient, fx: Fixture, model: str, code: str,
            sub: str | None = None, summary: str = "Proposed edit") -> dict:
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(sub or fx.editor_sub),
        json={"summary": summary, "changes": [{"model_id": model, "code": code}]},
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- the gate ---------------------------------------------------------------
def test_the_gate_is_off_by_default(client: TestClient, fx: Fixture, model: str) -> None:
    """Turning review on for every existing project would break the way every
    existing project is edited (migration 0031)."""
    r = client.patch(f"{pbase(fx)}/models/{model}", headers=hdr(fx.editor_sub),
                     json={"code": "SELECT id, val FROM raw"})
    assert r.status_code == 200, r.text


def test_with_review_on_a_direct_edit_is_refused_on_both_surfaces(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The gate lives in `models.update`, not in a route, because that is the
    function that makes a definition live - and the Models editor and the Code
    change-set endpoint are two doors into it."""
    client.put(f"{cbase(fx)}/review-policy", headers=hdr(fx.owner_sub),
               json={"require_code_review": True})

    direct = client.patch(f"{pbase(fx)}/models/{model}", headers=hdr(fx.editor_sub),
                          json={"code": "SELECT id, val FROM raw"})
    assert direct.status_code == 422
    assert "requires review" in direct.json()["detail"]

    grouped = client.post(
        f"{cbase(fx)}/change-sets", headers=hdr(fx.editor_sub),
        json={"summary": "Sneak past", "changes": [{"model_id": model, "code": "SELECT 1 AS x"}]},
    )
    assert grouped.status_code == 422
    assert "requires review" in grouped.json()["detail"]


def test_the_gate_does_not_block_scheduling_changes(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Trigger mode is how and when a model runs, not what it computes.
    Gating it would leave a project that requires review unable to pause a
    job."""
    client.put(f"{cbase(fx)}/review-policy", headers=hdr(fx.owner_sub),
               json={"require_code_review": True})
    r = client.patch(f"{pbase(fx)}/models/{model}", headers=hdr(fx.editor_sub),
                     json={"trigger_mode": "manual"})
    assert r.status_code == 200, r.text


def test_only_an_owner_sets_the_policy(client: TestClient, fx: Fixture) -> None:
    """Deciding whether changes need review is a governance decision about the
    project, not an editing action within it."""
    r = client.put(f"{cbase(fx)}/review-policy", headers=hdr(fx.editor_sub),
                   json={"require_code_review": True})
    assert r.status_code == 403


# ---- the proposal lifecycle -------------------------------------------------
def test_a_proposal_is_not_a_definition(client: TestClient, fx: Fixture, model: str) -> None:
    """Nothing runs a proposal: its code lives on the proposal, and
    model_versions - what a run resolves against - is untouched until it is
    applied."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    assert proposal["state"] == "open"
    assert proposal["files"][0]["diff"].count("\n") > 0

    live = client.get(f"{pbase(fx)}/models/{model}", headers=hdr(fx.viewer_sub)).json()
    assert live["code"] == "SELECT id FROM raw"
    versions = client.get(f"{pbase(fx)}/models/{model}/versions",
                          headers=hdr(fx.viewer_sub)).json()
    assert [v["version_number"] for v in versions] == [1]


def test_applying_writes_one_change_set_and_closes_the_proposal(
    client: TestClient, fx: Fixture, model: str
) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                headers=hdr(fx.owner_sub), json={"verdict": "approve"})
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    applied = r.json()
    assert applied["state"] == "applied" and applied["change_set_id"]

    live = client.get(f"{pbase(fx)}/models/{model}", headers=hdr(fx.viewer_sub)).json()
    assert live["code"] == "SELECT id, val FROM raw"
    # The record of what happened is one change set in the same log as every
    # other edit, not a separate kind of history.
    log = client.get(f"{cbase(fx)}/history", headers=hdr(fx.viewer_sub)).json()
    entry = next(e for e in log if e["id"] == applied["change_set_id"])
    assert entry["kind"] == "change_set"


def test_an_unapproved_proposal_cannot_be_applied(
    client: TestClient, fx: Fixture, model: str
) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    assert "nobody has approved" in " ".join(proposal["blockers"])
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 422
    assert "approved" in r.json()["detail"]


def test_nobody_reviews_their_own_proposal(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """A review somebody gave themselves is not a review, and letting it count
    would make the gate a formality anyone in a hurry can perform alone."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw", sub=fx.editor_sub)
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                    headers=hdr(fx.editor_sub), json={"verdict": "approve"})
    assert r.status_code == 422
    assert "your own" in r.json()["detail"]


def test_requested_changes_block_until_the_same_reviewer_approves(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Verdicts are append-only, so changing your mind leaves both rows - what
    counts is each reviewer's latest."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    blocked = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                          headers=hdr(fx.owner_sub),
                          json={"verdict": "request_changes", "comment": "add a filter"}).json()
    assert "asked for changes" in " ".join(blocked["blockers"])

    cleared = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                          headers=hdr(fx.owner_sub), json={"verdict": "approve"}).json()
    assert cleared["blockers"] == []
    assert len(cleared["reviews"]) == 2, "both verdicts are kept"


def test_editing_a_proposal_invalidates_its_approvals(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Approve-then-swap-the-code is otherwise a way to get arbitrary code
    past a reviewer who read something else."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    approved = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                           headers=hdr(fx.owner_sub), json={"verdict": "approve"}).json()
    assert approved["blockers"] == []

    swapped = client.patch(
        f"{cbase(fx)}/proposals/{proposal['id']}", headers=hdr(fx.editor_sub),
        json={"changes": [{"model_id": model, "code": "SELECT id, val, 1 AS sneaky FROM raw"}]},
    )
    assert swapped.status_code == 200, swapped.text
    assert "nobody has approved the current version" in " ".join(swapped.json()["blockers"])
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply", headers=hdr(fx.editor_sub))
    assert r.status_code == 422


def test_editing_only_the_summary_keeps_the_approval(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The reviewer approved code, not prose."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                headers=hdr(fx.owner_sub), json={"verdict": "approve"})
    r = client.patch(f"{cbase(fx)}/proposals/{proposal['id']}", headers=hdr(fx.editor_sub),
                     json={"summary": "Clearer title"})
    assert r.status_code == 200, r.text
    assert r.json()["blockers"] == []


def test_only_the_author_edits_a_proposal(
    client: TestClient, fx: Fixture, model: str
) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw", sub=fx.editor_sub)
    r = client.patch(f"{cbase(fx)}/proposals/{proposal['id']}", headers=hdr(fx.owner_sub),
                     json={"summary": "Not mine to edit"})
    assert r.status_code == 422
    assert "author" in r.json()["detail"]


def test_a_stale_proposal_refuses_to_overwrite_work_nobody_reviewed(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The point of `base_version`. An approval is an approval of a diff
    against a particular state; applying it after somebody else edited the
    same file would silently discard their work with a reviewer's name
    attached to it."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                headers=hdr(fx.owner_sub), json={"verdict": "approve"})

    # Somebody else edits the same file in the meantime (review is off here).
    assert client.patch(f"{pbase(fx)}/models/{model}", headers=hdr(fx.owner_sub),
                        json={"code": "SELECT id FROM raw WHERE id > 1"}).status_code == 200

    detail = client.get(f"{cbase(fx)}/proposals/{proposal['id']}",
                        headers=hdr(fx.viewer_sub)).json()
    assert "changed since this was proposed" in " ".join(detail["blockers"])
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply", headers=hdr(fx.editor_sub))
    assert r.status_code == 422
    live = client.get(f"{pbase(fx)}/models/{model}", headers=hdr(fx.viewer_sub)).json()
    assert live["code"] == "SELECT id FROM raw WHERE id > 1", "the other edit survived"


def test_a_proposal_that_asks_for_nothing_is_refused(
    client: TestClient, fx: Fixture, model: str
) -> None:
    current = client.get(f"{pbase(fx)}/models/{model}", headers=hdr(fx.viewer_sub)).json()
    r = client.post(
        f"{cbase(fx)}/proposals", headers=hdr(fx.editor_sub),
        json={"summary": "No-op", "changes": [{"model_id": model, "code": current["code"]}]},
    )
    assert r.status_code == 422
    assert "unchanged" in r.json()["detail"]


def test_withdrawing_closes_it_without_applying(
    client: TestClient, fx: Fixture, model: str
) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/withdraw",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and r.json()["state"] == "withdrawn"
    assert client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                       headers=hdr(fx.owner_sub),
                       json={"verdict": "approve"}).status_code == 422
    live = client.get(f"{pbase(fx)}/models/{model}", headers=hdr(fx.viewer_sub)).json()
    assert live["code"] == "SELECT id FROM raw"


def test_an_applied_proposal_cannot_be_applied_twice(
    client: TestClient, fx: Fixture, model: str
) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                headers=hdr(fx.owner_sub), json={"verdict": "approve"})
    assert client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply",
                       headers=hdr(fx.editor_sub)).status_code == 200
    again = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply",
                        headers=hdr(fx.editor_sub))
    assert again.status_code == 422
    assert "applied" in again.json()["detail"]


# ---- permissions and audit --------------------------------------------------
def test_reviewing_is_editor_level(client: TestClient, fx: Fixture, model: str) -> None:
    """A viewer who could approve would be able to authorise an edit they are
    not allowed to write."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                    headers=hdr(fx.viewer_sub), json={"verdict": "approve"})
    assert r.status_code == 403
    assert client.get(f"{cbase(fx)}/proposals/{proposal['id']}",
                      headers=hdr(fx.viewer_sub)).status_code == 200


def test_proposals_are_scoped_to_their_project(
    client: TestClient, fx: Fixture, model: str
) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.get(f"{cbase(fx)}/proposals/{proposal['id']}", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404


def test_review_actions_are_audited(client: TestClient, fx: Fixture, model: str) -> None:
    proposal = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/reviews",
                headers=hdr(fx.owner_sub), json={"verdict": "approve"})
    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/apply", headers=hdr(fx.editor_sub))
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {"code_proposal.create", "code_proposal.review", "code_proposal.apply"} <= actions


def test_the_proposal_list_filters_by_state(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The UI asks for open proposals specifically. Worth its own test: the
    filter is a nullable enum parameter, and the first version of it made
    Postgres refuse the statement outright ("could not determine data type of
    parameter") - which never showed up until a browser called it."""
    proposal = propose(client, fx, model, "SELECT id, val FROM raw", summary="Listable")
    r = client.get(f"{cbase(fx)}/proposals?state=open", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert proposal["id"] in {p["id"] for p in r.json()}
    assert all(p["state"] == "open" for p in r.json())
    assert r.json()[0]["file_count"] == 1

    unfiltered = client.get(f"{cbase(fx)}/proposals", headers=hdr(fx.viewer_sub))
    assert unfiltered.status_code == 200, unfiltered.text
    assert proposal["id"] in {p["id"] for p in unfiltered.json()}

    client.post(f"{cbase(fx)}/proposals/{proposal['id']}/withdraw", headers=hdr(fx.editor_sub))
    still_open = client.get(f"{cbase(fx)}/proposals?state=open", headers=hdr(fx.viewer_sub))
    assert proposal["id"] not in {p["id"] for p in still_open.json()}
