"""p.300's Geometry and Legend visibility on the Map's object layers (§670).

> "Geometries can be added by selecting Add geometry. Reorder geometries by
> dragging them … If an object type includes a Geoshape property and you
> configure it in a Map layer geometry, the Map widget automatically loads
> and renders it." (p.300)
>
> "An object layer and its geometries are visible by default in the legend
> panel of the map. Under the Legend visibility section, you can toggle the
> visibility of the entire layer or individual geometries." (p.300)

Two parcels, each a pin, an outline and (one of them) a route. The map's own
layer draws the outlines in red and the route in the layer's colour, the
route left out of the legend. A second layer of zones has no geopoint at
all: it is its outlines alone, and none of its zones is said to have nowhere
to stand. How geometries are read, ordered and turned into shapes is
`map-geometry.test.ts`.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled


def square(lon: float, lat: float) -> str:
    return json.dumps({"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + 1, lat], [lon + 1, lat + 1], [lon, lat + 1], [lon, lat]]]})


ROUTE = json.dumps({"type": "LineString", "coordinates": [[-1.0, 51.0], [0.5, 52.0]]})
PARCELS = [
    {"id": "P1", "name": "Alpha parcel", "outline": square(-1.0, 51.0), "route": ROUTE, "where": "51.5,-0.5"},
    {"id": "P2", "name": "Beta parcel", "outline": square(2.0, 48.0), "route": "", "where": "48.5,2.5"},
]
ZONES = [
    {"code": "Z1", "title": "North zone", "area": square(-3.0, 53.0)},
    {"code": "Z2", "title": "South zone", "area": square(-3.0, 45.0)},
    {"code": "Z3", "title": "No zone", "area": ""},
]
RED = "#dc2626"
LAYER = "#14646e"


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Map geometry")
    mod.parcels = mod.object_type(
        columns=["id", "name", "outline", "route", "where"], rows=PARCELS, key="id", title="name",
        types={"outline": "geoshape", "route": "geoshape", "where": "geopoint"})
    mod.zones = mod.object_type(
        columns=["code", "title", "area"], rows=ZONES, key="code", title="title",
        types={"area": "geoshape"}, slug=f"zones_{mod.tag}")
    return mod


def build(api, world, name: str, **props) -> Module:
    mod = Module(api, name, beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_parcels", "objectTypeId": None,
                "locationProperty": "where", "labelProperty": "name", "limit": 500,
                "showLegend": True, "layerLabel": "Parcels", "layerColor": LAYER,
                "geometries": [{"id": "geometry-1", "property": "outline", "color": RED},
                               {"id": "geometry-2", "property": "route", "legend": False}],
                "layers": [{"id": "layer-2", "objectSetVariable": "v_zones", "labelProperty": "title",
                            "label": "Zones", "geometries": [{"id": "geometry-1", "property": "area"}]}],
                **props}},
        }),
        "variables": {
            "v_parcels": {"id": "v_parcels", "kind": "object_set", "label": "Parcels",
                          "object_set": object_set(world.parcels)},
            "v_zones": {"id": "v_zones", "kind": "object_set", "label": "Zones",
                        "object_set": object_set(world.zones)},
        },
        "events": {},
    })
    return mod


def shapes(page, layer: str, geometry: str):
    return page.locator(f"svg[aria-label='Map'] path[data-testid^='map-shape-{layer}-{geometry}-']")


def legend_entries(page):
    return page.get_by_test_id("map-legend-entry")


def test_each_geometry_is_drawn_in_its_colour_and_listed(page, api, world) -> None:
    open_module(page, build(api, world, "Map geometry drawn"))
    outlines = shapes(page, "layer-1", "geometry-1")
    expect(outlines).to_have_count(2, timeout=20000)
    expect(outlines.first).to_have_attribute("stroke", RED)
    # The route is one parcel's; the other's blank route is no shape.
    routes = shapes(page, "layer-1", "geometry-2")
    expect(routes).to_have_count(1)
    expect(routes).to_have_attribute("stroke", LAYER)
    expect(routes.locator("title")).to_have_text("Alpha parcel")
    # A zones layer of shapes alone: two zones drawn, the blank one not.
    expect(shapes(page, "layer-2", "geometry-1")).to_have_count(2)
    note = page.locator(".canvas-map-note")
    expect(note).to_contain_text("2 placed")
    expect(note).to_contain_text("5 shapes")
    expect(note).not_to_contain_text("without a usable location")
    # The legend: the pins, the outlines and the zones - not the route.
    entries = legend_entries(page)
    expect(entries).to_have_count(3)
    expect(entries.nth(0)).to_contain_text("Parcels")
    expect(entries.nth(1)).to_have_attribute("data-kind", "shape")
    expect(entries.nth(1)).to_contain_text("Parcels · outline")
    expect(entries.nth(1)).to_contain_text("2")
    expect(entries.nth(2)).to_contain_text("Zones · area")


def test_a_layer_left_out_of_the_legend_is_still_drawn(page, api, world) -> None:
    open_module(page, build(api, world, "Map geometry legend", layerInLegend=False))
    expect(shapes(page, "layer-1", "geometry-1")).to_have_count(2, timeout=20000)
    entries = legend_entries(page)
    expect(entries).to_have_count(1)
    expect(entries).to_contain_text("Zones · area")


def test_a_map_of_shapes_alone(page, api, world) -> None:
    """The map's own layer with no geopoint: its outlines, no pins, and no
    parcel said to have nowhere to stand; its legend lists the outlines and
    not an empty set of pins."""
    open_module(page, build(api, world, "Map geometry alone", locationProperty=None, layers=[]))
    expect(shapes(page, "layer-1", "geometry-1")).to_have_count(2, timeout=20000)
    note = page.locator(".canvas-map-note")
    expect(note).to_contain_text("0 placed")
    expect(note).not_to_contain_text("without a usable location")
    entries = legend_entries(page)
    expect(entries).to_have_count(1)
    expect(entries).to_have_attribute("data-kind", "shape")


def test_later_geometries_are_drawn_over_earlier_ones(page, api, world) -> None:
    open_module(page, build(api, world, "Map geometry order"))
    paths = page.locator("svg[aria-label='Map'] path[data-testid^='map-shape-layer-1-']")
    expect(paths).to_have_count(3, timeout=20000)
    ids = [p.get_attribute("data-testid") for p in paths.all()]
    assert [i.split("-")[5] for i in ids] == ["1", "1", "2"], ids


def test_the_panel_adds_orders_and_styles_geometries(page, api, world) -> None:
    mod = build(api, world, "Map geometry panel", geometries=[], layers=[])
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-layer-add-geometry").click()
    page.get_by_label("Geometry 1 property").select_option("outline")
    page.get_by_test_id("map-layer-add-geometry").click()
    # Only the geoshape properties are offered.
    expect(page.get_by_label("Geometry 2 property").locator("option")).to_have_text(
        ["Geoshape property…", "outline", "route"])
    page.get_by_label("Geometry 2 property").select_option("route")
    page.get_by_label("Geometry 2 in the legend").uncheck()
    page.get_by_label("Move geometry 2 earlier").click()
    page.get_by_test_id("map-layer-in-legend").uncheck()
    save(page)
    eventually(lambda: mod.definition()["layout"]["mp"]["props"],
               lambda p: ([(g["property"], g["legend"]) for g in p.get("geometries", [])],
                          p.get("layerInLegend"))
               == ([("route", False), ("outline", True)], False),
               what="the geometries, in their new order, saved")
