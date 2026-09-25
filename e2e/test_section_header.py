"""p.13's Section Header and p.58's header formatting (§473).

> "Header formatting options can be added when the header is enabled on a
> section. There are three available: Block: The section header is in its own
> container above the body. Contained: The section header appears to be
> contained within the body area. Floating: The section header appears above
> the body area and is visually on the background of the parent section."
> (p.58)

Which box a floating header moves is `section-header.test.ts`. What needs a
browser is what a reader sees: the header's title, icon and description, a
bar for Block and none for the other two, and for Floating a section box that
starts below the header rather than around it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, select_node

TRANSPARENT = "rgba(0, 0, 0, 0)"


def section_module(api, name: str, props: dict) -> Module:
    mod = Module(api, name)
    mod.define({"format": 2, "layout": layout({
        "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                "props": {"direction": "columns", "gap": 12, "title": "Inbox",
                          "background": "shade-2", **props},
                "nodes": ["inside"]},
        "inside": {"resolvedName": "CanvasText", "parent": "sec",
                   "props": {"tag": "p", "text": "INSIDE THE SECTION"}},
    }), "variables": {}, "events": {}})
    return mod


def header(page):
    return page.get_by_test_id("section-header-sec")


def section(page):
    return page.locator(".canvas-section", has=page.get_by_text("INSIDE THE SECTION")).first


def body(page):
    return section(page).locator(".canvas-section-parts").first


def test_a_header_shows_its_title_icon_and_description(page, api) -> None:
    mod = section_module(api, "Section header", {
        "showHeader": True, "headerIcon": "✉", "description": "Alerts awaiting triage"})
    open_module(page, mod)
    # p.28: section headers are the second largest text - a heading.
    expect(header(page).get_by_role("heading", level=3)).to_have_text("Inbox")
    expect(header(page)).to_contain_text("✉")
    expect(header(page).locator(".canvas-section-description")).to_have_text(
        "Alerts awaiting triage")


def test_without_the_setting_there_is_no_header(page, api) -> None:
    mod = section_module(api, "Section no header", {})
    open_module(page, mod)
    expect(page.get_by_text("INSIDE THE SECTION")).to_be_visible()
    expect(header(page)).to_have_count(0)


def test_block_is_a_bar_of_its_own(page, api) -> None:
    mod = section_module(api, "Section block", {"showHeader": True, "headerStyle": "block"})
    open_module(page, mod)
    expect(header(page)).to_have_css("border-bottom-style", "solid")
    expect(header(page)).not_to_have_css("background-color", TRANSPARENT)
    # "Its own container": the width of the box, not inset by its padding.
    assert abs(header(page).bounding_box()["width"] - section(page).bounding_box()["width"]) < 3


def test_block_moves_the_padding_to_the_body(page, api) -> None:
    mod = section_module(api, "Section block padded", {
        "showHeader": True, "headerStyle": "block", "padding": "compact"})
    open_module(page, mod)
    expect(body(page)).to_have_css("padding-left", "16px")
    expect(section(page)).to_have_css("padding-left", "0px")


def test_contained_sits_in_the_body_with_no_bar(page, api) -> None:
    mod = section_module(api, "Section contained", {"showHeader": True,
                                                    "headerStyle": "contained"})
    open_module(page, mod)
    expect(header(page)).to_have_css("border-bottom-style", "none")
    expect(header(page)).to_have_css("background-color", TRANSPARENT)
    # Inside the section's own box, which is the section's background.
    expect(section(page)).not_to_have_css("background-color", TRANSPARENT)


def test_floating_sits_on_the_parent_and_the_box_starts_below_it(page, api) -> None:
    mod = section_module(api, "Section floating", {"showHeader": True,
                                                   "headerStyle": "floating"})
    open_module(page, mod)
    expect(header(page)).to_be_visible()
    expect(section(page)).to_have_css("background-color", TRANSPARENT)
    expect(body(page)).not_to_have_css("background-color", TRANSPARENT)
    assert header(page).bounding_box()["y"] + header(page).bounding_box()["height"] \
        <= body(page).bounding_box()["y"] + 1


def test_a_collapsible_section_s_control_is_its_header(page, api) -> None:
    mod = section_module(api, "Section collapsible header", {
        "showHeader": True, "collapsible": True, "description": "Tap to hide"})
    open_module(page, mod)
    toggle = header(page).get_by_test_id("section-toggle-sec")
    expect(toggle).to_contain_text("Inbox")
    toggle.click()
    expect(page.get_by_text("INSIDE THE SECTION")).to_be_hidden()
    # The description stays, as the title does: it says what is shut.
    expect(header(page).locator(".canvas-section-description")).to_be_visible()


def test_the_panel_turns_the_header_on_and_formats_it(page, api) -> None:
    mod = section_module(api, "Section header panel", {"background": None})
    open_builder(page, mod)
    select_node(page, "Section")
    page.get_by_test_id("section-show-header").check()
    page.get_by_test_id("section-title").fill("Filters")
    page.get_by_test_id("section-description").fill("Narrow the table")
    page.get_by_test_id("section-header-style").select_option("floating")
    save(page)
    props = mod.definition()["layout"]["sec"]["props"]
    assert (props["showHeader"], props["title"], props["description"], props["headerStyle"]) \
        == (True, "Filters", "Narrow the table", "floating"), props
