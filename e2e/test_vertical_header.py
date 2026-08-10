"""The vertical header, and what a collapsed one hides (parity `workshop.md` §1.1).

Most of a header is styling. One part is a **rule**, and it is the reason this
file exists:

    "When enabling collapsed headers, the Button Group and Tabs widgets will
     also have collapsed states that will only show the icons; the text will be
     dropped in this state. All other widgets will be hidden when a module
     header is collapsed." (docs/pal/foundry_workshop.pdf p.49)

So a collapsed header is not a narrower header — it is a different set of
widgets. `workshop.md` §12 asks for exactly this: "collapsed, a Tabs widget
shows icons only and a Metric Card in the header is **not rendered**. Mutation:
render it anyway, and the test goes red."

The header fixture therefore holds one of each: a Tabs widget and a Button
(which survive), and a Text widget (which must not).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, no_console_errors, open_builder, open_module


def header_module(api, name: str, **header_props):
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader",
                    "props": {"title": "MODULE TITLE", **header_props},
                    "isCanvas": True,
                    "nodes": ["tabs", "btn", "txt"]},
            "tabs": {"resolvedName": "CanvasTabs", "props": {}, "parent": "hdr"},
            "btn": {"resolvedName": "CanvasButton",
                    "props": {"label": "Refresh", "icon": "⟳"}, "parent": "hdr"},
            # The widget that must disappear. Text rather than a Metric Card
            # only because it needs no data to render — the rule is about the
            # widget's *kind*, not about what it is showing.
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "HEADER EXTRA"}, "parent": "hdr"},
            "page": {"resolvedName": "CanvasPage",
                     "props": {"title": "Overview", "icon": "◎"},
                     "isCanvas": True,
                     "nodes": ["body"]},
            "body": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "PAGE BODY"}, "parent": "page"},
        }),
        "variables": {},
        "events": {},
    })
    return mod


@pytest.fixture(scope="module")
def horizontal(api):
    return header_module(api, "Header horizontal")


@pytest.fixture(scope="module")
def vertical(api):
    return header_module(api, "Header vertical", orientation="vertical", width=200)


@pytest.fixture(scope="module")
def collapsed(api):
    return header_module(api, "Header collapsed", orientation="vertical", width=200,
                         collapsible=True, collapsedByDefault=True)


def header(page):
    return page.locator(".canvas-header")


def test_a_vertical_header_sits_to_the_left_of_the_page(page, vertical):
    """p.47: horizontal is "at the top", vertical is "on the left of the
    module". Asserting geometry rather than a class, because a class no rule
    matched would still be present on a header stacked above the page."""
    open_module(page, vertical)
    hdr = header(page).bounding_box()
    body = page.get_by_text("PAGE BODY").bounding_box()

    assert hdr["x"] + hdr["width"] <= body["x"] + 2, f"header left of the page: {hdr}, {body}"
    # And it is a column, not a strip: taller than one line of content.
    assert hdr["height"] > 40, hdr
    assert not no_console_errors(page)


def test_a_horizontal_header_sits_above_the_page(page, horizontal):
    """The baseline the test above is a change *from*. Without it, a build that
    ignored orientation entirely would have to be wrong in both directions to
    fail anything."""
    open_module(page, horizontal)
    hdr = header(page).bounding_box()
    body = page.get_by_text("PAGE BODY").bounding_box()
    assert hdr["y"] + hdr["height"] <= body["y"] + 2, f"header above the page: {hdr}, {body}"


def test_the_vertical_width_is_the_configured_one(page, vertical):
    open_module(page, vertical)
    eventually(lambda: header(page).bounding_box()["width"],
               lambda w: abs(w - 200) < 3, what="the configured header width")


def test_a_collapsed_header_hides_every_widget_but_tabs_and_buttons(page, collapsed):
    """**The rule** (p.49), and the assertion §12 asks for by name.

    Three claims in one place because they are one rule: the header is
    collapsed, the two survivors are drawn, and the third widget is *not*.
    """
    open_module(page, collapsed)
    expect(header(page)).to_have_attribute("data-collapsed", "true")

    # Presence before absence — the survivors are on screen, so "no Text
    # widget" is about the rule rather than about a header that never rendered.
    expect(page.locator(".canvas-tabs")).to_be_visible()
    expect(page.get_by_role("button", name="Refresh")).to_be_visible()
    expect(page.get_by_text("HEADER EXTRA")).to_have_count(0)

    # The page itself is untouched: the rule is about the header's contents.
    expect(page.get_by_text("PAGE BODY")).to_be_visible()


def test_a_collapsed_header_drops_the_text_and_shows_the_icon(page, collapsed):
    """p.49: the surviving widgets "will only show the icons; the text will be
    dropped in this state"."""
    open_module(page, collapsed)

    refresh = page.get_by_role("button", name="Refresh")
    assert refresh.inner_text().strip() == "⟳", refresh.inner_text()

    tab = page.locator(".canvas-tab").first
    assert tab.inner_text().strip() == "◎", tab.inner_text()
    # The label survives as the accessible name, so dropping the text does not
    # drop the meaning for anything that is not eyes.
    expect(tab).to_have_attribute("aria-label", "Overview")

    # And the module title is text too, so it goes with the rest.
    expect(page.get_by_text("MODULE TITLE")).to_have_count(0)


def test_expanding_a_collapsed_header_brings_everything_back(page, collapsed):
    """Collapsed-by-default is a starting state, not a permanent one (p.48)."""
    open_module(page, collapsed)
    page.get_by_role("button", name="Expand the header").click()

    expect(header(page)).to_have_attribute("data-collapsed", "false")
    expect(page.get_by_text("HEADER EXTRA")).to_be_visible()
    expect(page.get_by_text("MODULE TITLE")).to_be_visible()
    assert page.get_by_role("button", name="Refresh").inner_text().strip() == "Refresh"


def test_a_horizontal_header_offers_no_collapse_control(page, horizontal):
    """Collapsing is a vertical-header affordance (p.48). Offering it on a
    horizontal header would let somebody hide a header with no way to get it
    back."""
    open_builder(page, horizontal)
    expect(page.locator(".canvas-header")).to_be_visible()
    expect(page.get_by_role("button", name="Collapse the header")).to_have_count(0)
    expect(page.get_by_role("button", name="Expand the header")).to_have_count(0)
