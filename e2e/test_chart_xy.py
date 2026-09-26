"""p.281–282's Series aggregation and Segment by on Chart XY (parity
`workshop.md` §10's Chart XY row; §467).

> "Series aggregation: Determines the aggregation method used to produce each
> value plotted on the chart. By default, this is set to "Count." Other options
> include: "Average," "Min," "Max," "Sum"…" (p.281)
>
> "Segment by: … each bar would show the count of objects of each "Alert Type"
> segmented by each "Aircraft Type"." (p.281–282)
>
> "Segment overrides: … "Stacked," "Percentage," and "Grouped."" (p.282)

The layout arithmetic is `chart-segments.test.ts`. What needs a browser is that
the bars are of the right data: an object-set chart drew a count whatever its
Measure said, and a picture of the wrong numbers looks entirely convincing.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

# By count `open` is the taller bar (3 to 1); by total capacity it is the
# shorter (30 to 90). A chart that counted when asked for a sum is backwards.
ROWS = [
    {"id": "S1", "status": "open", "region": "north", "capacity": 10},
    {"id": "S2", "status": "open", "region": "south", "capacity": 10},
    {"id": "S3", "status": "open", "region": "north", "capacity": 10},
    {"id": "S4", "status": "closed", "region": "east", "capacity": 90},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Chart XY")
    mod.site_type_id = mod.object_type(
        columns=["id", "status", "region", "capacity"], rows=ROWS, key="id", title="id",
        types={"capacity": "integer"},
    )
    return mod


def build(api, sites, name: str, props: dict, *, with_table: bool = False):
    nodes = {"chart": {"resolvedName": "CanvasChart", "props": {
        "objectSetVariable": "v_set", "kind": "bar", "dimension": "status", **props}}}
    if with_table:
        nodes["tbl"] = {"resolvedName": "CanvasObjectTable", "props": {
            "objectSetVariable": "v_picked", "columns": "id,status", "pageSize": 50}}
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(sites.site_type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Drilled"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Picked",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_set", "v_clauses"]}},
        },
        "events": {},
    })
    return mod


def bar_titles(page) -> list[str]:
    return page.locator("svg[aria-label='Bar chart'] rect title").all_text_contents()


def segment(page, category: str, name: str):
    return page.locator(
        f"[data-testid='chart-segment'][data-category='{category}'][data-segment='{name}']")


def box(locator) -> dict:
    got = locator.bounding_box()
    assert got, locator
    return got


def test_a_sum_is_drawn_rather_than_a_count(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY sum", {"aggregate": "sum", "measure": "capacity"})
    open_module(page, mod)
    eventually(lambda: bar_titles(page), lambda got: got == ["closed: 90", "open: 30"],
               what="bars of total capacity, the largest first")


def test_a_count_still_counts_and_an_average_is_not_a_sum(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY count", {})
    open_module(page, mod)
    eventually(lambda: bar_titles(page), lambda got: got == ["open: 3", "closed: 1"],
               what="bars of how many")
    mod = build(api, sites, "Chart XY avg", {"aggregate": "avg", "measure": "capacity"})
    open_module(page, mod)
    eventually(lambda: sorted(bar_titles(page)), lambda got: got == ["closed: 90", "open: 10"],
               what="bars of the average capacity")


def test_an_unfinished_aggregation_asks_for_its_property(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY unfinished", {"aggregate": "sum"})
    open_module(page, mod)
    expect(page.get_by_text("Chart - pick a property to sum")).to_be_visible()


def test_stacked_segments_split_each_bar_by_the_second_property(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY stacked", {"segmentBy": "region"})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-segment")).to_have_count(3)
    north, south = box(segment(page, "open", "north")), box(segment(page, "open", "south"))
    east = box(segment(page, "closed", "east"))
    # One bar, two parts: the same column, north twice south's height, on top
    # of one another.
    assert abs(north["x"] - south["x"]) < 1, (north, south)
    assert abs(north["height"] - 2 * south["height"]) < 2, (north, south)
    assert abs(east["height"] - south["height"]) < 2, (east, south)
    # One colour per segment, whichever bar it is in; three in the legend.
    expect(page.get_by_test_id("chart-legend-entry")).to_have_text(["north", "east", "south"])


def test_percentage_segments_make_every_bar_the_same_height(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY percent", {"segmentBy": "region", "segmentMode": "percentage"})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-segment")).to_have_count(3)
    north, south = box(segment(page, "open", "north")), box(segment(page, "open", "south"))
    east = box(segment(page, "closed", "east"))
    assert abs((north["height"] + south["height"]) - east["height"]) < 2, (north, south, east)
    expect(page.get_by_text("100%")).to_be_visible()


def test_grouped_segments_stand_side_by_side(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY grouped", {"segmentBy": "region", "segmentMode": "grouped",
                                                 "showLegend": False})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-segment")).to_have_count(3)
    north, south = box(segment(page, "open", "north")), box(segment(page, "open", "south"))
    # Side by side on one baseline, not stacked.
    assert abs((north["y"] + north["height"]) - (south["y"] + south["height"])) < 1
    assert abs(north["x"] - south["x"]) > north["width"] - 1, (north, south)
    expect(page.get_by_test_id("chart-legend-entry")).to_have_count(0)


def test_a_sum_with_a_segment_saved_draws_the_sum_unsegmented(page, api, sites) -> None:
    """Segments count (the cross-tab has no metric per cell). A document that
    holds both - a segment chosen, then the Measure changed - draws the sum it
    asks for, rather than a segmented count that quietly is not one."""
    mod = build(api, sites, "Chart XY sum segment", {
        "aggregate": "sum", "measure": "capacity", "segmentBy": "region"})
    open_module(page, mod)
    eventually(lambda: bar_titles(page), lambda got: got == ["closed: 90", "open: 30"],
               what="bars of total capacity")
    expect(page.get_by_test_id("chart-segment")).to_have_count(0)


def test_a_segment_drills_into_its_bar(page, api, sites) -> None:
    """The drill-down writes one clause on the X axis property; a segment is a
    second property it does not name, so a click on either part of a bar
    narrows to the bar."""
    mod = build(api, sites, "Chart XY drill", {"segmentBy": "region",
                                               "drilldownVariable": "v_clauses"},
                with_table=True)
    open_module(page, mod)
    cells = page.locator(".data-grid tbody tr td:first-child")
    eventually(lambda: len(cells.all_text_contents()), lambda n: n == 4, what="every site")
    segment(page, "open", "south").click()
    eventually(lambda: sorted(c.strip() for c in cells.all_text_contents()),
               lambda got: got == ["S1", "S2", "S3"], what="the open sites")
    expect(segment(page, "open", "north")).to_have_attribute("aria-pressed", "true")


def test_the_panel_segments_a_count_and_only_a_count(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY panel", {})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Chart").first.click()
    by = page.get_by_test_id("chart-segment-by")
    # The Category is not offered as its own segment.
    expect(by.locator("option")).to_have_text(["No segments", "id", "region", "capacity"])
    by.select_option("region")
    page.get_by_test_id("chart-segment-mode").select_option("grouped")
    save(page)
    props = mod.definition()["layout"]["chart"]["props"]
    assert (props["segmentBy"], props["segmentMode"]) == ("region", "grouped"), props
    # A sum cannot be segmented: the split comes from counts.
    page.get_by_test_id("chart-aggregate").select_option("sum")
    expect(by).to_be_disabled()
    expect(page.get_by_text("Segments count objects")).to_be_visible()
    # And its property is a number.
    expect(page.get_by_test_id("chart-measure").locator("option")).to_have_text(
        ["Choose…", "capacity"])


# ---- p.281's Labels, p.283's Sort by, p.284's orientation (§468) --------------
def region_titles(page, chart: str = "Bar chart") -> list[str]:
    return page.locator(f"svg[aria-label='{chart}'] rect title").all_text_contents()


@pytest.mark.parametrize("sort, expected", [
    # The data's own order: largest first, a tie by key.
    (None, ["north: 2", "east: 1", "south: 1"]),
    ("keyAsc", ["east: 1", "north: 2", "south: 1"]),
    ("keyDesc", ["south: 1", "north: 2", "east: 1"]),
    ("valueAsc", ["east: 1", "south: 1", "north: 2"]),
])
def test_the_bars_are_in_the_order_asked_for(page, api, sites, sort, expected) -> None:
    mod = build(api, sites, f"Chart XY sort {sort}",
                {"dimension": "region", **({"sort": sort} if sort else {})})
    open_module(page, mod)
    eventually(lambda: region_titles(page), lambda got: got == expected, what=f"sorted {sort}")


def test_a_horizontal_bar_chart_runs_across(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY horizontal", {"dimension": "region",
                                                    "orientation": "horizontal"})
    open_module(page, mod)
    bars = page.locator("svg[aria-label='Horizontal bar chart'] rect")
    expect(bars).to_have_count(3)
    north, east = box(bars.nth(0)), box(bars.nth(1))
    # North is twice east, measured along the bar - its width - and the two
    # start from the same edge.
    assert abs(north["width"] - 2 * east["width"]) < 2, (north, east)
    assert abs(north["x"] - east["x"]) < 1, (north, east)
    assert north["y"] < east["y"], (north, east)


def test_value_labels_write_each_value(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY labels", {"dimension": "region", "valueLabels": True})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-value-label")).to_have_text(["2", "1", "1"])
    mod = build(api, sites, "Chart XY no labels", {"dimension": "region"})
    open_module(page, mod)
    expect(page.locator("svg[aria-label='Bar chart'] rect")).to_have_count(3)
    expect(page.get_by_test_id("chart-value-label")).to_have_count(0)


def test_the_panel_sets_the_display(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY display panel", {})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Chart").first.click()
    page.get_by_test_id("chart-sort").select_option("keyAsc")
    page.get_by_test_id("chart-orientation").select_option("horizontal")
    page.get_by_test_id("chart-value-labels").check()
    save(page)
    props = mod.definition()["layout"]["chart"]["props"]
    assert (props["sort"], props["orientation"], props["valueLabels"]) == (
        "keyAsc", "horizontal", True), props
