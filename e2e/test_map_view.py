"""p.304's interface options on the Workshop Map (§560).

    "Legend: Display the legend panel … Collapse legend panel … Panel size …
     Show selection panel: Display the list of currently selected objects or
     a selected object's details … Viewport auto zoom: … Object set … All
     objects … Only update if outside viewport … Viewport bounds: a
     bidirectional string variable where the GeoJSON value represents the
     current viewing window … Viewport follow object set …" (p.304)

§550's three sites. The caption says how many pins are outside the view,
which is how a test can see where the map is looking.
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
AROUND_PARIS = ('{"type":"Polygon","coordinates":[[[2,48.5],[3,48.5],[3,49.2],[2,49.2],'
                '[2,48.5]]]}')


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Map view")
    mod.type_id = mod.object_type(
        columns=["id", "name", "where"], rows=SITES, key="id", title="name",
        types={"where": "geopoint"})
    return mod


def only(sites, key: str) -> dict:
    return object_set(sites.type_id, [{"property": "$primary_key", "op": "in", "value": [key]}])


def build(api, sites, name: str, selected=None, bounds=None, **props) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "mp": {"resolvedName": "CanvasMap", "props": {
                "source": "objects", "objectSetVariable": "v_all", "locationProperty": "where",
                "labelProperty": "name", "limit": 500, **props}},
            "echo": {"resolvedName": "CanvasText", "props": {"tag": "p",
                                                             "text": "bounds {{v_bounds}}"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(sites.type_id)},
            "v_sel": {"id": "v_sel", "kind": "array", "label": "Selected",
                      **({"default": selected} if selected is not None else {})},
            "v_nyc": {"id": "v_nyc", "kind": "object_set", "label": "New York",
                      "object_set": only(sites, "NYC")},
            "v_par": {"id": "v_par", "kind": "object_set", "label": "Paris",
                      "object_set": only(sites, "PAR")},
            "v_bounds": {"id": "v_bounds", "kind": "string", "label": "Bounds",
                         **({"default": bounds} if bounds is not None else {})},
        },
        "events": {},
    })
    return mod


def note(page):
    return page.locator(".canvas-map-note")


def pin(page, name: str):
    return page.locator("svg[aria-label='Map'] circle",
                        has=page.locator("title", has_text=name))


def test_the_legend_lists_the_layer_open_or_collapsed(page, api, sites) -> None:
    open_module(page, build(api, sites, "View legend", showLegend=True, layerLabel="Offices"))
    legend = page.get_by_test_id("map-legend")
    expect(legend).to_have_attribute("open", "", timeout=20000)
    expect(legend.get_by_test_id("map-legend-entry")).to_have_text("Offices3")
    open_module(page, build(api, sites, "View legend closed", showLegend=True,
                            legendCollapsed=True, legendSize="compact"))
    legend = page.get_by_test_id("map-legend")
    expect(legend).to_have_attribute("data-size", "compact", timeout=20000)
    expect(legend).not_to_have_attribute("open", "")
    legend.locator("summary").click()
    expect(legend.get_by_test_id("map-legend-entry")).to_have_text("Objects")


def test_no_legend_unless_asked(page, api, sites) -> None:
    open_module(page, build(api, sites, "View no legend"))
    expect(pin(page, "London")).to_be_visible(timeout=20000)
    expect(page.get_by_test_id("map-legend")).to_have_count(0)


def test_the_selection_panel_shows_one_objects_details_or_a_list(page, api, sites) -> None:
    open_module(page, build(api, sites, "View selection", selectedVariable="v_sel",
                            showSelectionPanel=True, selected=[
                                {"property": "$primary_key", "op": "in", "value": ["PAR"]}]))
    details = page.get_by_test_id("map-selection-details")
    expect(details).to_contain_text("Paris", timeout=20000)
    expect(details.get_by_test_id("map-selection-property").filter(has_text="name")).to_contain_text("Paris")
    expect(details).not_to_contain_text("[object Object]")
    pin(page, "London").click()
    expect(page.get_by_test_id("map-selection-list").locator("li")).to_have_text(
        ["London", "Paris"])


def test_viewport_bounds_are_read_and_written(page, api, sites) -> None:
    """Bounds around Paris: the other two are outside the view. And the view
    taken is written back as a GeoJSON polygon."""
    open_module(page, build(api, sites, "View bounds", boundsVariable="v_bounds",
                            bounds=AROUND_PARIS))
    expect(note(page)).to_contain_text("2 of them outside the view", timeout=20000)
    expect(page.locator("p", has_text="bounds")).to_contain_text('"type":"Polygon"')


def test_the_view_it_takes_is_written_when_nothing_was_given(page, api, sites) -> None:
    open_module(page, build(api, sites, "View bounds out", boundsVariable="v_bounds"))
    expect(page.locator("p", has_text="bounds")).to_contain_text('"type":"Polygon"',
                                                                 timeout=20000)
    expect(note(page)).not_to_contain_text("outside the view")


def test_auto_zoom_fits_an_object_set(page, api, sites) -> None:
    open_module(page, build(api, sites, "View zoom set", autoZoom="set",
                            autoZoomSetVariable="v_nyc"))
    expect(note(page)).to_contain_text("2 of them outside the view", timeout=20000)


def test_auto_zoom_only_if_outside_leaves_a_set_already_in_view(page, api, sites) -> None:
    """Paris is in the first view, which fits every site, so the view stays."""
    open_module(page, build(api, sites, "View zoom inside", autoZoom="set",
                            autoZoomSetVariable="v_par", autoZoomOutsideOnly=True))
    expect(pin(page, "New York")).to_be_visible(timeout=20000)
    expect(note(page)).not_to_contain_text("outside the view")


def test_the_viewport_follows_an_object_set(page, api, sites) -> None:
    """Following is not auto zoom: "only if outside" is auto zoom's, so New
    York, in the first view already, is still zoomed to."""
    open_module(page, build(api, sites, "View follow", followSetVariable="v_nyc",
                            autoZoomOutsideOnly=True))
    expect(note(page)).to_contain_text("2 of them outside the view", timeout=20000)


def test_the_panel_sets_the_interface(page, api, sites) -> None:
    mod = build(api, sites, "View panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-showLegend").check()
    page.get_by_test_id("map-legendSize").select_option("compact")
    page.get_by_test_id("map-autoZoom").select_option("set")
    page.get_by_test_id("map-autoZoomSetVariable").select_option("v_nyc")
    page.get_by_test_id("map-boundsVariable").select_option("v_bounds")
    save(page)
    eventually(lambda: mod.definition()["layout"]["mp"]["props"],
               lambda p: (p.get("showLegend"), p.get("legendSize"), p.get("autoZoom"),
                          p.get("autoZoomSetVariable"), p.get("boundsVariable"))
               == (True, "compact", "set", "v_nyc", "v_bounds"),
               what="the interface options, saved")
