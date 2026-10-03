"""Widget display optimization (parity `workshop.md` §9; Foundry workshop
p.180-182).

> "Widget display optimization is a Workshop setting that controls when
> individual widgets mount and unmount as users navigate within a module."
> (p.180)

> "Delay until on-screen: The widget delays mounting until it is scrolled into
> view." / "Unmount when off-screen: The widget unmounts whenever it is
> scrolled out of view, in addition to the default condition." (p.182)

The rules are `display-optimization.test.ts` - which option wins, what shows
this frame, what height the placeholder holds. **What needs a browser is the
only thing that decides whether any of it is real**: a viewport, a scroll, and
an `IntersectionObserver` actually reporting. A unit test can assert `shows()`
forever without the widget ever mounting or unmounting on a page.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, settled

TARGET = "Target widget"
TOP = "Top widget"
#: Tall enough that the target starts well below the fold whatever the viewport
#: is, so "not mounted yet" cannot pass because it happened to be visible.
SPACER_HEIGHT = 3000


def build(api, name: str, *, mount=None, unmount=None, target_first=False):
    """A tall spacer and a target, with p.182's settings on the target.

    `target_first` puts the target *above* the spacer, which is what the
    unmount test needs: it has to start on screen and then be scrolled away.
    """
    mod = Module(api, name)
    display = {"mode": "auto"}
    if mount:
        display["mount"] = mount
    if unmount:
        display["unmount"] = unmount

    spacer = {
        "resolvedName": "CanvasText",
        "props": {"text": "Spacer", "tag": "p"},
        # Sizing is §12's half of the same `custom.display`, used here purely
        # to make a deterministic tall column - a spacer built from repeated
        # text would be a different height on every font.
        "custom": {"display": {"mode": "absolute", "height": SPACER_HEIGHT}},
    }
    target = {
        "resolvedName": "CanvasText",
        "props": {"text": TARGET, "tag": "h2"},
        "custom": {"display": display},
    }
    top = {"resolvedName": "CanvasText", "props": {"text": TOP, "tag": "p"}}

    nodes = ({"top": top, "tgt": target, "sp": spacer} if target_first
             else {"top": top, "sp": spacer, "tgt": target})
    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {},
        "events": {},
    })
    return mod


def wrapper(page):
    return page.locator("[data-mount]")


def mounted(page) -> str:
    return wrapper(page).get_attribute("data-mounted") or ""


def test_a_delayed_widget_is_absent_until_it_is_scrolled_to(page, api):
    """p.182's "Delay until on-screen".

    **Absent, not hidden.** The point of the setting is that the widget has not
    run - a hidden one has already fetched whatever it fetches, which is the
    cost p.181 says this exists to avoid. So the assertion is on the text being
    gone from the document, not on its visibility.
    """
    mod = build(api, "Display opt delayed", mount="on_screen")
    open_module(page, mod)
    # Presence before absence (§318): the wrapper is there from the first
    # frame, which is what makes "the body is not" a statement about the
    # setting rather than about a page that has not rendered.
    eventually(lambda: wrapper(page).count(), lambda n: n == 1,
               what="the optimised widget's wrapper")
    assert mounted(page) == "no"
    expect(page.get_by_text(TARGET, exact=True)).to_have_count(0)

    wrapper(page).scroll_into_view_if_needed()
    eventually(lambda: mounted(page), lambda v: v == "yes",
               what="the widget to mount once scrolled to")
    expect(page.get_by_text(TARGET, exact=True)).to_be_visible()


def test_a_delayed_widget_stays_mounted_once_it_has_been_seen(page, api):
    """p.182 says it "delays mounting", not that it unmounts again — that is
    the other setting, and the two are independent. A one-way door."""
    mod = build(api, "Display opt one way", mount="on_screen")
    open_module(page, mod)
    wrapper(page).scroll_into_view_if_needed()
    eventually(lambda: mounted(page), lambda v: v == "yes", what="the first mount")

    page.mouse.wheel(0, -SPACER_HEIGHT * 2)
    # Asserted as *staying* rather than as a single read: a check taken one
    # frame after the scroll would pass before the observer had reported.
    eventually(lambda: mounted(page), lambda v: v == "yes",
               what="it to still be mounted after scrolling away")
    page.wait_for_timeout(300)
    assert mounted(page) == "yes"


def test_an_off_screen_widget_unmounts_and_comes_back(page, api):
    """p.182's "Unmount when off-screen", which is the aggressive one."""
    mod = build(api, "Display opt off screen", unmount="off_screen",
                target_first=True)
    open_module(page, mod)
    eventually(lambda: mounted(page), lambda v: v == "yes",
               what="the widget mounted at the top of the page")
    expect(page.get_by_text(TARGET, exact=True)).to_be_visible()

    page.mouse.wheel(0, SPACER_HEIGHT)
    eventually(lambda: mounted(page), lambda v: v == "no",
               what="the widget to unmount once scrolled away")
    expect(page.get_by_text(TARGET, exact=True)).to_have_count(0)

    page.mouse.wheel(0, -SPACER_HEIGHT)
    eventually(lambda: mounted(page), lambda v: v == "yes",
               what="the widget to come back")
    expect(page.get_by_text(TARGET, exact=True)).to_be_visible()


