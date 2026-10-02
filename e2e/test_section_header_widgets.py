"""Widgets in a section header (§680; `workshop` p.14, p.44).

> "Select the section header above the newly configured Object View header.
> Choose the plus sign (+) on the right, then select the Button Group widget
> from the selector that appears." (p.14)
>
> "Always include counts to indicate the length of tables and lists by
> configuring a Metric Card widget in the table's section header." (p.44)

Which children count as the header's is `section-header.test.ts`. What needs
a browser is where they land: in the header, to the right of its title; still
there when the body is shut; not a tab of a tabbed section; and back in the
body when the header goes.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, select_node


def header_module(api, name: str, props: dict) -> Module:
    mod = Module(api, name)
    mod.define({"format": 2, "layout": layout({
        "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                "props": {"direction": "columns", "gap": 12, "title": "Alerts",
                          "showHeader": True, "headerWidgets": 1, **props},
                "nodes": ["count", "body1", "body2"]},
        "count": {"resolvedName": "CanvasText", "parent": "sec",
                  "props": {"tag": "p", "text": "THREE OPEN"}},
        "body1": {"resolvedName": "CanvasText", "parent": "sec",
                  "props": {"tag": "p", "text": "FIRST BODY"}},
        "body2": {"resolvedName": "CanvasText", "parent": "sec",
                  "props": {"tag": "p", "text": "SECOND BODY"}},
    }), "variables": {}, "events": {}})
    return mod


def header(page):
    return page.get_by_test_id("section-header-sec")


def in_header(page):
    return page.get_by_test_id("section-header-widgets-sec")


def body(page):
    return page.locator(".canvas-section-parts").first


def test_the_first_widget_sits_on_the_right_of_the_header(page, api) -> None:
    mod = header_module(api, "Header widgets", {})
    open_module(page, mod)
    expect(in_header(page)).to_contain_text("THREE OPEN")
    expect(body(page)).not_to_contain_text("THREE OPEN")
    expect(body(page)).to_contain_text("FIRST BODY")
    expect(body(page)).to_contain_text("SECOND BODY")
    title = header(page).get_by_role("heading", level=3).bounding_box()
    widget = in_header(page).bounding_box()
    assert widget["x"] > title["x"] + title["width"], (title, widget)
    # "On the right": its far edge is the header's.
    box = header(page).bounding_box()
    assert abs((widget["x"] + widget["width"]) - (box["x"] + box["width"])) < 24, (widget, box)


def test_a_shut_section_keeps_its_header_widgets(page, api) -> None:
    mod = header_module(api, "Header widgets collapsed", {"collapsible": True})
    open_module(page, mod)
    page.get_by_test_id("section-toggle-sec").click()
    expect(page.get_by_text("FIRST BODY")).to_be_hidden()
    expect(page.get_by_text("THREE OPEN")).to_be_visible()


def test_a_header_widget_is_not_a_tab(page, api) -> None:
    mod = header_module(api, "Header widgets tabs", {"direction": "tabs", "tabs": "One,Two"})
    open_module(page, mod)
    expect(page.get_by_role("tab")).to_have_count(2)
    expect(page.get_by_role("tab", name="One")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_text("FIRST BODY")).to_be_visible()
    expect(page.get_by_text("SECOND BODY")).to_be_hidden()
    expect(page.get_by_text("THREE OPEN")).to_be_visible()


def test_without_a_header_they_come_back_to_the_body(page, api) -> None:
    mod = header_module(api, "Header widgets no header", {"showHeader": False})
    open_module(page, mod)
    expect(body(page)).to_contain_text("THREE OPEN")
    expect(in_header(page)).to_have_count(0)


def test_the_panel_moves_widgets_into_the_header(page, api) -> None:
    mod = header_module(api, "Header widgets panel", {"headerWidgets": 0})
    open_builder(page, mod)
    select_node(page, "Section")
    field = page.get_by_test_id("section-header-widgets")
    expect(field).to_have_value("0")
    expect(field).to_have_attribute("max", "3")
    field.fill("2")
    expect(page.get_by_test_id("section-header-widgets-sec")).to_contain_text("FIRST BODY")
    save(page)
    assert mod.definition()["layout"]["sec"]["props"]["headerWidgets"] == 2
