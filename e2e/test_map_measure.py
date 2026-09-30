"""p.302's measurements of a shape drawn on the Map (§575).

> "Enable measurements: Allow users to view the measurements of their drawn
> shapes. … Enable polygon perimeter: Show the length of each segment or the
> total perimeter length along a drawn polygon's edges. Enable polygon area:
> Show the polygon's area in the center of the drawn polygon." (p.302)

The figures themselves are `map-measure.test.ts`'s; here, that a drawn
shape shows them and a map that has not asked for them does not.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from conftest import open_builder, open_module, save, settled
from test_map_area import build, drag_around, pin, rows_are, sites  # noqa: F401

LENGTH = re.compile(r"^[\d,.]+ k?m$")
AREA = re.compile(r"^[\d,.]+ (m|km)²$")


def labels(page, kind: str):
    return page.locator(f"[data-testid='map-measure'][data-kind='{kind}']")


def draw_box(page) -> None:
    expect(pin(page, "London")).to_be_visible()
    page.get_by_test_id("map-select-area").click()
    drag_around(page, "London", "Paris")
    rows_are(page, ["LON", "PAR"], "London and Paris")


def test_a_drawn_shape_shows_its_area_and_perimeter(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map measure total", enableMeasurements=True))
    draw_box(page)
    expect(labels(page, "area")).to_have_count(1)
    expect(labels(page, "area")).to_have_text(AREA)
    expect(labels(page, "perimeter")).to_have_count(1)
    expect(labels(page, "perimeter")).to_have_text(LENGTH)
    expect(labels(page, "segment")).to_have_count(0)
    page.get_by_test_id("map-clear-area").click()
    expect(page.get_by_test_id("map-measure")).to_have_count(0)


def test_each_segment_instead_of_the_total(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map measure segments", enableMeasurements=True,
                            perimeterMode="segments", measureArea=False))
    draw_box(page)
    expect(labels(page, "segment")).to_have_count(4)
    for n in range(4):
        expect(labels(page, "segment").nth(n)).to_have_text(LENGTH)
    expect(labels(page, "area")).to_have_count(0)
    expect(labels(page, "perimeter")).to_have_count(0)


def test_a_map_that_has_not_asked_shows_none(page, api, sites) -> None:
    open_module(page, build(api, sites, "Map measure off"))
    draw_box(page)
    expect(page.get_by_test_id("map-area")).to_be_visible()
    expect(page.get_by_test_id("map-measure")).to_have_count(0)


def test_the_panel_turns_them_on(page, api, sites) -> None:
    mod = build(api, sites, "Map measure panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-measure-enabled").check()
    page.get_by_test_id("map-measure-perimeter-mode").select_option("segments")
    page.get_by_test_id("map-measure-area").uncheck()
    save(page)
    props = mod.definition()["layout"]["mp"]["props"]
    assert props["enableMeasurements"] is True
    assert props["perimeterMode"] == "segments"
    assert props["measureArea"] is False
    assert props["measurePerimeter"] is True
