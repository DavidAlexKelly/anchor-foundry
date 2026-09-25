"""p.47's application logo (§445; `workshop` p.47, p.49).

    "Enable an application logo by choosing an icon or uploading an image.
     Icon: Choose an icon and an icon color." (p.47)

**The divergence, stated once:** this platform has no icon library, and
`workshop.md` has recorded that since §80 — a Button and a Page take one or
two characters instead, an emoji or an initial. p.47's logo takes the same,
with the colour p.47 names. The *behaviour* is faithful; the picker is not
built. p.47's **Image** half is `test_header_image.py` (§472).

What needs a browser is the pair no unit test reaches: that the logo is drawn
from the document at all, and p.49's rule applied to it — **the title goes
when a vertical header collapses and the logo stays**, because p.49 drops
labels and a logo is a mark rather than a word.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, select_node


def module_with(api, name: str, props: dict) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader", "props": props},
            "page": {"resolvedName": "CanvasPage",
                     "props": {"title": "Overview", "icon": "◎"},
                     "isCanvas": True, "nodes": ["body"]},
            "body": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "PAGE BODY"}, "parent": "page"},
        }),
        "variables": {},
        "events": {},
    })
    return mod


@pytest.fixture(scope="module")
def badged(api):
    return module_with(api, "Header logo", {"title": "Fleet status", "icon": "🛰"})


def test_the_logo_is_drawn_beside_the_title(page, badged) -> None:
    open_module(page, badged)
    logo = page.get_by_test_id("header-logo")
    expect(logo).to_be_visible(timeout=30000)
    expect(logo).to_have_text("🛰")


def test_a_header_with_no_logo_draws_none(page, api) -> None:
    """Empty is no logo, which is what every header has had until now — and
    §318: the title is waited for before the absence is asserted."""
    mod = module_with(api, "Header no logo", {"title": "Plain"})
    open_module(page, mod)
    expect(page.locator(".canvas-header-title")).to_contain_text("Plain", timeout=30000)
    expect(page.get_by_test_id("header-logo")).to_have_count(0)


def test_only_two_characters_of_a_longer_one_are_drawn(page, api) -> None:
    """A document may carry anything — it is a stored prop, and the builder's
    own field is the only thing that limits it. A header that stretched to fit
    a sentence somebody pasted is a layout nobody chose."""
    mod = module_with(api, "Header long logo", {"title": "Long", "icon": "ABCDEF"})
    open_module(page, mod)
    expect(page.get_by_test_id("header-logo")).to_have_text("AB", timeout=30000)


def test_the_logo_takes_the_colour_it_was_given(page, api) -> None:
    """p.47: "Choose an icon and an icon color." A control that stored a
    colour and drew the default is §214's shape."""
    mod = module_with(api, "Header logo colour",
                      {"title": "Tinted", "icon": "A", "iconColour": "#b3261e"})
    open_module(page, mod)
    logo = page.get_by_test_id("header-logo")
    expect(logo).to_be_visible(timeout=30000)
    assert logo.evaluate("el => getComputedStyle(el).color") == "rgb(179, 38, 30)"


def test_the_logo_stays_when_a_collapsed_header_drops_the_title(page, api) -> None:
    """**p.49's rule, and the distinction this row turns on.**

    "When enabling collapsed headers, the Button Group and Tabs widgets will
    also have collapsed states that will only show the icons; the text will be
    dropped in this state." A title is a label and goes; a logo is a mark and
    stays, because a collapsed rail with nothing at the top of it is one
    nobody can tell from a blank one.
    """
    mod = module_with(api, "Header collapsed logo", {
        "title": "Fleet status", "icon": "🛰",
        "orientation": "vertical", "collapsible": True, "collapsedByDefault": True,
    })
    open_module(page, mod)
    expect(page.locator(".canvas-header")).to_have_attribute(
        "data-collapsed", "true", timeout=30000)
    expect(page.get_by_test_id("header-logo")).to_be_visible()
    expect(page.locator(".canvas-header-title")).to_have_count(0)


def test_the_builder_writes_the_logo_the_reader_sees(page, api) -> None:
    """End to end through the control somebody uses, rather than through a
    document a fixture wrote — the seam a `data-testid` on an input hides."""
    mod = module_with(api, "Header logo typed", {"title": "Typed"})
    open_builder(page, mod)
    select_node(page, "Header")

    field = page.get_by_test_id("header-icon")
    expect(field).to_be_visible(timeout=30000)
    field.fill("QQ")
    expect(page.get_by_test_id("header-logo")).to_have_text("QQ", timeout=30000)

    # And the field refuses a third character rather than letting it be typed
    # and cut, which is the difference between a limit and a surprise.
    assert field.get_attribute("maxlength") == "2"


def test_the_hint_says_there_is_no_icon_library(page, api) -> None:
    """§337: somebody expecting a picker finds out at the control, rather than
    by typing a word and watching it cut in half."""
    mod = module_with(api, "Header logo hint", {"title": "Hinted"})
    open_builder(page, mod)
    select_node(page, "Header")
    expect(page.locator(".canvas-settings")).to_contain_text("no icon library", timeout=30000)
