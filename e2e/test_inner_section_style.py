"""p.62's Inner section style (§704).

> "Inner section style: Optionally select one of various pre-defined section
> styles to be applied to all children sections" (p.62)

Which preset is which three settings, and which of a child's own values win,
is `inner-section-style.test.ts`. What needs a browser is that a child drawn
under a parent naming one *looks* like it - the header where the preset puts
it, the border it casts, the body's colour - that a grandchild does not, and
that the builder sets one and lets a child give up its own values for it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, select_node

TRANSPARENT = "rgba(0, 0, 0, 0)"
WHITE = "rgb(255, 255, 255)"
SHADE_3 = "rgb(241, 244, 246)"


def nested(api, name: str, outer: dict, child: dict, *, page: dict | None = None) -> Module:
    """An outer section holding a child section with a header, which holds a
    grandchild - optionally all on a page."""
    nodes = {
        "outer": {"resolvedName": "CanvasSection", "isCanvas": True,
                  "props": {"direction": "rows", "gap": 12, **outer},
                  "nodes": ["child", "plain"], "custom": {"displayName": "Outer"}},
        "child": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "outer",
                  "props": {"direction": "rows", "gap": 12, "showHeader": True,
                            "title": "Alerts", **child},
                  "nodes": ["grand"], "custom": {"displayName": "Child"}},
        "plain": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "outer",
                  "props": {"direction": "rows", "gap": 12, "background": "shade-4",
                            "border": "borderless"},
                  "nodes": ["plaintext"]},
        "plaintext": {"resolvedName": "CanvasText", "parent": "plain",
                      "props": {"tag": "p", "text": "OWN COLOURS"}},
        "grand": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "child",
                  "props": {"direction": "rows", "gap": 12}, "nodes": ["text"]},
        "text": {"resolvedName": "CanvasText", "parent": "grand",
                 "props": {"tag": "p", "text": "GRANDCHILD"}},
    }
    if page is not None:
        nodes = {"pg": {"resolvedName": "CanvasPage", "isCanvas": True,
                        "props": {"title": "Main", **page}, "nodes": ["outer"]},
                 **{k: ({**v, "parent": "pg"} if k == "outer" else v) for k, v in nodes.items()}}
    mod = Module(api, name)
    mod.define({"format": 2, "layout": layout(nodes), "variables": {}, "events": {}})
    return mod


def child(page):
    return page.locator(".canvas-section", has=page.get_by_test_id("section-header-child")).last


def child_body(page):
    return child(page).locator(":scope > .canvas-section-parts")


def grandchild(page):
    return page.locator(".canvas-section", has=page.get_by_text("GRANDCHILD")).last


def plain(page):
    return page.locator(".canvas-section", has=page.get_by_text("OWN COLOURS")).last


def test_minimal_elevated_floats_the_header_over_a_shadowed_box(page, api) -> None:
    mod = nested(api, "Inner minimal", {"innerSectionStyle": "minimal-elevated"}, {})
    open_module(page, mod)
    expect(page.get_by_test_id("section-header-child")).to_have_class(
        "canvas-section-header canvas-section-header--floating")
    # Floating puts the box under the header, so the shadow is the body's.
    expect(child(page)).to_have_css("background-color", TRANSPARENT)
    expect(child_body(page)).to_have_css("background-color", WHITE)
    expect(child_body(page)).not_to_have_css("box-shadow", "none")
    # Children, not descendants.
    expect(grandchild(page)).to_have_css("box-shadow", "none")
    expect(grandchild(page)).to_have_css("border-top-style", "none")


def test_a_child_keeps_what_it_set_and_takes_the_rest(page, api) -> None:
    mod = nested(api, "Inner own values", {"innerSectionStyle": "classic"},
                 {"headerStyle": "contained"})
    open_module(page, mod)
    expect(page.get_by_test_id("section-header-child")).to_have_class(
        "canvas-section-header canvas-section-header--contained")
    expect(child(page)).to_have_css("border-top-style", "solid")
    expect(child(page)).to_have_css("background-color", WHITE)
    # A section that chose a colour and no border keeps both.
    expect(plain(page)).to_have_css("background-color", "rgb(226, 232, 237)")
    expect(plain(page)).to_have_css("border-top-style", "none")


def test_a_page_greys_classic_gray_s_body_under_a_white_bar(page, api) -> None:
    mod = nested(api, "Inner page", {}, {}, page={"innerSectionStyle": "classic-gray"})
    open_module(page, mod)
    outer = page.locator(".canvas-section", has=page.get_by_text("OWN COLOURS")).first
    expect(outer).to_have_css("background-color", WHITE)
    expect(outer).to_have_css("border-top-style", "solid")
    expect(outer.locator(":scope > .canvas-section-parts")).to_have_css("background-color", SHADE_3)
    # The page's preset is the outer section's; the outer section names none.
    expect(child(page)).to_have_css("border-top-style", "none")


def test_without_a_preset_nothing_changes(page, api) -> None:
    mod = nested(api, "Inner none", {}, {})
    open_module(page, mod)
    expect(page.get_by_test_id("section-header-child")).to_have_class(
        "canvas-section-header canvas-section-header--block")
    expect(child(page)).to_have_css("background-color", TRANSPARENT)
    expect(child(page)).to_have_css("border-top-style", "none")


def test_the_builder_names_a_preset_and_a_child_gives_up_its_own(page, api) -> None:
    mod = nested(api, "Inner builder", {}, {"headerStyle": "block", "border": "bordered"})
    open_builder(page, mod)
    select_node(page, "Outer")
    page.get_by_test_id("inner-section-style").select_option("muted-gray")
    select_node(page, "Child")
    note = page.get_by_test_id("inherited-section-style")
    expect(note).to_contain_text("The parent's inner section style is Muted gray.")
    expect(note).to_contain_text("This section's own header format and border take its place.")
    page.get_by_test_id("use-inner-section-style").click()
    expect(note).to_contain_text("This section takes all of it.")
    expect(page.get_by_test_id("use-inner-section-style")).to_have_count(0)
    save(page)
    layout_ = mod.definition()["layout"]
    assert layout_["outer"]["props"]["innerSectionStyle"] == "muted-gray"
    props = layout_["child"]["props"]
    assert (props.get("headerStyle"), props.get("border")) == (None, None), props
    open_module(page, mod)
    expect(page.get_by_test_id("section-header-child")).to_have_class(
        "canvas-section-header canvas-section-header--contained")
    expect(child(page)).to_have_css("background-color", SHADE_3)


def test_a_page_names_a_preset_in_the_builder(page, api) -> None:
    mod = nested(api, "Inner page builder", {}, {}, page={})
    open_builder(page, mod)
    select_node(page, "Page")
    page.get_by_test_id("inner-section-style").select_option("minimal-ghost")
    save(page)
    assert mod.definition()["layout"]["pg"]["props"]["innerSectionStyle"] == "minimal-ghost"
