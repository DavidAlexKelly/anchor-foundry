"""p.300's settings for the Map's object layer (§559).

    "Selected objects: Specify an object set variable that represents the
     collection of selected objects in a layer in the Map widget. This
     variable is bidirectional … Layer visibility: … a static value or a
     boolean variable. Lock layer: … Objects in locked layers cannot be
     selected by users. Style: … the default color, opacity …" (p.300)

The sites are §550's. A table beside the map reads the set the selection
narrows, so what the map says is selected is what the rest of the app acts on.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

SITES = [
    {"id": "LON", "name": "London", "where": "51.5,-0.1"},
    {"id": "PAR", "name": "Paris", "where": "48.85,2.35"},
    {"id": "NYC", "name": "New York", "where": "40.7,-74.0"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Map layer")
    mod.type_id = mod.object_type(
        columns=["id", "name", "where"], rows=SITES, key="id", title="name",
        types={"where": "geopoint"})
    return mod


def build(api, sites, name: str, selected=None, **props) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "locationProperty": "where",
                "labelProperty": "name", "limit": 500, "selectedVariable": "v_sel", **props}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(sites.type_id)},
            "v_sel": {"id": "v_sel", "kind": "array", "label": "Selected",
                      **({"default": selected} if selected is not None else {})},
            "v_show": {"id": "v_show", "kind": "boolean", "label": "Show", "default": False},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Picked",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_sel"]}},
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


def test_clicking_pins_selects_and_unselects_their_objects(page, api, sites) -> None:
    open_module(page, build(api, sites, "Layer select"))
    # "None selected" is written up front, so the narrowed set starts empty
    # rather than as every site.
    rows_are(page, [], "nothing selected yet")
    pin(page, "London").click()
    expect(pin(page, "London")).to_have_attribute("data-selected", "true")
    rows_are(page, ["LON"], "London, selected")
    pin(page, "Paris").click()
    rows_are(page, ["LON", "PAR"], "London and Paris")
    pin(page, "London").click()
    rows_are(page, ["PAR"], "Paris alone")
    expect(page.locator(".canvas-map-note")).to_contain_text("1 selected")


def test_the_selection_is_read_from_its_variable_too(page, api, sites) -> None:
    """p.300's "bidirectional": a selection the variable already holds is the
    one the map shows."""
    open_module(page, build(api, sites, "Layer preset", selected=[
        {"property": "$primary_key", "op": "in", "value": ["PAR"]}]))
    expect(pin(page, "Paris")).to_have_attribute("data-selected", "true", timeout=20000)
    expect(pin(page, "London")).not_to_have_attribute("data-selected", "true")
    rows_are(page, ["PAR"], "Paris, as the variable says")


def test_a_locked_layer_cannot_be_selected(page, api, sites) -> None:
    open_module(page, build(api, sites, "Layer locked", lockLayer=True))
    expect(pin(page, "London")).to_be_visible(timeout=20000)
    pin(page, "London").click()
    expect(pin(page, "London")).not_to_have_attribute("data-selected", "true")
    rows_are(page, [], "nothing selected")


def test_layer_visibility_hides_the_layer_statically_or_by_variable(page, api, sites) -> None:
    open_module(page, build(api, sites, "Layer hidden", layerVisible=False))
    expect(page.locator(".canvas-map-note")).to_contain_text("0 placed", timeout=20000)
    expect(pin(page, "London")).to_have_count(0)
    open_module(page, build(api, sites, "Layer hidden by variable",
                            layerVisibleVariable="v_show"))
    expect(page.locator(".canvas-map-note")).to_contain_text("0 placed", timeout=20000)
    expect(pin(page, "London")).to_have_count(0)


def test_the_style_and_label_are_the_layers(page, api, sites) -> None:
    open_module(page, build(api, sites, "Layer style", layerColor="#aa3300",
                            layerOpacity=0.5, layerLabel="Offices"))
    expect(pin(page, "London")).to_have_attribute("fill", "#aa3300", timeout=20000)
    expect(pin(page, "London")).to_have_attribute("fill-opacity", "0.5")
    expect(page.locator(".canvas-map-note")).to_contain_text("Offices: 3 placed")


def test_the_panel_sets_the_layer(page, api, sites) -> None:
    mod = build(api, sites, "Layer panel", selectedVariable=None)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-layer-label").fill("Offices")
    page.get_by_test_id("map-selected-variable").select_option("v_sel")
    page.get_by_test_id("map-lock-layer").check()
    page.get_by_test_id("map-layer-visible-variable").select_option("v_show")
    save(page)
    eventually(lambda: mod.definition()["layout"]["mp"]["props"],
               lambda p: (p.get("layerLabel"), p.get("selectedVariable"), p.get("lockLayer"),
                          p.get("layerVisibleVariable")) == ("Offices", "v_sel", True, "v_show"),
               what="the layer settings, saved")
