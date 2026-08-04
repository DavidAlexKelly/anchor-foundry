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


# ---- the review surface (ROADMAP.md phase 2, item 2.7) -----------------------
def test_a_side_by_side_diff_carries_both_sides_line_numbers() -> None:
    """A comment anchors to a line of a file. Recovering that from a unified
    diff means re-reading hunk headers and counting, so it is computed from
    the opcodes instead."""
    from src.services.code import side_by_side

    rows = side_by_side("a\nb\nc", "a\nB\nc\nd")
    assert [(r["kind"], r["live_line"], r["proposed_line"]) for r in rows] == [
        ("same", 1, 1),
        ("changed", 2, 2),
        ("same", 3, 3),
        ("added", None, 4),
    ]
    assert rows[1]["live_text"] == "b" and rows[1]["proposed_text"] == "B"


def test_an_uneven_replacement_pairs_what_it_can_and_no_more() -> None:
    """Three lines becoming five is three changes and two additions, not five
    of anything - the alignment has to stop where the pairing does."""
    from src.services.code import side_by_side

    rows = side_by_side("1\n2\n3", "a\nb\nc\nd\ne")
    kinds = [r["kind"] for r in rows]
    assert kinds == ["changed", "changed", "changed", "added", "added"]
    assert [r["proposed_line"] for r in rows] == [1, 2, 3, 4, 5]
    assert [r["live_line"] for r in rows] == [1, 2, 3, None, None]


def test_a_deletion_is_one_sided() -> None:
    from src.services.code import side_by_side

    rows = side_by_side("keep\ngone\n", "keep\n")
    assert [(r["kind"], r["live_text"], r["proposed_text"]) for r in rows] == [
        ("same", "keep", "keep"),
        ("removed", "gone", None),
    ]


def test_a_comment_anchors_to_a_line_and_comes_back_on_the_file(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1,
              "body": "why is val needed here?"},
    )
    assert r.status_code == 201, r.text
    detail = r.json()
    assert len(detail["comments"]) == 1
    comment = detail["comments"][0]
    assert comment["line"] == 1 and comment["side"] == "proposed"
    assert comment["outdated"] is False and comment["resolved_at"] is None
    assert comment["author_email"]
    # And it arrives on the file it hangs on, not only in the timeline.
    assert [c["id"] for c in detail["files"][0]["comments"]] == [comment["id"]]


def test_a_viewer_may_comment_but_still_may_not_approve(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """A verdict is editor-level because approving a change is as consequential
    as making one. Asking a question about a line is not a verdict."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    said = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "a question"},
    )
    assert said.status_code == 201, said.text
    approved = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/reviews", headers=hdr(fx.viewer_sub),
        json={"verdict": "approve", "comment": ""},
    )
    assert approved.status_code == 403, approved.text


def test_the_author_may_answer_a_question_on_their_own_proposal(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """They may not approve it - that is checked elsewhere - but a proposal
    whose author cannot reply is a one-directional conversation."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.editor_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "because X"},
    )
    assert r.status_code == 201, r.text


def test_editing_a_proposal_outdates_the_comments_written_about_it(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Line 14 of the code somebody read is not line 14 of the code somebody
    else will apply. The comment is marked, not hidden: it said something true
    about the code it was written against."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "on the old text"},
    )
    edited = client.patch(
        f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.editor_sub),
        json={"changes": [{"model_id": model, "code": "SELECT id, val, val*2 AS d FROM raw"}]},
    )
    assert edited.status_code == 200, edited.text
    assert len(edited.json()["comments"]) == 1
    assert edited.json()["comments"][0]["outdated"] is True
    assert edited.json()["comments"][0]["body"] == "on the old text"


def test_a_comment_cannot_hang_on_a_file_the_proposal_does_not_change(
    client: TestClient, fx: Fixture, model: str, source: str
) -> None:
    """A remark that exists and renders nowhere is worse than one refused."""
    other = client.post(
        f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Elsewhere {uuid.uuid4().hex[:6]}", "code": "SELECT id FROM raw",
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    ).json()["id"]
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": other, "side": "proposed", "line": 1, "body": "nowhere"},
    )
    assert r.status_code == 422, r.text
    assert "does not change that file" in r.json()["detail"]


