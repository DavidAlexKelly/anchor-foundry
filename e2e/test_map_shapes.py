"""p.301's single draw mode, and several shapes out of it (§640).

> "Enable single draw mode: Limit users to only draw one shape at a time on
> the map interface, automatically removing the previous shape when a new one
> is drawn." (p.301)

A map in single draw mode, which is every map saved before the choice, keeps
the shape drawn last. Out of it each shape joins the others, and the objects
inside any of them are selected, through §639's `within_any`: a circle round
London and Paris and another round Madrid select those three, and not New
York.
"""
from __future__ import annotations

import json

from playwright.sync_api import expect

from conftest import eventually, open_builder, open_module, save, settled
from test_map_area import pin, rows_are, sites  # noqa: F401
from test_map_drawn_shapes import ALL, SHAPE, build, drag_circle, shapes_box

# Madrid, and nothing else.
AROUND_MADRID = {"type": "Polygon",
                 "coordinates": [[[-6, 38], [-1, 38], [-1, 42], [-6, 42], [-6, 38]]]}
BOTH = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": SHAPE, "properties": {"shape": "polygon"}},
    {"type": "Feature", "geometry": AROUND_MADRID, "properties": {"shape": "polygon"}},
]}


def circle_round(page, name: str, px: float = 12) -> None:
    """A small circle round one pin: a drag from it out a few pixels."""
    b = pin(page, name).bounding_box()
    page.get_by_test_id("map-draw-circle").click()
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + px, y + px, steps=5)
    page.mouse.up()


def written(page, count: int) -> list[dict]:
    text = eventually(lambda: shapes_box(page).input_value(),
                      lambda got: got.startswith("{") and len(json.loads(got)["features"]) == count,
                      what=f"{count} shapes as GeoJSON")
    return json.loads(text)["features"]


def test_out_of_single_draw_mode_each_shape_joins_the_rest(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map several", events=True, singleDrawMode=False))
    expect(pin(page, "London")).to_be_visible()
    drag_circle(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris, within the first circle")
    circle_round(page, "Madrid")
    rows_are(page, ["LON", "PAR", "MAD"], "inside either circle")
    expect(page.get_by_test_id("map-area")).to_have_count(2)
    features = written(page, 2)
    assert [f["properties"]["shape"] for f in features] == ["circle", "circle"]
    # p.301's On drawn shape: `{{value}}` is the shape just drawn, not all of them.
    latest = json.dumps({"type": "FeatureCollection", "features": [features[1]]},
                        separators=(",", ":"))
    expect(page.get_by_text(f"drawn: [{latest}]")).to_be_visible()
    # Clearing clears them all.
    expect(page.get_by_test_id("map-clear-area")).to_have_text("Clear 2 areas")
    page.get_by_test_id("map-clear-area").click()
    rows_are(page, ALL, "every site once cleared")
    expect(page.get_by_test_id("map-area")).to_have_count(0)
    expect(shapes_box(page)).to_have_value("")


def test_in_single_draw_mode_a_new_shape_replaces_the_last(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map single"))
    expect(pin(page, "London")).to_be_visible()
    drag_circle(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris, within the first circle")
    circle_round(page, "Madrid")
    rows_are(page, ["MAD"], "Madrid alone, the first circle gone")
    expect(page.get_by_test_id("map-area")).to_have_count(1)
    written(page, 1)
    expect(page.get_by_test_id("map-clear-area")).to_have_text("Clear area")


def test_several_shapes_written_elsewhere_are_all_drawn(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map several in", singleDrawMode=False))
    rows_are(page, ALL, "every site before a shape")
    shapes_box(page).fill(json.dumps(BOTH))
    rows_are(page, ["LON", "PAR", "MAD"], "inside either shape typed in")
    expect(page.get_by_test_id("map-area")).to_have_count(2)


def test_single_draw_mode_draws_the_first_shape_written(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map single in"))
    rows_are(page, ALL, "every site before a shape")
    shapes_box(page).fill(json.dumps(BOTH))
    rows_are(page, ["LON", "PAR"], "inside the first shape alone")
    expect(page.get_by_test_id("map-area")).to_have_count(1)


def test_the_panel_turns_single_draw_mode_off(page, api, sites) -> None:
    mod = build(api, sites, "Map single panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    toggle = page.get_by_test_id("map-single-draw")
    expect(toggle).to_be_checked()
    toggle.uncheck()
    save(page)
    assert mod.definition()["layout"]["mp"]["props"]["singleDrawMode"] is False


def test_each_shape_is_measured(page, api, sites) -> None:
    """p.302's measurements, on every shape drawn and not only the first."""
    open_module(page, build(api, sites, "Map several measured", singleDrawMode=False,
                            enableMeasurements=True))
    expect(pin(page, "London")).to_be_visible()
    drag_circle(page, "London", "Paris")
    circle_round(page, "Madrid")
    expect(page.get_by_test_id("map-area")).to_have_count(2)
    area_labels = page.locator("[data-testid='map-measure'][data-kind='area']")
    expect(area_labels).to_have_count(2)
