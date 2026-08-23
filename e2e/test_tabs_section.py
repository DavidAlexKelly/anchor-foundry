"""Tabs sections and p.84's Switch-to-tab (parity `workshop.md` §1.3, §4.2;
Foundry p.54, p.84).

> "**Tabs**: Adds tabs to the top of a section and allows module builders to
> configure different configurations of widgets within each tab of a section."
> (p.54)

A *section* layout. The Tabs **widget** in this repo switches pages, and
`CanvasSection`'s own comment called that "the same idea one level up" — it is
not, because a module has one set of pages, so two independent tab groups on a
page could not be expressed and the rule below had nothing to attach to:

> "Unlike the Switch to {page name}, and section collapse state events, events
> that change the selected tab **will also update the value of the string
> variable** configured for Variable-Based Tab Selection." (p.84)

The resolution arithmetic is checked directly in
`apps/web/src/components/canvas/tab-selection.test.ts`. What needs a browser is
the wiring, and above all that write-back — which is the mirror image of what
`test_collapsible_sections.py` and `test_page_selection.py` assert, so the same
readout device is used to make the claim falsifiable in the other direction.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module

TAB_BODIES = {"t0": "INSIDE OVERVIEW", "t1": "INSIDE DETAILS", "t2": "INSIDE HISTORY"}
NAMES = "Overview,Details,History"


def module_with(api, name: str, *, variables: dict, events: dict, tab_variable=None,
                tabs: str = NAMES, children: int = 3):
    """One Tabs section holding a text widget per tab, plus a button and a
    readout outside it.

    The button is deliberately **outside** the section, so a Switch-to-tab
    event has to reach a section it has no reference to beyond the event —
    decision 0002's argument for events living beside the layout, and p.82's
    own worked example one row down.
    """
    kids = [f"t{i}" for i in range(children)]
    nodes: dict = {
        "btn": {"resolvedName": "CanvasButton", "props": {"label": "Act"}},
        # The same clock `test_collapsible_sections.py` uses: a claim that a
        # variable did *not* change needs a second variable that demonstrably
        # did, or it passes before any write could have landed. Here the claim
        # is the opposite - the variable *does* change - but the readout is
        # what makes either version falsifiable.
        "readout": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "TAB={{v_tab}} MARK={{v_mark}}"}},
        "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                "props": {"direction": "tabs", "gap": 12, "tabs": tabs,
                          **({"tabVariable": tab_variable} if tab_variable else {})},
                "nodes": kids},
    }
    for kid in kids:
        nodes[kid] = {"resolvedName": "CanvasText", "parent": "sec",
                      "props": {"tag": "p", "text": TAB_BODIES[kid]}}
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {
            "v_mark": {"id": "v_mark", "kind": "string", "label": "Mark", "default": "no"},
            **variables,
        },
        "events": events,
    })
    return mod


def tab_variable(default: str = "") -> dict:
    return {"v_tab": {"id": "v_tab", "kind": "string", "label": "Tab", "default": default}}


def switch_tab(tab: str) -> dict:
    return {"type": "switch_tab", "config": {"section": "sec", "tab": tab}}


def on_click(*effects: dict) -> dict:
    return {"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": list(effects)}}


def showing(page, kid: str) -> None:
    """Exactly one tab's contents is on screen, and it is this one.

    Hidden rather than absent, like a collapsed section: a table in a tab
    nobody is looking at should not refetch every time somebody comes back.
    """
    expect(page.get_by_text(TAB_BODIES[kid])).to_be_visible()
    for other, body in TAB_BODIES.items():
        if other != kid:
            expect(page.get_by_text(body)).to_be_hidden()


def readout(page, text: str) -> None:
    """Wait for the header to say exactly this — §189's ordering rule.

    Variables resolve on the server, so for the first few hundred milliseconds
    the backing variable reads as *absent*, and an assertion made in that
    window is an assertion about a section on its way somewhere else.
    """
    expect(page.get_by_text(text, exact=True)).to_be_visible(timeout=15000)


def test_a_tabs_section_shows_one_tab_at_a_time(page, api) -> None:
    """p.54's layout, and the assertion that separates it from a Rows section:
    three children, one visible."""
    mod = module_with(api, "Tabs plain", variables={}, events={})
    open_module(page, mod)

    strip = page.get_by_role("tablist")
    expect(strip).to_be_visible()
    expect(strip.get_by_role("tab")).to_have_count(3)
    showing(page, "t0")


def test_clicking_a_tab_switches_it(page, api) -> None:
    mod = module_with(api, "Tabs click", variables={}, events={})
    open_module(page, mod)

    page.get_by_role("tab", name="History").click()
    showing(page, "t2")
    expect(page.get_by_role("tab", name="History")).to_have_attribute(
        "aria-selected", "true",
    )


def test_two_tab_groups_on_one_page_are_independent(page, api) -> None:
    """**The thing page tabs cannot express, and the reason this is a section
    layout.** p.54 puts tabs on a section, so a page can have several — and a
    module has exactly one set of pages, so the previous substitution could
    hold at most one tab group in the whole module.

    **Both groups use the same tab names, and that is the whole test.** The
    first version gave them different names and a mutant survived it: sharing
    one tab choice across the module still looked correct, because `activeTab`
    drops an override naming a tab the section does not have, so the right-hand
    group ignored the left-hand group's choice and fell back to its first tab -
    the right answer for the wrong reason. Two panes each offering "Chart" and
    "Table" is the ordinary case and the one where shared state actually shows.
    """
    mod = Module(api, "Tabs two groups")
    mod.define({
        "format": 2,
        "layout": layout({
            "left": {"resolvedName": "CanvasSection", "isCanvas": True,
                     "props": {"direction": "tabs", "tabs": "Chart,Table"},
                     "nodes": ["la", "lb"]},
            "la": {"resolvedName": "CanvasText", "parent": "left",
                   "props": {"tag": "p", "text": "LEFT CHART"}},
            "lb": {"resolvedName": "CanvasText", "parent": "left",
                   "props": {"tag": "p", "text": "LEFT TABLE"}},
            "right": {"resolvedName": "CanvasSection", "isCanvas": True,
                      "props": {"direction": "tabs", "tabs": "Chart,Table"},
                      "nodes": ["ra", "rb"]},
            "ra": {"resolvedName": "CanvasText", "parent": "right",
                   "props": {"tag": "p", "text": "RIGHT CHART"}},
            "rb": {"resolvedName": "CanvasText", "parent": "right",
                   "props": {"tag": "p", "text": "RIGHT TABLE"}},
        }),
        "variables": {},
        "events": {},
    })
    open_module(page, mod)

    expect(page.get_by_text("LEFT CHART")).to_be_visible()
    expect(page.get_by_text("RIGHT CHART")).to_be_visible()

    # Two tabs now read "Table", so the click has to name which section's.
    page.locator("#left-tab-Table").click()
    expect(page.get_by_text("LEFT TABLE")).to_be_visible()
    # The right-hand group has not moved. Without one map keyed by section
    # node id, switching either group would switch both.
    expect(page.get_by_text("RIGHT CHART")).to_be_visible()
    expect(page.get_by_text("RIGHT TABLE")).to_be_hidden()


def test_a_backing_variable_decides_before_anything_is_clicked(page, api) -> None:
    """p.84's "Variable-Based Tab Selection". A variable ignored until somebody
    clicks is a decorative setting — and the section would show its first tab,
    which is what it does with no variable at all."""
    mod = module_with(api, "Tabs backed", variables=tab_variable("Details"),
                      events={}, tab_variable="v_tab")
    open_module(page, mod)

    readout(page, "TAB=Details MARK=no")
    showing(page, "t1")


def test_a_variable_naming_no_tab_shows_the_first_one(page, api) -> None:
    """Tabs get renamed after a module is saved, and the server deliberately
    does not refuse a stale value for that reason — so the rendering side has
    to have an answer, and blanking the section is not one."""
    mod = module_with(api, "Tabs typo", variables=tab_variable("Histroy"),
                      events={}, tab_variable="v_tab")
    open_module(page, mod)

    readout(page, "TAB=Histroy MARK=no")
    showing(page, "t0")


def test_an_event_switches_a_tab_in_a_section_it_has_never_met(page, api) -> None:
    """The button is outside the section and references it only through the
    event."""
    mod = module_with(api, "Tabs event", variables={},
                      events=on_click(switch_tab("History")))
    open_module(page, mod)

    showing(page, "t0")
    page.get_by_role("button", name="Act").click()
    showing(page, "t2")


def test_switching_a_tab_writes_the_backing_variable(page, api) -> None:
    """**p.84's difference from p.81 and p.82, and the only assertion in the
    three files that runs the other way.**

    > "Unlike the Switch to {page name}, and section collapse state events,
    > events that change the selected tab will also update the value of the
    > string variable configured for Variable-Based Tab Selection."

    A page event and a section event both leave their variable alone; this one
    must not. The readout is what makes the difference visible — an
    implementation that copied the other two would move the tab and leave
    `TAB=Overview`, and every assertion about the tab itself would still pass.
    """
    mod = module_with(
        api, "Tabs writeback", variables=tab_variable("Overview"),
        events=on_click(switch_tab("History"),
                        {"type": "set_variable",
                         "config": {"variable": "v_mark", "value": "yes"}}),
        tab_variable="v_tab",
    )
    open_module(page, mod)

    readout(page, "TAB=Overview MARK=no")
    showing(page, "t0")

    page.get_by_role("button", name="Act").click()
    # The marker proves a full write-and-resolve cycle completed, so
    # `TAB=History` beside it is a value that came back from the server rather
    # than one that never left.
    readout(page, "TAB=History MARK=yes")
    showing(page, "t2")


def test_clicking_a_tab_writes_the_variable_too(page, api) -> None:
    """p.84 says "events that change the selected tab", and a click is the
    most ordinary way to change one. A write that only happened for the
    scripted event would be a variable that follows the module except when
    somebody uses it."""
    mod = module_with(api, "Tabs click writeback", variables=tab_variable("Overview"),
                      events={}, tab_variable="v_tab")
    open_module(page, mod)

    readout(page, "TAB=Overview MARK=no")
    page.get_by_role("tab", name="Details").click()
    # The tab moves at once - it does not wait for the round trip, which is
    # what the override in `tab-selection.ts` is for.
    showing(page, "t1")
    readout(page, "TAB=Details MARK=no")
    # And it is still on Details once the write has landed, rather than
    # snapping back as the variable arrives.
    showing(page, "t1")


def test_a_second_writer_moves_the_tab(page, api) -> None:
    """The variable is the section's, not the tab strip's: anything that writes
    it moves the tab. Here a plain Set-variable event does, which is the
    behaviour that makes "backed by a variable" mean something beyond the tab
    strip writing to itself."""
    mod = module_with(
        api, "Tabs second writer", variables=tab_variable("Overview"),
        events=on_click({"type": "set_variable",
                         "config": {"variable": "v_tab", "value": "History"}}),
        tab_variable="v_tab",
    )
    open_module(page, mod)

    readout(page, "TAB=Overview MARK=no")
    showing(page, "t0")

    page.get_by_role("button", name="Act").click()
    readout(page, "TAB=History MARK=no")
    showing(page, "t2")
