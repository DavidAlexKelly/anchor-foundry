"""p.225's Combine multiple object types (§689).

> "Combine multiple object types: This setting only affects tables displaying
> multiple object types. When disabled, each object type will be displayed
> within its own tab. When enabled, all object types will be displayed within
> a single table and, across object types, property types that share both
> display names and IDs will be combined into a single column." (p.225)

The page and its order are `apps/api/tests/test_union_reads.py`'s; the
columns and the selection's clauses `union-set.test.ts`'s. What needs a
browser is one table of both types, blank where a type has no such property,
and a selection across types reaching another widget as those objects - not
as every object sharing one of their keys.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

SITES = [{"id": "K1", "name": "Harbour", "region": "north"},
         {"id": "K2", "name": "Quarry", "region": "south"}]
STAFF = [{"id": "K1", "name": "Ada", "region": "south", "grade": 3},
         {"id": "K3", "name": "Grace", "region": "north", "grade": 4}]


@pytest.fixture(scope="module")
def combined(api):
    mod = Module(api, "Union combined")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name", "region"], rows=SITES, key="id",
                            title="name", slug=f"site_{tag}")
    staff = mod.object_type(columns=["id", "name", "region", "grade"], rows=STAFF, key="id",
                            title="name", types={"grade": "integer"}, slug=f"staff_{tag}")
    call_it_area(api, mod, staff)
    table = {"resolvedName": "CanvasObjectTable", "props": {
        "objectSetVariable": "v_all", "pageSize": 25, "sort": "key", "combineTypes": True,
        "multiSelect": True, "selectedVariable": "v_selected", "autoSelect": False}}
    mod.define({
        "format": 2,
        "layout": layout({
            "all": table,
            "picked": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "pageSize": 25, "sort": "key",
                "combineTypes": True, "columns": "name,region"}},
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
    return mod


def call_it_area(api, mod, type_id: str) -> None:
    """The staff's `region`, displayed as "Area": one ID, two display names."""
    base = f"/workspaces/{mod.workspace_id}/object-types/{type_id}"
    detail = api.call("GET", base)
    api.call("PATCH", base, {
        "display_name": detail["display_name"],
        "properties": [{"api_name": p["api_name"], "data_type": p["data_type"],
                        "display_name": "Area" if p["api_name"] == "region" else p["display_name"]}
                       for p in detail["properties"]]})


def column(page, table: int, name: str) -> list[str]:
    """One column's cells, by its header, in row order."""
    grid = page.locator(".data-grid").nth(table)
    headers = [h.strip() for h in grid.locator("thead th").all_text_contents()]
    # The columns wait for every type's properties; until then there are none.
    if name not in headers:
        return []
    index = headers.index(name)
    return [c.strip() for c in grid.locator(f"tbody tr td:nth-child({index + 1})")
            .all_text_contents()]


def test_both_types_are_one_table_with_shared_columns(page, combined) -> None:
    open_module(page, combined)
    expect(page.get_by_role("tablist", name="Object types")).to_have_count(0)
    first = page.locator(".data-grid").first
    # "Region" and "Area" share an ID and not a display name, so they are two
    # columns (p.225's "share both display names and IDs").
    expect(first.locator("thead th")).to_have_text(
        ["", "Key", "Id", "Name", "Region", "Area", "Grade"])
    eventually(lambda: column(page, 0, "Name"), lambda got: got == [
        "Harbour", "Ada", "Quarry", "Grace"], what="both types, by key")
    # A site has no grade: its cell is empty rather than "no value".
    assert column(page, 0, "Grade") == ["", "3", "", "4"]
    assert column(page, 0, "Region") == ["north", "", "south", ""]
    assert column(page, 0, "Area") == ["", "south", "", "north"]
    # Configured by name, a table shows every column of that name.
    expect(page.locator(".data-grid").nth(1).locator("thead th")).to_have_text(
        ["Key", "Name", "Region", "Area"])


