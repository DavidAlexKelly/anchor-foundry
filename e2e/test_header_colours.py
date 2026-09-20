"""p.47's two header colours (§415; `workshop` p.47).

> "Choose a custom color for the title text."
> "Select a background color for the header."

What each stored value resolves to is `style.test.ts`'s and
`saved-colours.test.ts`'s. What needs a browser is what neither can see: that
a colour on the header reaches the *navigation inside it* through p.59-60's
brightness rule, that a saved colour is offered here as it is everywhere else
(§414), and that the padding a coloured header needs arrives with the colour
and not before it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, select_node, settled

TEAL = "#1f7a70"
NIGHT = "#16232f"
PALE = "#f4efe6"


def header_module(api, name: str, *, palette=None, **header_props):
    mod = Module(api, name)
    doc = {
        "format": 2,
        "layout": layout({
            "hdr": {"resolvedName": "CanvasHeader",
                    "props": {"title": "MODULE TITLE", **header_props},
                    "isCanvas": True, "nodes": ["btn"]},
            "btn": {"resolvedName": "CanvasButton",
                    "props": {"label": "Refresh"}, "parent": "hdr"},
        }),
        "variables": {}, "events": {},
    }
    if palette is not None:
        doc["saved_colours"] = palette
    mod.define(doc)
    return mod


def header(page):
    return page.locator(".canvas-header").first


def css(page, selector: str, prop: str) -> str:
    return page.eval_on_selector(selector, f"el => getComputedStyle(el)[{prop!r}]")


def test_a_header_with_no_colour_is_unchanged(page, api) -> None:
    """The baseline, and it has to hold before any of the rest means anything:
    a header nobody has coloured keeps the padding and the scheme it had.

    §318 — this follows a positive wait on the title, so it cannot pass merely
    by running before the header rendered.
    """
    mod = header_module(api, "Header plain")
    open_module(page, mod)
    settled(page)
    expect(page.locator(".canvas-header-title")).to_have_text("MODULE TITLE")
    expect(header(page)).not_to_have_attribute("data-tinted", "true")
    assert css(page, ".canvas-header", "paddingLeft") == "0px"


def test_a_background_colours_the_header_and_pads_it(page, api) -> None:
    """p.47's second sentence, and the padding that has to come with it: a
    coloured band running to the edge of the viewport reads as a rendering
    fault rather than as a choice."""
    mod = header_module(api, "Header background", background=TEAL)
    open_module(page, mod)
    settled(page)
    eventually(lambda: css(page, ".canvas-header", "backgroundColor"),
               lambda c: c == "rgb(31, 122, 112)",
               what="the header's colour")
    expect(header(page)).to_have_attribute("data-tinted", "true")
    assert css(page, ".canvas-header", "paddingLeft") != "0px"


def test_a_dark_header_relights_the_navigation_inside_it(page, api) -> None:
    """**The reason the background goes through the style block rather than
    being a colour on a box.**

    p.59-60: "widgets within that section automatically switch between light
    and dark mode based on the brightness of the background". A header holds
    the module's navigation, so a dark header with dark buttons is a module
    nobody can steer — and the button knows nothing about any of this.
    """
    dark = header_module(api, "Header dark", background=NIGHT)
    open_module(page, dark)
    settled(page)
    eventually(lambda: css(page, ".canvas-header", "backgroundColor"),
               lambda c: c == "rgb(22, 35, 47)", what="the dark header")
    expect(header(page)).to_have_attribute("data-scheme", "dark")
    # **The title, not a button.** A `.btn` carries its own colour — white on
    # an accent fill, legible on any band — so it could never answer this
    # question, and asking it was a check that could not fail. The title sets
    # no colour of its own, which makes it exactly the text p.59-60 is about.
    on_dark = css(page, ".canvas-header-title", "color")

    light = header_module(api, "Header light", background=PALE)
    open_module(page, light)
    settled(page)
    eventually(lambda: css(page, ".canvas-header", "backgroundColor"),
               lambda c: c == "rgb(244, 239, 230)", what="the pale header")
    # The same markup, no colour set on it, two different paints — which is the
    # whole of p.59-60 and none of it is the title's doing.
    on_light = css(page, ".canvas-header-title", "color")
    assert on_light != on_dark, (on_light, on_dark)


def test_the_title_takes_its_own_colour(page, api) -> None:
    """p.47's first sentence. Separate from the background, because a title is
    the one thing on a header that a background cannot settle."""
    mod = header_module(api, "Header title colour", titleColour=TEAL)
    open_module(page, mod)
    settled(page)
    eventually(lambda: css(page, ".canvas-header-title", "color"),
               lambda c: c == "rgb(31, 122, 112)",
               what="the title's own colour")


def test_a_saved_colour_is_offered_for_both(page, api) -> None:
    """§414's palette reaching p.47's two controls. By name, and stored as a
    reference — so editing the saved colour later moves the header with
    everything else, which is the whole point of a saved colour."""
    mod = header_module(
        api, "Header saved", titleColour="saved:c1", background="saved:c1",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL}],
    )
    open_module(page, mod)
    settled(page)
    eventually(lambda: css(page, ".canvas-header", "backgroundColor"),
               lambda c: c == "rgb(31, 122, 112)", what="the header, on the saved colour")
    assert css(page, ".canvas-header-title", "color") == "rgb(31, 122, 112)"

    open_builder(page, mod)
    select_node(page, "Header")
    labels = page.eval_on_selector_all(
        "[data-testid='header-title-colour'] option", "els => els.map(e => e.textContent)")
    assert "Brand" in labels, labels
    expect(page.get_by_test_id("header-title-colour")).to_have_value("saved:c1")
    expect(page.get_by_test_id("style-background")).to_have_value("saved:c1")


def test_the_header_is_offered_no_padding_or_border(page, api) -> None:
    """p.60 puts borders on "sections and widgets" and p.62 puts padding on
    "pages and sections". A header is neither, so it gets the one setting p.47
    names — and a control that did nothing would be worse than absent (§214).

    §318: asserted after the background control is on screen, so the absences
    are about the panel rather than about timing.
    """
    mod = header_module(api, "Header style scope")
    open_builder(page, mod)
    select_node(page, "Header")
    expect(page.get_by_test_id("style-background")).to_be_visible()
    expect(page.get_by_test_id("style-padding")).to_have_count(0)
    expect(page.get_by_test_id("style-border")).to_have_count(0)


def test_choosing_custom_seeds_the_title_colour_with_what_is_showing(page, api) -> None:
    """p.59's rule for the background control, applied to this one: reaching
    for a shade of the colour already there should not start by losing it."""
    mod = header_module(
        api, "Header title seed", titleColour="saved:c1",
        palette=[{"id": "c1", "name": "Brand", "light": TEAL, "dark": TEAL}],
    )
    open_builder(page, mod)
    select_node(page, "Header")
    expect(page.get_by_test_id("header-title-colour-hex")).to_have_count(0)
    page.get_by_test_id("header-title-colour").select_option("custom")
    expect(page.get_by_test_id("header-title-colour-hex")).to_have_value(TEAL)
