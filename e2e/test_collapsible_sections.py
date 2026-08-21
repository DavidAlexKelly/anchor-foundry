"""Collapsible sections and p.82's three events (parity `workshop.md` §1.3;
Foundry p.55, p.82).

> "For each collapsible section in the module, the following three events are
> available: **Expand**… **Collapse**… **Toggle**." (p.82)

The resolution rule — which of a backing variable and an event is on screen —
is arithmetic and is checked directly in
`apps/web/src/components/canvas/collapse.test.ts`. What needs a browser is the
wiring: that a button in one part of the module can act on a section it has
never met, that Toggle reads *what is on screen* rather than what the variable
says, and above all p.82's gotcha:

> "If the specified section has a Boolean variable backing the collapse state,
> **the value of this variable will not be updated** as a result of one of
> these events."

That last one is a claim about something *not* happening, which is the shape a
test can only make fail if it renders the variable somewhere. So these modules
put the variable's value on screen in a Text widget and assert it stays put.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def module_with(api, name: str, *, section_props: dict, variables: dict, events: dict) -> Module:
    """A collapsible section holding one text widget, plus a button wired to
    whatever effects the test is about, plus a readout of the variable."""
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Act"}},
            # **`MARK` is what makes the gotcha checkable.** Asserting that a
            # variable did *not* change, right after a click, passes trivially:
            # a write would take a debounce plus a server round trip to show
            # up, and the assertion runs long before that. So the click also
            # sets a marker, and the test waits for the marker to land - by
            # which time a write to `v_shut` would have landed too.
            "readout": {"resolvedName": "CanvasText",
                        "props": {"tag": "p",
                                  "text": "BACKING={{v_shut}} MARK={{v_mark}}"}},
            "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                    "props": {"direction": "columns", "gap": 12,
                              "collapsible": True, "title": "Details",
                              **section_props},
                    "nodes": ["inside"]},
            "inside": {"resolvedName": "CanvasText", "parent": "sec",
                       "props": {"tag": "p", "text": "INSIDE THE SECTION"}},
        }),
        "variables": {
            "v_mark": {"id": "v_mark", "kind": "string", "label": "Mark", "default": "no"},
            **variables,
        },
        "events": events,
    })
    return mod


def effect(kind: str) -> dict:
    return {"type": kind, "config": {"section": "sec"}}


def click(page):
    page.get_by_role("button", name="Act").click()


def body(page):
    """The section's contents. `hidden` rather than unmounted, so a table
    inside a collapsed section does not refetch every time it is opened."""
    return page.locator(".canvas-section-parts")


def test_a_collapsible_section_starts_where_it_says_and_toggles_itself(page, api) -> None:
    """p.55's collapsible sections, and the control the section draws for
    itself. Its header stays on screen when it is shut — a section that
    collapses to nothing cannot be reopened, and one that collapses to a bare
    chevron cannot be identified."""
    mod = module_with(
        api, "Collapse own control",
        section_props={"collapsedByDefault": True},
        variables={}, events={},
    )
    open_module(page, mod)

    toggle = page.locator(".canvas-section-toggle")
    expect(toggle).to_be_visible()
    expect(toggle).to_contain_text("Details")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(body(page)).to_be_hidden()

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(body(page)).to_be_visible()


def test_a_button_expands_a_section_it_has_never_met(page, api) -> None:
    """**p.82's own worked example**, near enough: "an object table and an
    initially-collapsed object view that the builder would like to expand when
    the Open Hospital Object View button is selected".

    The button is not inside the section and has no reference to it beyond the
    event — which is decision 0002's argument for events living beside the
    layout rather than inside a widget's props.
    """
    mod = module_with(
        api, "Collapse expand",
        section_props={"collapsedByDefault": True},
        variables={},
        events={"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                        "effects": [effect("expand_section")]}},
    )
    open_module(page, mod)

    expect(body(page)).to_be_hidden()
    click(page)
    expect(body(page)).to_be_visible()


def test_toggle_reads_what_is_on_screen(page, api) -> None:
    """Toggle is the one of the three that depends on the current state, so it
    is the one that can be wired to the wrong "current". Clicked twice, it must
    come back to where it started rather than sticking."""
    mod = module_with(
        api, "Collapse toggle",
        section_props={"collapsedByDefault": False},
        variables={},
        events={"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                        "effects": [effect("toggle_section")]}},
    )
    open_module(page, mod)

    expect(body(page)).to_be_visible()
    click(page)
    expect(body(page)).to_be_hidden()
    click(page)
    expect(body(page)).to_be_visible()


def test_a_backing_variable_decides_before_anything_is_clicked(page, api) -> None:
    """p.82 calls it a variable "backing the collapse state". A section whose
    variable is ignored until somebody clicks has a decorative setting."""
    mod = module_with(
        api, "Collapse backed",
        section_props={"collapsedWhen": "v_shut", "collapsedByDefault": False},
        variables={"v_shut": {"id": "v_shut", "kind": "boolean", "label": "Shut",
                              "default": True}},
        events={},
    )
    open_module(page, mod)

    expect(page.get_by_text("BACKING=true MARK=no")).to_be_visible()
    expect(body(page)).to_be_hidden()


def test_an_event_moves_the_section_and_pointedly_leaves_the_variable(page, api) -> None:
    """**p.82's gotcha, both halves.**

    > "the value of this variable will not be updated as a result of one of
    > these events. If you wish to keep this variable value in sync… you can
    > use a Set Variable Value event instead."

    The section opens *and* the variable still reads true. Asserting only the
    first half would pass just as well if the effect wrote the variable, which
    is the implementation somebody would reach for by default — so the readout
    is what makes this check able to fail.
    """
    mod = module_with(
        api, "Collapse gotcha",
        section_props={"collapsedWhen": "v_shut", "collapsedByDefault": False},
        variables={"v_shut": {"id": "v_shut", "kind": "boolean", "label": "Shut",
                              "default": True}},
        events={"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                        "effects": [
                            effect("expand_section"),
                            # Not part of the claim - it is the clock. See the
                            # note on the readout in `module_with`.
                            {"type": "set_variable",
                             "config": {"variable": "v_mark", "value": "yes"}},
                        ]}},
    )
    open_module(page, mod)

    expect(body(page)).to_be_hidden()
    expect(page.get_by_text("BACKING=true MARK=no")).to_be_visible()

    click(page)
    expect(body(page)).to_be_visible()
    # A full write-and-resolve cycle has now demonstrably completed - and
    # `v_shut` came back through it untouched, which is the whole point of the
    # page's warning. Asserted as one string so the two cannot be read apart.
    expect(page.get_by_text("BACKING=true MARK=yes")).to_be_visible(timeout=15000)


def test_the_documented_fix_keeps_the_two_in_step(page, api) -> None:
    """The other half of p.82's sentence: a Set Variable Value event beside the
    Expand does what the builder probably meant. Worth a test of its own
    because it is the advice the settings panel gives, and advice that does not
    work is worse than none."""
    mod = module_with(
        api, "Collapse synced",
        section_props={"collapsedWhen": "v_shut", "collapsedByDefault": False},
        variables={"v_shut": {"id": "v_shut", "kind": "boolean", "label": "Shut",
                              "default": True}},
        events={"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                        "effects": [
                            effect("expand_section"),
                            {"type": "set_variable",
                             "config": {"variable": "v_shut", "value": False}},
                        ]}},
    )
    open_module(page, mod)

    click(page)
    expect(body(page)).to_be_visible()
    expect(page.get_by_text("BACKING=false")).to_be_visible(timeout=15000)
