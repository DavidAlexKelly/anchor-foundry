"""A prominent geoshape renders on a Map (§426; `object-views` p.11).

> "Geospatial properties: Objects with prominent geohash, **geoshape**, or
>  geotemporal series reference (GTSR) properties will render on a Map."

§425 gave this platform the type; this is the rendering p.11 asks for, and the
claim §425's parity row left open. The projection is pure and unit-tested in
`apps/web/src/components/canvas/map-shapes.test.ts`. What needs a browser is
the part no unit test can reach: that a geoshape on a card **draws a map** at
all rather than the table summary, that the outline is in it, and that the map
opens fitted to the shape rather than on the whole world with a speck in it.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

#: A square over southern England, and a line across it. Both are real
#: geometries rather than `[0,0]` boxes, so "fitted to the data" is a claim
#: with somewhere to be wrong.
SQUARE = json.dumps({
    "type": "Polygon",
    "coordinates": [[[-1.0, 51.0], [0.5, 51.0], [0.5, 52.0], [-1.0, 52.0], [-1.0, 51.0]]],
})
ROUTE = json.dumps({
    "type": "LineString",
    "coordinates": [[-1.0, 51.0], [0.5, 52.0]],
})


@pytest.fixture(scope="module")
def module(api):
    """One object type with a prominent geoshape and a prominent geopoint, so
    the two renderings sit side by side and neither can be mistaken for the
    other's doing."""
    mod = Module(api, "Geoshape map")
    mod.object_type(
        columns=["id", "name", "outline", "route", "where"],
        rows=[{
            "id": "P1", "name": "Alpha parcel",
            "outline": SQUARE, "route": ROUTE, "where": "51.5,-0.12",
        }],
        key="id",
        title="name",
        types={"outline": "geoshape", "route": "geoshape", "where": "geopoint"},
        visibility={"name": "prominent", "outline": "prominent",
                    "route": "prominent", "where": "prominent"},
    )
    return mod


def open_the_object(page, module):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 1, what="this type's object")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()


def test_a_prominent_geoshape_gets_a_map(page, module):
    """p.11's sentence, on the card. **A stronger case than the geopoint's**:
    a coordinate pair can at least be read, while a polygon's coordinates are
    a paragraph nobody reads at all."""
    open_the_object(page, module)
    expect(page.get_by_test_id("sov-map-outline")).to_be_visible()
    # And the outline is in it, not just a map of nothing.
    expect(page.locator("[data-testid='map-shape-outline']")).to_have_count(1)


def test_a_line_draws_as_a_line_and_an_area_as_an_area(page, module):
    """The two renderings a geometry type decides between: a polygon encloses
    and a line does not, and a line drawn filled is a shape nobody meant."""
    open_the_object(page, module)
    area = page.locator("[data-testid='map-shape-outline']")
    line = page.locator("[data-testid='map-shape-route']")
    expect(area).to_have_count(1)
    expect(line).to_have_count(1)
    assert area.get_attribute("fill") != "none", area.get_attribute("fill")
    assert line.get_attribute("fill") == "none", line.get_attribute("fill")


def test_the_map_says_how_many_shapes_it_drew(page, module):
    """The map's own rule, one value type along: what is on it is counted, so
    "no shape here" cannot be mistaken for "the map is empty"."""
    open_the_object(page, module)
    note = page.get_by_test_id("sov-map-outline").locator(".canvas-map-note")
    expect(note).to_contain_text("1 shape")


def test_the_map_opens_fitted_to_the_shape(page, module):
    """**Without this the map opens on the whole world with the polygon a
    speck in it, and "Fit to data" does nothing** — because the fit is
    computed from the pins, and a shape-only map has none.

    **Asserted as a fraction of the canvas, not in pixels.** The card's map is
    scaled by CSS to fit the card, so a pixel count is a claim about the
    layout rather than about the view — and the first version of this test
    passed only because §426 was drawing the shape through the basemap's
    transform as well as its own, which made it several canvases wide. §427's
    track test found that; this one now measures what it meant to.

    At the fitted view a square 1.5 degrees across is about a tenth of the
    canvas; on a world view it is four thousandths. Three per cent sits well
    clear of both.
    """
    open_the_object(page, module)
    shape = page.locator("[data-testid='map-shape-outline']").bounding_box()
    canvas = page.get_by_test_id("sov-map-outline").locator("svg").bounding_box()
    assert shape is not None and canvas is not None
    assert shape["width"] / canvas["width"] > 0.03, (shape, canvas)
    assert shape["height"] / canvas["height"] > 0.03, (shape, canvas)
    # And not the whole canvas, which is what a *failed* fit looks like from
    # the other side — a view zoomed so far in that the shape fills it.
    assert shape["width"] / canvas["width"] < 0.9, (shape, canvas)


def test_a_geopoint_still_gets_its_pin(page, module):
    """The negative control for the change: the geopoint card is the one that
    already worked, and a shape layer that had taken its place would look like
    a working feature."""
    open_the_object(page, module)
    expect(page.get_by_test_id("sov-map-where")).to_be_visible()
    # A pin, not a shape — the two cards draw different things.
    expect(page.get_by_test_id("sov-map-where")
           .locator("[data-testid^='map-shape-']")).to_have_count(0)
    expect(page.get_by_test_id("sov-map-where").locator("circle")).not_to_have_count(0)
