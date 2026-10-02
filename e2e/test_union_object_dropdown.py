"""An Object Dropdown over a union of object sets of different types (§688).

> "Module builders can use the Object Dropdown widget to do the following:
> Display data on one or multiple object types." (p.455)
> "Sort items by: … If multiple object types exist in the object set, only
> shared properties can be sorted on." (p.458)

The page and its order are `apps/api/tests/test_union_reads.py`'s. What needs a
browser is one list of both types, each option drawn by its own type, and a
pick that narrows the union to that object - not to whatever shares its key.
"""
from __future__ import annotations

import re
import time
import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

SITES = [{"id": "K1", "name": "Harbour", "rank": 4, "size": 9},
         {"id": "K2", "name": "Quarry", "rank": 5, "size": 1}]
STAFF = [{"id": "K1", "name": "Ada", "rank": 3}, {"id": "K3", "name": "Grace", "rank": 1}]


@pytest.fixture(scope="module")
def picker(api):
    mod = Module(api, "Union dropdown")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(columns=["id", "name", "rank", "size"], rows=SITES, key="id",
                            title="name", types={"rank": "integer", "size": "integer"},
                            slug=f"site_{tag}")
    staff = mod.object_type(columns=["id", "name", "rank"], rows=STAFF, key="id",
                            title="name", types={"rank": "integer"}, slug=f"staff_{tag}")
    mod.define({
        "format": 2,
        "layout": layout({
            "dd": {"resolvedName": "CanvasObjectDropdown", "props": {
                "objectSetVariable": "v_all", "selectedVariable": "v_picked",
                "sortProperty": "-rank"}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_chosen", "columns": "id,name", "pageSize": 25}},
            # Sorted by the Sites' own number, which p.458 does not allow.
            "dd2": {"resolvedName": "CanvasObjectDropdown", "props": {
                "objectSetVariable": "v_all", "sortProperty": "size"}},
        }),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(staff)},
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                      "derivation": {"transform": "union_set", "inputs": ["v_sites", "v_staff"]}},
            "v_picked": {"id": "v_picked", "kind": "object_set_filter", "label": "Picked"},
            "v_chosen": {"id": "v_chosen", "kind": "object_set", "label": "Chosen",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_picked"]}},
        },
        "events": {},
    })
    mod.names = {"sites": f"Site {tag}", "staff": f"Staff {tag}"}
    return mod


def keys(page) -> list[str]:
    cells = page.locator(".data-grid tbody tr td:first-child")
    return sorted(c.strip() for c in cells.all_text_contents())


def test_one_list_of_both_types_in_a_shared_order(page, picker) -> None:
    open_module(page, picker)
    # Auto-selected: the first in the order, a site.
    expect(page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-value")).to_have_text("Quarry")
    eventually(lambda: keys(page), lambda got: got == ["K2"], what="the site")
    page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-toggle").click()
    options = page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-option")
    expect(options.locator(".canvas-dropdown-title")).to_have_text(
        ["Quarry", "Harbour", "Ada", "Grace"])
    expect(options.get_by_test_id("dropdown-type")).to_have_text(
        [picker.names["sites"], picker.names["sites"], picker.names["staff"],
         picker.names["staff"]])
    page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-search").fill("gr")
    expect(options.locator(".canvas-dropdown-title")).to_have_text(["Grace"])


def test_a_pick_is_that_object_and_not_its_keys_namesake(page, picker) -> None:
    open_module(page, picker)
    expect(page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-value")).to_have_text("Quarry")
    page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-toggle").click()
    page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-option").filter(has_text="Ada").click()
    expect(page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-value")).to_have_text("Ada")
    tabs = page.get_by_role("tablist", name="Object types").get_by_role("tab")
    tabs.nth(1).click()
    eventually(lambda: keys(page), lambda got: got == ["K1"], what="Ada")
    tabs.first.click()
    expect(page.get_by_test_id("table-empty-state")).to_be_visible()
    # Harbour shares Ada's key and is not the one chosen.
    page.get_by_test_id("object-dropdown").first.get_by_test_id("dropdown-toggle").click()
    selected = page.locator("[data-testid=dropdown-option][aria-selected=true]")
    expect(selected.locator(".canvas-dropdown-title")).to_have_text(["Ada"])


def test_a_sort_by_one_types_property_falls_back_to_the_key(page, picker) -> None:
    """p.458: "only shared properties can be sorted on". Asked to sort by a
    property only the Sites have, the dropdown reads back to its default
    rather than sending a sort the union refuses and showing nothing."""
    open_module(page, picker)
    second = page.get_by_test_id("object-dropdown").nth(1)
    second.get_by_test_id("dropdown-toggle").click()
    expect(second.get_by_test_id("dropdown-option").locator(".canvas-dropdown-title")) \
        .to_have_text(["Harbour", "Ada", "Quarry", "Grace"])


def test_the_panel_offers_only_shared_properties_to_sort_by(page, picker) -> None:
    """p.458, in the panel: `rank` is both types', `size` the Sites' alone."""
    open_builder(page, picker)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object Dropdown").first.click()
    sort = page.get_by_test_id("dropdown-sort")
    # Until the union's common properties arrive, the stored `-rank` is shown
    # as its own "no longer sortable" option; read the list once they have.
    expect(sort.locator("option[value=rank]")).to_have_count(1)
    values = sort.locator("option").evaluate_all(
        "options => options.map(o => o.value)")
    assert "rank" in values and "-rank" in values, values
    assert "size" not in values and "-size" not in values, values


def test_the_list_waits_for_the_types_that_decide_its_order(page, picker) -> None:
    """p.457's auto-selection takes the first object of the first page it
    sees. A page read before the types arrive cannot be sorted by rank, and
    falls back to the key, whose first object here is Harbour - so the
    dropdown must not read one.
    The types are held back to make that the order things happen in."""
    def slowly(route) -> None:
        time.sleep(1.5)
        route.continue_()

    page.route(re.compile(r".*/api/workspaces/[^/]+/object-types/[^/?]+$"), slowly)
    open_module(page, picker)
    first = page.get_by_test_id("object-dropdown").first
    expect(first.get_by_test_id("dropdown-value")).to_have_text("Quarry")
