"""p.164's action metrics, on the screen (§323; `action-types` p.164-166).

    "Action metrics display the near real-time usage of an action type over the
     last 30 days… Success/failure metrics… P95 duration metric… You are also
     able to access run history, which provides a complete view of a given
     action's executions over the past seven days." (p.164)

    "Action metrics do not require action logs to be displayed. **Unlike action
     logs, action metrics track failures.**" (p.165)

The counting is in `apps/api/tests/test_action_metrics.py` and the wording in
`apps/web/src/lib/action-metrics.test.ts`. What needs a browser is the claim
neither can reach: that **a submission refused by the server appears in the
numbers a person is looking at**.

That is one round trip end to end — a form refuses, a row is written on a
connection that outlives the refusal, and a panel two queries away shows a
number one higher — and every layer of it can be right on its own while the
screen shows nothing.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import ApiError, Module
from conftest import WEB_BASE, eventually


@pytest.fixture(scope="module")
def measured(api):
    """A type, an action over it, and nothing run yet."""
    mod = Module(api, "Metrics")
    type_id = mod.object_type(
        columns=["ticket_id", "status"],
        rows=[{"ticket_id": "1", "status": "open"},
              {"ticket_id": "2", "status": "open"}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"set_status_{uuid.uuid4().hex[:8]}",
         "display_name": "Set status", "editable_properties": ["status"]},
    )
    mod.action_id = action["id"]
    return mod


def open_type(page, module) -> None:
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}"
        f"/objects/{module.object_type_id}"
    )
    # **The instances table by test id** (§321): this page now carries four
    # tables — instances, usage by application, the failure breakdown and the
    # run history — so any locator that says "the table" is one a later panel
    # breaks.
    expect(page.get_by_test_id("instances-table")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("action-metrics")).to_be_visible(timeout=30000)


def apply(api, module, ticket: str, status: str):
    """Submit the action through the API, as the screen's form would.

    The form is exercised by `test_action_undo.py`; what this file is about is
    what the *panel* says afterwards, and driving four dialogs to produce four
    runs would make every assertion below wait on something it is not testing.
    """
    instances = api.call(
        "GET", f"/workspaces/{module.workspace_id}"
                f"/object-types/{module.object_type_id}/instances",
    )["items"]
    instance = next(i for i in instances if i["primary_key"] == ticket)
    return api.call(
        "POST", f"{module.base}/actions/{module.action_id}/execute",
        {"instance_id": instance["id"], "values": {"status": status}},
    )


def test_an_action_nobody_has_run_says_so(page, api) -> None:
    """**A sentence, not an empty panel.** Zero succeeded and zero failed is a
    true pair of numbers that reads as a broken feature; p.164's metrics are
    "near real-time usage", and an action nobody has run has none."""
    mod = Module(api, "Metrics idle")
    type_id = mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "1", "status": "open"}],
        key="ticket_id", title="ticket_id",
    )
    api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"noop_{uuid.uuid4().hex[:8]}",
         "display_name": "Noop", "editable_properties": ["status"]},
    )
    open_type(page, mod)
    expect(page.get_by_test_id("metrics-idle")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("metrics-idle")).to_contain_text("30 days")
    # The figures are absent rather than a row of zeroes beside the sentence.
    expect(page.get_by_test_id("metrics-figures")).to_have_count(0)


def test_a_successful_run_reaches_the_panel(page, api, measured) -> None:
    """p.164's success count, end to end through the screen."""
    result = apply(api, measured, "1", f"open-{uuid.uuid4().hex[:4]}")
    assert result.get("ok") is True, result

    open_type(page, measured)
    expect(page.get_by_test_id("metrics-succeeded")).to_have_text("1", timeout=30000)
    # It finished, so it has a duration — and a duration is not the dash that
    # means nothing has finished.
    expect(page.get_by_test_id("metrics-p95")).not_to_have_text("—")
    expect(page.get_by_test_id("metrics-success-rate")).to_have_text("100.0%")


