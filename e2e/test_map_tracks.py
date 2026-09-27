"""Tracks on the Workshop Map, with p.303's timeline (§557).

    "Enable timeline: Display the timeline open button at the bottom of the
     map interface. … Selected time: Control the selected time using a
     Workshop variable of type Timestamp or Date." (p.303)

Two vehicles: V1 moves at midnight and one o'clock, V2 only from two. At
half past midnight V1 is on the map and V2 is nowhere yet; with no time
selected ("View latest") both stand at their last fixes. Each track is drawn
as a line. Positions and the time arithmetic are `map-tracks.test.ts`; the
batch read is `apps/api/tests/test_time_series.py`.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

VEHICLES = b"id,name\nV1,Van one\nV2,Van two\n"
FIXES = (
    b"vehicle_id,seen_at,position\n"
    b'V1,2026-01-01T00:00:00,"51.5,-0.12"\n'
    b'V1,2026-01-01T01:00:00,"52.5,-1.12"\n'
    b'V2,2026-01-01T02:00:00,"48.85,2.35"\n'
    b'V2,2026-01-01T03:00:00,"48.0,3.0"\n'
)
HALF_PAST_MIDNIGHT = "2026-01-01T00:30:00Z"


@pytest.fixture(scope="module")
def fleet(api):
    mod = Module(api, "Map tracks")
    vehicles = api.upload_csv(f"{mod.base}/datasets/upload", f"vehicles_{mod.tag}", VEHICLES)
    fixes = api.upload_csv(f"{mod.base}/datasets/upload", f"fixes_{mod.tag}", FIXES)
    declared = api.call("POST", f"/workspaces/{mod.workspace_id}/object-types", {
        "api_name": f"vehicle_{mod.tag}", "display_name": f"Vehicle {mod.tag}",
        "properties": [
            {"api_name": "name", "display_name": "Name", "data_type": "string"},
            {"api_name": "trail", "display_name": "Trail", "data_type": "geotemporal_series"},
        ],
        "title_property": "name"})
    source = api.call("POST", f"{mod.base}/object-type-sources", {
        "object_type_id": declared["id"], "dataset_id": vehicles["id"],
        "primary_key_column": "id", "column_mappings": {"name": "name", "id": "trail"}})
    api.call("PUT", f"{mod.base}/object-type-sources/{source['id']}/series", {
        "property_api_name": "trail", "dataset_id": fixes["id"], "key_column": "vehicle_id",
        "timestamp_column": "seen_at", "point_column": "position"})
    assert api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})["upserted"] == 2
    mod.vehicle_type = declared["id"]
    return mod


def build(api, fleet, name: str, **props) -> Module:
    mod = Module(api, name, beside=fleet)
    mod.define({
        "format": 2,
        "layout": layout({"mp": {"resolvedName": "CanvasMap", "props": {
            "source": "objects", "objectSetVariable": "v_all", "labelProperty": "name",
            "trackProperty": "trail", "enableTimeline": True, **props}}}),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Vehicles",
                      "object_set": object_set(fleet.vehicle_type)},
            "v_time": {"id": "v_time", "kind": "timestamp", "label": "Time",
                       "default": HALF_PAST_MIDNIGHT},
        },
        "events": {},
    })
    return mod


def pin(page, name: str):
    return page.locator("svg[aria-label='Map'] circle",
                        has=page.locator("title", has_text=name))


def test_with_no_time_selected_every_vehicle_is_at_its_last_fix(page, api, fleet) -> None:
    open_module(page, build(api, fleet, "Tracks latest"))
    expect(pin(page, "Van one")).to_have_count(1, timeout=20000)
    expect(pin(page, "Van two")).to_have_count(1)
    expect(page.get_by_test_id("map-timeline-time")).to_have_text("Latest")
    # p.302's breadcrumbs: both tracks drawn as lines under the pins.
    expect(page.locator("svg[aria-label='Map'] path", has=page.locator("title"))).to_have_count(2)


def test_a_selected_time_variable_places_the_vehicles_then(page, api, fleet) -> None:
    """Half past midnight: V1 has moved once, V2 has not appeared yet."""
    open_module(page, build(api, fleet, "Tracks at a time", selectedTimeVariable="v_time"))
    expect(pin(page, "Van one")).to_have_count(1, timeout=20000)
    expect(pin(page, "Van two")).to_have_count(0)
    expect(page.get_by_test_id("map-timeline-time")).to_have_text("2026-01-01T00:30:00Z")
    # Not unplaceable - only not anywhere yet, and said so.
    caption = page.locator(".canvas-block").first
    expect(caption).to_contain_text("1 with no position yet at this time")
    expect(caption).not_to_contain_text("without a usable location")
    # View latest lets the time go, and V2 arrives at its last fix.
    page.get_by_test_id("map-timeline-latest").click()
    expect(pin(page, "Van two")).to_have_count(1)
    expect(page.get_by_test_id("map-timeline-time")).to_have_text("Latest")


def test_the_slider_moves_the_selected_time(page, api, fleet) -> None:
    open_module(page, build(api, fleet, "Tracks slider"))
    expect(pin(page, "Van two")).to_have_count(1, timeout=20000)
    slider = page.get_by_test_id("map-timeline-slider")
    # Midnight, the start of the span: only V1 had a fix.
    slider.evaluate("""(el) => {
        const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        set.call(el, el.min);
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }""")
    expect(page.get_by_test_id("map-timeline-time")).to_have_text("2026-01-01T00:00:00Z")
    expect(pin(page, "Van two")).to_have_count(0)
    expect(pin(page, "Van one")).to_have_count(1)


def test_the_panel_sets_the_track_and_the_timeline(page, api, fleet) -> None:
    mod = build(api, fleet, "Tracks panel", trackProperty=None, enableTimeline=False)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Map").first.click()
    page.get_by_test_id("map-track-property").select_option("trail")
    page.get_by_test_id("map-enable-timeline").check()
    page.get_by_test_id("map-selected-time").select_option("v_time")
    save(page)
    eventually(lambda: mod.definition()["layout"]["mp"]["props"],
               lambda p: (p.get("trackProperty"), p.get("enableTimeline"),
                          p.get("selectedTimeVariable")) == ("trail", True, "v_time"),
               what="the track, the timeline and the selected time, saved")
