"""The Performance Profiler (§394; parity `workshop.md` §9; p.177-178).

> "To use Performance Profiler, enter Edit mode, open the Profiler tab, and
> select Reload in Profiler Mode… A banner will be displayed at the top of the
> page." (p.177)

> "The profiler will display: The total module load time. The timeline view as
> widget and variables load or reload. The breakdown of load time by widgets
> and variables." (p.178)

**This row was blocked until §392-§393**, and by the sentence right under that
list: *"Only widgets and variables that affect the on-screen display are
calculated… This mirrors the behavior and performance that users experience in
View mode."* A profiler over an evaluator that computed the whole graph would
have been an accurate measurement of a program no reader runs.

What the numbers *mean* is decided in `profiler.ts` and tested there. What
needs a browser is the seam, and it has three parts that only exist together:
the mode survives a reload (it is in the address, because p.177 refreshes the
page so recording starts at initialisation), the recorder is actually
listening, and the rows that arrive are this module's.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, open_builder, settled


@pytest.fixture(scope="module")
def two_pages(api):
    """Two pages, each with its own derived variable, and an Object Table.

    **Both halves of p.178 need a module that has both.** The table is what
    makes a *request* row possible at all - a Text widget issues no query, so a
    module of text can only ever exercise the variable half. And the second
    page is what makes the lazy rule observable: p.178's "only widgets and
    variables that affect the on-screen display are calculated" is a claim
    about what is *absent* from the breakdown.
    """
    mod = Module(api, "Profiled pages")
    type_id = mod.object_type(
        columns=["id", "name"],
        rows=[{"id": f"P{i}", "name": f"Row {i}"} for i in range(1, 4)],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader", "props": {"title": "P"},
                    "isCanvas": True, "nodes": ["go2", "open"]},
            "go2": {"resolvedName": "CanvasButton", "props": {"label": "Second"},
                    "parent": "hdr"},
            "open": {"resolvedName": "CanvasButton", "props": {"label": "Detail"},
                     "parent": "hdr"},
            "pg1": {"resolvedName": "CanvasPage",
                    "props": {"title": "One", "pageId": "one"},
                    "isCanvas": True, "nodes": ["one_txt", "tbl"]},
            "one_txt": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "FIRST={{v_first}}"},
                        "parent": "pg1"},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_rows", "columns": "id,name",
                              "pageSize": 25},
                    "parent": "pg1"},
            "ov": {"resolvedName": "CanvasOverlay",
                   "props": {"title": "Detail"},
                   "isCanvas": True, "nodes": ["ov_txt"]},
            "ov_txt": {"resolvedName": "CanvasText",
                       "props": {"tag": "p", "text": "OVER={{v_over}}"},
                       "parent": "ov"},
            "pg2": {"resolvedName": "CanvasPage",
                    "props": {"title": "Two", "pageId": "two"},
                    "isCanvas": True, "nodes": ["two_txt"]},
            "two_txt": {"resolvedName": "CanvasText",
                        "props": {"tag": "p", "text": "SECOND={{v_second}}"},
                        "parent": "pg2"},
        }),
        "variables": {
            "v_rows": {"id": "v_rows", "kind": "object_set", "label": "The rows",
                       "object_set": object_set(type_id)},
            "v_first_in": {"id": "v_first_in", "kind": "string", "label": "first in",
                           "default": "ONE"},
            "v_first": {"id": "v_first", "kind": "string", "label": "First page value",
                        "derivation": {"transform": "concat", "inputs": ["v_first_in"]}},
            "v_second_in": {"id": "v_second_in", "kind": "string", "label": "second in",
                            "default": "TWO"},
            "v_second": {"id": "v_second", "kind": "string",
                         "label": "Second page value",
                         "derivation": {"transform": "concat", "inputs": ["v_second_in"]}},
            "v_over_in": {"id": "v_over_in", "kind": "string", "label": "over in",
                          "default": "DEEP"},
            "v_over": {"id": "v_over", "kind": "string", "label": "Overlay value",
                       "derivation": {"transform": "concat", "inputs": ["v_over_in"]}},
        },
        "events": {
            "e_go2": {"id": "e_go2", "trigger": {"node": "go2", "on": "click"},
                      "effects": [{"type": "navigate", "config": {"page": "pg2"}}]},
            "e_open": {"id": "e_open", "trigger": {"node": "open", "on": "click"},
                       "effects": [{"type": "navigate", "config": {"page": "ov"}}]},
        },
    })
    return mod


@pytest.fixture(scope="module")
def profiled(api):
    """A module whose text is derived, so a row in the breakdown is evidence
    the evaluator ran rather than that the document had a default in it."""
    mod = Module(api, "Profiled")
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "VALUE={{v_shown}}"}},
        }),
        "variables": {
            "v_source": {"id": "v_source", "kind": "string", "label": "Source",
                         "default": "HERE"},
            "v_shown": {"id": "v_shown", "kind": "string", "label": "Shown value",
                        "derivation": {"transform": "concat", "inputs": ["v_source"]}},
        },
        "events": {},
    })
    return mod


def open_profiler_tab(page, mod):
    open_builder(page, mod)
    page.get_by_role("button", name="Profiler", exact=True).click()


def test_the_profiler_tab_offers_the_reload_and_records_nothing_yet(page, profiled):
    """p.177's entry point. Before the reload there is no recording, and the
    panel says what the control will do rather than showing an empty result -
    which would read as a module that loaded nothing."""
    open_profiler_tab(page, profiled)
    expect(page.get_by_test_id("profiler-panel")).to_be_visible()
    expect(page.get_by_test_id("profiler-enter")).to_be_visible()
    expect(page.get_by_test_id("profiler-banner")).to_have_count(0)


def test_entering_profiler_mode_reloads_and_shows_the_banner(page, profiled):
    """**The reload is the feature** (p.177): recording has to start at the
    module's initialisation, so the mode lives in the address and entering is a
    navigation. The banner is p.177's own requirement and carries the way out,
    because a mode whose exit is only in a panel is a mode people get stuck in.
    """
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    assert "profiler=1" in page.url


def test_the_profiler_records_this_modules_variables(page, profiled):
    """p.178's breakdown, the variable half - which is exact here rather than
    apportioned, because the evaluator times each variable and this platform
    resolves them all in one request.

    Asserted by the author's *label* rather than the id: a breakdown of
    `v_shown` is a list somebody has to decode, and the panel diagnosing a slow
    module has to say what the author called it.
    """
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)

    # No second click: the reload lands on the Profiler tab, because that is
    # where the control that caused it lives (p.177).
    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_be_visible(timeout=30000)
    expect(breakdown).to_contain_text("Shown value")
    expect(breakdown).to_contain_text("Source")
    expect(breakdown).to_contain_text("Variable")


def test_the_total_is_reported_and_is_not_a_measurement_of_nothing(page, profiled):
    """p.178's "total module load time". The summary must say what loaded, not
    `0ms` - a measurement of nothing wearing the clothes of a fast module is
    the one answer this panel must never give (§214)."""
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)

    total = page.get_by_test_id("profiler-total")
    expect(total).to_be_visible(timeout=30000)
    expect(total).to_contain_text("variable")
    expect(total).not_to_contain_text("Nothing has loaded")


def test_the_timeline_is_drawn_beside_the_breakdown(page, profiled):
    """p.178 lists them separately because they answer different questions: the
    breakdown asks what was expensive, the timeline asks what was waiting on
    what."""
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)

    expect(page.get_by_test_id("profiler-timeline")).to_be_visible(timeout=30000)
    expect(page.locator(".canvas-profiler-span").first).to_be_visible()


def test_clearing_empties_the_panel_without_leaving_profiler_mode(page, profiled):
    """p.178's "clear all captured load events". A reader clears in order to
    watch *one* interaction, so the mode has to survive it - clearing that also
    exited would make the control useless for the thing it is for."""
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("profiler-breakdown")).to_be_visible(timeout=30000)

    page.get_by_test_id("profiler-clear").click()
    expect(page.get_by_test_id("profiler-total")).to_contain_text("Nothing has loaded")
    expect(page.get_by_test_id("profiler-breakdown")).to_have_count(0)
    expect(page.get_by_test_id("profiler-banner")).to_be_visible()


def test_exiting_reloads_out_of_profiler_mode(page, profiled):
    """p.177: "Exiting Profiler mode will refresh the module's web browser
    page." The address is what says so, and the banner going is what a reader
    sees."""
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)

    page.get_by_test_id("profiler-exit").click()
    expect(page.get_by_test_id("profiler-banner")).to_have_count(0, timeout=30000)
    assert "profiler=1" not in page.url


def test_a_module_opened_normally_is_not_measured(page, profiled):
    """The counterweight, and the one that keeps the rest honest: the server is
    asked to time variables only when a profiler is listening. A module opened
    without the flag must not be recording, or "off by default" is a claim
    nothing checks."""
    import contextlib
    import json

    sent: list = []

    def record(route):
        body = route.request.post_data
        if body:
            with contextlib.suppress(ValueError):
                sent.append(json.loads(body))
        route.continue_()

    page.route("**/variables/evaluate", record)
    try:
        open_builder(page, profiled)
        settled(page)
        expect(page.get_by_text("VALUE=HERE")).to_be_visible(timeout=30000)
    finally:
        page.unroute("**/variables/evaluate")

    assert sent, "the module never resolved its variables"
    assert all(not b.get("profile") for b in sent), \
        "a module nobody is profiling asked the server to measure"


def test_the_panel_is_readable_while_profiling(page, profiled):
    """**The one the first run found**, and it is p.177 rather than a nicety:
    "To exit Profiler mode select Exit at the top of the Profiler panel or in
    the Profiler mode banner" - so the panel is on screen *while* profiling.

    Profiler mode drops the canvas to run mode so the measurement is of what a
    viewer experiences (p.178), and the first version tied that to the same
    flag that draws the settings column. The panel vanished exactly when it had
    something to say, and four tests timed out looking for a tab they had just
    pressed a button on.
    """
    open_profiler_tab(page, profiled)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    # The panel, and the tab it lives behind, are both still there.
    expect(page.get_by_test_id("profiler-panel")).to_be_visible()
    expect(page.get_by_role("button", name="Profiler", exact=True)).to_be_visible()


def test_a_widget_that_queries_shows_up_as_a_request(page, two_pages):
    """p.178's other half, and the one R1 found missing (§394).

    Every test above reads a *variable* row, which arrives from the bridge.
    The request half comes from a different place entirely - a subscription to
    the query cache - and a module of text issues no queries, so disabling that
    subscription altogether passed all nine of them.

    A row says what loaded rather than who asked: sixteen widget types share
    one cache and a key names the request. The column says "Request" for that
    reason, and this asserts the honest thing rather than a widget name the
    panel does not have.
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)

    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_be_visible(timeout=30000)
    expect(breakdown).to_contain_text("Request", timeout=30000)


