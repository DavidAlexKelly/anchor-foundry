"""p.52's layout template picker (parity `workshop.md` §1.2; Foundry p.52-53).

> "You can also explore other layout templates using the layout template picker
> at the bottom of the page. You can preview what each layout would look like by
> hovering over its icon. If you would like to use a template, you can select
> that icon; the page layout will update to the one you selected." (p.52-53)

The transform is checked node by node in
`apps/web/src/components/canvas/layout-template.test.ts`. What needs a browser
is the round trip Craft.js makes of it — `getSerializedNodes` out,
`deserialize` back in — and then a **save and reload**, because a layout that
only lives in the editor's memory is one that vanishes the first time somebody
comes back to the module. Plus the two things that are only true on screen: the
picker is where p.52 says it is, and hovering previews.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, settled


def module_with(api, name: str, sections: int):
    """A page with `sections` sections, each holding one identifiable widget.

    The widgets are what the "loses nothing" claim is about, so they carry
    distinct text: a template that dropped one would leave a readout that is
    missing a word rather than a count that happens to match.
    """
    nodes = {
        "page": {"resolvedName": "CanvasPage", "isCanvas": True,
                 "props": {"title": "Page"},
                 "nodes": [f"s{i}" for i in range(1, sections + 1)]},
    }
    for i in range(1, sections + 1):
        nodes[f"s{i}"] = {
            "resolvedName": "CanvasSection", "isCanvas": True, "parent": "page",
            "props": {"direction": "columns"}, "nodes": [f"w{i}"],
        }
        nodes[f"w{i}"] = {
            "resolvedName": "CanvasText", "parent": f"s{i}",
            "props": {"tag": "p", "text": f"widget-{i}"},
        }
    mod = Module(api, name)
    mod.define({"format": 2, "layout": layout(nodes), "variables": {}, "events": {}})
    return mod


def save(page):
    """Click Save and wait for the version line to say it landed."""
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved", timeout=15000)


def widgets_on(page):
    """The identifiable widgets, wherever on the page they ended up."""
    return page.locator(".canvas-page p", has_text="widget-")


def test_the_picker_sits_at_the_bottom_of_the_page(page, api) -> None:
    """p.52 puts it there, and only in the builder: it is an authoring
    control, and a reader has no layout to choose."""
    mod = module_with(api, "Template picker", 1)
    open_builder(page, mod)

    expect(page.get_by_test_id("layout-template-picker")).to_be_visible()
    expect(page.get_by_test_id("layout-template-two-rows")).to_be_visible()


def test_hovering_an_icon_previews_that_layout(page, api) -> None:
    """p.52: "You can preview what each layout would look like by hovering over
    its icon."

    The preview names the template it is previewing, which is the assertion
    that would catch a strip wired to show one fixed panel for every icon.
    """
    mod = module_with(api, "Template preview", 1)
    open_builder(page, mod)

    # Nothing before the pointer arrives - a preview that is always up is not
    # a preview, and `settled` above makes this absence honest.
    expect(page.get_by_test_id("layout-template-preview")).to_have_count(0)

    page.get_by_test_id("layout-template-sidebar").hover()
    preview = page.get_by_test_id("layout-template-preview")
    expect(preview).to_be_visible()
    expect(preview).to_contain_text("Sidebar and body")

    page.get_by_test_id("layout-template-stacked-rows").hover()
    expect(preview).to_contain_text("Stacked widgets")


def test_selecting_a_template_changes_the_page_and_survives_a_reload(page, api) -> None:
    """p.53: "the page layout will update to the one you selected."

    **The reload is the point.** `deserialize` is easy to get right in memory
    and easy to get wrong on the way to the document — a node whose `parent`
    disagrees with its new section's child list renders correctly once and
    comes back wrong.
    """
    mod = module_with(api, "Template applies", 1)
    open_builder(page, mod)
    expect(page.locator(".canvas-section")).to_have_count(1)

    page.get_by_test_id("layout-template-three-rows").click()
    expect(page.locator(".canvas-section")).to_have_count(3)

    save(page)
    page.reload()
    settled(page)
    expect(page.locator(".canvas-section")).to_have_count(3)


def test_applying_a_template_loses_no_widget(page, api) -> None:
    """**The claim the feature stands on**, and the one p.53 does not make.

    Three sections holding three widgets, narrowed to a one-section template.
    p.53 says the layout updates; it does not say the author's work is
    deleted, and a picker that can silently destroy an hour of arranging is
    the failure this repo exists to remove. So all three widgets are still
    there afterwards — and still there after a reload, which is where a
    widget orphaned by a bad parent pointer would disappear.
    """
    mod = module_with(api, "Template keeps widgets", 3)
    open_builder(page, mod)
    expect(widgets_on(page)).to_have_count(3)

    page.get_by_test_id("layout-template-single").click()
    expect(page.locator(".canvas-section")).to_have_count(1)
    expect(widgets_on(page)).to_have_count(3)

    save(page)
    page.reload()
    settled(page)
    expect(widgets_on(page)).to_have_count(3)
    expect(page.locator(".canvas-section")).to_have_count(1)
    # Named rather than counted: three surviving nodes with the wrong text
    # would be three widgets too. **Scoped to the canvas** - the Layout panel's
    # tree lists every widget by the same text, so an unscoped `get_by_text`
    # matches twice and fails strict mode (§192's lesson, third time).
    for i in (1, 2, 3):
        expect(page.locator(".canvas-page").get_by_text(f"widget-{i}", exact=True)).to_be_visible()


def test_a_template_does_not_touch_another_page(page, api) -> None:
    """A template applies to one page. Damage to another is the kind nobody
    looks for, because they were not on that page when they clicked."""
    mod = Module(api, "Template one page")
    mod.define({"format": 2, "layout": layout({
        "p1": {"resolvedName": "CanvasPage", "isCanvas": True,
               "props": {"title": "One"}, "nodes": ["s1"]},
        "s1": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "p1",
               "props": {"direction": "columns"}, "nodes": ["w1"]},
        "w1": {"resolvedName": "CanvasText", "parent": "s1",
               "props": {"tag": "p", "text": "widget-1"}},
        "p2": {"resolvedName": "CanvasPage", "isCanvas": True,
               "props": {"title": "Two"}, "nodes": ["s2"]},
        "s2": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "p2",
               "props": {"direction": "columns"}, "nodes": ["w2"]},
        "w2": {"resolvedName": "CanvasText", "parent": "s2",
               "props": {"tag": "p", "text": "widget-2"}},
    }), "variables": {}, "events": {}})
    open_builder(page, mod)
    expect(page.locator(".canvas-section")).to_have_count(2)

    # The first page's picker, so the second page is the one that must not move.
    page.locator(".canvas-page").first.get_by_test_id("layout-template-three-rows").click()

    save(page)
    page.reload()
    settled(page)
    # Three on the first page, one untouched on the second.
    expect(page.locator(".canvas-section")).to_have_count(4)
    expect(page.locator(".canvas-page").get_by_text("widget-2", exact=True)).to_be_visible()
    expect(page.locator(".canvas-page").nth(1).locator(".canvas-section")).to_have_count(1)
