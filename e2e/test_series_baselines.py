"""p.592-593's baselines on the Object Table's series column, and the Metric
Card's numeric property one (§563).

    "There are three types of baseline: Static, Numeric property, and Time
     series property. … The Numeric property type means that the user can
     specify a numeric property of the object type feeding the widget, whose
     value for each object is used as the baseline for the corresponding
     series. … The Time series type means that the user can configure a time
     series summarizer to generate a unique baseline value for every
     series." (p.592-593)

S1 reads 10 to 40 and holds 25 people; S2 reads 900 twice and holds no count,
so its numeric property baseline is no line rather than one at zero.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

SENSORS = b"id,name,capacity\nS1,North sensor,25\nS2,South sensor,\n"
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,10\n"
    b"S1,2026-01-02T00:00:00,20\n"
    b"S1,2026-01-03T00:00:00,30\n"
    b"S1,2026-01-04T00:00:00,40\n"
    b"S2,2026-01-01T00:00:00,900\n"
    b"S2,2026-01-02T00:00:00,900\n"
)


@pytest.fixture(scope="module")
def sensors(api):
    mod = Module(api, "Series baselines")
    table = api.upload_csv(f"{mod.base}/datasets/upload", f"sensors_{mod.tag}", SENSORS)
    points = api.upload_csv(f"{mod.base}/datasets/upload", f"readings_{mod.tag}", READINGS)
    declared = api.call("POST", f"/workspaces/{mod.workspace_id}/object-types", {
        "api_name": f"sensor_{mod.tag}", "display_name": f"Sensor {mod.tag}",
        "properties": [
            {"api_name": "name", "display_name": "Name", "data_type": "string"},
            {"api_name": "capacity", "display_name": "Capacity", "data_type": "integer"},
            {"api_name": "readings", "display_name": "Readings", "data_type": "time_series"},
        ],
        "title_property": "name"})
    source = api.call("POST", f"{mod.base}/object-type-sources", {
        "object_type_id": declared["id"], "dataset_id": table["id"],
        "primary_key_column": "id",
        "column_mappings": {"name": "name", "capacity": "capacity", "id": "readings"}})
    api.call("PUT", f"{mod.base}/object-type-sources/{source['id']}/series", {
        "property_api_name": "readings", "dataset_id": points["id"], "key_column": "sensor_id",
        "timestamp_column": "taken_at", "value_column": "reading"})
    assert api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})["upserted"] == 2
    mod.sensor_type = declared["id"]
    return mod


def build(api, sensors, name: str, baselines=None, **card) -> Module:
    mod = Module(api, name, beside=sensors)
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_all", "columns": "name,readings", "pageSize": 25,
                "seriesBaselines": baselines}},
            "card": {"resolvedName": "CanvasMetricCard", "props": {
                "objectSetVariable": "v_all", "aggregation": "count", "label": "Sensors",
                "showVisualization": True, "seriesVariable": "v_series", **card}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sensors",
                      "object_set": object_set(sensors.sensor_type)},
            "v_picked": {"id": "v_picked", "kind": "single_object", "label": "Picked"},
            "v_series": {"id": "v_series", "kind": "time_series_set", "label": "Readings",
                         "derivation": {"transform": "object_series", "inputs": ["v_picked"],
                                        "config": {"property": "readings", "interval": "day",
                                                   "aggregate": "avg"}}},
        },
        "events": {"e_row": {"id": "e_row", "trigger": {"node": "tbl", "on": "row_select"},
                             "effects": [{"type": "set_variable",
                                          "config": {"variable": "v_picked", "from": "object"}}]}},
    })
    return mod


def baseline_of(page, name: str):
    row = page.locator("tr", has=page.get_by_text(name, exact=True))
    return row.get_by_test_id("series-spark-baseline")


def test_a_static_baseline_is_on_every_row(page, api, sensors) -> None:
    open_module(page, build(api, sensors, "Baseline static",
                            {"readings": {"kind": "static", "value": 15}}))
    expect(baseline_of(page, "North sensor")).to_have_attribute("data-value", "15", timeout=20000)
    expect(baseline_of(page, "South sensor")).to_have_attribute("data-value", "15")


def test_a_numeric_property_baseline_is_each_rows_own(page, api, sensors) -> None:
    open_module(page, build(api, sensors, "Baseline property",
                            {"readings": {"kind": "property", "property": "capacity"}}))
    expect(baseline_of(page, "North sensor")).to_have_attribute("data-value", "25", timeout=20000)
    # South holds no count: its line is drawn, with no baseline beside it.
    south = page.locator("tr", has=page.get_by_text("South sensor", exact=True))
    expect(south.get_by_test_id("series-spark")).to_be_visible()
    expect(baseline_of(page, "South sensor")).to_have_count(0)


def test_a_series_baseline_summarises_each_rows_series(page, api, sensors) -> None:
    open_module(page, build(api, sensors, "Baseline series",
                            {"readings": {"kind": "series", "summary": "max"}}))
    expect(baseline_of(page, "North sensor")).to_have_attribute("data-value", "40", timeout=20000)
    expect(baseline_of(page, "South sensor")).to_have_attribute("data-value", "900")


def test_no_baseline_unless_asked(page, api, sensors) -> None:
    open_module(page, build(api, sensors, "Baseline none"))
    north = page.locator("tr", has=page.get_by_text("North sensor", exact=True))
    expect(north.get_by_test_id("series-spark")).to_be_visible(timeout=20000)
    expect(baseline_of(page, "North sensor")).to_have_count(0)


def test_the_panel_sets_a_columns_baseline(page, api, sensors) -> None:
    mod = build(api, sensors, "Baseline panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object table").first.click()
    page.get_by_label("Baseline for readings").select_option("property")
    expect(page.get_by_label("Baseline property for readings")).to_have_value("capacity")
    page.get_by_label("Baseline for readings").select_option("static")
    page.get_by_label("Baseline value for readings").fill("12")
    save(page)
    eventually(lambda: mod.definition()["layout"]["tbl"]["props"].get("seriesBaselines"),
               lambda b: b == {"readings": {"kind": "static", "value": 12}},
               what="the column's baseline, saved")


def test_the_metric_card_baseline_is_its_objects_property(page, api, sensors) -> None:
    open_module(page, build(api, sensors, "Baseline card", baselineKind="property",
                            baselineProperty="capacity"))
    page.locator("tr", has=page.get_by_text("North sensor", exact=True)).first.click()
    expect(page.get_by_test_id("metric-spark-line-baseline")).to_have_attribute(
        "data-value", "25", timeout=20000)
