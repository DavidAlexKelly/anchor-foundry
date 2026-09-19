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

from api import Module, layout
from conftest import WEB_BASE, open_builder, settled


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