def test_unmounting_does_not_collapse_the_layout(page, api):
    """**The half that makes the feature usable rather than maddening.**

    A widget removed from a long scrollable layout takes its height with it,
    which pulls everything below upward and moves the viewport out from under
    the reader — the widget scrolls back into view, remounts, and the page
    oscillates. The placeholder holds the last measured height.
    """
    mod = build(api, "Display opt height", unmount="off_screen",
                target_first=True)
    open_module(page, mod)
    eventually(lambda: mounted(page), lambda v: v == "yes", what="the first mount")
    tall = wrapper(page).bounding_box()["height"]
    assert tall > 0, tall

    page.mouse.wheel(0, SPACER_HEIGHT)
    eventually(lambda: mounted(page), lambda v: v == "no", what="the unmount")
    # Still occupying its space, within a pixel or two of what it had.
    held = wrapper(page).bounding_box()["height"]
    assert abs(held - tall) < 3, (held, tall)


def test_a_module_that_configures_nothing_is_untouched(page, api):
    """The common case, and the one that would be a cost paid by every app.

    No setting means no wrapper attributes and no observer — a module written
    before this existed renders exactly as it did.
    """
    mod = build(api, "Display opt none")
    open_module(page, mod)
    expect(page.get_by_text(TOP, exact=True)).to_be_visible()
    expect(page.locator("[data-mount]")).to_have_count(0)
    expect(page.locator("[data-unmount]")).to_have_count(0)


def test_the_builder_is_not_optimised(page, api):
    """p.182's own instructions for configuring this begin "in edit mode,
    select the widget in the canvas" — so a widget that vanished when it
    scrolled away would be one the author cannot reach, and the layout tree
    would select into nothing."""
    mod = build(api, "Display opt builder", mount="on_screen")
    open_builder(page, mod)
    settled(page)
    expect(page.locator("[data-mount]")).to_have_count(0)
    # And the widget itself is there to be selected, unscrolled.
    #
    # **Scoped to the canvas.** Unscoped this finds two: the widget, and the
    # layout tree row that names it - so `count == 1` failed against a product
    # that was working. The claim is about the canvas, so it says canvas
    # (§337: name the control, not its neighbourhood).
    expect(page.locator(".canvas-block").get_by_text(TARGET, exact=True)).to_have_count(1)


def test_the_panel_offers_p182s_two_and_says_why_not_the_others(page, api):
    """p.182 lists three of each, and since §609 all six are offered - with
    p.181's caution beside them, since keeping widgets mounted costs memory."""
    mod = build(api, "Display opt panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Text").first.click()
    page.get_by_role("tab", name="Display").click()

    mounts = page.get_by_test_id("display-mount").locator("option")
    expect(mounts).to_have_count(3)
    labels = [mounts.nth(i).inner_text() for i in range(mounts.count())]
    assert {"Delay until on-screen", "Eagerly mount"} <= set(labels), labels

    unmounts = page.get_by_test_id("display-unmount").locator("option")
    expect(unmounts).to_have_count(3)
    ulabels = [unmounts.nth(i).inner_text() for i in range(unmounts.count())]
    assert {"Unmount when off-screen", "Never unmount"} <= set(ulabels), ulabels

    expect(page.get_by_test_id("display-note")).to_contain_text("across page switches")



# ---- p.182's Eagerly mount and Never unmount, across pages (§609) -------------

PLAIN, KEPT, EAGER, HOME = "Plain on B", "Kept on B", "Eager on B", "Home page body"
DEEP, SIBLING = "Kept inside a section", "Plain inside a section"