def test_a_selection_across_types_is_those_objects(page, combined) -> None:
    open_module(page, combined)
    first = page.locator(".data-grid").first
    eventually(lambda: column(page, 0, "Name"), lambda got: len(got) == 4, what="the rows")
    first.locator("tbody tr", has_text="Harbour").locator("input[type=checkbox]").check()
    first.locator("tbody tr", has_text="Grace").locator("input[type=checkbox]").check()
    # Ada shares Harbour's key and is not picked.
    eventually(lambda: column(page, 1, "Name"), lambda got: got == ["Harbour", "Grace"],
               what="the two picked")
    expect(first.locator("tbody input[type=checkbox]:checked")).to_have_count(2)
    # And one type's alone.
    first.locator("tbody tr", has_text="Grace").locator("input[type=checkbox]").uncheck()
    eventually(lambda: column(page, 1, "Name"), lambda got: got == ["Harbour"],
               what="the site alone")


def test_the_panel_offers_combine_over_a_union(page, combined) -> None:
    open_builder(page, combined)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object table").first.click()
    toggle = page.get_by_test_id("table-combine-types")
    expect(toggle).to_be_checked()
    toggle.uncheck()
    expect(page.get_by_role("tablist", name="Object types").first).to_be_visible()


# ---- past a page, and past the depth -----------------------------------------
@pytest.fixture(scope="module")
def deep(api):
    mod = Module(api, "Union combined deep")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name"], key="id", title="name", slug=f"site_{tag}",
                            rows=[{"id": f"S{n:03d}", "name": f"Site {n}"} for n in range(150)])
    staff = mod.object_type(columns=["id", "name"], key="id", title="name", slug=f"staff_{tag}",
                            rows=[{"id": f"T{n:03d}", "name": f"Person {n}"} for n in range(60)])
    mod.define({
        "format": 2,
        "layout": layout({
            "all": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_all", "pageSize": 100, "sort": "key",
                "combineTypes": True, "multiSelect": True, "selectedVariable": "v_selected",
                "autoSelect": False, "exportCsv": True}},
            "picked": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "pageSize": 25, "sort": "key",
                "combineTypes": True, "columns": "name"}},
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
    return mod


def pager(page, table: int):
    return page.locator(".canvas-table-pager").nth(table)


def test_a_combined_table_pages_to_its_depth_and_says_so(page, deep) -> None:
    open_module(page, deep)
    first = pager(page, 0)
    expect(first).to_contain_text("1–100 of 210")
    first.get_by_role("button", name="Next").click()
    expect(first).to_contain_text("101–200 of 210")
    expect(first.get_by_role("button", name="Next")).to_be_disabled()
    expect(page.get_by_test_id("table-combined-depth")).to_contain_text("the first 200")


def test_select_all_adds_this_page_to_the_others(page, deep) -> None:
    open_module(page, deep)
    table = page.locator(".data-grid").first
    table.locator("tbody tr", has_text="Site 0").first.locator("input[type=checkbox]").check()
    expect(page.locator(".data-grid").nth(1).locator("tbody tr")).to_have_count(1)
    pager(page, 0).get_by_role("button", name="Next").click()
    # The page itself, not the pager: the pager counts the rows on screen,
    # which are the last page's until the next arrives.
    expect(table.locator("tbody tr").first).to_contain_text("Site 100")
    table.get_by_test_id("table-select-all").check()
    expect(pager(page, 1)).to_contain_text("of 101")


def test_a_combined_table_offers_no_export(page, deep) -> None:
    """It pages to 200, and p.223's export is of up to 10,000."""
    open_module(page, deep)
    rows = page.locator(".data-grid").first.locator("tbody tr")
    expect(rows).to_have_count(100)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)


# ---- "not available when Enable inline editing is set to true" ----------------
@pytest.fixture(scope="module")
def edited(api, combined):
    mod = Module(api, "Union combined edited", beside=combined)
    document = combined.definition()
    props = document["layout"]["all"]["props"]
    props["inlineEditAction"] = "00000000-0000-0000-0000-000000000001"
    mod.define(document)
    return mod


def test_inline_editing_keeps_the_tabs(page, edited) -> None:
    open_module(page, edited)
    expect(page.get_by_role("tablist", name="Object types").first).to_be_visible()
    open_builder(page, edited)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object table").first.click()
    toggle = page.get_by_test_id("table-combine-types")
    expect(toggle).not_to_be_checked()
    expect(toggle).to_be_disabled()
