"""p.301's Selected shapes on the Map (§641).

> "Selected shapes: A bidirectional string variable that reflects the shapes
> selected on the map interface as a GeoJSON string." (p.301)

Two circles drawn, round London and round Madrid; a click on Madrid's
selects it, and the variable, in a text input beside the map, holds it as
GeoJSON. Text written there selects the drawn shape it names, and a shape
cleared from the map is no longer selected.
"""
from __future__ import annotations

import json

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled
from test_map_area import pin, rows_are, sites  # noqa: F401
from test_map_shapes import circle_round


def build(api, sites, name: str, **props) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "objectTypeId": None,
                "locationProperty": "where", "labelProperty": "name", "limit": 500,
                "areaVariable": "v_area", "drawnShapesVariable": "v_shapes",
                "selectedShapesVariable": "v_sel", "singleDrawMode": False, **props}},
            "txt": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_shapes", "label": "Shapes", "placeholder": "",
                              "format": "line", "rows": 4}},
            "sel": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_sel", "label": "Selected", "placeholder": "",
                              "format": "line", "rows": 4}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(sites.type_id)},
            "v_area": {"id": "v_area", "kind": "array", "label": "Area"},
            "v_shapes": {"id": "v_shapes", "kind": "string", "label": "Shapes"},
            "v_sel": {"id": "v_sel", "kind": "string", "label": "Selected"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "In the area",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_area"]}},
        },
        "events": {},
    })
    return mod


def two_circles(page) -> None:
    expect(pin(page, "London")).to_be_visible()
    circle_round(page, "London", 20)
    circle_round(page, "Madrid", 20)
    rows_are(page, ["LON", "MAD"], "inside either circle")
    expect(page.get_by_test_id("map-area")).to_have_count(2)


def click_beside(page, name: str, dx: float = 20) -> None:
    """A click inside the circle round a pin, clear of the pin itself."""
    b = pin(page, name).bounding_box()
    page.mouse.click(b["x"] + b["width"] / 2 + dx, b["y"] + b["height"] / 2)


def selected(page):
    return page.get_by_label("Selected")


def areas(page):
    return page.get_by_test_id("map-area")


def test_a_click_selects_a_drawn_shape_and_another_takes_it_off(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map selected click"))
    two_circles(page)
    click_beside(page, "Madrid")
    expect(areas(page).nth(1)).to_have_attribute("data-selected", "true")
    expect(areas(page).nth(0)).to_have_attribute("data-selected", "false")
    text = eventually(lambda: selected(page).input_value(), lambda got: got.startswith("{"),
                      what="the selected shape as GeoJSON")
    [feature] = json.loads(text)["features"]
    lon, lat = feature["geometry"]["coordinates"]
    assert abs(lat - 40.4) < 1 and abs(lon + 3.7) < 1, (lat, lon)
    # Selecting is not drawing: the objects selected by the areas stay.
    rows_are(page, ["LON", "MAD"], "still inside either circle")
    # Both selected, in the order they were drawn.
    click_beside(page, "London")
    both = eventually(lambda: selected(page).input_value(),
                      lambda got: got.startswith("{") and len(json.loads(got)["features"]) == 2,
                      what="both shapes selected")
    assert json.loads(both)["features"][1] == feature
    click_beside(page, "Madrid")
    click_beside(page, "London")
    expect(selected(page)).to_have_value("")
    expect(areas(page).nth(1)).to_have_attribute("data-selected", "false")


def test_text_written_there_selects_the_shape_it_names(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map selected in"))
    two_circles(page)
    drawn = json.loads(page.get_by_label("Shapes").input_value())
    selected(page).fill(json.dumps({"type": "FeatureCollection",
                                    "features": [drawn["features"][0]]}))
    expect(areas(page).nth(0)).to_have_attribute("data-selected", "true")
    expect(areas(page).nth(1)).to_have_attribute("data-selected", "false")


def test_a_shape_cleared_is_no_longer_selected(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map selected cleared"))
    two_circles(page)
    click_beside(page, "Madrid")
    expect(areas(page).nth(1)).to_have_attribute("data-selected", "true")
    page.get_by_test_id("map-clear-area").click()
    expect(selected(page)).to_have_value("")


def test_a_pan_that_ends_on_a_shape_selects_nothing(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map selected pan"))
    two_circles(page)
    b = pin(page, "Madrid").bounding_box()
    x, y = b["x"] + b["width"] / 2 + 20, b["y"] + b["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 30, y + 30, steps=5)
    page.mouse.move(x, y, steps=5)
    page.mouse.up()
    expect(areas(page).nth(1)).to_have_attribute("data-selected", "false")
    expect(selected(page)).to_have_value("")


def test_a_map_with_nowhere_to_write_leaves_its_shapes_unclickable(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map selected none", selectedShapesVariable=None))
    two_circles(page)
    click_beside(page, "Madrid")
    expect(areas(page).nth(1)).to_have_attribute("data-selected", "false")
    # A click on one reaches the map beneath, as before there were selections.
    expect(areas(page).nth(1)).to_have_css("pointer-events", "none")


def test_the_panel_names_the_variable(page, api, sites) -> None:
    mod = build(api, sites, "Map selected panel", selectedShapesVariable=None)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-selected-shapes-variable").select_option("v_sel")
    save(page)
    assert mod.definition()["layout"]["mp"]["props"]["selectedShapesVariable"] == "v_sel"
