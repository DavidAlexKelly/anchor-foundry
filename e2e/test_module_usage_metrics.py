"""A Workshop module's usage metrics, on the screen (§396; `workshop` p.185-188).

**Named for the module, not for "usage metrics"**, because
`test_usage_metrics.py` is §320's and is about an *ontology type's* usage -
two different features whose pages both call the thing usage metrics. This
file was briefly written over that one, which is the strongest possible
argument for a name that says which.

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
from conftest import eventually, open_builder, publish, viewer_url


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


# ---- layout views (§397; p.186-188) ------------------------------------------
@pytest.fixture(scope="module")
def two_page_module(api):
    """A module with two pages and a header that switches between them."""
    mod = Module(api, "Views")
    mod.define({
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader", "props": {"title": "V"},
                    "isCanvas": True, "nodes": ["go2"]},
            "go2": {"resolvedName": "CanvasButton", "props": {"label": "Second"},
                    "parent": "hdr"},
            "pg1": {"resolvedName": "CanvasPage",
                    "props": {"title": "First", "pageId": "one"},
                    "isCanvas": True, "nodes": ["t1"]},
            "t1": {"resolvedName": "CanvasText",
                   "props": {"tag": "p", "text": "PAGE ONE"}, "parent": "pg1"},
            "pg2": {"resolvedName": "CanvasPage",
                    "props": {"title": "Second", "pageId": "two"},
                    "isCanvas": True, "nodes": ["t2"]},
            "t2": {"resolvedName": "CanvasText",
                   "props": {"tag": "p", "text": "PAGE TWO"}, "parent": "pg2"},
        }),
        "variables": {},
        "events": {"e_go2": {"id": "e_go2", "trigger": {"node": "go2", "on": "click"},
                             "effects": [{"type": "navigate",
                                          "config": {"page": "pg2"}}]}},
    })
    return mod


def set_tracking(api, mod, on: bool):
    api.call("PUT", f"{mod.base}/canvas-apps/{mod.app_id}/usage-tracking", {"on": on})


def layout_views(api, mod, days: int = 30) -> dict:
    body = api.call(
        "GET", f"{mod.base}/canvas-apps/{mod.app_id}/metrics?days={days}")
    return {row["node_id"]: row["views"] for row in body["layouts"]}


def test_viewing_a_module_counts_the_page_it_shows(page, api, two_page_module):
    """**The seam.** The viewer reports what is on screen and the server counts
    it - which only works if the two agree on what "on screen" means and the
    module has opted in."""
    mod = two_page_module
    set_tracking(api, mod, True)
    publish(mod)
    page.goto(viewer_url(mod))
    expect(page.get_by_text("PAGE ONE")).to_be_visible(timeout=30000)

    eventually(lambda: layout_views(api, mod), lambda v: v.get("pg1", 0) >= 1,
               what="the first page's view to be recorded")


def test_navigating_counts_the_page_navigated_to(page, api, two_page_module):
    """p.186 counts each page, so a reader moving through a module leaves a
    trail rather than one entry for wherever they landed first."""
    mod = two_page_module
    set_tracking(api, mod, True)
    publish(mod)
    page.goto(viewer_url(mod))
    expect(page.get_by_text("PAGE ONE")).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Second", exact=True).click()
    expect(page.get_by_text("PAGE TWO")).to_be_visible(timeout=30000)

    eventually(lambda: layout_views(api, mod), lambda v: v.get("pg2", 0) >= 1,
               what="the second page's view to be recorded")


def test_a_module_that_has_not_opted_in_records_nothing(page, api):
    """p.187's opt-in, from the other end - and the assertion has to be about
    an *absence*, so it comes after a positive wait on the page rendering
    (§318): otherwise it passes on a page that never loaded."""
    mod = Module(api, "Untracked")
    mod.define({"format": 2, "layout": layout({
        "pg1": {"resolvedName": "CanvasPage",
                "props": {"title": "First", "pageId": "one"},
                "isCanvas": True, "nodes": ["t1"]},
        "t1": {"resolvedName": "CanvasText",
               "props": {"tag": "p", "text": "UNTRACKED"}, "parent": "pg1"},
    }), "variables": {}, "events": {}})
    publish(mod)

    page.goto(viewer_url(mod))
    expect(page.get_by_text("UNTRACKED")).to_be_visible(timeout=30000)
    # The page has rendered and any report it was going to send has been sent.
    assert layout_views(api, mod) == {}


def test_the_builder_does_not_count_as_a_view(page, api, two_page_module):
    """p.188: "Views in Edit mode… are not tracked."

    An author arranging widgets is not a reader, and counting them would make
    the busiest page of every module the one its builder was last editing.
    Preview is the same thing: it is the author looking at their own work.
    """
    mod = two_page_module
    set_tracking(api, mod, True)
    before = layout_views(api, mod)

    open_builder(page, mod)
    # Scoped to the rendered paragraph: the builder's layout tree draws a row
    # per node, so the text of a Text widget appears twice on this screen
    # (§337 - name the control, not its neighbourhood).
    shown = page.get_by_role("paragraph").filter(has_text="PAGE ONE")
    expect(shown.first).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Preview", exact=True).click()
    expect(shown.first).to_be_visible(timeout=30000)

    assert layout_views(api, mod) == before, (
        "the builder counted as a view of the module"
    )


def test_the_panel_shows_what_was_viewed_by_name(page, api, two_page_module):
    """p.186's list, named the way the author named the pages rather than by
    node id - the panel has the counts and the editor has the tree."""
    mod = two_page_module
    set_tracking(api, mod, True)
    publish(mod)
    page.goto(viewer_url(mod))
    expect(page.get_by_text("PAGE ONE")).to_be_visible(timeout=30000)
    eventually(lambda: layout_views(api, mod), lambda v: v.get("pg1", 0) >= 1,
               what="a view to record before the panel is opened")

    open_metrics(page, mod)
    rows = page.get_by_test_id("views-rows")
    expect(rows).to_be_visible(timeout=30000)
    expect(rows).to_contain_text("First")


def test_the_panel_says_when_nothing_is_being_recorded(page, api):
    """**Three states, not two.** "No views" for a module nobody is recording
    reports it as unused when it was never watched."""
    mod = Module(api, "Off")
    mod.define({"format": 2, "layout": layout({
        "t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "OFF"}},
    }), "variables": {}, "events": {}})

    open_metrics(page, mod)
    expect(page.get_by_test_id("views-empty")).to_contain_text(
        "not being recorded", timeout=30000)


def test_the_toggle_turns_recording_on(page, api):
    """p.187: "Open Module settings. Navigate to the Metrics tab. Toggle on
    Usage Metrics Tracking.""" 
    mod = Module(api, "Toggle")
    mod.define({"format": 2, "layout": layout({
        "t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "T"}},
    }), "variables": {}, "events": {}})

    open_metrics(page, mod)
    toggle = page.get_by_test_id("metrics-tracking")
    expect(toggle).not_to_be_checked()
    # **`click` and then a polled assertion, never `check`.** Playwright's
    # `check()` reads `el.checked` in the same tick as the click and does not
    # retry that read. A *controlled* checkbox cannot satisfy it: React
    # reverts the native click on the input and writes the true value back on
    # its next render, ~14ms later under no load and later under some. The
    # claim this test makes is "ticking it turns recording on", and
    # `to_be_checked()` polls for exactly that - so it still fails if the
    # control does nothing, and stops failing when the machine is busy.
    toggle.click()
    expect(toggle).to_be_checked()
    expect(page.get_by_test_id("views-empty")).to_contain_text(
        "No layouts have been viewed", timeout=30000)


def test_the_toggle_waits_for_the_current_state(page, api):
    """A box ticked before the first read arrives saves "on", and then that
    read - which left before the save - says "off". So the box cannot be used
    until the state it shows is the module's."""
    mod = Module(api, "Toggle wait")
    mod.define({"format": 2, "layout": layout({
        "t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "W"}},
    }), "variables": {}, "events": {}})
    held = []
    page.route("**/metrics?days=*", lambda route: held.append(route))
    open_metrics(page, mod)
    toggle = page.get_by_test_id("metrics-tracking")
    expect(toggle).to_be_disabled()
    eventually(lambda: len(held), lambda n: n >= 1, what="the first read to be held")
    for route in held:
        route.continue_()
    page.unroute("**/metrics?days=*")
    expect(toggle).to_be_enabled()
    toggle.click()
    expect(page.get_by_test_id("views-empty")).to_contain_text(
        "No layouts have been viewed", timeout=30000)
