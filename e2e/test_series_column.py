"""p.583's time series column in the Object table (parity `workshop.md` §10,
`ontology.md` §1.1; Foundry p.582-583).

> "This object is displayed in a Workshop Object table widget… The Object table
> widget is configured to display two visualizations for each time series: the
> latest value of the time series on the left, and a sparkline showing the
> history of the time series on the right." (p.583)

The geometry is checked directly in
`apps/web/src/components/canvas/sparkline.test.ts` and the batch read in
`apps/api/tests/test_time_series.py`. What needs a browser is the seam: that a
table of *several* rows draws each row's own history from one read, that a
`time_series` column stops showing the opaque series id it used to show, and
that a reading the dataset does not have is a gap rather than a zero.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module

SENSORS = b"id,name\nS1,North sensor\nS2,South sensor\nS3,Patchy sensor\n"
# S1 rises to 40; S2 is flat at 900 (a flat series is the one that divides by a
# zero range if the band is missing); S3 has a single reading and then a null.
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,10\n"
    b"S1,2026-01-02T00:00:00,20\n"
    b"S1,2026-01-03T00:00:00,30\n"
    b"S1,2026-01-04T00:00:00,40\n"
    b"S2,2026-01-01T00:00:00,900\n"
    b"S2,2026-01-02T00:00:00,900\n"
    b"S3,2026-01-01T00:00:00,5\n"
    b"S3,2026-01-02T00:00:00,\n"
)


@pytest.fixture(scope="module")
def module(api):
    """A sensor type with a `time_series` property, in an Object table.

    Built directly rather than through `Module.object_type` for the reason
    `test_series_card.py` gives: the primary key column has to be mapped to
    the series property *as well* as being the key, and a mapping of
    `{column: same-named property}` has nowhere to say so.
    """
    mod = Module(api, "Series column")
    sensors = mod.api.upload_csv(
        f"{mod.base}/datasets/upload", f"sensors_{mod.tag}", SENSORS,
    )
    points = mod.api.upload_csv(
        f"{mod.base}/datasets/upload", f"readings_{mod.tag}", READINGS,
    )
    declared = mod.api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"sensor_{mod.tag}",
            "display_name": f"Sensor {mod.tag}",
            "properties": [
                {"api_name": "name", "display_name": "Name", "data_type": "string"},
                {"api_name": "readings", "display_name": "Readings",
                 "data_type": "time_series"},
            ],
            "title_property": "name",
        },
    )
    type_id = declared["id"]
    source = mod.api.call(
        "POST", f"{mod.base}/object-type-sources",
        {
            "object_type_id": type_id,
            "dataset_id": sensors["id"],
            "primary_key_column": "id",
            "column_mappings": {"name": "name", "id": "readings"},
        },
    )
    mod.api.call(
        "PUT", f"{mod.base}/object-type-sources/{source['id']}/series",
        {
            "property_api_name": "readings",
            "dataset_id": points["id"],
            "key_column": "sensor_id",
            "timestamp_column": "taken_at",
            "value_column": "reading",
        },
    )
    synced = mod.api.call(
        "POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {},
    )
    assert synced["upserted"] == 3, synced

    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_all",
                          "columns": "name,readings", "pageSize": 25},
            },
        }),
        "variables": {
            "v_all": {
                "id": "v_all", "kind": "object_set", "label": "All sensors",
                "object_set": object_set(type_id),
            },
        },
        "events": {},
    })
    return mod


def row_for(page, name: str):
    return page.locator("tr", has=page.get_by_text(name, exact=True))


def test_every_row_draws_its_own_history_from_one_read(page, module):
    """p.583's column, and the claim the API test cannot make: three rows, one
    request, three different lines.

    **Each row's own line.** The failure this replaces is a single capped read
    spending its budget on whichever series sorts first - which draws the top
    row and leaves the others blank, and looks exactly like missing data.
    """
    open_module(page, module)
    eventually(lambda: page.get_by_test_id("series-cell").count(),
               lambda n: n == 3, what="a series cell per row")

    north = row_for(page, "North sensor")
    south = row_for(page, "South sensor")
    expect(north.get_by_test_id("series-spark")).to_have_count(1)
    expect(south.get_by_test_id("series-spark")).to_have_count(1)
    # Different shapes, so "a line is drawn" cannot pass on the same line
    # twice: S1 rises and S2 is flat.
    assert north.locator("path").get_attribute("d") != south.locator("path").get_attribute("d")


def test_the_latest_value_is_shown_beside_the_line(page, module):
    """p.583: "the latest value of the time series on the left"."""
    open_module(page, module)
    eventually(lambda: page.get_by_test_id("series-latest").count(),
               lambda n: n == 3, what="a latest value per row")
    expect(row_for(page, "North sensor").get_by_test_id("series-latest")).to_have_text("40")
    expect(row_for(page, "South sensor").get_by_test_id("series-latest")).to_have_text("900")


def test_the_column_stops_showing_the_series_id(page, module):
    """**What the column did before.** A `time_series` property stores the
    *identifier* of its readings, so the ordinary renderer put an opaque key in
    the cell - `S1` where the reading should be. This is the assertion that
    fails if the column ever falls back to `PropertyValue`."""
    open_module(page, module)
    eventually(lambda: page.get_by_test_id("series-cell").count(),
               lambda n: n == 3, what="the series cells")
    cell = row_for(page, "North sensor").get_by_test_id("series-cell")
    expect(cell).to_contain_text("40")
    expect(cell).not_to_contain_text("S1")


def test_a_missing_reading_is_a_gap_and_not_a_zero(page, module):
    """S3 has one reading and then a null. `Number(null)` is 0 - a finite
    number that plots as a real measurement - so a series with a missing
    reading is the only fixture that can tell a *dropped* gap from a zeroed
    one. One usable reading has no shape, so the cell says so rather than
    drawing a line to nowhere."""
    open_module(page, module)
    eventually(lambda: page.get_by_test_id("series-cell").count(),
               lambda n: n == 3, what="the series cells")
    patchy = row_for(page, "Patchy sensor")
    expect(patchy.get_by_test_id("series-empty")).to_have_text("One reading")
    expect(patchy.get_by_test_id("series-spark")).to_have_count(0)
    # And the reading it does have is still the latest value.
    expect(patchy.get_by_test_id("series-latest")).to_have_text("5")


def test_a_flat_series_still_draws_a_line(page, module):
    """S2 never changes. A range of zero divides every point onto one pixel or
    onto NaN, so a flat series is the one that disappears when the band around
    a constant is missing."""
    open_module(page, module)
    eventually(lambda: page.get_by_test_id("series-spark").count(),
               lambda n: n == 2, what="the two drawable sparklines")
    d = row_for(page, "South sensor").locator("path").get_attribute("d")
    assert d and "NaN" not in d, d
    # Flat means the same y at both ends.
    ys = [float(part.split(" ")[1]) for part in d.replace("M", "").split("L")]
    assert len(set(ys)) == 1, d
