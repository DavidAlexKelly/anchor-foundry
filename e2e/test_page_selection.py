"""Variable-Based Page Selection and p.81's gotcha (parity `workshop.md` §1.2;
Foundry p.81).

> "For each page in the module, an event is available to switch to the chosen
> page when the event is triggered. If the module is using a string variable
> for the **Variable-Based Page Selection** option, **the value of this
> variable will not be updated** as a result of a Switch to Page event. If you
> wish to keep this variable value in sync with the selected page, you can use
> a Set Variable Value event instead." (p.81)

That is p.82's sentence with a page id where the boolean was, so this file is
`test_collapsible_sections.py` one row up and borrows its two devices.

The resolution rule — which of a backing variable and an event is on screen —
is arithmetic and is checked directly in
`apps/web/src/components/canvas/page-selection.test.ts`. What needs a browser
is the wiring, and above all the gotcha, which is a claim about something *not*
happening: the variable's value is drawn in the header so that a check on it
staying put can fail.

**Three pages, not two.** The interesting claim — that a variable which
*changes* takes control back from an event — cannot be caught with two: the
event and the variable would be pointing at the same page, and an
implementation where the event kept winning forever would pass. Three pages
let the event send the reader to a page the variable never names.
"""
from __future__ import annotations

from playwright.sync_api import expect  # noqa: F401 - used by showing() and readout()

from api import Module, layout
from conftest import open_module

# Page bodies, one per page. Asserted by text because a page that is not
# showing is not rendered at all (`CanvasPage` returns null in run mode), so
# "which page am I on" is answerable as "which of these three is visible".
BODIES = {"p1": "PAGE OVERVIEW", "p2": "PAGE DETAIL", "p3": "PAGE SUMMARY"}
PAGE_IDS = {"p1": "overview", "p2": "detail", "p3": "summary"}


def module_with(api, name: str, *, variables: dict, events: dict, backed_by: str | None):
    """Three pages, plus a header carrying the buttons and the readout.

    **The header rather than a page**, because a button inside page one is
    gone the moment page one is. A header is the module-wide toolbar and is
    drawn whichever page is showing, which is the only place a control that
    changes the page can live.
    """
    mod = Module(api, name)
    nodes: dict = {
        "hdr": {
            "resolvedName": "CanvasHeader",
            "props": {"title": "PAGES"},
            "isCanvas": True,
            "nodes": ["go", "set", "readout"],
        },
        "go": {"resolvedName": "CanvasButton", "props": {"label": "Go"}, "parent": "hdr"},
        "set": {"resolvedName": "CanvasButton", "props": {"label": "Set"}, "parent": "hdr"},
        # **`MARK` is what makes the gotcha checkable**, exactly as in
        # `test_collapsible_sections.py`: asserting a variable did *not* change
        # right after a click passes trivially, because a write needs a
        # debounce plus a round trip to show up and the assertion runs long
        # before that. So the click also sets a marker and the test waits for
        # the marker, by which time a write to `v_page` would have landed too.
        "readout": {
            "resolvedName": "CanvasText",
            "props": {"tag": "p", "text": "PAGE={{v_page}} MARK={{v_mark}}"},
            "parent": "hdr",
        },
    }
    for node_id, page_id in PAGE_IDS.items():
        nodes[node_id] = {
            "resolvedName": "CanvasPage",
            "props": {"title": page_id.title(), "pageId": page_id},
            "isCanvas": True,
            "nodes": [f"{node_id}_body"],
        }
        nodes[f"{node_id}_body"] = {
            "resolvedName": "CanvasText",
            "props": {"tag": "p", "text": BODIES[node_id]},
            "parent": node_id,
        }
    document: dict = {
        "format": 2,
        "layout": layout(nodes),
        "variables": {
            "v_mark": {"id": "v_mark", "kind": "string", "label": "Mark", "default": "no"},
            **variables,
        },
        "events": events,
    }
    if backed_by:
        document["page_selection"] = backed_by
    mod.define(document)
    return mod


def page_variable(default: str) -> dict:
    return {"v_page": {"id": "v_page", "kind": "string", "label": "Page", "default": default}}


def on_click(node: str, *effects: dict) -> dict:
    return {"id": f"e_{node}", "trigger": {"node": node, "on": "click"},
            "effects": list(effects)}


def navigate(node_id: str) -> dict:
    return {"type": "navigate", "config": {"page": node_id}}


def set_variable(vid: str, value: str) -> dict:
    return {"type": "set_variable", "config": {"variable": vid, "value": value}}


def showing(page, node_id: str) -> None:
    """Exactly one page is on screen, and it is this one."""
    expect(page.get_by_text(BODIES[node_id])).to_be_visible()
    for other, body in BODIES.items():
        if other != node_id:
            expect(page.get_by_text(body)).to_have_count(0)


def readout(page, text: str) -> None:
    """Wait for the header to say exactly this.

    **Anything that could still be moving is asked about only after one of
    these, and that is not belt and braces.** Variables resolve on the server,
    so for the first few hundred milliseconds of a module's life `resolved` is
    empty and the backing variable reads as *absent* rather than as its value —
    which is the one state in which the event wins unconditionally. An
    assertion made in that window is an assertion about a page that is on its
    way somewhere else. (A `showing` after an event that writes nothing needs
    no readout: with no write in flight there is nothing left to settle.)

    Found by a mutant that should have been trivial to kill: recording no
    memory of the variable's value on a Switch-to-Page event left the reader on
    the right page for 250ms and then sent them home, and every check in this
    file had already run and passed. `to_be_visible` retries, so a wrong
    *first* frame is forgiven; it does not go back and look again once it has
    seen what it wanted. Waiting for the readout is waiting for the module to
    have an opinion at all.
    """
    expect(page.get_by_text(text, exact=True)).to_be_visible(timeout=15000)


