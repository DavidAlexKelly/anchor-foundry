"""A verdict per file, on the review surface (parity `code-repositories.md`
§4.1; Foundry `code-repositories` p.55).

> "To keep track of your progress while reviewing the changes in a pull
>  request, you can **approve or reject each file individually**." (p.55)

`apps/api/tests/test_code_review.py` owns what a verdict is and when it is
taken away; `apps/web/src/lib/file-verdict.test.ts` owns whose mark is whose
and what a press sends. What needs a browser is the pair neither can see: that
the controls show **my** state rather than anybody's, and that a second
reviewer is not offered a mark they never made.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import TOKENS_FILE, WEB_BASE


def make_model(mod: Module, name: str) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/models",
        {"name": name, "language": "sql", "code": "SELECT 1", "inputs": []},
    )


def propose(mod: Module, model: dict, summary: str, code: str) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/code/proposals",
        {"summary": summary, "description": "",
         "changes": [{"model_id": model["id"], "code": code}]},
    )


def open_review(page, mod: Module, proposal_id: str) -> None:
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/models"
        f"?proposal={proposal_id}"
    )
    expect(page.get_by_test_id("file-marks")).to_be_visible(timeout=30000)


def test_a_file_can_be_approved_and_the_control_says_so(page, api) -> None:
    """p.55, and the state has to be visible: a verdict a reviewer cannot see
    they gave is a verdict they will give twice."""
    mod = Module(api, "Verdict approve")
    model = make_model(mod, f"v_{uuid.uuid4().hex[:6]}")
    proposal = propose(mod, model, "Change it", "SELECT 2")
    open_review(page, mod, proposal["id"])

    marks = page.get_by_test_id("file-marks")
    expect(marks).to_have_attribute("data-state", "unread")
    page.get_by_test_id("mark-approved").click()
    expect(marks).to_have_attribute("data-state", "approved")
    expect(page.get_by_test_id("mark-approved")).to_have_attribute("aria-pressed", "true")

    # **And my own verdict is not reported back to me as somebody else's.** The
    # controls above already say where I am; a line that also said "me@x
    # approved" would turn a summary of what other people think into one I
    # have to subtract myself from.
    expect(page.get_by_test_id("others-say")).to_have_count(0)


def test_a_verdict_can_be_changed_and_taken_back(page, api) -> None:
    """Pressing the pressed one clears it — the only way back to unread, and it
    matters because a verdict nobody meant to give is worse than none."""
    mod = Module(api, "Verdict change")
    model = make_model(mod, f"v_{uuid.uuid4().hex[:6]}")
    proposal = propose(mod, model, "Change it", "SELECT 2")
    open_review(page, mod, proposal["id"])

    marks = page.get_by_test_id("file-marks")
    page.get_by_test_id("mark-approved").click()
    expect(marks).to_have_attribute("data-state", "approved")

    page.get_by_test_id("mark-rejected").click()
    expect(marks).to_have_attribute("data-state", "rejected")

    page.get_by_test_id("mark-rejected").click()
    expect(marks).to_have_attribute("data-state", "unread")


def test_reading_without_a_verdict_is_still_a_state(page, api) -> None:
    """What marking meant before verdicts existed, and where a reviewer spends
    most of a large diff."""
    mod = Module(api, "Verdict read")
    model = make_model(mod, f"v_{uuid.uuid4().hex[:6]}")
    proposal = propose(mod, model, "Change it", "SELECT 2")
    open_review(page, mod, proposal["id"])

    page.get_by_test_id("mark-read").click()
    expect(page.get_by_test_id("file-marks")).to_have_attribute("data-state", "read")


def test_an_edit_takes_my_verdict_away(page, api) -> None:
    """db 0036's anchor, which the verdict inherits by riding on the same row:
    approving code that has since changed is the failure this could most easily
    have introduced."""
    mod = Module(api, "Verdict stale")
    model = make_model(mod, f"v_{uuid.uuid4().hex[:6]}")
    proposal = propose(mod, model, "Change it", "SELECT 2")
    open_review(page, mod, proposal["id"])

    page.get_by_test_id("mark-approved").click()
    expect(page.get_by_test_id("file-marks")).to_have_attribute("data-state", "approved")

    mod.api.call(
        "PATCH", f"{mod.base}/code/proposals/{proposal['id']}",
        {"changes": [{"model_id": model["id"], "code": "SELECT 3"}]},
    )
    page.reload()
    expect(page.get_by_test_id("file-marks")).to_have_attribute(
        "data-state", "unread", timeout=30000
    )


def test_another_reviewer_s_verdict_is_shown_and_not_mine_to_undo(page, api) -> None:
    """**The defect this unit had to fix before it could add anything.** The
    Unmark button was drawn whenever *anybody* had read the file, so a second
    reviewer arriving at a colleague's mark was offered "Unmark" for a mark
    they had never made — and pressing it did nothing they could see, because
    the delete is scoped to the caller."""
    import json

    mod = Module(api, "Verdict others")
    model = make_model(mod, f"v_{uuid.uuid4().hex[:6]}")
    proposal = propose(mod, model, "Change it", "SELECT 2")

    # The admin marks it; the browser is signed in as somebody else.
    with open(TOKENS_FILE) as handle:
        tokens = json.load(handle)
    from api import Api

    admin = Api(api.base, tokens["admin@acme.dev.local"])
    admin.call(
        "PUT", f"{mod.base}/code/proposals/{proposal['id']}/read",
        {"model_id": model["id"], "read": True, "verdict": "rejected"},
    )

    open_review(page, mod, proposal["id"])
    expect(page.get_by_test_id("others-say")).to_contain_text("rejected")
    expect(page.get_by_test_id("others-say")).to_contain_text("admin@acme.dev.local")
    # And my own state is untouched by theirs.
    expect(page.get_by_test_id("file-marks")).to_have_attribute("data-state", "unread")