def test_the_profile_is_of_what_a_viewer_sees(page, two_pages):
    """**p.178's sentence, which is why this feature was blocked until §392.**

    "Only widgets and variables that affect the on-screen display are
    calculated… This mirrors the behavior and performance that users experience
    in View mode." Profiler mode therefore drops the canvas to run mode, where
    the lazy rule applies - and in edit mode every page is on screen, so every
    page's variables would be computed and the breakdown would describe a
    program no reader runs.

    The claim is about an *absence*, which is why it needs two pages: the
    second page's variable must not be in the breakdown. Removing the run-mode
    switch passed all nine earlier tests, because none of them asked what the
    numbers were a measurement *of*.
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)

    breakdown = page.get_by_test_id("profiler-breakdown")
    # Positive wait first (§318): the first page's variable is there, so the
    # second one's absence is about the lazy rule rather than about an empty
    # panel.
    expect(breakdown).to_contain_text("First page value", timeout=30000)
    expect(breakdown).not_to_contain_text("Second page value")


def test_showing_the_second_page_adds_its_variable(page, two_pages):
    """The counterweight. A profiler that never recorded the second page would
    pass the test above and be useless - p.178 wants "new layout views to
    prompt loading of new widgets and variables", captured as they happen."""
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("profiler-breakdown")).to_contain_text(
        "First page value", timeout=30000)

    # `exact=True`, because profiler mode keeps the builder chrome and the
    # layout tree draws a row per node - so "Second" also matches the tree's
    # entries for the button and for the text that mentions the variable
    # (§337: name the control, not its neighbourhood).
    page.get_by_role("button", name="Second", exact=True).click()
    expect(page.get_by_test_id("profiler-breakdown")).to_contain_text(
        "Second page value", timeout=30000)


