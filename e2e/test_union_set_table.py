"""A union of sets of different object types in an Object Table (§686).

> "You can use a variable to store a union of multiple object sets of
> different object types" (p.450)

> "Combine multiple object types: This setting only affects tables displaying
> multiple object types. When disabled, each object type will be displayed
> within its own tab." (p.225)

The rules are `apps/api/tests/test_union_sets.py`'s. What needs a browser is
the tabs, and that a row picked in one tab narrows the union to that object
and not to whatever shares its key in another type: the two types here both
have a "K1".
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module, settled

SITES = [{"id": "K1", "name": "Harbour", "region": "north"},
         {"id": "K2", "name": "Quarry", "region": "south"}]
STAFF = [{"id": "K1", "name": "Ada", "region": "south", "grade": "3"},
         {"id": "K3", "name": "Grace", "region": "north", "grade": "4"}]


@pytest.fixture(scope="module")
def mixed(api):
    mod = Module(api, "Union table")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name", "region"], rows=SITES, key="id",
                            title="name", slug=f"site_{tag}")
    staff = mod.object_type(columns=["id", "name", "region", "grade"], rows=STAFF, key="id",
                            title="name", slug=f"staff_{tag}")
    mod.define({
        "format": 2,
        "layout": layout({
            "all": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_all", "columns": "id,name,grade", "pageSize": 25,
                "activeVariable": "v_active", "multiSelect": True,
                "selectedVariable": "v_selected"}},
            # Only Staff has a grade: the Sites tab shows every property.
            "chosen": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_chosen", "columns": "grade", "pageSize": 25}},
        }),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(staff)},
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                      "derivation": {"transform": "union_set", "inputs": ["v_sites", "v_staff"]}},
            "v_active": {"id": "v_active", "kind": "object_set_filter", "label": "Active"},
            "v_selected": {"id": "v_selected", "kind": "object_set_filter", "label": "Selected"},
            "v_chosen": {"id": "v_chosen", "kind": "object_set", "label": "Chosen",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_active"]}},
        },
        "events": {},
    })
    mod.names = {"sites": f"Site {tag}", "staff": f"Staff {tag}"}
    return mod


def keys_in(page, table: int) -> list[str]:
    # The key is the first cell that is not a multi-select checkbox.
    rows = page.locator(".data-grid").nth(table).locator("tbody tr")
    return sorted(k.strip() for k in rows.evaluate_all(
        "rows => rows.map(r => r.querySelector('td:not(.canvas-table-check)')?.textContent ?? '')"))


def test_each_type_is_its_own_tab(page, mixed) -> None:
    open_module(page, mixed)
    tabs = page.get_by_role("tablist", name="Object types").first.get_by_role("tab")
    expect(tabs).to_have_text([mixed.names["sites"], mixed.names["staff"]])
    expect(tabs.first).to_have_attribute("aria-selected", "true")
    eventually(lambda: keys_in(page, 0), lambda got: got == ["K1", "K2"], what="the sites")
    # The configured columns a type has; `grade` is only Staff's.
    head = page.locator(".data-grid").first.locator("thead th")
    expect(head).to_have_text(["", "Key", "Id", "Name"])

    tabs.nth(1).click()
    expect(tabs.nth(1)).to_have_attribute("aria-selected", "true")
    expect(tabs.first).to_have_attribute("aria-selected", "false")
    eventually(lambda: keys_in(page, 0), lambda got: got == ["K1", "K3"], what="the staff")
    expect(head).to_have_text(["", "Key", "Id", "Name", "Grade"])

    # The tablist's keys, as a section's tabs have them.
    tabs.nth(1).press("ArrowRight")
    expect(tabs.first).to_have_attribute("aria-selected", "true")
    expect(tabs.first).to_be_focused()


def test_a_row_picked_in_one_type_narrows_the_union_to_it(page, mixed) -> None:
    open_module(page, mixed)
    everything = page.get_by_role("tablist", name="Object types").first.get_by_role("tab")
    chosen = page.get_by_role("tablist", name="Object types").nth(1).get_by_role("tab")
    chosen_head = page.locator(".data-grid").nth(1).locator("thead th")
    # Auto-selected on load: the first site, K1. The Sites tab has no grade,
    # so it shows every property of a site.
    eventually(lambda: keys_in(page, 1), lambda got: got == ["K1"], what="the site picked")
    expect(chosen_head).to_have_text(["Key", "Id", "Name", "Region"])

    # Another tab is another type's rows: its first is picked, so no site is
    # chosen any more - even though a staff member shares the key "K1".
    everything.nth(1).click()
    expect(page.get_by_test_id("table-empty-state")).to_be_visible()

    # Picking Grace: the Staff tab holds her alone and the Sites tab nothing.
    page.locator(".data-grid").first.locator("tbody tr", has_text="Grace").click()
    chosen.nth(1).click()
    expect(chosen_head).to_have_text(["Key", "Grade"])
    eventually(lambda: keys_in(page, 1), lambda got: got == ["K3"], what="Grace alone")
    chosen.first.click()
    expect(page.get_by_test_id("table-empty-state")).to_be_visible()


def test_a_tab_reads_back_only_its_own_types_selection(page, mixed) -> None:
    """p.224's Selected objects, ticked in one tab, are not ticked in another
    because a key there happens to match."""
    open_module(page, mixed)
    everything = page.get_by_role("tablist", name="Object types").first.get_by_role("tab")
    table = page.locator(".data-grid").first
    eventually(lambda: keys_in(page, 0), lambda got: got == ["K1", "K2"], what="the sites")
    table.locator("tbody tr", has_text="Harbour").locator("input[type=checkbox]").check()
    expect(table.locator("tbody input[type=checkbox]:checked")).to_have_count(1)
    everything.nth(1).click()
    eventually(lambda: keys_in(page, 0), lambda got: got == ["K1", "K3"], what="the staff")
    expect(table.locator("tbody input[type=checkbox]:checked")).to_have_count(0)


@pytest.fixture(scope="module")
def undrawn(api):
    """The same two types, and a table over a set that is not a union yet."""
    mod = Module(api, "Union drawn")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name", "region"], rows=SITES, key="id",
                            title="name", slug=f"site_{tag}")
    staff = mod.object_type(columns=["id", "name", "region", "grade"], rows=STAFF, key="id",
                            title="name", slug=f"staff_{tag}")
    mod.define({
        "format": 2,
        "layout": layout({"tbl": {"resolvedName": "CanvasObjectTable", "props": {
            "objectSetVariable": "v_joined", "columns": "id,name", "pageSize": 25}}}),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(staff)},
            "v_joined": {"id": "v_joined", "kind": "object_set", "label": "Joined",
                         "object_set": object_set(sites)},
        },
        "events": {},
    })
    mod.names = {"sites": f"Site {tag}", "staff": f"Staff {tag}"}
    return mod


def test_a_union_is_drawn_in_the_variables_panel(page, undrawn) -> None:
    page.goto(f"{WEB_BASE}{undrawn.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("Joined", exact=True).first.click()
    page.get_by_test_id("set-source").select_option("joined")
    parts = page.get_by_test_id("union-parts")
    expect(parts).to_contain_text("Pick two or more sets")
    parts.get_by_label("Staff").check()
    parts.get_by_label("Sites").check()
    expect(parts).to_contain_text("One set per object type")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)

    open_module(page, undrawn)
    # In the order they were ticked.
    tabs = page.get_by_role("tablist", name="Object types").get_by_role("tab")
    expect(tabs).to_have_text([undrawn.names["staff"], undrawn.names["sites"]])
    eventually(lambda: keys_in(page, 0), lambda got: got == ["K1", "K3"], what="the staff")
