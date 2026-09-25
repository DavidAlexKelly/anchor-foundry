"""The builder's own marks belong to editing (§460).

A widget's dashed hover outline and the dashed frame round a page are how an
author finds things while arranging a module. They drew in **Preview**, the
mode an author uses to check what a reader sees, and the hover outline drew on
the **reader's own route** as well, since it was scoped to the frame area both
share. Found in a screenshot: a reader who had just dragged a row onto a drop
zone was left looking at a dashed box round the whole module.

Asserted on computed styles, waited for with `to_have_css` (§271: a one-shot
read of a computed style is the trap that passes on a fresh database).
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, publish, settled, viewer_url

TRANSPARENT = "rgba(0, 0, 0, 0)"


def build(api) -> Module:
    mod = Module(api, "Builder marks")
    mod.define({
        "format": 2,
        "layout": layout({
            "page": {"resolvedName": "CanvasPage", "props": {"title": "Overview"},
                     "isCanvas": True, "nodes": ["txt"]},
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "HOVER ME"},
                    "parent": "page"},
        }),
        "variables": {},
        "events": {},
    })
    return mod


def block(page):
    return page.locator(".canvas-block").filter(has_text="HOVER ME").first


def hovered(page):
    target = block(page)
    expect(target).to_be_visible()
    target.hover()
    return target


def test_the_builder_outlines_a_hovered_widget(page, api) -> None:
    """The counterweight: the mark is still there while arranging, so its
    absence below is about the mode and not about a style that went missing."""
    mod = build(api)
    open_builder(page, mod)
    settled(page)
    expect(hovered(page)).not_to_have_css("border-top-color", TRANSPARENT)
    # And the page carries its dashed frame, so a builder can see where it is.
    expect(page.locator(".canvas-page").first).to_have_css("border-top-style", "dashed")


def test_preview_shows_what_a_reader_sees(page, api) -> None:
    mod = build(api)
    open_module(page, mod)
    expect(hovered(page)).to_have_css("border-top-color", TRANSPARENT)
    # No dashed frame round the page either: in Preview one page renders, as
    # it does for a reader.
    expect(page.locator(".canvas-page").first).to_have_css("border-top-style", "none")


def test_a_reader_sees_no_builder_marks(page, api) -> None:
    mod = build(api)
    publish(mod)
    page.goto(viewer_url(mod))
    expect(hovered(page)).to_have_css("border-top-color", TRANSPARENT)


def _inside(page, selector: str) -> list[str]:
    """What under the settings column reaches past its right edge, by name."""
    return page.evaluate(
        """(selector) => {
            const column = document.querySelector('.canvas-settings');
            const edge = column.getBoundingClientRect().right + 1;
            return [...column.querySelectorAll(selector)]
                .filter((el) => el.getBoundingClientRect().width > 0)
                .filter((el) => el.getBoundingClientRect().right > edge)
                .map((el) => (el.textContent || el.tagName).trim().slice(0, 40));
        }""",
        selector,
    )


def test_every_settings_tab_is_inside_the_column(page, api) -> None:
    """Seven tabs in a 260px column. In one row the fourth onwards ran past
    the column's edge, off a laptop screen, so Profiler, Metrics,
    Translations and Check access could not be reached. They wrap."""
    page.set_viewport_size({"width": 1280, "height": 900})
    mod = build(api)
    open_builder(page, mod)
    settled(page)
    tabs = page.locator(".canvas-panel-tabs .ds-tab")
    expect(tabs).to_have_count(7)
    assert _inside(page, ".canvas-panel-tabs .ds-tab") == []
    # And the last one works, which is the point of it being reachable.
    tabs.last.click()
    expect(tabs.last).to_have_attribute("aria-current", "true")


def test_an_effect_editor_stays_inside_the_column(page, api) -> None:
    """A select is as wide as its longest option, and an export naming a set
    with a long label pushed the whole Events editor past the column."""
    page.set_viewport_size({"width": 1280, "height": 900})
    mod = Module(api, "Builder marks events")
    long = "Every site in the northern region, excluding decommissioned depots"
    mod.define({
        "format": 2,
        "layout": layout({
            # A long label too: the event's own "When" select lists buttons
            # by it, so the event body has a wide select of its own.
            "btn": {"resolvedName": "CanvasButton",
                    "props": {"label": "Go and export every northern site to a spreadsheet"}},
        }),
        "variables": {
            "v_long": {"id": "v_long", "kind": "object_set", "label": long,
                       "object_set": {"object_type_id": "00000000-0000-0000-0000-000000000001",
                                      "filters": []}},
        },
        "events": {
            "e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": [{"type": "export", "config": {"variable": "v_long"}}]},
        },
    })
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Events (1)").click()
    # The heading shortens a long label, so it is found by what it is.
    page.locator(".canvas-event-head").first.click()
    expect(page.get_by_test_id("effect-export-variable")).to_be_visible()
    assert _inside(page, "select, input, button, fieldset, label") == []
    # And the Properties group reads as one more field, not a boxed form.
    expect(page.locator(".canvas-settings fieldset.field").first).to_have_css(
        "border-top-style", "none")