# ---- p.178's interaction list (§395) -----------------------------------------
#
# > "You can also filter widget and variable loads based on the page or overlay
# > that triggered them, search for captured load events by widget or variable
# > name, and clear all captured load events in the profiler." (p.178)
#
# Clearing is tested above. These are the other two, and they need a module
# whose loads come from more than one page - which is what makes the filter a
# control rather than a label.
def test_loads_can_be_filtered_by_the_page_that_triggered_them(page, two_pages):
    """p.178's filter. The picker only offers pages that actually triggered
    something, so this navigates first - a module that has only ever loaded on
    one page has nothing to filter between, and offering a choice that cannot
    change the panel is a control that looks like it works (§214).
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("profiler-breakdown")).to_contain_text(
        "First page value", timeout=30000)

    page.get_by_role("button", name="Second", exact=True).click()
    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_contain_text("Second page value", timeout=30000)

    # Both pages have now triggered loads, so the filter appears and means
    # something. Picking the second leaves only what it triggered.
    chooser = page.get_by_test_id("profiler-page")
    expect(chooser).to_be_visible()
    chooser.select_option(index=2)
    expect(breakdown).to_contain_text("Second page value")
    expect(breakdown).not_to_contain_text("First page value")


def test_events_can_be_searched_by_name(page, two_pages):
    """p.178's search, over the name because that is what a reader can see.

    The positive match comes first (§318): asserting that something is gone is
    only meaningful once the panel has been shown to still be drawing.
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_contain_text("First page value", timeout=30000)

    page.get_by_test_id("profiler-search").fill("first")
    expect(breakdown).to_contain_text("First page value")
    expect(breakdown).not_to_contain_text("The rows")


