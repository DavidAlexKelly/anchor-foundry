"""A Filter List over a union of object sets of different types (§687).

> "You can use a variable to store a union of multiple object sets of
> different object types and pass it to the Filter List widget. The Filter
> List will allow the following filtering options: Common property… Single
> property… The output variable of the Filter List widget can then be used to
> filter the variable containing the unioned object sets and all object types
> instances will be filtered." (p.450)

The readings are `apps/api/tests/test_union_reads.py`'s and the narrowing
`test_union_sets.py`'s. What needs a browser is the whole loop: options read
from every type, a choice written once, and every tab of a table over the
narrowed union following it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

SITES = [{"id": "K1", "name": "Harbour", "region": "north", "size": 1},
         {"id": "K2", "name": "Quarry", "region": "south", "size": 2}]
STAFF = [{"id": "K1", "name": "Ada", "region": "south", "grade": 3},
         {"id": "K3", "name": "Grace", "region": "north", "grade": 4}]


@pytest.fixture(scope="module")
def filtered(api):
    mod = Module(api, "Union filter list")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name", "region", "size"], rows=SITES, key="id",
                            title="name", types={"size": "integer"}, slug=f"site_{tag}")
    staff = mod.object_type(columns=["id", "name", "region", "grade"], rows=STAFF, key="id",
                            title="name", types={"grade": "integer"}, slug=f"staff_{tag}")
    mod.define({
        "format": 2,
        "layout": layout({
            "fl": {"resolvedName": "CanvasFilterList", "props": {
                "objectSetVariable": "v_all", "variable": "v_clauses", "title": "Everything",
                "filters": [{"id": "f_1", "property": "region", "component": "histogram"},
                            {"id": "f_2", "property": "size", "component": "histogram"}]}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 25}},
        }),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(staff)},
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                      "derivation": {"transform": "union_set", "inputs": ["v_sites", "v_staff"]}},
            "v_clauses": {"id": "v_clauses", "kind": "object_set_filter", "label": "Filters"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Narrowed",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_clauses"]}},
        },
        "events": {},
    })
    mod.names = {"sites": f"Site {tag}", "staff": f"Staff {tag}"}
    return mod


def keys(page) -> list[str]:
    cells = page.locator(".data-grid tbody tr td:first-child")
    return sorted(c.strip() for c in cells.all_text_contents())


def bar(page, text: str):
    return page.locator(".canvas-filter-bar", has_text=text)


def test_one_filter_narrows_every_type(page, filtered) -> None:
    open_module(page, filtered)
    tabs = page.get_by_role("tablist", name="Object types").get_by_role("tab")
    # A common property's values, counted over both types.
    expect(bar(page, "north").locator(".canvas-filter-count")).to_have_text("2")
    expect(bar(page, "south").locator(".canvas-filter-count")).to_have_text("2")
    # A single property is named with its type.
    expect(page.get_by_test_id("filter-f_2").locator("legend")).to_have_text(
        f"Size ({filtered.names['sites']})")

    bar(page, "north").get_by_role("checkbox").check()
    eventually(lambda: keys(page), lambda got: got == ["K1"], what="the northern site")
    tabs.nth(1).click()
    eventually(lambda: keys(page), lambda got: got == ["K3"], what="the northern staff")

    # p.450's Single property: a site's size leaves the staff nothing.
    bar(page, "north").get_by_role("checkbox").uncheck()
    eventually(lambda: keys(page), lambda got: got == ["K1", "K3"], what="all the staff")
    page.get_by_test_id("filter-f_2").locator(".canvas-filter-bar", has_text="2") \
        .get_by_role("checkbox").check()
    expect(page.get_by_test_id("table-empty-state")).to_be_visible()
    tabs.first.click()
    eventually(lambda: keys(page), lambda got: got == ["K2"], what="the site of size 2")


def test_the_panel_offers_common_and_single_properties(page, filtered) -> None:
    open_builder(page, filtered)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Filter list").first.click()
    add = page.get_by_test_id("filter-add")
    expect(add.locator("optgroup[label='Common properties'] option")).to_have_text(
        ["Id", "Name", "Region"])
    expect(add.locator("optgroup[label='Single properties'] option")).to_have_text(
        [f"Size ({filtered.names['sites']})", f"Grade ({filtered.names['staff']})"])
    # And no link to follow, which starts from one type.
    expect(add.locator("optgroup[label='Filter on a link']")).to_have_count(0)
