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
    """p.182 lists three of each. Two of the six are not offered, and the panel
    says so rather than leaving somebody hunting — the same shape as §406's
    hint, and this one is true."""
    mod = build(api, "Display opt panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Text").first.click()
    page.get_by_role("tab", name="Display").click()

    mounts = page.get_by_test_id("display-mount").locator("option")
    expect(mounts).to_have_count(2)
    labels = [mounts.nth(i).inner_text() for i in range(mounts.count())]
    assert "Delay until on-screen" in labels, labels
    assert not any("Eager" in label for label in labels), labels

    unmounts = page.get_by_test_id("display-unmount").locator("option")
    expect(unmounts).to_have_count(2)
    ulabels = [unmounts.nth(i).inner_text() for i in range(unmounts.count())]
    assert "Unmount when off-screen" in ulabels, ulabels
    assert not any("Never" in label for label in ulabels), ulabels

    expect(page.get_by_test_id("display-unsupported")).to_contain_text(
        "Eagerly mount and Never unmount are not offered"
    )
