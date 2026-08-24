"""p.68's *Unused widgets* area (parity `workshop.md` §1.3; Foundry p.68).

> "Use `Cmd+V` to paste the widget into the Unused widgets area located at the
> bottom of the Layouts section in the left side panel. Add the widget to your
> module by choosing **+ Add widget**…" (p.68)

The transform is checked node by node in
`apps/web/src/components/canvas/unused.test.ts`. Three things need a browser:

* the round trip through Craft — `getSerializedNodes` out, `deserialize` back
  in — and a **save and reload**, because a parked widget that only lives in
  the editor's memory is one that vanishes the first time somebody comes back;
* that a parked widget is **not on the page for a reader**, which is the
  property `docs/decisions/0010-unused-widgets.md` names as the one this design
  is most likely to lose later;
* that its **variable survives** being parked, which is the whole reason the
  holding node lives in the node map rather than in a sibling key.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str):
    """One page, one section, two widgets — one of which is bound to a
    variable, because the binding is what parking must not break."""
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "p1": {"resolvedName": "CanvasPage", "isCanvas": True,
                   "props": {"title": "Page"}, "nodes": ["s1"]},
            "s1": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "p1",
                   "props": {"direction": "columns"}, "nodes": ["w_keep", "w_park"]},
            "w_keep": {"resolvedName": "CanvasText", "parent": "s1",
                       "props": {"tag": "p", "text": "kept-widget"}},
            "w_park": {"resolvedName": "CanvasText", "parent": "s1",
                       "props": {"tag": "p", "text": "parked-widget",
                                 "visibleWhen": "v_show"}},
        }),
        "variables": {
            "v_show": {"id": "v_show", "kind": "boolean", "label": "Show it",
                       "default": True},
        },
        "events": {},
    })
    return mod


def save(page):
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved", timeout=15000)


def tree_row(page, text: str):
    return page.locator(".canvas-tree-row").filter(has_text=text).first


def park(page, text: str):
    tree_row(page, text).click()
    page.get_by_test_id("unused-park").click()


def test_the_area_is_there_and_says_it_is_empty(page, api) -> None:
    """p.68 puts it at the bottom of the Layout panel. Empty is a state it has
    to be able to show: an area that only appears once something is in it is
    one nobody discovers."""
    mod = module_with(api, "Unused empty")
    open_builder(page, mod)

    expect(page.get_by_test_id("unused-area")).to_be_visible()
    expect(page.get_by_test_id("unused-row")).to_have_count(0)


def test_parking_moves_a_widget_out_of_the_tree_and_off_the_page(page, api) -> None:
    """The widget leaves the page and the layout tree, and turns up in the
    area — one widget in one place, never two."""
    mod = module_with(api, "Unused park")
    open_builder(page, mod)
    expect(page.locator(".canvas-page").get_by_text("parked-widget")).to_be_visible()

    park(page, "parked-widget")

    expect(page.get_by_test_id("unused-row")).to_have_count(1)
    expect(page.locator(".canvas-page").get_by_text("parked-widget")).to_have_count(0)
    # And the other widget is untouched, which is what makes this about the one
    # that was selected rather than about parking in general.
    expect(page.locator(".canvas-page").get_by_text("kept-widget")).to_be_visible()


def test_a_parked_widget_survives_a_save_and_reload(page, api) -> None:
    """**The round trip.** A holding node that Craft dropped on deserialize
    would look right until somebody came back to the module."""
    mod = module_with(api, "Unused reload")
    open_builder(page, mod)
    park(page, "parked-widget")

    save(page)
    page.reload()
    settled(page)

    expect(page.get_by_test_id("unused-row")).to_have_count(1)
    expect(page.locator(".canvas-page").get_by_text("parked-widget")).to_have_count(0)


def test_a_reader_never_sees_a_parked_widget(page, api) -> None:
    """**The property decision 0010 names as the one most likely to be lost.**

    `CanvasUnused` renders nothing, in both modes. A version that drew its
    children would put every parked widget on the page for every reader — and
    nothing else in this file would notice, because every other test is in the
    builder.
    """
    mod = module_with(api, "Unused reader")
    open_builder(page, mod)
    park(page, "parked-widget")
    save(page)

    open_module(page, mod)
    expect(page.get_by_text("kept-widget")).to_be_visible()
    expect(page.get_by_text("parked-widget")).to_have_count(0)


def test_adding_it_back_puts_it_on_the_page_with_its_binding(page, api) -> None:
    """p.68's "+ Add widget", and the reason parking is a *move*.

    The widget is bound to `v_show` by `visibleWhen`. If placing minted a new
    id, or if parking had dropped the props, the widget would come back
    unbound — identical on screen, and wrong the moment the variable changed.
    So this checks the binding survived, not just that a widget reappeared.
    """
    mod = module_with(api, "Unused add back")
    open_builder(page, mod)
    park(page, "parked-widget")
    save(page)
    page.reload()
    settled(page)

    tree_row(page, "Section").click()
    page.get_by_test_id("unused-add").click()

    expect(page.get_by_test_id("unused-row")).to_have_count(0)
    expect(page.locator(".canvas-page").get_by_text("parked-widget")).to_be_visible()

    save(page)
    page.reload()
    settled(page)
    # The binding: the Variables panel counts usages from the saved document,
    # so "used 1×" here is the whole claim - a re-added widget that had lost
    # its `visibleWhen` would read as unused.
    page.get_by_role("button", name="Variables", exact=False).first.click()
    expect(page.locator(".vars-row").first).to_contain_text("used 1×")


def test_a_parked_widget_still_counts_as_using_its_variable(page, api) -> None:
    """**The reason the holding node lives in the node map** (decision 0010).

    `usages()` iterates the node map, so a parked widget is counted. Under the
    sibling-key design it would not be: the variable would report as unused,
    an author would delete it, and the widget would come back bound to
    nothing — with no error at any step.
    """
    mod = module_with(api, "Unused counts")
    open_builder(page, mod)
    park(page, "parked-widget")
    save(page)
    page.reload()
    settled(page)

    page.get_by_role("button", name="Variables", exact=False).first.click()
    expect(page.locator(".vars-row").first).to_contain_text("used 1×")


def test_a_page_cannot_be_parked(page, api) -> None:
    """p.68 is about widgets. Parking a page would take its whole contents off
    the module in a click, so the control is disabled rather than offered and
    then refused — §193's rule."""
    mod = module_with(api, "Unused not a page")
    open_builder(page, mod)

    tree_row(page, "Page").click()
    expect(page.get_by_test_id("unused-park")).to_be_disabled()

    tree_row(page, "parked-widget").click()
    expect(page.get_by_test_id("unused-park")).to_be_enabled()
