"""Style formatting for pages, sections and widgets (parity `workshop.md` §1.5;
Foundry p.57-62).

> "Workshop offers control over various style formatting settings… These
> options are available at the page, section, and widget levels." (p.57)

Almost all of it is values, and the values are checked directly in
`apps/web/src/components/canvas/style.test.ts` — p.62's own numbers, p.60's
four borders, p.59-60's brightness threshold. What needs a browser is the one
claim arithmetic cannot make:

> "When a custom background color is applied to a section, **widgets within
> that section** automatically switch between light and dark mode based on the
> brightness of the background, ensuring text and controls remain legible."
> (p.59-60)

`isDarkBackground` deciding correctly and the widgets inside still rendering
dark-on-dark is a passing unit suite and an unreadable module. So the checks
here read **computed colours**, per the rough edge this repo has been caught by
twice: an undefined custom property is silently nothing, and a structural check
walks straight past it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module

# The platform's own ink, which is comfortably below p.59-60's crossover.
DARK = "#16232f"


def styled_module(api, name: str, section_props: dict) -> Module:
    """One section holding one text widget, so "widgets within that section"
    has something to be about."""
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                    "props": {"direction": "columns", "gap": 12, **section_props},
                    "nodes": ["txt"]},
            "txt": {"resolvedName": "CanvasText", "parent": "sec",
                    "props": {"tag": "p", "text": "READ ME"}},
        }),
        "variables": {},
        "events": {},
    })
    return mod


def luminance(page, selector: str, prop: str = "color") -> float:
    """The rendered colour of an element, as WCAG relative luminance.

    Reading the number rather than the string: `rgb(242, 245, 247)` and
    `#f2f5f7` are the same colour and different assertions, and a test that
    pinned the exact token would fail the next time somebody adjusted a shade
    by a point — which is a test that gets deleted rather than fixed.
    """
    return page.evaluate(
        """([sel, prop]) => {
            const el = document.querySelector(sel);
            const parsed = getComputedStyle(el)[prop].match(/[\\d.]+/g).map(Number);
            const [r, g, b] = parsed.slice(0, 3).map((v) => {
                const c = v / 255;
                return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
            });
            return 0.2126 * r + 0.7152 * g + 0.0722 * b;
        }""",
        [selector, prop],
    )


def test_a_dark_section_makes_the_text_inside_it_light(page, api) -> None:
    """**p.59-60's rule, and the half a unit test cannot see.**

    The text widget is not told anything. It reads `--ink` like every other
    widget, and the section redefines that token beneath itself — which is what
    makes the rule reach widgets written years before it existed.
    """
    mod = styled_module(api, "Style dark", {"background": DARK})
    open_module(page, mod)

    section = ".canvas-section"
    expect(page.locator(f'{section}[data-scheme="dark"]')).to_have_count(1)
    # The background really is the dark colour...
    assert luminance(page, section, "backgroundColor") < 0.05
    # ...and the text on it is light. Asserted as a comparison rather than a
    # threshold: the claim is legibility, which is about the two together.
    assert luminance(page, f"{section} p", "color") > 0.5


def test_a_light_section_leaves_the_text_dark(page, api) -> None:
    """The other half, and the one that fails if the rule is wired to fire
    whenever a background is set at all."""
    mod = styled_module(api, "Style light", {"background": "shade-4"})
    open_module(page, mod)

    section = ".canvas-section"
    expect(page.locator(f'{section}[data-scheme="dark"]')).to_have_count(0)
    assert luminance(page, section, "backgroundColor") > 0.5
    assert luminance(page, f"{section} p", "color") < 0.1


def test_an_unstyled_section_renders_as_it_always_did(page, api) -> None:
    """Every module in the corpus predates these props. A section that started
    drawing a box, or padding, the day they landed would be a regression
    nothing in the diff mentioned."""
    mod = styled_module(api, "Style none", {})
    open_module(page, mod)

    section = page.locator(".canvas-section")
    expect(section).not_to_have_attribute("data-scheme", "dark")
    assert page.evaluate(
        """() => {
            const s = getComputedStyle(document.querySelector('.canvas-section'));
            return [s.padding, s.borderTopWidth];
        }"""
    ) == ["0px", "0px"]


def test_padding_uses_p62s_numbers_and_is_not_square(page, api) -> None:
    """p.62: "Regular: Adds 24 pixels of top/bottom padding and 48 pixels of
    left/right padding". The asymmetry is the part that gets lost, so it is the
    part asserted — through a real render, since a style attribute that never
    reached the element passes any check on the prop."""
    mod = styled_module(api, "Style padding", {"background": "shade-2", "padding": "regular"})
    open_module(page, mod)

    assert page.evaluate(
        """() => {
            const s = getComputedStyle(document.querySelector('.canvas-section'));
            return [s.paddingTop, s.paddingLeft];
        }"""
    ) == ["24px", "48px"]


def test_each_level_offers_what_p57_to_p62_says_it_does(page, api) -> None:
    """p.60 names "sections and widgets"; p.62's padding names "pages and
    sections". Offering all four controls everywhere would be less code and
    would put a padding control on a widget with nothing to pad.

    **The widget compared against is a Container, not the Text widget.** Text
    has no style block at all, so its panel is missing every one of these
    controls whatever the rule says — a check made there passes for a reason it
    did not state, and cannot fail when the rule is wrong. The Container is the
    widget that *does* carry the block, so it is the one that can tell a
    correct per-level rule from a missing one.
    """
    mod = Module(api, "Style levels")
    mod.define({
        "format": 2,
        "layout": layout({
            "box": {"resolvedName": "CanvasContainer", "isCanvas": True,
                    "props": {"background": "", "padding": 12}, "nodes": ["sec"]},
            "sec": {"resolvedName": "CanvasSection", "parent": "box", "isCanvas": True,
                    "props": {"direction": "columns", "gap": 12}, "nodes": []},
        }),
        "variables": {},
        "events": {},
    })
    open_builder(page, mod)

    # The section is the one level that gets all three.
    page.locator(".canvas-tree-row", has_text="Section").first.click()
    expect(page.get_by_test_id("style-background")).to_be_visible()
    expect(page.get_by_test_id("style-padding")).to_be_visible()
    expect(page.get_by_test_id("style-border")).to_be_visible()

    # A widget gets the background and the border, and no padding scale.
    page.locator(".canvas-tree-row", has_text="Container").first.click()
    expect(page.get_by_test_id("style-background")).to_be_visible()
    expect(page.get_by_test_id("style-border")).to_be_visible()
    expect(page.get_by_test_id("style-padding")).to_have_count(0)


def test_choosing_custom_reveals_the_hex_field_seeded_with_what_is_showing(
    page, api
) -> None:
    """p.59: "Select the custom color tile to open the color picker to enter a
    hex code". Seeded rather than blanked, so reaching for a shade of the
    current colour does not start by losing it."""
    mod = styled_module(api, "Style custom", {"background": "shade-4"})
    open_builder(page, mod)
    page.locator(".canvas-tree-row", has_text="Section").first.click()

    expect(page.get_by_test_id("style-background-hex")).to_have_count(0)
    page.get_by_test_id("style-background").select_option("custom")
    hex_field = page.get_by_test_id("style-background-hex")
    expect(hex_field).to_be_visible()
    expect(hex_field).to_have_value("#e2e8ed")

    # And typing a dark one flips the section in the builder, live.
    hex_field.fill(DARK)
    expect(page.locator('.canvas-section[data-scheme="dark"]')).to_have_count(1)
