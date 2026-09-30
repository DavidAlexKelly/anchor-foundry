"""p.301's Drawn shapes, Shape output type and On drawn shape (§574).

> "Shape output type: Control whether the GeoJSON string output of the drawn
> shapes variable and selected shape variable are represented as a GeoJSON
> feature or geometry collection. Drawn shapes: A bidirectional string
> variable that reflects the shapes drawn within the map interface as a
> GeoJSON string. On drawn shape: Configure Workshop events to trigger when a
> shape is drawn in the map." (p.301)

The variable sits in a text input beside the map, so both directions show:
a circle drawn on the map appears there as GeoJSON, and GeoJSON typed there
is drawn on the map and selects what it holds.
"""
from __future__ import annotations

import json

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled
from test_map_area import pin, rows_are, sites  # noqa: F401

ALL = ["LON", "PAR", "MAD", "NYC"]
# London and Paris, and not Madrid.
SHAPE = {"type": "Polygon",
         "coordinates": [[[-5, 47], [5, 47], [5, 53], [-5, 53], [-5, 47]]]}


def build(api, sites, name: str, events: bool = False, **props) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "objectTypeId": None,
                "locationProperty": "where", "labelProperty": "name", "limit": 500,
                "areaVariable": "v_area", "drawnShapesVariable": "v_shapes", **props}},
            "txt": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_shapes", "label": "Shapes", "placeholder": "",
                              "format": "line", "rows": 4}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "drawn: [{{v_last}}]"}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(sites.type_id)},
            "v_area": {"id": "v_area", "kind": "array", "label": "Area"},
            "v_shapes": {"id": "v_shapes", "kind": "string", "label": "Shapes"},
            "v_last": {"id": "v_last", "kind": "string", "label": "Last drawn"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "In the area",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_area"]}},
        },
        "events": {
            "e_drawn": {"id": "e_drawn", "trigger": {"node": "mp", "on": "change"},
                        "effects": [{"type": "set_variable",
                                     "config": {"variable": "v_last", "value": "{{value}}"}}]},
        } if events else {},
    })
    return mod


def shapes_box(page):
    return page.get_by_label("Shapes")


def drag_circle(page, around: str, past: str) -> None:
    a, b = (pin(page, n).bounding_box() for n in (around, past))
    page.get_by_test_id("map-draw-circle").click()
    page.mouse.move(a["x"] + a["width"] / 2, a["y"] + a["height"] / 2)
    page.mouse.down()
    page.mouse.move(b["x"] + b["width"] / 2 + 10, b["y"] + b["height"] / 2 + 10, steps=5)
    page.mouse.up()


def test_a_drawn_circle_is_written_as_a_feature(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map shapes out", events=True))
    expect(pin(page, "London")).to_be_visible()
    drag_circle(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris, within the circle")
    text = eventually(lambda: shapes_box(page).input_value(), lambda got: got.startswith("{"),
                      what="the drawn shape as GeoJSON")
    feature = json.loads(text)["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["properties"]["shape"] == "circle"
    lon, lat = feature["geometry"]["coordinates"]
    assert abs(lat - 51.5) < 1 and abs(lon + 0.1) < 1, (lat, lon)
    assert 300_000 < feature["properties"]["radius"] < 900_000
    # p.301's On drawn shape: `{{value}}` is the same GeoJSON.
    expect(page.get_by_text(f"drawn: [{text}]")).to_be_visible()
    # Clearing the area clears the variable, and is not a drawn shape.
    page.get_by_test_id("map-clear-area").click()
    expect(shapes_box(page)).to_have_value("")
    rows_are(page, ALL, "every site once cleared")
    expect(page.get_by_text(f"drawn: [{text}]")).to_be_visible()


def test_geometries_carry_a_circle_as_its_outline(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map shapes geometries", shapeOutputType="geometries"))
    expect(pin(page, "London")).to_be_visible()
    drag_circle(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris, within the circle")
    text = eventually(lambda: shapes_box(page).input_value(), lambda got: got.startswith("{"),
                      what="the drawn shape as GeoJSON")
    parsed = json.loads(text)
    assert parsed["type"] == "GeometryCollection"
    assert parsed["geometries"][0]["type"] == "Polygon"
    assert len(parsed["geometries"][0]["coordinates"][0]) == 91


def test_geojson_written_elsewhere_is_drawn_and_selects(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map shapes in"))
    rows_are(page, ALL, "every site before a shape")
    shapes_box(page).fill(json.dumps(SHAPE))
    rows_are(page, ["LON", "PAR"], "London and Paris, inside the shape typed in")
    expect(page.get_by_test_id("map-area")).to_have_attribute("data-shape", "polygon")
    # Text that is no shape leaves the area as it was; empty text clears it.
    shapes_box(page).fill("not a shape")
    rows_are(page, ["LON", "PAR"], "still London and Paris")
    shapes_box(page).fill("")
    rows_are(page, ALL, "every site once the variable is emptied")
    expect(page.get_by_test_id("map-area")).to_have_count(0)


def test_a_default_shape_is_drawn_on_opening(page, api, sites) -> None:
    mod = build(api, sites, "Map shapes default")
    definition = mod.definition()
    definition["variables"]["v_shapes"]["default"] = json.dumps(SHAPE)
    mod.define(definition)
    open_module(page, mod)
    rows_are(page, ["LON", "PAR"], "London and Paris, inside the default shape")
    expect(page.get_by_test_id("map-area")).to_have_attribute("data-shape", "polygon")


def test_the_panel_names_the_variable_and_the_output(page, api, sites) -> None:
    mod = build(api, sites, "Map shapes panel", drawnShapesVariable=None)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-drawn-shapes-variable").select_option("v_shapes")
    page.get_by_test_id("map-shape-output").select_option("geometries")
    save(page)
    props = mod.definition()["layout"]["mp"]["props"]
    assert props["drawnShapesVariable"] == "v_shapes"
    assert props["shapeOutputType"] == "geometries"


def test_the_builder_offers_shape_drawn(page, api, sites) -> None:
    """p.301's On drawn shape, offered on a map as "Shape drawn"."""
    mod = build(api, sites, "Map shapes event")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    trigger = page.locator(".canvas-event-body label.field", has_text="Is").locator("select")
    expect(trigger.locator("option")).to_have_text(["Pin selected", "Shape drawn"])
    trigger.select_option(label="Shape drawn")
    save(page)
    assert [e["trigger"] for e in mod.definition()["events"].values()] == [
        {"node": "mp", "on": "change"}]