def test_the_backing_variable_decides_before_anything_is_clicked(page, api) -> None:
    """p.81 calls it the variable the module "is using… for the Variable-Based
    Page Selection option". A variable ignored until somebody clicks is a
    decorative setting — and the module would open on its first page, which is
    what it does with no setting at all, so this is the assertion that tells
    the feature from its absence."""
    mod = module_with(
        api, "Pages backed",
        variables=page_variable("detail"), events={}, backed_by="v_page",
    )
    open_module(page, mod)

    readout(page, "PAGE=detail MARK=no")
    showing(page, "p2")


def test_a_variable_naming_no_page_opens_the_default_one(page, api) -> None:
    """p.197's rule for a URL, reused for a variable: "users will be returned
    to the module's default page". A string can hold a typo or the ID of a
    page since deleted, and the alternative to falling back is a blank module
    with no way out."""
    mod = module_with(
        api, "Pages typo",
        variables=page_variable("summarry"), events={}, backed_by="v_page",
    )
    open_module(page, mod)

    # The readout first, and here it is doing more than settling the race: an
    # unresolved variable *also* opens the default page, so a check made before
    # resolution would pass against a build that never read the variable at all.
    readout(page, "PAGE=summarry MARK=no")
    showing(page, "p1")


def test_an_event_moves_the_reader_and_pointedly_leaves_the_variable(page, api) -> None:
    """**p.81's gotcha, both halves.**

    The reader is on Summary *and* the variable still reads `overview`.
    Asserting only the first half would pass just as well against an
    implementation that wrote the variable — which is the implementation
    anybody would reach for by default — so the readout is what makes this
    check able to fail.
    """
    mod = module_with(
        api, "Pages gotcha",
        variables=page_variable("overview"),
        # The marker is not part of the claim; it is the clock. See the note on
        # the readout in `module_with`.
        events={"e_go": on_click("go", navigate("p3"), set_variable("v_mark", "yes"))},
        backed_by="v_page",
    )
    open_module(page, mod)

    readout(page, "PAGE=overview MARK=no")
    showing(page, "p1")
    page.get_by_role("button", name="Go").click()
    # The marker first, then the page. A full write-and-resolve cycle has now
    # demonstrably completed - `v_page` came back through it untouched, which
    # is the whole of p.81's warning - and only *then* is it meaningful to ask
    # which page the reader is on. The other order passes against a build that
    # shows Summary for a quarter of a second and then goes home.
    readout(page, "PAGE=overview MARK=yes")
    showing(page, "p3")


def test_a_variable_that_changes_takes_control_back_from_an_event(page, api) -> None:
    """The rule p.81 does not state, and the reason `page-selection.ts` exists:
    a module can be told two things at once, and **the most recent instruction
    wins**.

    Three pages are what make this checkable. The event sends the reader to
    Summary, a page the variable never names; then the variable changes to
    Detail. An implementation where the event won forever would leave the
    reader on Summary and would pass a two-page version of this test.
    """
    mod = module_with(
        api, "Pages handover",
        variables=page_variable("overview"),
        events={
            "e_go": on_click("go", navigate("p3")),
            "e_set": on_click("set", set_variable("v_page", "detail")),
        },
        backed_by="v_page",
    )
    open_module(page, mod)

    readout(page, "PAGE=overview MARK=no")
    showing(page, "p1")
    page.get_by_role("button", name="Go").click()
    showing(page, "p3")

    page.get_by_role("button", name="Set").click()
    readout(page, "PAGE=detail MARK=no")
    showing(page, "p2")


def test_the_documented_fix_keeps_the_two_in_step(page, api) -> None:
    """The other half of p.81's sentence: "you can use a Set Variable Value
    event instead". Worth a test of its own because it is the advice the Layout
    panel gives beside the picker, and advice that does not work is worse than
    none."""
    mod = module_with(
        api, "Pages synced",
        variables=page_variable("overview"),
        events={"e_go": on_click("go", navigate("p3"), set_variable("v_page", "summary"))},
        backed_by="v_page",
    )
    open_module(page, mod)

    readout(page, "PAGE=overview MARK=no")
    page.get_by_role("button", name="Go").click()
    # It *stays* on Summary once the variable's write lands, rather than
    # snapping back - which is what would happen if the write counted as a
    # change that overrode the event on the way to the same place.
    readout(page, "PAGE=summary MARK=no")
    showing(page, "p3")


def test_a_module_with_no_page_selection_is_unchanged(page, api) -> None:
    """The control group. Every module built before this existed has no
    `page_selection`, and its pages must still open first-page-first and move
    only on an event."""
    mod = module_with(
        api, "Pages unbacked",
        variables=page_variable("detail"),
        events={"e_go": on_click("go", navigate("p3"))},
        backed_by=None,
    )
    open_module(page, mod)

    # The variable says `detail` and is not backing anything, so it is ignored.
    # The readout proves it has resolved, so "ignored" is a statement about a
    # value the module has rather than one it has not fetched yet.
    readout(page, "PAGE=detail MARK=no")
    showing(page, "p1")
    page.get_by_role("button", name="Go").click()
    showing(page, "p3")
