"""p.64's widget selector, grouped (§447; `workshop` p.64).

    "To add a widget to a module, hover over any empty section to reveal the
     + Add widget button, then select it… Then, choose the desired widget from
     the widget selector modal that opens." (p.64)

The button and the Unused widgets tab are §197's. What was left is the
grouping, and the categories are Foundry's own — `workshop.md` already listed
every widget under the page its category comes from (p.444, p.220, p.276,
p.480), so `widget-palette.test.ts` owns the mapping and asserts it covers the
library exactly.

What needs a browser is that the panel is actually built from it: that a
builder sees headings rather than forty rows, that the filter narrows what is
in front of them, and — the part no unit test reaches — that an item under a
heading still **creates the widget it names**.

**Divergence, stated once:** a panel, not a modal. p.64 opens a modal because
forty entries do not fit beside a canvas; this platform put them in a column
that is always there, and grouping buys the room a modal would without taking
the canvas away while somebody chooses.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Widget palette")
    mod.define({
        "format": 2,
        "layout": layout({
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


def palette(page):
    return page.get_by_test_id("widget-palette")


def open_palette(page, module) -> None:
    open_builder(page, module)
    expect(palette(page)).to_be_visible(timeout=30000)


def test_the_library_is_grouped_rather_than_one_long_list(page, module) -> None:
    """p.64's categories. A builder looking for a way to filter an object set
    should not have to read past nine charts to find one."""
    open_palette(page, module)
    for group in ("layout", "filtering", "display", "visualization", "events"):
        expect(page.get_by_test_id(f"widget-group-{group}")).to_be_visible()


def test_each_heading_says_where_its_grouping_comes_from(page, module) -> None:
    """The categories are Foundry's, not ours — so a builder who wonders why
    Markdown is under Visualization can go and read p.276."""
    open_palette(page, module)
    expect(page.get_by_test_id("widget-group-filtering")).to_contain_text("p.444")
    expect(page.get_by_test_id("widget-group-visualization")).to_contain_text("p.276")


def test_layout_comes_first(page, module) -> None:
    """A module with no section has nowhere to put anything else."""
    open_palette(page, module)
    first = palette(page).locator("section").first
    expect(first).to_have_attribute("data-testid", "widget-group-layout")


def test_the_filter_narrows_the_list_and_drops_the_empty_groups(page, module) -> None:
    """A search that left five headings with nothing under them would be a
    list of headings."""
    open_palette(page, module)
    page.get_by_test_id("widget-search").fill("geopoint")

    expect(page.get_by_test_id("widget-group-visualization")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("widget-group-filtering")).to_have_count(0)
    expect(palette(page)).to_contain_text("Map")
    expect(palette(page)).not_to_contain_text("Filter list")


def test_a_search_that_matches_nothing_names_the_query(page, module) -> None:
    """A typo somebody can see beats a panel that might be broken."""
    open_palette(page, module)
    page.get_by_test_id("widget-search").fill("zzzz")
    empty = page.get_by_test_id("widget-palette-empty")
    expect(empty).to_be_visible(timeout=30000)
    expect(empty).to_contain_text("zzzz")
    expect(palette(page).locator("section")).to_have_count(0)


def test_every_widget_in_the_library_is_still_offered(page, module) -> None:
    """**The failure grouping actually risks**, and the one §440's rule asks
    for: a widget that fell out of the panel because nothing placed it.

    The count comes from the library file rather than from a number written
    here, so adding a widget does not need this test edited — and forgetting
    to place one makes it red rather than making it stale.

    **Not a drag.** Craft's palette uses the HTML5 drag protocol, which
    Playwright cannot drive, so no suite here has ever dropped a widget from
    it. What this does reach is the linkage: `PaletteItem` renders
    `<CANVAS_RESOLVER[componentKey] />`, so an item naming a key the resolver
    does not have throws while the panel is drawing. Forty items on screen is
    forty components that exist.
    """
    library = (
        pathlib.Path(__file__).resolve().parents[1]
        / "apps/web/src/components/canvas/widget-list.ts"
    ).read_text()
    expected = len(re.findall(r"^\s*\{ key: ", library, re.M))
    assert expected > 30, f"the library file parsed as {expected} widgets"

    open_palette(page, module)
    expect(palette(page).locator(".canvas-palette-item")).to_have_count(expected)


def test_a_palette_item_still_says_what_it_is_for(page, module) -> None:
    """The hint is what the filter searches and what a builder reads before
    choosing. Grouping rearranged every item; one that lost its hint would
    look fine and answer nothing."""
    open_palette(page, module)
    item = palette(page).locator(".canvas-palette-item", has_text="Metric card").first
    expect(item).to_be_visible(timeout=30000)
    assert "object set" in (item.get_attribute("title") or "")
