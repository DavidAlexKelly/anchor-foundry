"""A module's usage metrics, on the screen (§396; `workshop` p.185-188).

> "From the Metrics tab in the Workshop editor's left sidebar, you can view
> action submission counts… The overview card displays the total number of
> action submissions across the module for a selected time period along with
> the percentage change compared to the prior equivalent period. Below the
> overview are individual actions with their submission counts and a
> proportional bar indicating relative usage." (p.185)

What the numbers *mean* is decided in `apps/web/src/lib/workshop-metrics.ts`
and what is counted is in `apps/api/tests/test_workshop_metrics.py`. What needs
a browser is the seam - that the tab reaches the right module's actions - and
one thing no unit test can check: **that the panel says what it is counting.**

p.186's reading makes `submissions` a count of the *action*, not of this
module. A panel that printed the number without saying so would be read as
"submissions made here" by anybody who had not read the page, and would be
wrong by however much the action is used elsewhere. That sentence is the
feature, not a disclaimer on it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder


@pytest.fixture(scope="module")
def module_with_action(api):
    """A module whose form runs an action of its own."""
    mod = Module(api, "Metrics")
    type_id = mod.object_type(
        columns=["id", "state"],
        rows=[{"id": f"T{i}", "state": "open"} for i in range(1, 4)],
        key="id", title="id",
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"ship_{uuid.uuid4().hex[:8]}",
            "display_name": "Ship the order",
            "editable_properties": ["state"],
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {"resolvedName": "CanvasActionForm",
                     "props": {"actionTypeId": action["id"], "title": "Ship"}},
        }),
        "variables": {},
        "events": {},
    })
    return mod, action


def open_metrics(page, mod):
    open_builder(page, mod)
    page.get_by_role("button", name="Metrics", exact=True).click()


def test_the_tab_lists_the_actions_this_module_runs(page, module_with_action):
    """The seam: the panel reaches this module's document and names what it
    finds there, by the action's display name rather than its id."""
    mod, _ = module_with_action
    open_metrics(page, mod)
    expect(page.get_by_test_id("metrics-panel")).to_be_visible()
    rows = page.get_by_test_id("metrics-rows")
    expect(rows).to_be_visible(timeout=30000)
    expect(rows).to_contain_text("Ship the order")
    # p.185's "which widgets in the module use that action".
    expect(rows).to_contain_text("1 widget")


def test_the_panel_says_what_it_is_counting(page, module_with_action):
    """**The sentence that keeps the number honest**, and the reason it is a
    feature rather than a footnote.

    p.186's "available by default for all modules and do not require any
    additional configuration" is what makes `submissions` a count of the
    action rather than of this module. Without this line a reader takes it for
    the other thing, and the panel is confidently wrong about the only number
    it reports.
    """
    mod, _ = module_with_action
    open_metrics(page, mod)
    expect(page.get_by_test_id("metrics-scope")).to_contain_text(
        "outside this module", timeout=30000)


def test_an_action_nobody_has_submitted_shows_a_zero(page, module_with_action):
    """Not an absent row. "This action exists and has been submitted nought
    times" is the most useful thing this panel says about a new module."""
    mod, _ = module_with_action
    open_metrics(page, mod)
    expect(page.get_by_test_id("metrics-total")).to_contain_text("0", timeout=30000)
    expect(page.get_by_test_id("metrics-rows")).to_contain_text("Ship the order")
    # No comparison to make, so no percentage is offered - a first period is
    # not a trend.
    expect(page.get_by_test_id("metrics-change")).to_have_count(0)


def test_the_period_picker_offers_the_three_the_pages_offer(page, module_with_action):
    """p.188's three windows: "7 days, 30 days, or 90 days. The default is 30."
    """
    mod, _ = module_with_action
    open_metrics(page, mod)
    picker = page.get_by_test_id("metrics-period")
    expect(picker).to_be_visible(timeout=30000)
    assert picker.input_value() == "30"
    options = page.eval_on_selector_all(
        "[data-testid='metrics-period'] option", "els => els.map(e => e.value)")
    assert options == ["7", "30", "90"]


def test_changing_the_period_asks_again(page, module_with_action):
    """The picker is a control, not a label: choosing a window has to reach the
    server, because the window is what the server counts over."""
    mod, _ = module_with_action
    sent: list = []
    page.route("**/canvas-apps/*/metrics*", lambda route: (
        sent.append(route.request.url), route.continue_()))
    try:
        open_metrics(page, mod)
        expect(page.get_by_test_id("metrics-rows")).to_be_visible(timeout=30000)
        page.get_by_test_id("metrics-period").select_option("90")
        expect(page.get_by_test_id("metrics-rows")).to_be_visible(timeout=30000)
    finally:
        page.unroute("**/canvas-apps/*/metrics*")

    assert any("days=30" in u for u in sent), "the default window was never asked for"
    assert any("days=90" in u for u in sent), "choosing 90 days asked for 30"


def test_a_module_that_runs_nothing_says_so(page, api):
    """**Not the same as "no submissions".** A module that runs no actions has
    nothing to report; one whose action is unused has something to report and
    the answer is zero. Collapsing them tells a builder their action is unused
    when they never wired one up."""
    bare = Module(api, "No actions")
    bare.define({"format": 2, "layout": layout({
        "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "HI"}},
    }), "variables": {}, "events": {}})

    open_metrics(page, bare)
    expect(page.get_by_test_id("metrics-empty")).to_contain_text(
        "does not run any actions", timeout=30000)
    expect(page.get_by_test_id("metrics-rows")).to_have_count(0)