def two_pages(api, name: str):
    """A header that switches pages, page A with a body, and page B holding one
    widget of each kind: default, Never unmount, Eagerly mount."""
    mod = Module(api, name)

    def text(words: str, parent: str, display: dict | None = None) -> dict:
        spec = {"resolvedName": "CanvasText", "props": {"tag": "p", "text": words},
                "parent": parent}
        if display:
            spec["custom"] = {"display": {"mode": "auto", **display}}
        return spec

    nodes = {
        "hdr": {"resolvedName": "CanvasHeader", "props": {"title": "PAGES"},
                "isCanvas": True, "nodes": ["go_a", "go_b"]},
        "go_a": {"resolvedName": "CanvasButton", "props": {"label": "Go A"}, "parent": "hdr"},
        "go_b": {"resolvedName": "CanvasButton", "props": {"label": "Go B"}, "parent": "hdr"},
        "pa": {"resolvedName": "CanvasPage", "props": {"title": "A", "pageId": "a"},
               "isCanvas": True, "nodes": ["pa_body"]},
        "pa_body": text(HOME, "pa"),
        "pb": {"resolvedName": "CanvasPage", "props": {"title": "B", "pageId": "b"},
               "isCanvas": True, "nodes": ["pb_plain", "pb_kept", "pb_eager", "pb_sec"]},
        "pb_plain": text(PLAIN, "pb"),
        "pb_kept": text(KEPT, "pb", {"unmount": "never"}),
        "pb_eager": text(EAGER, "pb", {"mount": "eager"}),
        # A kept widget one level down: the section has to render on the
        # closed page for it to have somewhere to be.
        "pb_sec": {"resolvedName": "CanvasSection", "isCanvas": True, "props": {},
                   "parent": "pb", "nodes": ["pb_deep", "pb_sibling"]},
        "pb_deep": text(DEEP, "pb_sec", {"unmount": "never"}),
        "pb_sibling": text(SIBLING, "pb_sec"),
    }
    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {},
        "events": {
            "e_a": {"id": "e_a", "trigger": {"node": "go_a", "on": "click"},
                    "effects": [{"type": "navigate", "config": {"page": "pa"}}]},
            "e_b": {"id": "e_b", "trigger": {"node": "go_b", "on": "click"},
                    "effects": [{"type": "navigate", "config": {"page": "pb"}}]},
        },
    })
    return mod


def in_document(page, words: str) -> int:
    """Mounted is in the document; visible is a different question."""
    return page.get_by_text(words, exact=True).count()


def test_an_eager_widget_is_mounted_before_its_page_is_opened(page, api):
    """p.182: "The widget mounts as soon as the module loads, even if it is
    not yet visible." And only it: the rest of page B is not mounted early."""
    mod = two_pages(api, "Display opt eager")
    open_module(page, mod)
    expect(page.get_by_text(HOME, exact=True)).to_be_visible()
    eventually(lambda: in_document(page, EAGER), lambda n: n == 1, what="the eager widget")
    expect(page.get_by_text(EAGER, exact=True)).to_be_hidden()
    assert in_document(page, PLAIN) == 0
    assert in_document(page, KEPT) == 0


def test_a_never_unmount_widget_stays_after_its_page_closes(page, api):
    """p.182: "Once mounted, the widget remains mounted for the rest of the
    session." The default widget beside it unmounts, as a closed page's
    widgets always have."""
    mod = two_pages(api, "Display opt never")
    open_module(page, mod)
    page.get_by_role("button", name="Go B").click()
    for words in (PLAIN, KEPT, EAGER):
        expect(page.get_by_text(words, exact=True)).to_be_visible(timeout=15000)

    page.get_by_role("button", name="Go A").click()
    expect(page.get_by_text(HOME, exact=True)).to_be_visible()
    eventually(lambda: in_document(page, PLAIN), lambda n: n == 0, what="the plain widget gone")
    assert in_document(page, KEPT) == 1 and in_document(page, EAGER) == 1
    expect(page.get_by_text(KEPT, exact=True)).to_be_hidden()
    # One level down too, and only the kept one: its section renders so it has
    # somewhere to be, and the section's other widget unmounts as usual.
    assert in_document(page, DEEP) == 1
    assert in_document(page, SIBLING) == 0

    # And back: the kept one was there all along; the plain one mounts again.
    page.get_by_role("button", name="Go B").click()
    for words in (PLAIN, KEPT, EAGER):
        expect(page.get_by_text(words, exact=True)).to_be_visible(timeout=15000)


# ---- p.182's Default unmount, across a section's tabs (§711) ----------------

