"""p.300's Add object layer on the Map (§642).

> "In the widget editor, select Add object layer to add a new layer to the
> map. Then, open the newly created layer, and create a new object set
> variable or reuse an existing one … Once added, the new object layer will
> populate on the map." (p.300)

The map's own layer is the four sites. A second layer holds three ports, of
another object type, in its own colour and with its own Selected objects: a
click on a port selects it into that layer's variable, which a table beside
the map reads, and leaves the sites' selection alone.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled
from test_map_area import pin, sites  # noqa: F401

# Out at sea, each well clear of every site, so no pin shares a bubble.
PORTS = [
    {"code": "PDL", "title": "Ponta Delgada", "at": "37.74,-25.67"},
    {"code": "BDA", "title": "Hamilton", "at": "32.29,-64.78"},
    {"code": "HFX", "title": "Halifax", "at": "44.65,-63.57"},
]
PORT_COLOR = "#aa3300"


@pytest.fixture(scope="module")
def ports(api, sites):
    sites.ports_id = sites.object_type(
        columns=["code", "title", "at"], rows=PORTS, key="code", title="title",
        types={"at": "geopoint"}, slug=f"ports_{sites.tag}")
    return sites


def build(api, ports, name: str, **layer) -> Module:
    mod = Module(api, name, beside=ports)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "objectTypeId": None,
                "locationProperty": "where", "labelProperty": "name", "limit": 500,
                "selectedVariable": "v_site_sel", "showLegend": True,
                "layers": [{"id": "layer-2", "objectSetVariable": "v_ports",
                            "locationProperty": "at", "labelProperty": "title",
                            "label": "Ports", "selectedVariable": "v_port_sel",
                            "color": PORT_COLOR, **layer}]}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_port_picked", "columns": "code,title", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(ports.type_id)},
            "v_ports": {"id": "v_ports", "kind": "object_set", "label": "Ports",
                        "object_set": object_set(ports.ports_id)},
            "v_site_sel": {"id": "v_site_sel", "kind": "array", "label": "Sites selected"},
            "v_port_sel": {"id": "v_port_sel", "kind": "array", "label": "Ports selected"},
            "v_show": {"id": "v_show", "kind": "boolean", "label": "Show ports",
                       "default": False},
            "v_port_picked": {"id": "v_port_picked", "kind": "object_set",
                              "label": "Ports picked",
                              "derivation": {"transform": "narrow_set",
                                             "inputs": ["v_ports", "v_port_sel"]}},
        },
        "events": {},
    })
    return mod


def port_rows(page, ids: list[str], what: str) -> None:
    cells = page.locator(".data-grid tbody tr td:first-child")
    eventually(lambda: sorted(c.strip() for c in cells.all_text_contents()),
               lambda got: got == sorted(ids), what=what)


def port_pins(page):
    return page.locator("svg[aria-label='Map'] circle[data-layer='layer-2']")


def test_an_added_layer_draws_its_own_objects_in_its_own_colour(page, api, ports) -> None:
    open_module(page, build(api, ports, "Map layers drawn"))
    expect(pin(page, "London")).to_be_visible()
    expect(pin(page, "Ponta Delgada")).to_be_visible()
    expect(pin(page, "Ponta Delgada")).to_have_attribute("fill", PORT_COLOR)
    expect(pin(page, "London")).not_to_have_attribute("fill", PORT_COLOR)
    expect(page.locator(".canvas-map-note")).to_contain_text("7 placed")
    legend = page.get_by_test_id("map-legend")
    expect(legend).to_contain_text("Ports")
    expect(legend).to_contain_text("3")


def test_a_click_selects_into_the_layer_it_belongs_to(page, api, ports) -> None:
    open_module(page, build(api, ports, "Map layers select"))
    port_rows(page, [], "no port selected to start")
    pin(page, "Ponta Delgada").click()
    port_rows(page, ["PDL"], "Ponta Delgada, selected into the ports' variable")
    expect(pin(page, "Ponta Delgada")).to_have_attribute("data-selected", "true")
    expect(page.locator(".canvas-map-note")).to_contain_text("1 selected")
    pin(page, "Ponta Delgada").click()
    port_rows(page, [], "Ponta Delgada taken off again")


def test_a_locked_layer_cannot_be_selected(page, api, ports) -> None:
    open_module(page, build(api, ports, "Map layers locked", locked=True))
    expect(pin(page, "Ponta Delgada")).to_be_visible()
    pin(page, "Ponta Delgada").click()
    expect(pin(page, "Ponta Delgada")).not_to_have_attribute("data-selected", "true")
    port_rows(page, [], "still no port selected")


def test_a_layer_follows_its_visibility_variable(page, api, ports) -> None:
    open_module(page, build(api, ports, "Map layers hidden", visibleVariable="v_show"))
    expect(pin(page, "London")).to_be_visible()
    expect(port_pins(page)).to_have_count(0)
    expect(page.get_by_test_id("map-legend")).not_to_contain_text("Ports")


def test_a_hidden_layer_by_its_setting(page, api, ports) -> None:
    open_module(page, build(api, ports, "Map layers off", visible=False))
    expect(pin(page, "London")).to_be_visible()
    expect(port_pins(page)).to_have_count(0)


def test_the_panel_adds_a_layer(page, api, ports) -> None:
    mod = build(api, ports, "Map layers panel")
    definition = mod.definition()
    definition["layout"]["mp"]["props"]["layers"] = []
    mod.define(definition)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-add-layer").click()
    tag = "map-added-layer-layer-2"
    page.get_by_test_id(f"{tag}-label").fill("Harbours")
    page.get_by_test_id(f"{tag}-set").select_option("v_ports")
    page.get_by_test_id(f"{tag}-location").select_option("at")
    page.get_by_test_id(f"{tag}-selected").select_option("v_port_sel")
    save(page)
    [layer] = mod.definition()["layout"]["mp"]["props"]["layers"]
    assert (layer["label"], layer["objectSetVariable"], layer["locationProperty"],
            layer["selectedVariable"]) == ("Harbours", "v_ports", "at", "v_port_sel")
    page.get_by_test_id(f"{tag}-remove").click()
    # A second save's "saved" is already on screen from the first, so the
    # stored document is polled rather than trusted at once.
    page.get_by_role("button", name="Save", exact=True).click()
    eventually(lambda: mod.definition()["layout"]["mp"]["props"]["layers"],
               lambda got: got == [], what="the layer removed and saved")
