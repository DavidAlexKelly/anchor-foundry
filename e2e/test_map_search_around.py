"""p.303's search around on the Map (§734).

> "Enable search around: Enable search arounds using the toolbar and context
> menu." (`workshop` p.303)

> "A Search Around would create a new set by traversing a link on every
> object in the current set." (`action-types` p.37)

The map's own layer is the four sites. Three ports each serve one site -
Ponta Delgada serves London, Halifax and Hamilton serve New York - and a
search around follows that link from the sites to the ports they are served
by, drawing what it finds as a layer of its own. Which ports appear is the
whole test: a walk that ignored where it started would draw all three every
time.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled
from test_map_area import pin, sites  # noqa: F401

PORTS = [
    {"code": "PDL", "title": "Ponta Delgada", "at": "37.74,-25.67", "site": "LON"},
    {"code": "BDA", "title": "Hamilton", "at": "32.29,-64.78", "site": "NYC"},
    {"code": "HFX", "title": "Halifax", "at": "44.65,-63.57", "site": "NYC"},
    # Served, and nowhere to stand: counted rather than dropped.
    {"code": "XXX", "title": "Unsurveyed", "at": "", "site": "NYC"},
]


@pytest.fixture(scope="module")
def world(api, sites):
    sites.ports_id = sites.object_type(
        columns=["code", "title", "at", "site"], rows=PORTS, key="code", title="title",
        types={"at": "geopoint"}, slug=f"sa_ports_{sites.tag}")
    # A type with nowhere to stand: linked, but no geopoint.
    sites.notes_id = sites.object_type(
        columns=["id", "site", "text"], rows=[{"id": "N1", "site": "LON", "text": "busy"}],
        key="id", title="text", slug=f"sa_notes_{sites.tag}")
    sites.served = api.call("POST", f"/workspaces/{sites.workspace_id}/link-types", {
        "api_name": f"serves_{sites.tag}", "display_name": "Serves",
        "from_type_id": sites.ports_id, "to_type_id": sites.type_id,
        "cardinality": "one_to_many", "from_property": "site", "to_property": "$primary_key"})
    sites.noted = api.call("POST", f"/workspaces/{sites.workspace_id}/link-types", {
        "api_name": f"notes_{sites.tag}", "display_name": "Notes",
        "from_type_id": sites.notes_id, "to_type_id": sites.type_id,
        "cardinality": "one_to_many", "from_property": "site", "to_property": "$primary_key"})
    return sites


def build(api, world, name: str, **props) -> Module:
    mod = Module(api, name, beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "objectTypeId": None,
                "locationProperty": "where", "labelProperty": "name", "limit": 500,
                "layerLabel": "Sites", "selectedVariable": "v_sel", "showLegend": True,
                "enableSearchAround": True, **props}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(world.type_id)},
            "v_sel": {"id": "v_sel", "kind": "array", "label": "Sites selected"},
        },
        "events": {},
    })
    return mod


def follow(page, world, link) -> None:
    panel = page.get_by_test_id("map-search-around-panel")
    expect(panel).to_be_visible()
    panel.get_by_test_id("map-search-around-link").select_option(f"{link['id']}:inbound")


def result_pins(page):
    return page.locator("svg[aria-label='Map'] circle[data-layer^='search-']")


def test_the_toolbar_searches_around_the_selection(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around selected"))
    pin(page, "New York").click()
    expect(pin(page, "New York")).to_have_attribute("data-selected", "true")
    page.get_by_test_id("map-search-around").click()
    expect(page.get_by_test_id("map-search-around-panel")).to_contain_text(
        "Search around 1 selected")
    follow(page, world, world.served)
    page.get_by_test_id("map-search-around-add").click()
    expect(result_pins(page)).to_have_count(2)
    expect(pin(page, "Halifax")).to_be_visible()
    expect(pin(page, "Hamilton")).to_be_visible()
    expect(pin(page, "Ponta Delgada")).to_have_count(0)
    [result] = page.get_by_test_id("map-search-result").all()
    expect(result).to_contain_text("of 1 selected")
    expect(result.get_by_test_id("map-search-result-count")).to_have_text(
        "2 placed, 1 without a usable location")
    expect(page.locator(".canvas-map-note")).to_contain_text("1 without a usable location")
    # A result has no Selected objects, so its pins are not offered as a click.
    assert pin(page, "Halifax").evaluate("e => getComputedStyle(e).cursor") != "pointer"
    expect(page.get_by_test_id("map-legend")).to_contain_text("of 1 selected")
    expect(page.get_by_test_id("map-search-around-panel")).to_have_count(0)


def test_the_toolbar_with_nothing_selected_searches_the_whole_layer(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around all"))
    expect(pin(page, "London")).to_be_visible()
    page.get_by_test_id("map-search-around").click()
    expect(page.get_by_test_id("map-search-around-panel")).to_contain_text("Search around Sites")
    follow(page, world, world.served)
    page.get_by_test_id("map-search-around-add").click()
    expect(result_pins(page)).to_have_count(3)
    expect(page.get_by_test_id("map-search-result")).to_contain_text("of Sites")


def test_each_search_is_a_layer_in_its_own_colour(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around twice"))
    for site in ("London", "New York"):
        pin(page, site).click(button="right")
        page.get_by_test_id("map-pin-menu-search-around").click()
        follow(page, world, world.served)
        page.get_by_test_id("map-search-around-add").click()
    expect(page.get_by_test_id("map-search-result")).to_have_count(2)
    expect(result_pins(page)).to_have_count(3)
    assert (pin(page, "Ponta Delgada").get_attribute("data-layer"),
            pin(page, "Halifax").get_attribute("data-layer")) == ("search-0", "search-1")
    assert pin(page, "Ponta Delgada").get_attribute("fill") != pin(page, "Halifax").get_attribute("fill")


def test_a_pins_context_menu_searches_around_that_object(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around pin"))
    expect(pin(page, "London")).to_be_visible()
    # The map's menu, not the browser's.
    assert pin(page, "London").evaluate("""e => {
        const ev = new MouseEvent("contextmenu", {bubbles: true, cancelable: true});
        e.dispatchEvent(ev);
        return ev.defaultPrevented;
    }""")
    page.keyboard.press("Escape")
    pin(page, "London").click(button="right")
    item = page.get_by_test_id("map-pin-menu-search-around")
    expect(item).to_have_text("Search around London…")
    item.click()
    expect(page.get_by_test_id("map-pin-menu")).to_have_count(0)
    follow(page, world, world.served)
    page.get_by_test_id("map-search-around-add").click()
    expect(result_pins(page)).to_have_count(1)
    expect(pin(page, "Ponta Delgada")).to_be_visible()
    # A right-click does not select: the menu is not the pin's click.
    expect(pin(page, "London")).not_to_have_attribute("data-selected", "true")
    page.get_by_test_id("map-search-result-remove").click()
    expect(result_pins(page)).to_have_count(0)
    expect(page.get_by_test_id("map-search-results")).to_have_count(0)


def test_escape_closes_the_context_menu(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around escape"))
    pin(page, "Paris").click(button="right")
    expect(page.get_by_test_id("map-pin-menu")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("map-pin-menu")).to_have_count(0)


def test_a_type_with_no_geopoint_has_nowhere_to_stand(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around nowhere"))
    page.get_by_test_id("map-search-around").click()
    follow(page, world, world.noted)
    expect(page.get_by_test_id("map-search-around-nowhere")).to_contain_text(
        "has no geopoint property")
    expect(page.get_by_test_id("map-search-around-add")).to_be_disabled()
    follow(page, world, world.served)
    expect(page.get_by_test_id("map-search-around-nowhere")).to_have_count(0)
    expect(page.get_by_test_id("map-search-around-add")).to_be_enabled()


def test_off_unless_turned_on(page, api, world) -> None:
    open_module(page, build(api, world, "Map search around off", enableSearchAround=False))
    expect(pin(page, "London")).to_be_visible()
    expect(page.get_by_test_id("map-search-around")).to_have_count(0)
    pin(page, "London").click(button="right")
    expect(page.get_by_test_id("map-pin-menu")).to_have_count(0)


def test_the_panel_turns_it_on(page, api, world) -> None:
    mod = build(api, world, "Map search around panel", enableSearchAround=False)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-enableSearchAround").click()
    expect(page.get_by_test_id("map-enableSearchAround")).to_be_checked()
    save(page)
    eventually(lambda: mod.definition()["layout"]["mp"]["props"]["enableSearchAround"],
               lambda got: got is True, what="search around turned on")
