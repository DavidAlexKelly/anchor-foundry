"""Time series set variables, and the chart that reads one (`foundry_workshop`
p.76, p.280, p.582).

    "Time series set: Stores a time series property of a single object,
    optionally allowing the application of time series transforms to it."
    (p.76)

    "The Time series set option allows a Workshop time series set variable to
    be used as input. This configures a time series chart, with the time range
    on the X axis, and the time series values of the variable on the Y axis."
    (p.280)

The variable graph is the test:

    v_all     (object_set)      every sensor
    v_picked  (single_object)   the row somebody clicked
    v_series  (time_series_set) object_series(v_picked), property `readings`

What needs a browser rather than an API test is the *chain*: a click on a row
becomes an object, the object becomes a series reference, the reference
becomes a line - and the line **changes** when a different row is clicked.
Each half is provable on its own and neither proves the app works.

Nothing is copied to make this happen (decision 0009): the readings live in
their own dataset, the variable holds a question, and the widget asks it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module

SENSORS = [
    {"id": "S1", "name": "North sensor"},
    {"id": "S2", "name": "South sensor"},
    {"id": "S3", "name": "Patchy sensor"},
]
# S1 rises, S2 is flat and much higher. Two shapes and two ranges, so "the
# chart changed" cannot pass on a redraw of the same numbers.
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,10\n"
    b"S1,2026-01-02T00:00:00,20\n"
    b"S1,2026-01-03T00:00:00,30\n"
    b"S1,2026-01-04T00:00:00,40\n"
    b"S2,2026-01-01T00:00:00,900\n"
    b"S2,2026-01-02T00:00:00,900\n"
    # S3 has a gap. `Number(null)` is 0 - a finite number that plots as a real
    # measurement of zero (the bug §149 caught in `plot`), so a series with a
    # missing reading is the only fixture that can tell a *dropped* gap from a
    # zeroed one.
    b"S3,2026-01-01T00:00:00,5\n"
    b"S3,2026-01-02T00:00:00,\n"
)
S1_POINTS = 4
S2_POINTS = 2
CHART_TITLE = "Sensor readings over time"


@pytest.fixture(scope="module")
def module(api):
    """A sensor type with a `time_series` property, and a module reading it.

    Built directly rather than through `Module.object_type` for the reason
    `test_series_card.py` gives: the primary key column has to be mapped to
    the series property *as well* as being the key, and a mapping of
    `{column: same-named property}` has nowhere to say so.
    """
    mod = Module(api, "Series variable")
    sensors = api.upload_csv(
        f"{mod.base}/datasets/upload", f"sensors_{mod.tag}",
        b"id,name\nS1,North sensor\nS2,South sensor\nS3,Patchy sensor\n",
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
                 "data_type": "time_series"},
            ],
            "title_property": "name",
        },
    )
    type_id = declared["id"]
    mod.object_type_id = type_id

    source = api.call(
        "POST", f"{mod.base}/object-type-sources",
        {
            "object_type_id": type_id,
            "dataset_id": sensors["id"],
            "primary_key_column": "id",
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

    mod.define(
        {
            "format": 2,
            "layout": layout(
                {
                    "tbl": {
                        "resolvedName": "CanvasObjectTable",
                        "props": {"objectSetVariable": "v_all",
                                  "columns": "id,name", "pageSize": 25},
                    },
                    "cht": {
                        "resolvedName": "CanvasChart",
                        # `kind` is deliberately *not* line: p.281 says a time
                        # series set is drawn as a line whatever the widget was
                        # set to, and a fixture that agreed with the widget
                        # could not tell whether the rule was applied.
                        "props": {"kind": "bar", "title": CHART_TITLE,
                                  "seriesVariable": "v_series"},
                    },
                }
            ),
            "variables": {
                "v_all": {
                    "id": "v_all", "kind": "object_set", "label": "All sensors",
                    "object_set": object_set(type_id),
                },
                "v_picked": {
                    "id": "v_picked", "kind": "single_object", "label": "Picked sensor",
                },
                "v_series": {
                    "id": "v_series", "kind": "time_series_set", "label": "Readings",
                    "derivation": {
                        "transform": "object_series", "inputs": ["v_picked"],
                        "config": {"property": "readings",
                                   "interval": "day", "aggregate": "avg"},
                    },
                },
            },
            "events": {
                "e_row": {
                    "id": "e_row",
                    "trigger": {"node": "tbl", "on": "row_select"},
                    "effects": [
                        {"type": "set_variable",
                         "config": {"variable": "v_picked", "from": "object"}}
                    ],
                }
            },
        }
    )
    return mod


def chart_block(page):
    """The chart's own block, found by its title.

    `.last` because the module's root container is a `.canvas-block` too and
    contains the same heading; an ancestor precedes its descendant in document
    order, so the innermost match is the widget. Not `has=svg`: this has to
    work *before* anything is picked, when there is no chart to find.
    """
    return page.locator(".canvas-block").filter(
        has=page.get_by_role("heading", name=CHART_TITLE)
    ).last


def pick(page, name: str) -> None:
    page.locator("table tbody tr").filter(has_text=name).first.click()


def caption(page) -> str:
    return page.get_by_test_id("chart-series-caption").inner_text()


def test_a_series_variable_charts_the_object_somebody_picked(page, module):
    """p.76's whole sentence, end to end: a property of *a single object*, and
    which object is the viewer's click."""
    open_module(page, module)
    # Before any click the variable is unset, so there is nothing to ask for.
    # An empty axis here would be the widget claiming a reading it never had -
    # and a blank block would leave a builder wondering what is broken, so it
    # says which of the two it is.
    expect(page.get_by_test_id("chart-series-caption")).to_have_count(0)
    expect(chart_block(page).get_by_text("nothing picked yet")).to_be_visible()

    pick(page, "North sensor")
    eventually(lambda: page.get_by_test_id("chart-series-caption").count(),
               lambda n: n == 1, what="the chart's caption once a row is picked")
    assert f"{S1_POINTS} points" in caption(page), caption(page)
    # A path, not merely an `<svg>`: an empty chart element passes the weaker
    # check and is exactly the failure this is most likely to have.
    assert chart_block(page).locator("path").count() >= 1