def test_a_search_that_matches_nothing_says_so_rather_than_looking_empty(
    page, two_pages
):
    """**The sentence that keeps the panel honest.** "Nothing has loaded yet"
    and "no events match this filter" are different facts, and showing the
    first for the second sends somebody to diagnose a module that is fine."""
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("profiler-breakdown")).to_be_visible(timeout=30000)

    page.get_by_test_id("profiler-search").fill("nothing is called this")
    expect(page.get_by_test_id("profiler-empty")).to_contain_text("match this filter")
    expect(page.get_by_test_id("profiler-breakdown")).to_have_count(0)


def test_an_overlay_is_what_triggered_a_load_opened_over_a_page(page, two_pages):
    """p.178 says "the page **or overlay** that triggered them", and an overlay
    opens *over* a page - so both are on screen and only one of them is what
    the reader opened.

    Attributing the overlay's loads to the page underneath passed every other
    test in this file, because none of them opened an overlay.
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_contain_text("First page value", timeout=30000)

    page.get_by_role("button", name="Detail", exact=True).click()
    expect(breakdown).to_contain_text("Overlay value", timeout=30000)

    # Two layouts have triggered loads, so the filter means something. The last
    # option is the overlay, and filtering to it must leave the page's loads
    # out - which is only true if the overlay was recorded as the trigger.
    # Selected by value rather than by index: the options are ordered by which
    # layout triggered something first, so an index is a guess about timing.
    chooser = page.get_by_test_id("profiler-page")
    expect(chooser).to_be_visible()
    chooser.select_option("ov")
    expect(breakdown).to_contain_text("Overlay value")
    expect(breakdown).not_to_contain_text("First page value")


def test_filtering_does_not_move_the_timelines_zero(page, two_pages):
    """**The scale is the whole run, not the rows on screen.**

    A timeline that rescaled to the filtered rows would put the second page's
    loads at the far left - as though they had happened at start-up - and
    comparing when two pages loaded is the reason to filter in the first place.

    Asserted on the bar's offset, because that is where the claim lives: the
    second page loaded well after the first, so its bar must still start some
    way along the track once everything else is filtered out.
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_contain_text("First page value", timeout=30000)

    # **The run has to continue well past the first load, so this makes it.**
    # The early bar's offset is (its start) / (the run's end), and without a
    # pause the run's end is however soon this line clicked: on a slow runner
    # the first load started late and the second page followed at once, and
    # the bar sat at 54% - failing the precondition below on timing alone. A
    # pause is the input here, not a wait for something: what is being set up
    # is "the second page was opened some time after the first", which is the
    # situation a filter-to-compare exists for.
    page.wait_for_timeout(3000)
    page.get_by_role("button", name="Second", exact=True).click()
    expect(breakdown).to_contain_text("Second page value", timeout=30000)

    # **Measured before and after, because the claim is that it does not
    # move.** An absolute threshold cannot tell the two apart: a late load is
    # near the right-hand end on the full scale *and* near it on a scale made
    # only of itself. The number that changes under a rescale is this one,
    # compared with itself.
    def offset_of(name: str) -> float:
        return page.evaluate(
            """(wanted) => {
                const rows = [...document.querySelectorAll(
                    '[data-testid=profiler-timeline] li')];
                const row = rows.find((li) => li.textContent.includes(wanted));
                return row ? parseFloat(row.querySelector(
                    '.canvas-profiler-span').style.left) : -1;
            }""",
            name,
        )

    # **Measured on an *early* row, which is the half that makes this
    # checkable.** Filtering to the *last* row cannot tell the two apart: its
    # own end is where the whole run ends, so a scale made only of it is the
    # same scale. The first page's value loaded near the beginning, so under a
    # rescale it would jump from near the left to the far right.
    before = offset_of("First page value")
    assert before < 50, (
        f"the first page's bar starts at {before}% of a run that continued well "
        "past it - the timeline is not measuring what it claims to"
    )

    page.get_by_test_id("profiler-search").fill("First page value")
    expect(breakdown).to_contain_text("First page value")
    expect(breakdown).not_to_contain_text("Second page value")
    after = offset_of("First page value")
    assert abs(after - before) < 1.0, (
        f"the bar moved from {before}% to {after}% when the panel was filtered - "
        "the timeline rescaled to what is shown, so an early load now reads as "
        "having happened at a different time than it did"
    )


def test_a_request_is_attributed_to_the_page_that_triggered_it(page, two_pages):
    """The *request* half of the filter, which the variable tests do not reach.

    Both kinds of row carry a page and they get it from different places: a
    variable's comes from the bridge with the resolve, a request's from the
    recorder's map of in-flight fetches. Blanking the second passed every test
    here, because filtering to a page still had that page's variables to show.
    """
    open_profiler_tab(page, two_pages)
    page.get_by_test_id("profiler-enter").click()
    expect(page.get_by_test_id("profiler-banner")).to_be_visible(timeout=30000)
    breakdown = page.get_by_test_id("profiler-breakdown")
    expect(breakdown).to_contain_text("First page value", timeout=30000)
    # The table on page one issues queries, so page one has requests of its own.
    expect(breakdown).to_contain_text("Request", timeout=30000)

    page.get_by_role("button", name="Detail", exact=True).click()
    expect(breakdown).to_contain_text("Overlay value", timeout=30000)

    page.get_by_test_id("profiler-page").select_option("pg1")
    # Filtered to the page the table is on, its requests are still here - which
    # is only true if a request remembered where it started.
    expect(breakdown).to_contain_text("Request")
    expect(breakdown).not_to_contain_text("Overlay value")
