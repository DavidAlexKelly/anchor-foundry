"""p.302's shape-based selection on the Map, with a rectangle (§550).

> "Enable shaped-based selection: Enable a tool to select objects on the map
> that intersect a drawn shape." (p.302)

A rectangle dragged around London and Paris selects those two: it becomes a
`within_box` on the sites' geopoint, written into the array a narrowed set
reads, and the table beside the map shows what the area holds. Madrid is just
south-west of the box and New York an ocean away, so a box that were drawn in
the wrong place, or answered as the whole map, would show them.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

SITES = [
    {"id": "LON", "name": "London", "where": "51.5,-0.1"},
    {"id": "PAR", "name": "Paris", "where": "48.85,2.35"},
    {"id": "MAD", "name": "Madrid", "where": "40.4,-3.7"},
    {"id": "NYC", "name": "New York", "where": "40.7,-74.0"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Map area")
    mod.type_id = mod.object_type(
        columns=["id", "name", "where"], rows=SITES, key="id", title="name",
        types={"where": "geopoint"})
    return mod


def build(api, sites, name: str, **props) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "objectTypeId": None,
                "locationProperty": "where", "labelProperty": "name", "limit": 500,
                "areaVariable": "v_area", **props}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(sites.type_id)},
            "v_area": {"id": "v_area", "kind": "array", "label": "Area"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "In the area",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_area"]}},
        },
        "events": {},
    })
    return mod


def pin(page, name: str):
    return page.locator("svg[aria-label='Map'] circle",
                        has=page.locator("title", has_text=name))


def rows_are(page, ids: list[str], what: str) -> None:
    cells = page.locator(".data-grid tbody tr td:first-child")
    eventually(lambda: sorted(c.strip() for c in cells.all_text_contents()),
               lambda got: got == sorted(ids), what=what)


def drag_around(page, *names: str) -> None:
    boxes = [pin(page, n).bounding_box() for n in names]
    assert all(boxes), boxes
    left = min(b["x"] for b in boxes) - 6
    top = min(b["y"] for b in boxes) - 6
    right = max(b["x"] + b["width"] for b in boxes) + 6
    bottom = max(b["y"] + b["height"] for b in boxes) + 6
    page.mouse.move(left, top)
    page.mouse.down()
    page.mouse.move(right, bottom, steps=6)
    page.mouse.up()


def test_a_dragged_area_selects_the_objects_inside_it(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map area select"))
    rows_are(page, ["LON", "PAR", "MAD", "NYC"], "every site before an area")
    expect(pin(page, "London")).to_be_visible()
    page.get_by_test_id("map-select-area").click()
    drag_around(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris")
    expect(page.get_by_test_id("map-area")).to_be_visible()
    # A drawn area ends the tool: the next drag pans again.
    expect(page.get_by_test_id("map-select-area")).to_have_attribute("aria-pressed", "false")
    page.get_by_test_id("map-clear-area").click()
    rows_are(page, ["LON", "PAR", "MAD", "NYC"], "every site once cleared")
    expect(page.get_by_test_id("map-area")).to_have_count(0)


def test_a_click_is_not_an_area(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map area click"))
    expect(pin(page, "London")).to_be_visible()
    page.get_by_test_id("map-select-area").click()
    box = page.locator("svg[aria-label='Map']").bounding_box()
    page.mouse.click(box["x"] + 20, box["y"] + 20)
    expect(page.get_by_test_id("map-area")).to_have_count(0)
    rows_are(page, ["LON", "PAR", "MAD", "NYC"], "every site still")


def test_a_map_with_nowhere_to_write_offers_no_area_tool(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map area none", areaVariable=None))
    expect(pin(page, "London")).to_be_visible()
    expect(page.get_by_test_id("map-select-area")).to_have_count(0)


def test_the_panel_names_where_the_area_goes(page, api, sites) -> None:
    mod = build(api, sites, "Map area panel", areaVariable=None)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-area-variable").select_option("v_area")
    save(page)
    assert mod.definition()["layout"]["mp"]["props"]["areaVariable"] == "v_area"