def test_picking_a_different_object_redraws_the_series(page, module):
    """The claim an API test cannot make. Both sensors' points come back from
    the same endpoint; that the *chart* follows the selection is the chain."""
    open_module(page, module)
    pick(page, "North sensor")
    eventually(lambda: caption(page), lambda t: f"{S1_POINTS} points" in t,
               what="the first sensor's readings")
    first = chart_block(page).locator("path").first.get_attribute("d")

    pick(page, "South sensor")
    eventually(lambda: caption(page), lambda t: f"{S2_POINTS} points" in t,
               what="the second sensor's readings")
    # The geometry moved too. A caption that changed over a line that did not
    # would be two widgets disagreeing about which object is selected.
    assert chart_block(page).locator("path").first.get_attribute("d") != first


def test_a_time_series_set_is_drawn_as_a_line_whatever_the_chart_type_says(
    page, module
):
    """p.281: "If the data input is a time series set, only the Line Chart
    option is supported." The fixture asks for a bar chart, so a widget that
    honoured `kind` would draw rects."""
    open_module(page, module)
    pick(page, "North sensor")
    eventually(lambda: caption(page), lambda t: "points" in t, what="the drawn series")
    assert chart_block(page).locator("rect").count() == 0
    assert chart_block(page).locator("path").count() >= 1


def test_the_chart_says_which_property_and_which_bucket_it_drew(page, module):
    """A line of numbers is a shape until it says what it is measuring. The
    bucket and the summariser come from the *variable* (p.76's transforms), so
    naming them is naming where they were set."""
    open_module(page, module)
    pick(page, "North sensor")
    eventually(lambda: caption(page), lambda t: "readings" in t,
               what="the property the line came from")
    text = caption(page)
    assert "by day" in text and "avg" in text, text
    # UTC, for the reason `seriesLabel` is pinned to it: a viewer west of
    # Greenwich reading local-time buckets is a day behind the data.
    assert "UTC" in text, text


def test_a_missing_reading_is_a_gap_and_not_a_zero(page, module):
    """`Number(null)` is `0`, and so is `Number("")` - both finite, so a chart
    that trusted `Number` would draw a reading that never happened. §149 caught
    this inside `plot`; the same trap is here, one layer up, and the only
    fixture that can see it is a series with a hole in it.

    Dropped rather than zeroed, and **said** - a gap removed in silence is a
    chart that looks complete.
    """
    open_module(page, module)
    pick(page, "Patchy sensor")
    eventually(lambda: caption(page), lambda t: "point" in t,
               what="the patchy sensor's readings")
    text = caption(page)
    assert "1 point" in text, text
    assert "1 with no reading skipped" in text, text
