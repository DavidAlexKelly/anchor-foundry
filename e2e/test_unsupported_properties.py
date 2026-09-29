"""p.266 and p.595-597's unsupported properties in Workshop (§693).

> "Some large properties, such as Geoshape and Vector, are not loaded by
> default to improve performance. In View mode, users can select Load next to
> an unsupported property to reveal its value on demand. During
> configuration, unsupported properties are indicated with a warning icon and
> tooltip." (p.266)

> "Object Table: To view an unsupported property's value in an object table
> widget, select ... button to reveal its value." (p.596)

What needs a browser is that the page arrives without the geoshape, and that
Load brings the one asked for.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

SQUARE = json.dumps({
    "type": "Polygon",
    "coordinates": [[[-1.0, 51.0], [0.5, 51.0], [0.5, 52.0], [-1.0, 52.0], [-1.0, 51.0]]],
})


@pytest.fixture(scope="module")
def parcels(api):
    mod = Module(api, "Unsupported properties")
    type_id = mod.object_type(
        columns=["id", "name", "outline"],
        rows=[{"id": "P1", "name": "Alpha parcel", "outline": SQUARE},
              {"id": "P2", "name": "Beta parcel", "outline": SQUARE}],
        key="id", title="name", types={"outline": "geoshape"})
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_all", "columns": "name,outline", "pageSize": 25,
                "sort": "key", "autoSelect": False, "activeVariable": "v_active"}},
            "props": {"resolvedName": "CanvasPropertyList", "props": {
                "objectSetVariable": "v_all", "properties": "name,outline", "hideNull": True}},
            "cards": {"resolvedName": "CanvasObjectCards", "props": {
                "objectSetVariable": "v_all", "fields": "outline", "pageSize": 1}},
        }),
        "variables": {"v_all": {"id": "v_all", "kind": "object_set", "label": "Parcels",
                                "object_set": object_set(type_id)},
                      "v_active": {"id": "v_active", "kind": "object_set_filter",
                                   "label": "Active"}},
        "events": {},
    })
    return mod


def test_a_geoshape_is_not_in_the_page_and_is_loaded_when_asked(page, parcels) -> None:
    pages = []
    page.on("response", lambda r: pages.append(r) if "/object-sets/evaluate" in r.url else None)
    open_module(page, parcels)
    table = page.locator(".data-grid").first
    eventually(lambda: table.locator("tbody tr").count(), lambda n: n == 2, what="the rows")
    # Not loaded with any page.
    for response in pages:
        body = response.json()
        assert all("outline" not in i["properties"] for i in body["instances"]), body
    # p.596's "..." in the table, and it loads that object's value alone.
    first = table.locator("tbody tr").first
    first.get_by_test_id("load-outline").click()
    expect(first.get_by_test_id("geoshape-value")).to_contain_text("Polygon")
    expect(table.locator("tbody tr").nth(1).get_by_test_id("load-outline")).to_have_text("…")
    # A click in the cell is not a click on the row.
    expect(first).not_to_have_attribute("aria-current", "true")
    # p.266's Load in the Property List, whose hide-null does not hide what
    # it has not loaded.
    props = page.get_by_test_id("property-list")
    expect(props.get_by_test_id("load-outline")).to_have_text("Load")
    props.get_by_test_id("load-outline").click()
    expect(props.get_by_test_id("geoshape-value")).to_contain_text("Polygon")
    # And the Object List's.
    card = page.locator(".canvas-card").first
    expect(card.get_by_test_id("load-outline")).to_have_text("Load")
    card.get_by_test_id("load-outline").click()
    expect(card.get_by_test_id("geoshape-value")).to_contain_text("Polygon")


def test_the_panels_say_which_are_loaded_on_demand(page, parcels) -> None:
    open_builder(page, parcels)
    settled(page)
    for row, note in (("Object table", "table-unsupported"),
                      ("Property list", "property-list-unsupported"),
                      ("Card list", "cards-unsupported")):
        page.locator(".canvas-tree-row", has_text=row).first.click()
        hint = page.get_by_test_id(note)
        expect(hint).to_contain_text("⚠ Outline")
        expect(hint).to_contain_text("loaded on demand")
        expect(hint.locator("[title]").first).to_have_attribute("title", "Large: not loaded with the page, and shown when a reader asks for it (Load).")
