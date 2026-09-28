"""p.329's "Show visualization?" on the Metric Card (parity `workshop.md` §10;
Foundry p.329).

> "Show visualization? An optional configuration to display a sparkline
> depicting the history of a time series with the metric. Setting this toggle
> to Yes opens a configuration screen with the following options:
> Position: Specifies whether the sparkline should be displayed Side-by-side
> (alongside) or Stacked (under) with the metric value.
> Time series set: The time series that is to be visualized. This is specified
> using a Time series set variable." (p.329)

The geometry is `sparkline.test.ts`'s and the two settings are
`metric-card.test.ts`'s. What needs a browser is the chain p.329 describes: a
**time series set variable** - which points at a property of *one object,
picked by the viewer* - becoming a line next to a number, and the line
following the selection.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, save, settled, eventually, open_module

SENSORS = b"id,name\nS1,North sensor\nS2,South sensor\n"
# S1 rises; S2 is flat and far higher. Two shapes, so "a line is drawn" cannot
# pass on a redraw of the same numbers.
READINGS = (
    b"sensor_id,taken_at,reading\n"
    b"S1,2026-01-01T00:00:00,10\n"
    b"S1,2026-01-02T00:00:00,20\n"
    b"S1,2026-01-03T00:00:00,30\n"
    b"S2,2026-01-01T00:00:00,900\n"
    b"S2,2026-01-02T00:00:00,900\n"
)


def build(api, name: str, *, position: str = "side_by_side", show: bool = True,
          transforms: list | None = None, card: dict | None = None):
    mod = Module(api, name)
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
            "object_type_id": type_id, "dataset_id": sensors["id"],
            "primary_key_column": "id",
            "column_mappings": {"name": "name", "id": "readings"},
        },
    )
    mod.api.call(
        "PUT", f"{mod.base}/object-type-sources/{source['id']}/series",
        {
            "property_api_name": "readings", "dataset_id": points["id"],
            "key_column": "sensor_id", "timestamp_column": "taken_at",
            "value_column": "reading",
        },
    )
    mod.api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})

    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "name",
                              "pageSize": 25}},
            "card": {"resolvedName": "CanvasMetricCard",
                     "props": {"objectSetVariable": "v_all", "aggregation": "count",
                               "label": "Sensors",
                               "showVisualization": show,
                               "visualizationPosition": position,
                               "seriesVariable": "v_series" if show else None,
                               **(card or {})}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sensors",
                      "object_set": object_set(type_id)},
            "v_picked": {"id": "v_picked", "kind": "single_object",
                         "label": "Picked sensor"},
            # A series is a property *of an object*, so the variable carries an
            # `object_series` derivation naming which object and which property
            # - the server refuses a bare one, which is how the first run of
            # this file failed.
            "v_series": {
                "id": "v_series", "kind": "time_series_set", "label": "Readings",
                "derivation": {
                    "transform": "object_series", "inputs": ["v_picked"],
                    "config": {"property": "readings",
                               "interval": "none", "aggregate": "avg",
                               "transforms": transforms or []},
                },
            },
        },
        # The click that sets the object the series is read from. Without it
        # nothing is ever picked and the card has nothing to draw.
        "events": {
            "e_row": {
                "id": "e_row",
                "trigger": {"node": "tbl", "on": "row_select"},
                "effects": [
                    {"type": "set_variable",
                     "config": {"variable": "v_picked", "from": "object"}},
                ],
            },
        },
    })
    return mod


@pytest.fixture(scope="module")
def module(api):
    return build(api, "Metric sparkline")


def pick(page, name: str):
    page.get_by_text(name, exact=True).click()


def test_the_card_draws_a_line_for_the_object_somebody_picked(page, module):
    """p.329's chain, end to end. A time series set variable points at a
    property of *one object*, and which object is the viewer's click - so
    before any click there is nothing to draw and saying so is the honest
    answer, not an empty box."""
    open_module(page, module)
    # The number is there from the start; the line is not, because nothing is
    # picked. A line here would be a reading the widget never took.
    expect(page.get_by_test_id("metric-value")).to_be_visible()
    expect(page.get_by_test_id("metric-spark-unpicked")).to_be_visible()
    expect(page.get_by_test_id("metric-spark-line")).to_have_count(0)

    pick(page, "North sensor")
    eventually(lambda: page.get_by_test_id("metric-spark-line").count(),
               lambda n: n == 1, what="a sparkline once a row is picked")


def test_the_line_follows_the_selection(page, module):
    """The claim an API test cannot make. Both sensors' points come back from
    the same endpoint; that the *card* follows the selection is the chain."""
    open_module(page, module)
    pick(page, "North sensor")
    eventually(lambda: page.get_by_test_id("metric-spark-line").count(),
               lambda n: n == 1, what="the first sparkline")
    first = page.get_by_test_id("metric-spark-line").locator("path").get_attribute("d")

    pick(page, "South sensor")
    # S1 rises and S2 is flat, so the path must change - a redraw of the same
    # numbers would pass a weaker check.
    eventually(
        lambda: page.get_by_test_id("metric-spark-line").locator("path").get_attribute("d"),
        lambda d: d is not None and d != first,
        what="the sparkline to redraw for the other sensor",
    )


def test_the_number_and_the_line_are_both_there(page, module):
    """p.329 puts a sparkline *with* the metric - it does not replace it. A
    visualization that hid the number would be a chart, not a metric card."""
    open_module(page, module)
    pick(page, "North sensor")
    eventually(lambda: page.get_by_test_id("metric-spark-line").count(),
               lambda n: n == 1, what="the sparkline")
    expect(page.get_by_test_id("metric-value")).to_have_text("2")


def test_position_stacks_the_line_under_the_number(page, api):
    """p.329's Position: "Side-by-side (alongside) or Stacked (under) with the
    metric value". Asserted through the *rendered* direction rather than the
    stored prop, because a setting that reaches the document and not the
    layout is a control that does nothing."""
    mod = build(api, "Metric sparkline stacked", position="stacked")
    open_module(page, mod)
    body = page.get_by_test_id("metric-body")
    expect(body).to_have_attribute("data-position", "stacked")
    assert page.evaluate(
        """() => getComputedStyle(
            document.querySelector('[data-testid="metric-body"]')
        ).flexDirection""",
    ) == "column"


def test_side_by_side_is_the_other_direction(page, module):
    """The default, and the half that fails if both positions render the same
    way - which is what a `data-position` attribute alone would allow."""
    open_module(page, module)
    expect(page.get_by_test_id("metric-body")).to_have_attribute(
        "data-position", "side_by_side",
    )
    assert page.evaluate(
        """() => getComputedStyle(
            document.querySelector('[data-testid="metric-body"]')
        ).flexDirection""",
    ) == "row"


def test_a_card_without_the_toggle_draws_no_line(page, api):
    """p.329 calls it optional. A card that always drew one would make every
    metric in the corpus taller."""
    mod = build(api, "Metric sparkline off", show=False)
    open_module(page, mod)
    expect(page.get_by_test_id("metric-value")).to_be_visible()
    expect(page.get_by_test_id("metric-spark")).to_have_count(0)


def test_the_line_is_the_series_after_its_transforms(page, api):
    """§524: a transform is on the variable, so the sparkline reads the
    transformed series as the chart does, rather than the raw one."""
    mod = build(api, "Metric sparkline transformed",
                transforms=[{"kind": "cumulative", "aggregate": "sum"}])
    open_module(page, mod)
    with page.expect_response(lambda r: "/series/readings/points" in r.url) as asked:
        pick(page, "North sensor")
    assert "transforms=" in asked.value.url, asked.value.url
    # S1 reads 10, 20, 30: its running sum, not the readings themselves.
    assert [p["value"] for p in asked.value.json()["points"]] == [10, 30, 60]
    eventually(lambda: page.get_by_test_id("metric-spark-line").count(),
               lambda n: n == 1, what="the transformed sparkline")



# ---- §526: size, description, time range and baseline (p.326-330) --------------
def spark_values(page, name: str = "North sensor") -> tuple[str, list]:
    with page.expect_response(lambda r: "/series/readings/points" in r.url) as asked:
        pick(page, name)
    return asked.value.url, [p["value"] for p in asked.value.json()["points"]]


def test_the_card_takes_its_size_and_says_its_description(page, api):
    """p.326's size and p.328's "i tooltip", with p.592's static baseline
    drawn beside the line."""
    mod = build(api, "Metric display", card={
        "size": "large", "description": "Sensors reporting now", "baseline": 25})
    open_module(page, mod)
    expect(page.get_by_test_id("metric-card")).to_have_attribute("data-size", "large")
    info = page.get_by_test_id("metric-description")
    expect(info).to_have_attribute("title", "Sensors reporting now")
    expect(info).to_have_attribute("aria-label", "Sensors reporting now")
    pick(page, "North sensor")
    expect(page.get_by_test_id("metric-spark-line-baseline")).to_have_count(1)


def test_a_card_with_no_description_has_no_marker_and_no_baseline(page, module):
    open_module(page, module)
    expect(page.get_by_test_id("metric-card")).to_have_attribute("data-size", "regular")
    expect(page.get_by_test_id("metric-description")).to_have_count(0)
    pick(page, "North sensor")
    eventually(lambda: page.get_by_test_id("metric-spark-line").count(),
               lambda n: n == 1, what="the sparkline")
    expect(page.get_by_test_id("metric-spark-line-baseline")).to_have_count(0)


def test_a_custom_range_narrows_the_line(page, api):
    """p.330's Custom range: from the 2nd, S1's 10, 20, 30 is 20, 30."""
    mod = build(api, "Metric range", card={"sparkRange": "custom", "sparkStart": "2026-01-02T00:00"})
    open_module(page, mod)
    url, values = spark_values(page)
    assert "transforms=" in url, url
    assert values == [20, 30]


def test_the_last_week_of_january_readings_is_empty(page, api):
    """p.330's Last week counts back from now, and these readings are from
    January: the line says there are none rather than drawing January."""
    mod = build(api, "Metric last week", card={"sparkRange": "week"})
    open_module(page, mod)
    _, values = spark_values(page)
    assert values == []
    expect(page.get_by_test_id("metric-spark-line-empty")).to_be_visible()


def test_the_panel_sets_all_four(page, api):
    mod = build(api, "Metric display panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Metric card").first.click()
    page.get_by_test_id("metric-description-input").fill("Readings so far")
    page.get_by_test_id("metric-size").select_option("compact")
    page.get_by_test_id("metric-spark-range").select_option("custom")
    page.get_by_test_id("metric-spark-start").fill("2026-01-03T00:00")
    page.get_by_test_id("metric-spark-end").fill("2026-01-02T00:00")
    expect(page.get_by_test_id("metric-spark-range-problem")).to_have_text(
        "The range starts after it ends.")
    page.get_by_test_id("metric-spark-start").fill("2026-01-02T00:00")
    page.get_by_test_id("metric-spark-end").fill("2026-01-03T00:00")
    expect(page.get_by_test_id("metric-spark-range-problem")).to_have_count(0)
    page.get_by_test_id("metric-spark-baseline").fill("15")
    save(page)

    open_module(page, mod)
    expect(page.get_by_test_id("metric-card")).to_have_attribute("data-size", "compact")
    expect(page.get_by_test_id("metric-description")).to_have_attribute("title", "Readings so far")
    _, values = spark_values(page)
    assert values == [20, 30]
    expect(page.get_by_test_id("metric-spark-line-baseline")).to_have_count(1)


def test_a_tag_layout_draws_no_line(page, api):
    """§533, p.326: "time series visualizations are only supported in this
    layout style" (Card)."""
    mod = build(api, "Metric sparkline tag", card={"layoutStyle": "tag"})
    open_module(page, mod)
    pick(page, "North sensor")
    expect(page.get_by_test_id("metric-value")).to_have_text("2")
    expect(page.get_by_test_id("metric-spark")).to_have_count(0)