def test_a_comment_can_be_settled_and_unsettled(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    made = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "settle me"},
    ).json()["comments"][0]

    on = client.patch(
        f"{cbase(fx)}/proposals/{p['id']}/comments/{made['id']}",
        headers=hdr(fx.viewer_sub), json={"resolved": True},
    )
    assert on.status_code == 200, on.text
    assert on.json()["comments"][0]["resolved_at"] is not None

    off = client.patch(
        f"{cbase(fx)}/proposals/{p['id']}/comments/{made['id']}",
        headers=hdr(fx.viewer_sub), json={"resolved": False},
    )
    assert off.json()["comments"][0]["resolved_at"] is None


def test_resolution_survives_an_edit_while_the_anchor_does_not(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Two different claims. "This line moved" is derived from the files;
    "we settled this" is a decision somebody made, and unsettling it silently
    would put the conversation back without anybody saying anything."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    made = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "settled"},
    ).json()["comments"][0]
    client.patch(f"{cbase(fx)}/proposals/{p['id']}/comments/{made['id']}",
                 headers=hdr(fx.viewer_sub), json={"resolved": True})

    after = client.patch(
        f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.editor_sub),
        json={"changes": [{"model_id": model, "code": "SELECT id, val, 1 AS z FROM raw"}]},
    ).json()
    assert after["comments"][0]["outdated"] is True
    assert after["comments"][0]["resolved_at"] is not None


def test_marking_a_file_read_is_per_reviewer_and_cleared_by_an_edit(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The same rule an approval follows: a mark from before the last edit
    says somebody read a file that no longer exists in that form."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    marked = client.put(
        f"{cbase(fx)}/proposals/{p['id']}/read", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "read": True},
    )
    assert marked.status_code == 200, marked.text
    read_by = marked.json()["files"][0]["read_by"]
    assert len(read_by) == 1 and read_by[0]["reviewer_email"]

    after = client.patch(
        f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.editor_sub),
        json={"changes": [{"model_id": model, "code": "SELECT id, val, 2 AS z FROM raw"}]},
    )
    assert after.json()["files"][0]["read_by"] == []


def test_unmarking_a_file_removes_only_that_reviewers_mark(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    for sub in (fx.viewer_sub, fx.admin_sub):
        client.put(f"{cbase(fx)}/proposals/{p['id']}/read", headers=hdr(sub),
                   json={"model_id": model, "read": True})
    both = client.get(f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.viewer_sub))
    assert len(both.json()["files"][0]["read_by"]) == 2

    cleared = client.put(
        f"{cbase(fx)}/proposals/{p['id']}/read", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "read": False},
    )
    assert len(cleared.json()["files"][0]["read_by"]) == 1


def test_a_closed_proposal_cannot_be_commented_on(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{p['id']}/withdraw", headers=hdr(fx.editor_sub))
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "too late"},
    )
    assert r.status_code == 422, r.text
    assert "closed" in r.json()["detail"]