def test_a_refused_submission_shows_up_as_a_failure(page, api, measured) -> None:
    """**p.165's sentence, on the screen, which is the only place it counts.**

    The submission names a parameter the action does not have, so the server
    refuses it with a 422 before a run is ever opened. Until §323 that left no
    trace at all: the two failures a person actually causes were the two the
    metric could never show.

    The refusal's own answer is checked first — it really was refused — and
    then the number. Both, because either alone is satisfied by a broken half:
    a 422 with nothing recorded, or a count that moved for some other reason.
    """
    open_type(page, measured)
    started = page.get_by_test_id("metrics-failed").inner_text()

    # **The refusal is asserted as a refusal**, not merely allowed to happen.
    # A submission this platform quietly accepted would leave the count below
    # unmoved for an entirely different reason, and the test would report the
    # metric as broken.
    with pytest.raises(ApiError) as refused:
        api.call(
            "POST", f"{measured.base}/actions/{measured.action_id}/execute",
            {"instance_id": _any_instance(api, measured),
             "values": {"no_such_parameter": "x"}},
        )
    assert "422" in str(refused.value), str(refused.value)

    page.reload()
    expect(page.get_by_test_id("metrics-failed")).to_be_visible(timeout=30000)
    eventually(lambda: page.get_by_test_id("metrics-failed").inner_text(),
               lambda t: t != started,
               what="the failure count to notice the refused submission")

    # And it is named by p.166's category rather than by a column value.
    row = page.get_by_test_id("metrics-failure-invalid_parameter")
    expect(row).to_be_visible(timeout=30000)
    expect(row).to_contain_text("Invalid parameter")


def _any_instance(api, module) -> str:
    items = api.call(
        "GET", f"/workspaces/{module.workspace_id}"
                f"/object-types/{module.object_type_id}/instances",
    )["items"]
    return items[0]["id"]


def test_the_history_lists_the_refusal_beside_the_applies(page, api, measured) -> None:
    """p.164's run history, and the agreement that makes it worth opening.

    A history listing only the runs that opened would disagree with the failure
    count above it — which is worse than either number alone, because a reader
    who clicks through to see the failures finds nothing there.
    """
    open_type(page, measured)
    history = page.get_by_test_id("run-history")
    expect(history).to_be_visible(timeout=30000)
    # The positive wait first: the table has rendered rows (§318). Only then is
    # the presence of a failed one a fact about the product.
    expect(history.locator("tbody tr").first).to_be_visible(timeout=30000)
    expect(history).to_contain_text("Succeeded")
    expect(history).to_contain_text("Failed — Invalid parameter")
    # A run has an author. "Former member" would mean the person who submitted
    # it has left, which is not true of a run made moments ago.
    expect(history).not_to_contain_text("Former member")


def test_a_type_with_no_actions_has_no_metrics_panel(page, api) -> None:
    """**Absent, not empty** (§214).

    An object type with no action has no action metrics, and a panel drawn
    empty invites somebody to wonder why the numbers never move. The positive
    wait is on the instances table, so the absence below is about the product
    rather than about a page that has not finished (§318).
    """
    mod = Module(api, "Metrics none")
    mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "1", "status": "open"}],
        key="ticket_id", title="ticket_id",
    )
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}"
        f"/objects/{mod.object_type_id}"
    )
    expect(page.get_by_test_id("instances-table")).to_be_visible(timeout=30000)
    # The usage panel is on the same page and does render, so this is a page
    # that got as far as drawing its panels.
    expect(page.get_by_test_id("usage-panel")).to_be_visible(timeout=30000)
    # **The slot is empty, which is a stronger claim than "the panel is
    # missing".** Asserting only that `action-metrics-section` is absent is
    # satisfied by anything at all rendering in its place — a heading with no
    # numbers under it, a spinner that never resolves, a stray line of text —
    # and a mutant that put one there survived on exactly that. An empty slot
    # says nothing is drawn here, which is what §214 is about.
    slot = page.get_by_test_id("action-metrics-slot")
    expect(slot).to_have_count(1)
    expect(slot).to_be_empty()
    expect(page.get_by_test_id("action-metrics-section")).to_have_count(0)
