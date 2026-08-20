"""The Widget setup tab, organised variables-first (parity `workshop.md` §2;
Foundry p.65-67).

> "The core configuration options of a widget live within the Widget setup tab.
> This is where a module builder will configure the input and output variables
> of a widget … as well as any additional configuration and display options."
> (p.65)

The panel was a flat list of whatever each widget's author wrote first. p.65's
order is the order somebody has to *think* in - the set that populates the
widget, the options that set makes answerable, then what the widget produces -
and Foundry's own worked example is a Filter List, which is why this file
configures one.

**The claim that needs a browser is p.66's progressive disclosure**:

> "This configuration option is revealed in more detail once the Object Set is
> populated; it will then show the property types seen within the initial
> object set." (p.66)

Configuration revealed too early is a panel of empty dropdowns; too late is a
widget that looks unfinishable. Both are things a person sees and neither
raises anything, so both need a real render.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder


@pytest.fixture
def module(api):
    """A Filter List with **nothing bound**, which is p.65's own starting
    point: "the initial state of a newly added and not yet configured Filter
    List widget".

    Per test rather than shared: the disclosure test binds the object set, and
    a shared module would hand the next test a widget somebody had already
    configured - the fixture bug this repo has now paid for three times.
    """
    mod = Module(api, "Widget setup order")
    type_id = mod.object_type(
        columns=["id", "name"],
        rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "flt": {"resolvedName": "CanvasFilterList",
                    "props": {"objectSetVariable": None, "variable": None,
                              "properties": "", "title": ""}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Clauses"},
        },
        "events": {},
    })
    return mod


def select_widget(page):
    """Through the Layout panel, for the reason the config-tab suite gives: a
    canvas click lands on whatever is under the pointer."""
    page.locator(".canvas-tree-row").first.click()
    expect(page.get_by_test_id("widget-setup")).to_be_visible(timeout=15000)


def test_the_sections_are_in_p65s_order(page, module) -> None:
    """Inputs, then configuration, then outputs - and asserted as an *order*
    rather than as three presences, because a panel with all three sections in
    the wrong order passes every check that only asks whether they exist."""
    open_builder(page, module)
    select_widget(page)
    page.get_by_test_id("setup-inputs").wait_for()

    # Bind the set so all three sections are on screen at once.
    page.get_by_test_id("setup-inputs").locator("select").select_option("v_all")
    expect(page.get_by_test_id("setup-configuration")).to_be_visible(timeout=15000)

    sections = page.locator(
        '[data-testid="setup-inputs"], [data-testid="setup-configuration"], '
        '[data-testid="setup-outputs"]'
    )
    order = [
        sections.nth(i).get_attribute("data-testid") for i in range(sections.count())
    ]
    assert order == ["setup-inputs", "setup-configuration", "setup-outputs"], order


def test_the_configuration_waits_for_its_input(page, module) -> None:
    """**p.66's disclosure.** The filter options are read from the set's object
    type, so before a set is bound there is nothing to list - and the panel
    says which input it is waiting on rather than showing an empty control."""
    open_builder(page, module)
    select_widget(page)

    expect(page.get_by_test_id("setup-configuration")).to_have_count(0)
    waiting = page.get_by_test_id("setup-waiting")
    expect(waiting).to_be_visible()
    expect(waiting).to_contain_text("object set")

    page.get_by_test_id("setup-inputs").locator("select").select_option("v_all")
    expect(page.get_by_test_id("setup-configuration")).to_be_visible(timeout=15000)
    expect(page.get_by_test_id("setup-waiting")).to_have_count(0)


def test_the_output_stays_available_before_the_input_is_bound(
    page, module
) -> None:
    """**The half that keeps disclosure from being a wall.**

    p.66 hides the *configuration* until the object set is populated. It says
    nothing about the output, and p.67 is explicit that a Filter List's output
    exists from the moment the widget is added - "by default, an output
    variable will be created when adding a Filter List widget". Hiding it
    behind the input would make the widget look less finished than it is.
    """
    open_builder(page, module)
    select_widget(page)

    expect(page.get_by_test_id("setup-waiting")).to_be_visible()
    expect(page.get_by_test_id("setup-outputs")).to_be_visible()


def test_a_widget_with_no_output_shows_no_outputs_heading(page, api) -> None:
    """An empty heading is a promise of a control that does not exist. The
    time series reads a set and draws it; it produces nothing."""
    mod = Module(api, "Widget setup order (series)")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "ts": {"resolvedName": "CanvasTimeSeries",
                   "props": {"objectSetVariable": "v_all", "interval": "day",
                             "title": ""}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })

    open_builder(page, mod)
    select_widget(page)
    expect(page.get_by_test_id("setup-inputs")).to_be_visible()
    # Its set is already bound, so the configuration is showing...
    expect(page.get_by_test_id("setup-configuration")).to_be_visible()
    # ...and there is no Outputs section at all.
    expect(page.get_by_test_id("setup-outputs")).to_have_count(0)
