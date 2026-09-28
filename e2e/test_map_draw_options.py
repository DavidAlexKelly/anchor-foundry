"""p.301's Draw options and drawn shape style on the Map (§573).

> "Draw options: Configure which shape drawing tools will be available in the
> toolbar. Drawn shape colors: Configure the color of drawn shapes on the map.
> Drawn shape opacity: Configure the opacity of drawn shapes on the map."
> (p.301)
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import open_builder, open_module, save, settled
from test_map_area import build, pin, rows_are, sites  # noqa: F401

TOOLS = {"rectangle": "map-select-area", "polygon": "map-draw-shape", "circle": "map-draw-circle",
         "line": "map-draw-line"}
LONDON = {"property": "where", "op": "within_distance",
          "value": {"lat": 51.5, "lon": -0.1, "radius": 50_000}}


def tools_shown(page) -> set[str]:
    return {tool for tool, testid in TOOLS.items() if page.get_by_test_id(testid).count()}


def test_a_map_offers_only_the_tools_it_names(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map draw circles", drawOptions=["circle"]))
    expect(pin(page, "London")).to_be_visible()
    expect(page.get_by_test_id("map-draw-circle")).to_be_visible()
    assert tools_shown(page) == {"circle"}


def test_a_map_saved_before_the_choice_offers_every_tool(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map draw all"))
    expect(page.get_by_test_id("map-draw-circle")).to_be_visible()
    assert tools_shown(page) == set(TOOLS)


def test_a_map_with_no_tools_still_draws_and_clears_its_area(page, api, sites) -> None:
    """An area written by something else is still drawn and cleared, in the
    colour and fill opacity the map sets for drawn shapes."""
    mod = build(api, sites, "Map draw none", drawOptions=[],
                drawnShapeColor="#aa3300", drawnShapeOpacity=0.6)
    definition = mod.definition()
    definition["variables"]["v_area"]["default"] = [LONDON]
    mod.define(definition)
    open_module(page, mod)
    rows_are(page, ["LON"], "London, within the area its variable holds")
    area = page.get_by_test_id("map-area")
    expect(area).to_have_attribute("data-shape", "circle")
    expect(area).to_have_attribute("fill", "#aa3300")
    expect(area).to_have_attribute("stroke", "#aa3300")
    expect(area).to_have_attribute("fill-opacity", "0.6")
    assert tools_shown(page) == set()
    page.get_by_test_id("map-clear-area").click()
    rows_are(page, ["LON", "PAR", "MAD", "NYC"], "every site once cleared")


def test_the_panel_sets_the_tools_and_their_style(page, api, sites) -> None:
    mod = build(api, sites, "Map draw panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    rectangle = page.get_by_test_id("map-draw-option-rectangle")
    expect(rectangle).to_be_checked()
    rectangle.uncheck()
    expect(page.get_by_test_id("map-select-area")).to_have_count(0)
    page.get_by_test_id("map-drawn-color").fill("#aa3300")
    page.get_by_test_id("map-drawn-opacity").fill("0.6")
    save(page)
    props = mod.definition()["layout"]["mp"]["props"]
    assert props["drawOptions"] == ["polygon", "circle", "line"]
    assert props["drawnShapeColor"] == "#aa3300"
    assert props["drawnShapeOpacity"] == 0.6
