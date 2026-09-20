"""p.214's Saved colors (§414; `workshop` p.213-214).

> "Saved colors are defined at the module level. Add colors to the Saved
> colors section to make them selectable when configuring custom colors in
> layouts and widgets… You can rename saved colors, set separate colors for
> light and dark modes, and view where each color is used across layouts and
> widgets in your module. **When you edit a saved color, the change propagates
> to all layouts, sections, and widgets that reference it**, so you can update
> colors across your module in one place." (p.214)

What a palette entry means, which references resolve to what, and what the
Background control shows as chosen are all values, checked in
`saved-colours.test.ts`, `style.test.ts` and `used-colours.test.ts`.

**What needs a browser is the emphasised sentence**, and nothing short of a
browser can check it: two widgets that never mention each other, one edit in a
third place, and both repainting. A unit test can prove the resolver returns
the new hex; only a page can prove that both widgets asked it again.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import (
    eventually, open_builder, open_module, publish, save, settled, viewer_url,
)

TEAL = "#1f7a70"
RUST = "#a4471f"
NOWHERE = "saved:c9"


def module_with_palette(api, name: str, *, palette, backgrounds, events=None) -> Module:
    nodes = {
        node_id: {
            "resolvedName": "CanvasSection", "isCanvas": True,
            "props": {"direction": "columns", "gap": 12, "background": background},
            "nodes": [],
        }
        for node_id, background in backgrounds.items()
    }
    if events:
        nodes["btn"] = {"resolvedName": "CanvasButton", "props": {"label": "Do it"}}
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {},
        "events": events or {},
        "saved_colours": palette,
    })
    return mod


def background_of(page, index: int) -> str:
    return page.eval_on_selector_all(
        ".canvas-section",
        "els => els.map(e => getComputedStyle(e).backgroundColor)",
    )[index]


def test_a_widget_stores_a_reference_and_renders_the_colour(page, api) -> None:
    """The reference resolves on the way to the screen. Nothing on either
    section holds `#1f7a70`; both hold `saved:c1`."""
    mod = module_with_palette(
        api, "Saved reference",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": RUST}],
        backgrounds={"a": "saved:c1", "b": "saved:c1"},
    )
    open_module(page, mod)
    settled(page)
    eventually(lambda: background_of(page, 0),
               lambda c: c == "rgb(31, 122, 112)",
               what="the saved colour, resolved")
    assert background_of(page, 1) == "rgb(31, 122, 112)"


def test_editing_a_saved_colour_repaints_every_widget_that_references_it(
    page, api
) -> None:
    """**p.214's sentence, and the reason the palette is a reference rather
    than a copy.**

    Two sections, neither of which mentions the other or holds a hex. One edit,
    in a panel that belongs to neither. A palette that copied its value into
    each widget would pass every other test in this file and fail this one —
    on the second day, quietly, in a module somebody had already shipped.
    """
    mod = module_with_palette(
        api, "Saved propagation",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL}],
        backgrounds={"a": "saved:c1", "b": "saved:c1"},
    )
    open_builder(page, mod)
    eventually(lambda: background_of(page, 0), lambda c: c == "rgb(31, 122, 112)",
               what="the colour before the edit")

    field = page.get_by_test_id("saved-light-c1")
    field.fill(RUST)
    eventually(lambda: background_of(page, 0), lambda c: c == "rgb(164, 71, 31)",
               what="the first section, repainted")
    assert background_of(page, 1) == "rgb(164, 71, 31)", "and the second one"


def test_the_panel_says_where_a_saved_colour_is_used(page, api) -> None:
    """p.214: "view where each color is used across layouts and widgets". The
    same sentence the unsaved rows use, because two ways of saying "2 places"
    in one panel is two things a reader has to learn."""
    mod = module_with_palette(
        api, "Saved usage",
        palette=[
            {"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL},
            {"id": "c2", "name": "Spare", "light": RUST, "dark": RUST},
        ],
        backgrounds={"a": "saved:c1", "b": "saved:c1"},
    )
    open_builder(page, mod)
    expect(page.get_by_test_id("saved-uses-c1")).to_have_text("2 places")
    # A colour nothing points at says so rather than being left off the list:
    # p.214's palette is what a builder may select, not what they have selected.
    expect(page.get_by_test_id("saved-uses-c2")).to_have_text("0 places")
    page.get_by_test_id("saved-uses-c2").click()
    expect(page.get_by_test_id("saved-use-list-c2")).to_contain_text("Nothing uses")


def test_a_saved_colour_is_offered_by_name_on_a_background(page, api) -> None:
    """p.214: "selectable when configuring custom colors in layouts and
    widgets, including section and page backgrounds". By name — the name is
    the whole point of saving one."""
    mod = module_with_palette(
        api, "Saved selectable",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL}],
        backgrounds={"a": ""},
    )
    open_builder(page, mod)
    page.locator(".canvas-section").first.click()
    picker = page.get_by_test_id("style-background")
    expect(picker).to_be_visible()
    labels = page.eval_on_selector_all(
        "[data-testid='style-background'] option", "els => els.map(e => e.textContent)")
    assert "Brand" in labels, labels

    picker.select_option("saved:c1")
    eventually(lambda: background_of(page, 0), lambda c: c == "rgb(31, 122, 112)",
               what="the section, now on the saved colour")


def test_a_reference_to_a_colour_that_is_gone_paints_nothing(page, api) -> None:
    """§210. The palette entry has gone — a reverted version can do that — and
    the section is transparent rather than quietly black. The control says
    Custom over the raw value, which is the only place a builder could find
    out what happened."""
    mod = module_with_palette(
        api, "Saved dangling",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL}],
        backgrounds={"a": NOWHERE},
    )
    open_builder(page, mod)
    expect(page.locator(".canvas-section").first).to_be_visible()
    assert background_of(page, 0) == "rgba(0, 0, 0, 0)", background_of(page, 0)

    page.locator(".canvas-section").first.click()
    expect(page.get_by_test_id("style-background")).to_have_value("custom")
    expect(page.get_by_test_id("style-background-hex")).to_have_value(NOWHERE)


def test_the_dark_value_is_what_a_dark_module_uses(page, api) -> None:
    """p.214: "set separate colors for light and dark modes". The pair is only
    a pair if the second half is ever reached, and the module's scheme is what
    reaches it (p.91's Toggle theme)."""
    mod = module_with_palette(
        api, "Saved dark",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": RUST}],
        backgrounds={"a": "saved:c1"},
        events={"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                        "effects": [{"type": "toggle_theme"}]}},
    )
    open_module(page, mod)
    settled(page)
    eventually(lambda: background_of(page, 0), lambda c: c == "rgb(31, 122, 112)",
               what="the light value")
    page.get_by_role("button", name="Do it").click()
    eventually(lambda: background_of(page, 0), lambda c: c == "rgb(164, 71, 31)",
               what="the dark value, once the module is dark")


def test_adding_a_colour_does_not_claim_the_widgets_already_holding_that_hex(
    page, api
) -> None:
    """p.214 says adding a colour makes it *selectable*. It does not say the
    module rewrites itself — and rewriting every node holding that hex would
    be a silent edit to widgets nobody selected, and the one thing pressing
    the button again could not undo."""
    mod = module_with_palette(
        api, "Saved add", palette=[], backgrounds={"a": TEAL},
    )
    open_builder(page, mod)
    expect(page.get_by_test_id("saved-colours-empty")).to_be_visible()

    page.get_by_test_id(f"colour-save-{TEAL[1:]}").click()
    expect(page.get_by_test_id("saved-light-c1")).to_have_value(TEAL)
    # Still an unsaved colour, because the section still holds the hex.
    expect(page.locator('[data-testid="used-colours-rows"] > li')).to_have_count(1)
    expect(page.get_by_test_id("saved-uses-c1")).to_have_text("0 places")


def test_a_published_module_resolves_the_palette_too(page, api) -> None:
    """The route nobody is looking at while building.

    A palette wired into the builder and not into the viewer fails only where
    it is never seen during development: every referencing widget on the
    published page renders with no background at all, and the module looks
    fine to the person who built it.
    """
    mod = module_with_palette(
        api, "Saved published",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": RUST}],
        backgrounds={"a": "saved:c1"},
    )
    publish(mod)
    page.goto(viewer_url(mod))
    settled(page)
    eventually(lambda: background_of(page, 0), lambda c: c == "rgb(31, 122, 112)",
               what="the saved colour on the published route")


def test_the_palette_survives_a_save(page, api) -> None:
    """The Save button has to carry the palette, for the reason it carries
    the variables: a widget's background references it, so a save that dropped
    it would leave every one of those references naming nothing — and it would
    happen on the first save after opening, which is to say immediately."""
    mod = module_with_palette(
        api, "Saved persisted",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL}],
        backgrounds={"a": "saved:c1"},
    )
    open_builder(page, mod)
    page.get_by_test_id("saved-name-c1").fill("Primary")
    page.get_by_test_id("saved-light-c1").fill(RUST)
    save(page)

    stored = mod.definition().get("saved_colours")
    assert stored == [
        {"id": "c1", "name": "Primary", "light": RUST, "dark": TEAL},
    ], stored