def test_the_proposal_detail_carries_aligned_rows_for_every_file(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    detail = client.get(
        f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    rows = detail["files"][0]["rows"]
    assert rows and all(r["kind"] in ("same", "added", "removed", "changed") for r in rows)
    # The proposed side of the rows reconstructs the proposed file exactly -
    # a rendering that cannot be read back is a rendering that can drift.
    rebuilt = "\n".join(
        r["proposed_text"] for r in rows if r["proposed_text"] is not None
    )
    assert rebuilt == detail["files"][0]["code"].rstrip("\n")


def test_an_outsider_cannot_comment(client: TestClient, fx: Fixture, model: str) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.post(
            f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(sub),
            json={"model_id": model, "side": "proposed", "line": 1, "body": "hello"},
        )
        assert r.status_code in (403, 404), (sub, r.text)


def test_a_comment_is_anchored_to_a_version_not_to_a_moment(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The anchor is the proposal's own `files_updated_at`, not the API's
    clock. Two clocks deciding whether a comment is current is one clock too
    many - and the one that matters is the one the files are stamped with."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    detail = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "side": "proposed", "line": 1, "body": "anchored"},
    ).json()
    assert detail["comments"][0]["anchored_at"] == detail["files_updated_at"]


def test_a_comment_belonging_to_another_proposal_is_not_resolvable_here(
    client: TestClient, fx: Fixture, model: str, source: str
) -> None:
    """An id in a path is never trusted to belong to the resource in the path -
    the same rule the repository routes enforce for commits."""
    other_model = client.post(
        f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Second {uuid.uuid4().hex[:6]}", "code": "SELECT id FROM raw",
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    ).json()["id"]
    one = propose(client, fx, model, "SELECT id, val FROM raw")
    two = propose(client, fx, other_model, "SELECT id, val FROM raw", summary="Other")
    made = client.post(
        f"{cbase(fx)}/proposals/{two['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": other_model, "side": "proposed", "line": 1, "body": "over here"},
    ).json()["comments"][0]

    r = client.patch(
        f"{cbase(fx)}/proposals/{one['id']}/comments/{made['id']}",
        headers=hdr(fx.viewer_sub), json={"resolved": True},
    )
    assert r.status_code == 404, r.text

    still = client.get(f"{cbase(fx)}/proposals/{two['id']}", headers=hdr(fx.viewer_sub))
    assert still.json()["comments"][0]["resolved_at"] is None


# ---- checks (ROADMAP.md phase 2, item 2.8) -----------------------------------
def checks_of(detail: dict, name: str) -> list[dict]:
    return [c for c in detail["checks"] if c["name"] == name]


def run_checks(client: TestClient, fx: Fixture, proposal_id: str) -> dict:
    r = client.post(f"{cbase(fx)}/proposals/{proposal_id}/checks", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_proposal_starts_with_no_checks_and_is_not_blocked_by_that(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """A gate that engages by default leaves every project that turns review on
    unable to apply anything until somebody finds the button - the argument
    0031 already made for review itself."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    assert p["checks"] == []
    assert not any("check" in b for b in p["blockers"])


def test_a_transform_that_runs_passes_and_reports_its_columns(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    detail = run_checks(client, fx, p["id"])
    ran = checks_of(detail, "transform_runs")
    assert len(ran) == 1 and ran[0]["status"] == "pass", ran
    assert [c["name"] for c in ran[0]["detail"]["columns"]] == ["id", "val"]
    assert ran[0]["stale"] is False and ran[0]["ran_by_email"]
    # and both checks arrive on the file they are about, not only in the flat
    # list the timeline reads.
    assert sorted(c["name"] for c in detail["files"][0]["checks"]) == [
        "schema_compatible", "transform_runs",
    ]


def test_a_transform_that_does_not_run_fails_the_check_and_blocks_applying(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """This is the whole item: find out at review time rather than at run
    time."""
    p = propose(client, fx, model, "SELECT id, nosuchcolumn FROM raw")
    detail = run_checks(client, fx, p["id"])
    ran = checks_of(detail, "transform_runs")[0]
    assert ran["status"] == "fail", ran
    assert "nosuchcolumn" in ran["summary"]
    assert any(b.startswith("a check failed") for b in detail["blockers"]), detail["blockers"]

    # and the gate actually holds, even with an approval.
    client.post(f"{cbase(fx)}/proposals/{p['id']}/reviews", headers=hdr(fx.owner_sub),
                json={"verdict": "approve", "comment": ""})
    applied = client.post(f"{cbase(fx)}/proposals/{p['id']}/apply", headers=hdr(fx.editor_sub))
    assert applied.status_code == 422, applied.text
    assert "a check failed" in applied.json()["detail"]


def test_the_schema_check_has_nothing_to_compare_before_the_model_has_run(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """A model with no output dataset yet cannot break one."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    detail = run_checks(client, fx, p["id"])
    schema = checks_of(detail, "schema_compatible")[0]
    assert schema["status"] == "pass"
    assert "not written a dataset yet" in schema["summary"]


def test_editing_a_proposal_makes_its_checks_stale_and_they_stop_gating(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """A result older than the current files describes code nobody will apply.
    Blocking on it would mean an edit made to *fix* a failure keeps the failure
    in place until somebody re-runs."""
    p = propose(client, fx, model, "SELECT id, nosuchcolumn FROM raw")
    failed = run_checks(client, fx, p["id"])
    assert any(b.startswith("a check failed") for b in failed["blockers"])

    fixed = client.patch(
        f"{cbase(fx)}/proposals/{p['id']}", headers=hdr(fx.editor_sub),
        json={"changes": [{"model_id": model, "code": "SELECT id, val FROM raw"}]},
    ).json()
    assert all(c["stale"] for c in fixed["checks"]), fixed["checks"]
    assert not any(b.startswith("a check failed") for b in fixed["blockers"])
    # The results are still there, marked - not deleted.
    assert len(fixed["checks"]) == 2


def test_re_running_replaces_the_answer_rather_than_appending_one(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """A list of every time a check ran is a log. What a reviewer needs is the
    answer."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    first = run_checks(client, fx, p["id"])
    second = run_checks(client, fx, p["id"])
    assert len(second["checks"]) == len(first["checks"]) == 2
    assert {c["id"] for c in second["checks"]} == {c["id"] for c in first["checks"]}


def test_a_viewer_cannot_run_checks(client: TestClient, fx: Fixture, model: str) -> None:
    """A check executes the proposed SQL against datasets in the project, which
    is the act the preview endpoint gates at the same floor."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(f"{cbase(fx)}/proposals/{p['id']}/checks", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403, r.text


def test_a_closed_proposal_has_nothing_to_check(
    client: TestClient, fx: Fixture, model: str
) -> None:
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    client.post(f"{cbase(fx)}/proposals/{p['id']}/withdraw", headers=hdr(fx.editor_sub))
    r = client.post(f"{cbase(fx)}/proposals/{p['id']}/checks", headers=hdr(fx.editor_sub))
    assert r.status_code == 422, r.text
    assert "closed" in r.json()["detail"]


def _run(client: TestClient, fx: Fixture, model: str) -> dict:
    r = client.post(f"{pbase(fx)}/models/{model}/run", headers=hdr(fx.editor_sub))
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_a_change_that_drops_a_column_from_a_strict_dataset_fails_and_blocks(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The point of the item. Migration 0023's trigger would refuse this write
    when the transform ran - hours after somebody approved it. The check moves
    that refusal to review time, and reads the dataset's own policy rather than
    reimplementing one."""
    _run(client, fx, model)  # gives the model an output dataset with a schema
    out = client.get(f"{pbase(fx)}/models/{model}", headers=hdr(fx.editor_sub)).json()
    dataset_id = out["output_dataset_id"]
    assert dataset_id, out
    client.patch(f"{pbase(fx)}/datasets/{dataset_id}", headers=hdr(fx.editor_sub),
                 json={"schema_policy": "strict"})

    # The live transform selects `id`; this one does not.
    p = propose(client, fx, model, "SELECT val FROM raw")
    detail = run_checks(client, fx, p["id"])
    schema = checks_of(detail, "schema_compatible")[0]
    assert schema["status"] == "fail", schema
    assert "drops id" in schema["summary"] and "strict" in schema["summary"]
    assert [c["name"] for c in schema["detail"]["removed"]] == ["id"]
    assert any(b.startswith("a check failed") for b in detail["blockers"])


def test_the_same_change_on_a_permissive_dataset_warns_without_blocking(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Permissive is the default and means the write is allowed. It does not
    mean nothing breaks - anything reading the dropped column still does - so
    the reviewer is told, and decides."""
    _run(client, fx, model)
    p = propose(client, fx, model, "SELECT val FROM raw")
    detail = run_checks(client, fx, p["id"])
    schema = checks_of(detail, "schema_compatible")[0]
    assert schema["status"] == "warn", schema
    assert "drops id" in schema["summary"]
    assert not any(b.startswith("a check failed") for b in detail["blockers"])


def test_adding_a_column_passes_even_on_a_strict_dataset(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """0023 allows it deliberately: a policy people keep switching off is a
    policy nobody leaves on."""
    _run(client, fx, model)
    dataset_id = client.get(
        f"{pbase(fx)}/models/{model}", headers=hdr(fx.editor_sub)
    ).json()["output_dataset_id"]
    client.patch(f"{pbase(fx)}/datasets/{dataset_id}", headers=hdr(fx.editor_sub),
                 json={"schema_policy": "strict"})

    p = propose(client, fx, model, "SELECT id, val, val * 2 AS doubled FROM raw")
    detail = run_checks(client, fx, p["id"])
    schema = checks_of(detail, "schema_compatible")[0]
    assert schema["status"] == "pass", schema
    assert "doubled" in schema["summary"]


def test_a_retype_is_reported_with_both_types(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Any retype is breaking, including a widening one - 0023 decided that
    deliberately rather than encoding a type lattice per dialect."""
    _run(client, fx, model)  # the output dataset now has `id`, typed
    p = propose(client, fx, model, "SELECT CAST(id AS VARCHAR) AS id FROM raw")
    detail = run_checks(client, fx, p["id"])
    schema = checks_of(detail, "schema_compatible")[0]
    assert schema["status"] == "warn", schema
    assert "retypes id" in schema["summary"]
    retyped = schema["detail"]["retyped"][0]
    assert retyped["name"] == "id" and retyped["to"] == "VARCHAR"
    assert retyped["from"] != "VARCHAR"


def test_when_the_transform_did_not_run_the_schema_check_says_so_rather_than_passing(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """"I could not tell" is not "nothing is wrong". A schema check that
    reported `pass` because the code it was meant to judge never ran would be
    the most dangerous result on the screen."""
    _run(client, fx, model)  # so there *is* an output dataset to compare against
    p = propose(client, fx, model, "SELECT id, nosuchcolumn FROM raw")
    detail = run_checks(client, fx, p["id"])
    schema = checks_of(detail, "schema_compatible")[0]
    assert schema["status"] == "error", schema
    assert "did not run" in schema["summary"]


def test_re_running_updates_a_verdict_the_world_has_changed(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The files did not move; the dataset's policy did. A stored result that
    only ever gets written once would keep saying `warn` after the policy that
    made it a warning was tightened."""
    _run(client, fx, model)
    dataset_id = client.get(
        f"{pbase(fx)}/models/{model}", headers=hdr(fx.editor_sub)
    ).json()["output_dataset_id"]

    p = propose(client, fx, model, "SELECT val FROM raw")
    warned = run_checks(client, fx, p["id"])
    assert checks_of(warned, "schema_compatible")[0]["status"] == "warn"
    assert not any(b.startswith("a check failed") for b in warned["blockers"])

    client.patch(f"{pbase(fx)}/datasets/{dataset_id}", headers=hdr(fx.editor_sub),
                 json={"schema_policy": "strict"})
    again = run_checks(client, fx, p["id"])
    assert checks_of(again, "schema_compatible")[0]["status"] == "fail"
    assert any(b.startswith("a check failed") for b in again["blockers"])
    # Still one result, not two: re-running replaces the answer.
    assert len(checks_of(again, "schema_compatible")) == 1


def test_a_comment_naming_a_real_model_and_a_path_is_refused_not_a_500(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The anchor lookup catches a *wrong* model on its own. This is the case
    it cannot catch: a model the proposal really does change, named alongside a
    path. Two anchors is two answers to "which file is this about", and without
    the check it reaches the database's own CHECK as a 500."""
    p = propose(client, fx, model, "SELECT id, val FROM raw")
    r = client.post(
        f"{cbase(fx)}/proposals/{p['id']}/comments", headers=hdr(fx.viewer_sub),
        json={"model_id": model, "source_path": "src/anything.sql",
              "side": "proposed", "line": 1, "body": "which one?"},
    )
    assert r.status_code == 422, r.text
    assert "not both or neither" in r.json()["detail"]
