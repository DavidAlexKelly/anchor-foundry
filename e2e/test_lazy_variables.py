"""p.75's lazy variable loading, at the seam (§392; parity `workshop.md` §3.5).

> "In both view and edit mode, Workshop variables will compute and recompute
> lazily only when displayed by a visible widget or layout. This means that
> variables used in non-visible pages, tabs, overlays, or non-visible pages of
> a looped layout will not be computed until they are shown." (p.75)

**Which variables a screenful implies is arithmetic and is tested where it is
decided** — `visible-nodes.test.ts` for which nodes are on screen,
`test_workshop_variables.py` for the closure over their inputs, and
`test_canvas.py` for what the route does with a `visible` list. Every one of
those is precise in a way a browser cannot be: the response body is where you
can see that a variable was *not* computed, and a reader cannot see an absence.

What needs a browser is the other direction, and it is the failure that
matters. The client now tells the server what is on screen, and **if it
under-reports, a widget waits forever for a value nobody asked for.** No unit
test can catch that, because each half is right on its own: the walk returns
what it was asked for, and the server computes what it was told. So this file
is a module with variables on two pages, in two tabs and in an overlay, read
the way a person would read it — and every value has to be there.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def module_with_values(api, name: str) -> Module:
    """Two pages, a tabbed section on page one, and an overlay.

    Every readout is a *derived* variable rather than a static one, because a
    static value would be in the document already and would render whether the
    server computed anything or not — which is a test that passes with the
    evaluator switched off entirely (§213).
    """
    mod = Module(api, name)
    nodes: dict = {
        "hdr": {
            "resolvedName": "CanvasHeader",
            "props": {"title": "LAZY"},
            "isCanvas": True,
            "nodes": ["to1", "to2", "open"],
        },
        "to1": {"resolvedName": "CanvasButton", "props": {"label": "One"}, "parent": "hdr"},
        "to2": {"resolvedName": "CanvasButton", "props": {"label": "Two"}, "parent": "hdr"},
        "open": {"resolvedName": "CanvasButton", "props": {"label": "Open"}, "parent": "hdr"},

        "p1": {
            "resolvedName": "CanvasPage",
            "props": {"title": "One", "pageId": "one"},
            "isCanvas": True,
            "nodes": ["sec"],
        },
        # p.54's Tabs, so the tab half of p.75 is exercised by the same module.
        "sec": {
            "resolvedName": "CanvasSection",
            "props": {"direction": "tabs", "tabs": "Alpha,Beta"},
            "isCanvas": True,
            "nodes": ["t_alpha", "t_beta"],
            "parent": "p1",
        },
        "t_alpha": {
            "resolvedName": "CanvasText",
            "props": {"tag": "p", "text": "ALPHA={{v_alpha}}"},
            "parent": "sec",
        },
        "t_beta": {
            "resolvedName": "CanvasText",
            "props": {"tag": "p", "text": "BETA={{v_beta}}"},
            "parent": "sec",
        },

        "p2": {
            "resolvedName": "CanvasPage",
            "props": {"title": "Two", "pageId": "two"},
            "isCanvas": True,
            "nodes": ["p2_body"],
        },
        "p2_body": {
            "resolvedName": "CanvasText",
            "props": {"tag": "p", "text": "SECOND={{v_second}}"},
            "parent": "p2",
        },

        "ov": {
            "resolvedName": "CanvasOverlay",
            "props": {"title": "Detail"},
            "isCanvas": True,
            "nodes": ["ov_body"],
        },
        "ov_body": {
            "resolvedName": "CanvasText",
            "props": {"tag": "p", "text": "OVER={{v_over}}"},
            "parent": "ov",
        },
    }

    def derived(vid: str, word: str) -> dict:
        # `concat` of a static input, so the rendered text exists only if the
        # server computed this variable on the resolve that answered this
        # screen. A default would render without one.
        return {
            f"v_{vid}_in": {"id": f"v_{vid}_in", "kind": "string",
                            "label": f"{vid} in", "default": word},
            f"v_{vid}": {"id": f"v_{vid}", "kind": "string", "label": vid,
                         "derivation": {"transform": "concat",
                                        "inputs": [f"v_{vid}_in"]}},
        }

    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {
            **derived("alpha", "AY"),
            **derived("beta", "BEE"),
            **derived("second", "TWO"),
            **derived("over", "DEEP"),
        },
        "events": {
            "e_to1": {"id": "e_to1", "trigger": {"node": "to1", "on": "click"},
                      "effects": [{"type": "navigate", "config": {"page": "p1"}}]},
            "e_to2": {"id": "e_to2", "trigger": {"node": "to2", "on": "click"},
                      "effects": [{"type": "navigate", "config": {"page": "p2"}}]},
            "e_open": {"id": "e_open", "trigger": {"node": "open", "on": "click"},
                       "effects": [{"type": "open_overlay", "config": {"overlay": "ov"}}]},
        },
    })
    return mod


def test_the_page_on_screen_gets_its_values(page, api) -> None:
    """The load-bearing one. Page one opens, and the variable its widget reads
    is computed - which is only true if the walk reported that widget."""
    mod = module_with_values(api, "Lazy first page")
    open_module(page, mod)
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()


def test_the_second_page_gets_its_values_when_it_is_shown(page, api) -> None:
    """p.75's actual promise: *until they are shown*. A second page's variable
    is not computed on load, and a reader who navigates there must not find a
    widget waiting for a value nobody will ask for - which is exactly what an
    under-reporting walk produces, and what no unit test can see."""
    mod = module_with_values(api, "Lazy second page")
    open_module(page, mod)
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()

    page.get_by_role("button", name="Two").click()
    expect(page.get_by_text("SECOND=TWO")).to_be_visible()
    # And page one is gone, which is what made its variable stop being needed.
    expect(page.get_by_text("ALPHA=AY")).to_have_count(0)


def test_a_tab_gets_its_values_when_it_is_the_tab_showing(page, api) -> None:
    """p.75 names tabs beside pages, and they are the harder half: a tab panel
    stays *mounted* and hidden rather than unmounted, so the widget is there
    the whole time and only the walk decides it is not on screen."""
    mod = module_with_values(api, "Lazy tabs")
    open_module(page, mod)
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()

    page.get_by_role("tab", name="Beta").click()
    expect(page.get_by_text("BETA=BEE")).to_be_visible()


def test_an_overlay_gets_its_values_when_it_opens(page, api) -> None:
    """The third of p.75's three, and the one its own example is about: an
    overlay per row of a table is where computing everything on load stops
    being invisible."""
    mod = module_with_values(api, "Lazy overlay")
    open_module(page, mod)
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()

    page.get_by_role("button", name="Open").click()
    expect(page.get_by_text("OVER=DEEP")).to_be_visible()
    # The page underneath is still there: an overlay opens *over* a page.
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()


def test_going_back_to_a_page_still_shows_what_it_showed(page, api) -> None:
    """The one a wholesale replace would break.

    A resolve now answers about what is on screen, so the values for the page
    you left are absent from it. Replacing the resolved map rather than merging
    into it would blank the first page's variable while you were away, and
    coming back would show an empty widget until the next round trip - which
    reads as the page having lost its filter.
    """
    mod = module_with_values(api, "Lazy return")
    open_module(page, mod)
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()

    page.get_by_role("button", name="Two").click()
    expect(page.get_by_text("SECOND=TWO")).to_be_visible()

    page.get_by_role("button", name="One").click()
    expect(page.get_by_text("ALPHA=AY")).to_be_visible()
