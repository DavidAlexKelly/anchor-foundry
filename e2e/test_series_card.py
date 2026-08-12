"""A prominent time series, drawn (parity `ontology.md` §4.1; Foundry
`object-views` p.11).

    "Objects with prominent … properties will render on a Map." — the same
    sentence's other half, for a series: the property type says what this *is*,
    so the standard Object View draws it rather than printing the series id.

The API tests prove the points come back. What needs a browser is that they
reach a chart: an SVG with a path in it, on the object, without anybody
configuring anything.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

SENSORS = [{"id": "S1", "name": "North sensor"}, {"id": "S2", "name": "South sensor"}]
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,10\n"
    b"S1,2026-01-02T00:00:00,20\n"
    b"S1,2026-01-03T00:00:00,15\n"
    b"S2,2026-01-01T00:00:00,99\n"
)


@pytest.fixture(scope="module")
def module(api):
    """A sensor type whose `readings` property is prominent and time series.

    Built directly rather than through `Module.object_type`, because the one
    thing this fixture needs is the one thing that helper cannot express: the
    **primary key column mapped to the series property as well**. The series id
    is the instance's own key - the ordinary case decision 0009 describes - and
    a mapping of `{column: same-named property}` has nowhere to say so.

    The readings live in their own dataset and are never copied anywhere,
    which is what makes this a chart of the data rather than of a copy of it.
    """
    mod = Module(api, "Series card")
    sensors = api.upload_csv(
        f"{mod.base}/datasets/upload", f"sensors_{mod.tag}",
        b"id,name\nS1,North sensor\nS2,South sensor\n",
    )
    points = api.upload_csv(f"{mod.base}/datasets/upload", f"readings_{mod.tag}", READINGS)

    declared = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"sensor_{mod.tag}",
            "display_name": f"Sensor {mod.tag}",
            "properties": [
                {"api_name": "name", "display_name": "Name", "data_type": "string"},
                {"api_name": "readings", "display_name": "Readings",
                 "data_type": "time_series", "visibility": "prominent"},
            ],
            "title_property": "name",
        },
    )
    mod.object_type_id = declared["id"]

    source = api.call(
        "POST", f"{mod.base}/object-type-sources",
        {
            "object_type_id": mod.object_type_id,
            "dataset_id": sensors["id"],
            "primary_key_column": "id",
            # `id` twice: once as the key, once as the series id the points are
            # matched on. That is the mapping this whole fixture exists for.
            "column_mappings": {"name": "name", "id": "readings"},
        },
    )
    api.call(
        "PUT", f"{mod.base}/object-type-sources/{source['id']}/series",
        {
            "property_api_name": "readings",
            "dataset_id": points["id"],
            "key_column": "sensor_id",
            "timestamp_column": "taken_at",
            "value_column": "reading",
        },
    )
    synced = api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})
    assert synced["upserted"] == len(SENSORS), synced
    mod.source_id = source["id"]
    return mod


def open_first_sensor(page, module):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(SENSORS),
               what="this type's sensors, and only this type's")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()


def test_a_prominent_time_series_renders_a_chart(page, module):
    """p.11's rendering, for the type it was blocked on until decision 0009."""
    open_first_sensor(page, module)
    card = page.get_by_test_id("sov-series-readings")
    expect(card).to_be_visible()
    # **A path, not just an `<svg>`.** An empty chart element would pass the
    # weaker check and is exactly the failure this is most likely to have.
    eventually(lambda: card.locator("path").count(), lambda n: n >= 1,
               what="the drawn series line")
    assert card.locator("path").first.get_attribute("d").startswith("M")


def test_the_chart_says_what_it_drew(page, module):
    """A curve with no numbers on it is a shape. The range and the count are
    what make it a reading of the data."""
    open_first_sensor(page, module)
    card = page.get_by_test_id("sov-series-readings")
    eventually(lambda: card.inner_text(), lambda t: "readings" in t,
               what="the count and range under the line")


def test_the_series_is_not_drawn_as_a_property_row(page, module):
    """It is prominent, so it belongs in the cards above rather than as a value
    in the table - and printing the series id in a cell would be showing the
    key instead of the thing."""
    open_first_sensor(page, module)
    expect(page.get_by_test_id("sov-prominent").locator("[data-property='readings']")).to_be_visible()
    expect(page.get_by_test_id("sov-normal").locator("[data-property='readings']")).to_have_count(0)
