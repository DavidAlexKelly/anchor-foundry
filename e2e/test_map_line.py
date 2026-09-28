"""p.301's drawn line and p.302's line measurements on the Map (§634).

> "Enable line measurements: Show either individual segment lengths or the
> total length of a drawn line" (p.302)

A line encloses nothing, so it selects nothing: it is drawn, measured, and
written to Drawn shapes as a LineString. The GeoJSON and the lengths are
`map-drawn.test.ts` and `map-measure.test.ts`; here, that the tool draws one
from clicks, that the variable holds it, and that it and an area replace
each other, one drawn shape at a time.
"""
from __future__ import annotations

import json
import re

from playwright.sync_api import expect

from conftest import eventually, open_module
from test_map_area import drag_around, pin, rows_are, sites  # noqa: F401
from test_map_drawn_shapes import ALL, build, shapes_box

LENGTH = re.compile(r"^[\d,.]+ k?m$")


def click_near(page, name: str, *, double: bool = False) -> None:
    """Beside a pin rather than on it, so the click is the map's and not the
    pin's."""
    box = pin(page, name).bounding_box()
    assert box, name
    x, y = box["x"] + box["width"] / 2 + 12, box["y"] + box["height"] / 2 + 12
    if double:
        page.mouse.dblclick(x, y)
    else:
        page.mouse.click(x, y)


def draw_line(page) -> None:
    expect(pin(page, "London")).to_be_visible(timeout=20000)
    page.get_by_test_id("map-draw-line").click()
    expect(page.get_by_test_id("map-draw-line")).to_have_attribute("aria-pressed", "true")
    click_near(page, "Madrid")
    click_near(page, "Paris")
    click_near(page, "London", double=True)


def test_a_line_is_drawn_measured_and_written(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map line", enableMeasurements=True,
                            lineMode="segments", events=True))
    draw_line(page)
    expect(page.get_by_test_id("map-line")).to_be_visible()
    # Two segments, each measured, and nothing selected by a line.
    segments = page.locator("[data-testid='map-measure'][data-kind='segment']")
    expect(segments).to_have_count(2)
    expect(segments.first).to_have_text(LENGTH)
    rows_are(page, ALL, "every site: a line selects nothing")
    written = eventually(lambda: shapes_box(page).input_value(), lambda v: "LineString" in v,
                         what="the line in Drawn shapes")
    feature = json.loads(written)["features"][0]
    assert feature["properties"] == {"shape": "line"}
    assert len(feature["geometry"]["coordinates"]) == 3
    # On drawn shape fires for a line too.
    expect(page.get_by_text("drawn: [")).to_contain_text("LineString")

    page.get_by_test_id("map-clear-line").click()
    expect(page.get_by_test_id("map-line")).to_have_count(0)
    expect(shapes_box(page)).to_have_value("")


def test_the_total_length_at_the_end(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map line total", enableMeasurements=True))
    draw_line(page)
    expect(page.locator("[data-testid='map-measure'][data-kind='length']")).to_have_count(1)
    expect(page.locator("[data-testid='map-measure'][data-kind='segment']")).to_have_count(0)


def test_a_line_and_an_area_replace_each_other(page, api, sites) -> None:
    """One drawn shape at a time: a line clears the area, so the rows come
    back, and an area clears the line."""
    open_module(page, build(api, sites, "Map line and area"))
    expect(pin(page, "London")).to_be_visible(timeout=20000)
    page.get_by_test_id("map-select-area").click()
    drag_around(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris")
    draw_line(page)
    rows_are(page, ALL, "every site once the line replaced the area")
    expect(page.get_by_test_id("map-area")).to_have_count(0)
    # And the line stays: the area going is not the drawn shapes emptying.
    expect(page.get_by_test_id("map-line")).to_be_visible()
    eventually(lambda: shapes_box(page).input_value(), lambda v: "LineString" in v,
               what="the line in Drawn shapes after the area")
    page.get_by_test_id("map-select-area").click()
    drag_around(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris again")
    expect(page.get_by_test_id("map-line")).to_have_count(0)
    eventually(lambda: shapes_box(page).input_value(), lambda v: "Polygon" in v,
               what="the area in Drawn shapes")


def test_a_line_written_elsewhere_is_drawn(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map line in"))
    expect(pin(page, "London")).to_be_visible(timeout=20000)
    shapes_box(page).fill(json.dumps(
        {"type": "LineString", "coordinates": [[-3.7, 40.4], [2.35, 48.85]]}))
    expect(page.get_by_test_id("map-line")).to_be_visible()
    rows_are(page, ALL, "every site: a line selects nothing")