T_HOME, T_PLAIN, T_KEPT, T_EAGER = "On tab one", "Plain on tab two", "Kept on tab two", "Eager on tab two"


def two_tabs(api, name: str):
    """A Tabs section: tab One with a body, tab Two holding one widget of each
    kind - default, Never unmount, Eagerly mount."""
    mod = Module(api, name)

    def text(words: str, parent: str, display: dict | None = None) -> dict:
        spec = {"resolvedName": "CanvasText", "props": {"tag": "p", "text": words},
                "parent": parent}
        if display:
            spec["custom"] = {"display": {"mode": "auto", **display}}
        return spec

    mod.define({
        "format": 2,
        "layout": layout({
            "tabs": {"resolvedName": "CanvasSection", "isCanvas": True,
                     "props": {"direction": "tabs", "tabs": "One,Two"},
                     "nodes": ["one", "two"]},
            "one": text(T_HOME, "tabs"),
            "two": {"resolvedName": "CanvasSection", "isCanvas": True, "props": {},
                    "parent": "tabs", "nodes": ["t_plain", "t_kept", "t_eager"]},
            "t_plain": text(T_PLAIN, "two"),
            "t_kept": text(T_KEPT, "two", {"unmount": "never"}),
            "t_eager": text(T_EAGER, "two", {"mount": "eager"}),
        }),
        "variables": {},
        "events": {},
    })
    return mod


def test_a_tab_s_widgets_unmount_when_another_tab_shows(page, api):
    """p.182's Default: "The widget unmounts when its containing layout is no
    longer rendered; for example, when the user switches to another tab or
    page." Tabs kept every widget mounted until §711; Never unmount and
    Eagerly mount keep theirs, as on a page."""
    mod = two_tabs(api, "Display opt tabs")
    open_module(page, mod)
    expect(page.get_by_text(T_HOME, exact=True)).to_be_visible(timeout=30000)
    eventually(lambda: in_document(page, T_EAGER), lambda n: n == 1, what="the eager widget")
    assert in_document(page, T_PLAIN) == 0
    assert in_document(page, T_KEPT) == 0

    page.get_by_role("tab", name="Two").click()
    for words in (T_PLAIN, T_KEPT, T_EAGER):
        expect(page.get_by_text(words, exact=True)).to_be_visible(timeout=15000)

    page.get_by_role("tab", name="One").click()
    expect(page.get_by_text(T_HOME, exact=True)).to_be_visible()
    eventually(lambda: in_document(page, T_PLAIN), lambda n: n == 0, what="the plain widget gone")
    assert in_document(page, T_KEPT) == 1 and in_document(page, T_EAGER) == 1
    # The tab one tab replaced is mounted again, as a page coming back is.
    assert in_document(page, T_HOME) == 1


def test_a_tab_on_a_closed_page_stays_closed(page, api):
    """A Tabs section on a page nobody has opened: its showing tab is still on
    a closed page, so an ordinary widget there is not mounted - only the eager
    one beside it, which is what makes the section render at all."""
    mod = Module(api, "Display opt tab on closed page")
    mod.define({
        "format": 2,
        "layout": layout({
            "pa": {"resolvedName": "CanvasPage", "props": {"title": "A"},
                   "isCanvas": True, "nodes": ["pa_body"]},
            "pa_body": {"resolvedName": "CanvasText", "parent": "pa",
                        "props": {"tag": "p", "text": HOME}},
            "pb": {"resolvedName": "CanvasPage", "props": {"title": "B"},
                   "isCanvas": True, "nodes": ["tabs"]},
            "tabs": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "pb",
                     "props": {"direction": "tabs", "tabs": "Only"}, "nodes": ["inner"]},
            "inner": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "tabs",
                      "props": {}, "nodes": ["plain", "eager"]},
            "plain": {"resolvedName": "CanvasText", "parent": "inner",
                      "props": {"tag": "p", "text": T_PLAIN}},
            "eager": {"resolvedName": "CanvasText", "parent": "inner",
                      "props": {"tag": "p", "text": T_EAGER},
                      "custom": {"display": {"mode": "auto", "mount": "eager"}}},
        }),
        "variables": {},
        "events": {},
    })
    open_module(page, mod)
    expect(page.get_by_text(HOME, exact=True)).to_be_visible(timeout=30000)
    eventually(lambda: in_document(page, T_EAGER), lambda n: n == 1, what="the eager widget")
    assert in_document(page, T_PLAIN) == 0
