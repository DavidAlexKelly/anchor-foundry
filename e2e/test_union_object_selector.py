"""An Object Selector over a union of object sets of different types (§690).

> "Object Selector: Allow the user to select multiple objects from a list of
> objects" (p.444)

It is the Object Dropdown with several picks (§215), so over a union it lists
every type as the dropdown does (§688), and several types' picks are §689's
`[type, key]` pairs. What needs a browser is that ticking two objects of two
types reaches another widget as those two - not as every object sharing a key.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

SITES = [{"id": "K1", "name": "Harbour", "size": 9}, {"id": "K2", "name": "Quarry", "size": 1}]
STAFF = [{"id": "K1", "name": "Ada"}, {"id": "K3", "name": "Grace"}]


@pytest.fixture(scope="module")
def selector(api):
    mod = Module(api, "Union selector")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name", "size"], rows=SITES, key="id", title="name",
                            types={"size": "integer"}, slug=f"site_{tag}")
    staff = mod.object_type(columns=["id", "name"], rows=STAFF, key="id", title="name",
                            slug=f"staff_{tag}")
    mod.define({
        "format": 2,
        "layout": layout({
            "sel": {"resolvedName": "CanvasObjectSelector", "props": {
                "objectSetVariable": "v_all", "selectedVariable": "v_selected"}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "name", "pageSize": 25,
                "sort": "key", "combineTypes": True}},
        }),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(staff)},
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                      "derivation": {"transform": "union_set", "inputs": ["v_sites", "v_staff"]}},
            "v_selected": {"id": "v_selected", "kind": "object_set_filter", "label": "Selected"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Picked",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_selected"]}},
        },
        "events": {},
    })
    mod.names = {"sites": f"Site {tag}", "staff": f"Staff {tag}"}
    return mod


def names(page) -> list[str]:
    cells = page.locator(".data-grid tbody tr td:nth-child(2)")
    return [c.strip() for c in cells.all_text_contents()]


def option(page, title: str):
    return page.get_by_test_id("selector-option").filter(has_text=title)


def test_picks_of_two_types_are_those_two(page, selector) -> None:
    open_module(page, selector)
    # Nothing ticked is nothing chosen.
    expect(page.get_by_test_id("table-empty-state")).to_be_visible()
    page.get_by_test_id("selector-toggle").click()
    expect(page.get_by_test_id("selector-option").locator(".canvas-dropdown-title")).to_have_text(
        ["Harbour", "Ada", "Quarry", "Grace"])
    expect(option(page, "Ada").get_by_test_id("selector-type")).to_have_text(
        selector.names["staff"])
    option(page, "Harbour").locator("input").check()
    option(page, "Grace").locator("input").check()
    eventually(lambda: names(page), lambda got: got == ["Harbour", "Grace"], what="the two")
    # Harbour and Ada share a key, and only Harbour is ticked.
    expect(option(page, "Ada").locator("input")).not_to_be_checked()
    option(page, "Harbour").locator("input").uncheck()
    option(page, "Ada").locator("input").check()
    eventually(lambda: names(page), lambda got: got == ["Ada", "Grace"], what="Ada and Grace")
    expect(option(page, "Harbour").locator("input")).not_to_be_checked()
    # One pick is named: Ada, not the site listed first under her key.
    option(page, "Grace").locator("input").uncheck()
    expect(page.get_by_test_id("selector-value")).to_have_text("Ada")
    # Each type's titles are searched.
    page.get_by_test_id("selector-search").fill("gr")
    expect(page.get_by_test_id("selector-option").locator(".canvas-dropdown-title")).to_have_text(
        ["Grace"])


def test_the_panel_offers_only_shared_properties_to_sort_by(page, selector) -> None:
    open_builder(page, selector)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object selector").first.click()
    sort = page.get_by_test_id("selector-sort")
    values = sort.locator("option").evaluate_all("options => options.map(o => o.value)")
    assert "-key" in values, values
    assert "size" not in values and "-size" not in values, values
