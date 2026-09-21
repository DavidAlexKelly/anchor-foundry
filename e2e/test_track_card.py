"""A prominent geotemporal series, drawn on a Map (§427; `object-views` p.11;
`object-link-types` p.127).

> "Objects with prominent geohash, geoshape, or **geotemporal series reference
>  (GTSR)** properties will render on a Map."

The mapping's refusals and the track query are
`apps/api/tests/test_time_series.py`'s; the projection is
`apps/web/src/components/canvas/map-shapes.test.ts`'s. What needs a browser is
the seam across all of it: that a property holding nothing but a series *id*
draws a line through places the object has been — a dataset read, a
coercion, a LineString and a projection, none of which any one test can see
the far end of.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

VEHICLES = b"id,name\nV1,North van\nV2,South van\n"
#: "lat,lon" text, which is what a CSV column holds — and one deliberate piece
#: of nonsense, so "reported, never hidden" has something to report.
FIXES = (
    b'vehicle_id,seen_at,position\n'
    b'V1,2026-01-01T00:00:00,"51.5,-0.12"\n'
    b'V1,2026-01-01T01:00:00,"52.0,-0.60"\n'
    b'V1,2026-01-01T02:00:00,"52.5,-1.12"\n'
    b'V1,2026-01-01T03:00:00,banana\n'
    b'V2,2026-01-01T00:00:00,"10.0,10.0"\n'
)


@pytest.fixture(scope="module")
def module(api):
    """A van type whose `trail` property is prominent and a geotemporal series.

    Built directly rather than through `Module.object_type` for the reason
    `test_series_card` writes down: the primary key column is mapped to the
    series property as well, which is decision 0009's ordinary case and the
    one thing that helper cannot express.
    """
    mod = Module(api, "Track card")
    vans = api.upload_csv(
        f"{mod.base}/datasets/upload", f"vans_{mod.tag}", VEHICLES,
    )
    points = api.upload_csv(f"{mod.base}/datasets/upload", f"fixes_{mod.tag}", FIXES)

    declared = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"van_{mod.tag}",
            "display_name": f"Van {mod.tag}",
            "properties": [
                {"api_name": "name", "display_name": "Name", "data_type": "string"},
                {"api_name": "trail", "display_name": "Trail",
                 "data_type": "geotemporal_series", "visibility": "prominent"},
            ],
            "title_property": "name",
        },
    )
    mod.object_type_id = declared["id"]

    source = api.call(
        "POST", f"{mod.base}/object-type-sources",
        {
            "object_type_id": mod.object_type_id,
            "dataset_id": vans["id"],
            "primary_key_column": "id",
            "column_mappings": {"name": "name", "id": "trail"},
        },
    )
    api.call(
        "PUT", f"{mod.base}/object-type-sources/{source['id']}/series",
        {
            "property_api_name": "trail",
            "dataset_id": points["id"],
            "key_column": "vehicle_id",
            "timestamp_column": "seen_at",
            "point_column": "position",
        },
    )
    synced = api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})
    assert synced["upserted"] == 2, synced
    mod.source_id = source["id"]
    return mod


def open_first_van(page, module):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 2,
               what="this type's vans, and only this type's")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()


def test_a_prominent_geotemporal_series_renders_a_map(page, module):
    """p.11's sentence, on the card. The property holds a series id and
    nothing else; everything on screen came from a dataset read."""
    open_first_van(page, module)
    card = page.get_by_test_id("sov-track-trail")
    expect(card).to_be_visible(timeout=30000)
    # A line through the places it has been — §426's renderer, so the track is
    # a geometry like any other and the projection has one implementation.
    expect(card.locator("[data-testid='map-shape-trail']")).to_have_count(1)


def test_the_track_is_a_line_and_not_an_area(page, module):
    """A LineString, which is what a sequence of positions *is*. Filled, it
    would be a polygon claiming the van went round the edge of a region."""
    open_first_van(page, module)
    line = page.get_by_test_id("sov-track-trail").locator("[data-testid='map-shape-trail']")
    expect(line).to_have_count(1)
    assert line.get_attribute("fill") == "none", line.get_attribute("fill")


def test_the_latest_position_gets_a_pin(page, module):
    """"Where is it now" is the question a card-sized map is usually asked,
    and a line alone does not answer it — both ends look the same."""
    open_first_van(page, module)
    card = page.get_by_test_id("sov-track-trail")
    expect(card.locator("circle")).not_to_have_count(0)


def test_the_line_ends_where_the_pin_is(page, module):
    """**The coordinate-order check, and the only one that can catch it.**

    A track arrives with named `lat`/`lon` fields and a GeoJSON LineString
    takes a positional `[lon, lat]` — named on one side, positional on the
    other, which is exactly where this gets reversed (§425). A swapped pair is
    still a valid position, so nothing refuses it and the line still draws;
    it draws in the wrong hemisphere.

    The pin is built from the named fields and the line from the positional
    pair, so **the two disagree the moment the order is wrong** — and the last
    point of the line is the same fix the pin marks. A sweep found this: every
    other check here passed with the axes swapped.
    """
    open_first_van(page, module)
    card = page.get_by_test_id("sov-track-trail")
    expect(card).to_be_visible(timeout=30000)
    line = card.locator("[data-testid='map-shape-trail']").bounding_box()
    pin = card.locator("circle").first.bounding_box()
    assert line is not None and pin is not None
    pin_x = pin["x"] + pin["width"] / 2
    pin_y = pin["y"] + pin["height"] / 2
    # The pin sits on the line's own box rather than somewhere else on the
    # map. A few pixels of slack, because a pin has a radius and a stroke has
    # a width; a swapped pair moves it by most of the canvas.
    assert line["x"] - 6 <= pin_x <= line["x"] + line["width"] + 6, (line, pin)
    assert line["y"] - 6 <= pin_y <= line["y"] + line["height"] + 6, (line, pin)


def test_an_unreadable_position_is_reported_rather_than_hidden(page, module):
    """**The map's own rule, one value type along.** A track that silently
    dropped a bad reading would draw a straight line across the gap as though
    nothing had happened — which is a claim about where the van went."""
    open_first_van(page, module)
    note = page.get_by_test_id("sov-track-trail").locator(".canvas-map-note")
    expect(note).to_contain_text("without a usable location")


def test_a_van_with_one_position_gets_a_pin_and_no_line(page, module):
    """The honest drawing of a single fix: a LineString of one point draws
    nothing at all, and a card showing an empty map for an object with a known
    location would be worse than one showing the location.

    `V2` is the second row, and it has exactly one fix.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 2, what="both vans")
    rows.nth(1).get_by_role("button", name="Explore").click()
    card = page.get_by_test_id("sov-track-trail")
    expect(card).to_be_visible(timeout=30000)
    expect(card.locator("[data-testid='map-shape-trail']")).to_have_count(0)
    expect(card.locator("circle")).not_to_have_count(0)
