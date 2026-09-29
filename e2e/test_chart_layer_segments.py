"""p.282's Segment by on each Chart XY layer (§678).

> "Segment by: Optional. Enables each plotted value to be segmented by a
> secondary property type. As an example, if "Alert Type" was selected as the
> X axis property and then "Aircraft Type" was selected as the Segment by
> option on a bar chart, each bar would show the count of objects of each
> "Alert Type" segmented by each "Aircraft Type"." (p.282)

The four sites of `test_chart_xy.py`, by status: open 3 (north 2, south 1),
closed 1 (east). A layer counting them beside one split by region stand side
by side in each status, the split one stacked. How the columns are built and
laid out is `chart-series.test.ts` and `chart-segments.test.ts`.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import open_builder, open_module, save, settled
from test_chart_xy import box, build, segment, sites  # noqa: F401


def test_a_layer_split_by_region_stands_beside_the_chart_s_own(page, api, sites) -> None:
    mod = build(api, sites, "Chart layer segments", {
        "seriesName": "All", "series": [{"aggregate": "count", "name": "By region", "segmentBy": "region"}]})
    open_module(page, mod)
    rects = page.get_by_test_id("chart-segment")
    expect(rects).to_have_count(5, timeout=20000)
    everything = box(segment(page, "open", "All"))
    north, south = box(segment(page, "open", "By region · north")), box(segment(page, "open", "By region · south"))
    # The split layer's two parts are one bar, north twice south, piled.
    assert abs(north["x"] - south["x"]) < 1, (north, south)
    assert abs(north["height"] - 2 * south["height"]) < 2, (north, south)
    assert abs(min(north["y"] + north["height"], south["y"] + south["height"])
               - max(north["y"], south["y"])) < 2, (north, south)
    # Beside the chart's own bar, and as tall as it together: three objects.
    assert north["x"] > everything["x"] + everything["width"] - 1, (everything, north)
    assert abs(north["height"] + south["height"] - everything["height"]) < 2
    # The full names are the entries' own; the drawn text is shortened to fit.
    entries = page.locator("[data-testid='chart-legend-entry']")
    expect(entries).to_have_count(4)
    assert [e.get_attribute("data-segment") for e in entries.all()] == [
        "All", "By region · north", "By region · east", "By region · south"]


def test_the_chart_s_own_segments_keep_the_other_layers(page, api, sites) -> None:
    """A segmented bar chart keeps its layers since §678: its own bars split
    by region, a layer summing capacity beside them."""
    mod = build(api, sites, "Chart own segments with a layer", {
        "segmentBy": "region", "series": [{"aggregate": "sum", "measure": "capacity", "name": "Capacity"}]})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-segment")).to_have_count(5, timeout=20000)
    north = box(segment(page, "open", "Count · north"))
    capacity = box(segment(page, "open", "Capacity"))
    assert capacity["x"] > north["x"] + north["width"] - 1, (north, capacity)
    expect(page.locator("[data-testid='chart-legend-entry']")).to_have_count(4)


def test_the_panel_segments_a_counting_bar_layer(page, api, sites) -> None:
    mod = build(api, sites, "Chart layer segments panel", {
        "series": [{"aggregate": "count"}, {"aggregate": "sum", "measure": "capacity"}]})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Chart").first.click()
    # Offered on the counting layer, not on the one that sums.
    expect(page.get_by_label("Series 3 segment by")).to_have_count(0)
    page.get_by_label("Series 2 segment by").select_option("region")
    save(page)
    props = mod.definition()["layout"]["chart"]["props"]
    assert props["series"][0]["segmentBy"] == "region", props
