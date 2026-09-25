"""p.486's per-button settings on the Button widget (parity `workshop.md` §10's
Button Group row; §461).

> "Button color: … a preset "intent" … none, primary (blue), success (green),
> warning (amber), and danger (red) … or specify a custom color … Left icon …
> Right icon … Description: … a tooltip … Conditional visibility: … State if
> false: … disabled or hidden … Minimal style … Tag style … Large style … Fill
> available horizontal space" (p.486)

The class list and the custom colour's style are `button-look.test.ts`. What
needs a browser is what the reader sees: computed colours, including on a
disabled button, where the old accent rule used to win; a hidden button that is
gone for a reader and still there for the builder; and the width of a filled one.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, settled

ACCENT = "rgb(20, 100, 110)"
SUCCESS = "rgb(47, 107, 67)"
WARNING = "rgb(143, 91, 14)"
DANGER = "rgb(140, 47, 34)"
TRANSPARENT = "rgba(0, 0, 0, 0)"


def button(label: str, **props) -> dict:
    return {"resolvedName": "CanvasButton", "props": {"label": label, **props}}


@pytest.fixture(scope="module")
def buttons(api):
    mod = Module(api, "Button group")
    mod.define({
        "format": 2,
        "layout": layout({
            "b_none": button("None", intent="none"),
            "b_primary": button("Primary", intent="primary"),
            "b_success": button("Success", intent="success"),
            "b_warning": button("Warning", intent="warning"),
            "b_danger": button("Danger", intent="danger"),
            "b_custom": button("Custom", intent="custom", customColour="#0b3d2e"),
            "b_pale": button("Pale", intent="custom", customColour="#ffe08a"),
            "b_minimal": button("Minimal", intent="custom", customColour="#0b3d2e", minimal=True),
            "b_min_danger": button("Minimal danger", intent="danger", minimal=True),
            # Saved before §461: `style` and no intent.
            "b_old_danger": button("Old danger", style="danger"),
            "b_old_quiet": button("Old quiet", style="quiet"),
            "b_icons": button("Icons", leftIcon="←", rightIcon="→", description="Goes both ways"),
            "b_tag": button("Tag", tag=True),
            "b_large": button("Large", large=True),
            "b_fill": button("Fill", fill=True),
            "b_off": button("Off danger", intent="danger", enabledVariable="v_off"),
            "b_gone": button("Gone", enabledVariable="v_off", hideWhenFalse=True),
            # So a test can tell the variable has resolved before it asserts
            # anything that depends on it being false.
            "t_off": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "OFF={{v_off}}"}},
        }),
        "variables": {
            "v_off": {"id": "v_off", "kind": "boolean", "label": "Off", "default": False},
        },
        "events": {},
    })
    return mod


def by(page, label: str):
    return page.get_by_role("button", name=label, exact=True)


def test_each_intent_has_its_colour(page, buttons) -> None:
    open_module(page, buttons)
    expect(by(page, "Primary")).to_have_css("background-color", ACCENT)
    expect(by(page, "Success")).to_have_css("background-color", SUCCESS)
    expect(by(page, "Warning")).to_have_css("background-color", WARNING)
    expect(by(page, "Danger")).to_have_css("background-color", DANGER)
    # `none` is the outlined one: no fill, a border.
    expect(by(page, "None")).to_have_css("background-color", TRANSPARENT)
    expect(by(page, "None")).not_to_have_css("border-top-style", "none")


def test_a_custom_colour_fills_with_readable_text(page, buttons) -> None:
    open_module(page, buttons)
    expect(by(page, "Custom")).to_have_css("background-color", "rgb(11, 61, 46)")
    expect(by(page, "Custom")).to_have_css("color", "rgb(255, 255, 255)")
    # A pale custom colour gets dark text, not white.
    expect(by(page, "Pale")).to_have_css("color", "rgb(22, 35, 47)")


def test_minimal_reverses_the_colour(page, buttons) -> None:
    """p.486: "the background color and text color … will be reversed"."""
    open_module(page, buttons)
    expect(by(page, "Minimal")).to_have_css("color", "rgb(11, 61, 46)")
    expect(by(page, "Minimal")).to_have_css("background-color", TRANSPARENT)
    # And a preset intent, which a class reverses rather than an inline style.
    expect(by(page, "Minimal danger")).to_have_css("color", DANGER)
    expect(by(page, "Minimal danger")).to_have_css("background-color", TRANSPARENT)


def test_a_button_saved_before_intents_keeps_its_meaning(page, buttons) -> None:
    """Its `style` maps to the intent that means the same: danger is red, quiet
    is uncoloured. **Not the same pixels** - the old danger was outlined with
    red text, and p.486's danger intent is filled - but the same meaning, and
    not the primary colour every old button briefly got from Craft filling the
    missing `intent` from a default."""
    open_module(page, buttons)
    expect(by(page, "Old danger")).to_have_css("background-color", DANGER)
    expect(by(page, "Old quiet")).to_have_css("background-color", TRANSPARENT)


def test_a_disabled_button_keeps_its_colour(page, buttons) -> None:
    """`.btn:disabled` painted the accent, so a disabled danger button turned
    teal. Disabled is shown by fading, not by changing what it means."""
    open_module(page, buttons)
    off = by(page, "Off danger")
    expect(off).to_be_disabled()
    expect(off).to_have_css("background-color", DANGER)
    # Hovered too: `.btn:disabled:hover` outranks an intent class, and it is
    # the hover that repainted it.
    off.hover(force=True)
    expect(off).to_have_css("background-color", DANGER)


def test_icons_either_side_and_a_tooltip(page, buttons) -> None:
    open_module(page, buttons)
    icons = page.get_by_role("button", name="Icons")
    expect(icons).to_have_text("←Icons→")
    expect(icons).to_have_attribute("title", "Goes both ways")


def test_tag_large_and_fill(page, buttons) -> None:
    open_module(page, buttons)
    expect(by(page, "Tag")).to_have_css("border-top-left-radius", "999px")
    expect(by(page, "Large")).to_have_css("font-size", "15px")
    # Fill: as wide as what holds it, and wider than an ordinary button.
    fill = by(page, "Fill").bounding_box()
    plain = by(page, "Primary").bounding_box()
    holder = page.locator(".canvas-button-wrap--fill").bounding_box()
    assert fill and plain and holder
    assert abs(fill["width"] - holder["width"]) < 2, (fill, holder)
    assert fill["width"] > plain["width"] * 3, (fill, plain)


def test_state_if_false_hidden_is_gone_for_a_reader(page, buttons) -> None:
    """Positive first (§318): the disabled one on the same variable is there,
    so the hidden one's absence is the setting and not a slow page."""
    open_module(page, buttons)
    expect(by(page, "Off danger")).to_be_visible()
    expect(by(page, "Gone")).to_have_count(0)


def test_the_builder_still_shows_a_hidden_button(page, buttons) -> None:
    """Hidden applies to readers: a builder who could not see the button could
    not select it to change the setting back."""
    open_builder(page, buttons)
    settled(page)
    # Once the variable is known to be false - before that, a button that
    # hid itself for the builder would still look present.
    expect(page.get_by_text("OFF=false")).to_be_visible()
    expect(by(page, "Gone")).to_be_visible()


def test_the_panel_sets_an_intent(page, api) -> None:
    mod = Module(api, "Button panel")
    mod.define({"format": 2, "layout": layout({"b": button("Go")}),
                "variables": {}, "events": {}})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Button").first.click()
    page.get_by_test_id("button-intent").select_option("success")
    page.get_by_test_id("button-large").check()
    save(page)
    props = mod.definition()["layout"]["b"]["props"]
    assert props["intent"] == "success" and props["large"] is True, props
    # Custom reveals its colour box, which says when what is typed is not one.
    page.get_by_test_id("button-intent").select_option("custom")
    page.get_by_test_id("button-custom-colour").fill("red")
    expect(page.locator(".field-hint", has_text="Not a colour yet")).to_be_visible()
