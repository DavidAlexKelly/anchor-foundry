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


# ---- p.283's value axis and titles (§536) -----------------------------------

def value_ticks(page) -> list[str]:
    return page.get_by_test_id("chart-value-tick").all_text_contents()


def bar_heights(page) -> dict[str, float]:
    bars = page.locator("svg[aria-label='Bar chart'] rect")
    out = {}
    for i in range(bars.count()):
        title = bars.nth(i).locator("title").text_content() or ""
        out[title.split(":")[0]] = box(bars.nth(i))["height"]
    return out


def test_a_logarithmic_axis_draws_by_the_power_of_ten(page, api, sites) -> None:
    # Sums of 30 and 90: linear draws closed three times open's height, and
    # a logarithm from 10 draws log(9) / log(3) = 2 times.
    mod = build(api, sites, "Chart XY log", {
        "aggregate": "sum", "measure": "capacity", "scaleType": "log"})
    open_module(page, mod)
    eventually(lambda: value_ticks(page), lambda got: got == ["10", "100"], what="log ticks")
    heights = bar_heights(page)
    assert abs(heights["closed"] / heights["open"] - 2) < 0.05, heights
    mod = build(api, sites, "Chart XY linear", {"aggregate": "sum", "measure": "capacity"})
    open_module(page, mod)
    eventually(lambda: value_ticks(page), lambda got: got[-1:] == ["90"], what="linear ticks")
    heights = bar_heights(page)
    assert abs(heights["closed"] / heights["open"] - 3) < 0.05, heights


def test_fixed_bounds_hold_the_axis_and_cut_what_runs_past(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY bounds", {
        "dimension": "region", "minBound": 0, "maxBound": 4, "valueLabels": True})
    open_module(page, mod)
    eventually(lambda: value_ticks(page), lambda got: got == ["0", "1", "2", "3", "4"],
               what="bounded ticks")
    heights = bar_heights(page)
    # North's 2 is half of 4, and east's 1 a quarter.
    assert abs(heights["north"] / heights["east"] - 2) < 0.05, heights
    mod = build(api, sites, "Chart XY cut", {
        "dimension": "region", "maxBound": 1.5, "valueLabels": True})
    open_module(page, mod)
    eventually(lambda: value_ticks(page), lambda got: got[-1:] == ["1.50"], what="cut ticks")
    expect(page.get_by_test_id("chart-plot-clip")).to_have_count(3)
    # North's 2 runs past 1.5: its bar is cut and its number not written in
    # the margin, and east's and south's are.
    expect(page.get_by_test_id("chart-value-label")).to_have_text(["1", "1"])


def test_a_calculated_axis_is_not_cut(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY uncut", {"dimension": "region"})
    open_module(page, mod)
    expect(page.locator("svg[aria-label='Bar chart'] rect")).to_have_count(3)
    expect(page.get_by_test_id("chart-plot-clip")).to_have_count(0)
    assert value_ticks(page) == ["0", "0.50", "1", "1.50", "2"]


def test_bounds_that_cannot_be_drawn_are_said(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY backwards", {
        "dimension": "region", "minBound": 5, "maxBound": 2})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-axis-problem")).to_contain_text("below the maximum bound")
    assert value_ticks(page)[0] == "0" and value_ticks(page)[-1] == "2", value_ticks(page)
    mod = build(api, sites, "Chart XY log of zero", {
        "dimension": "region", "scaleType": "log", "minBound": 0})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-axis-problem")).to_contain_text("above 0")
    mod = build(api, sites, "Chart XY fine bounds", {"dimension": "region", "minBound": 0})
    open_module(page, mod)
    expect(page.locator("svg[aria-label='Bar chart'] rect")).to_have_count(3)
    expect(page.get_by_test_id("chart-axis-problem")).to_have_count(0)


def test_a_logarithm_says_what_it_could_not_draw(page, api) -> None:
    # Averages by bin: a 50, b 0, c 5 and d 0.5, so the axis runs from 0.1 to
    # 100 and `b` has nothing a logarithm can draw.
    mod = Module(api, "Chart XY zeroes")
    type_id = mod.object_type(
        columns=["id", "bin", "weight"], key="id", title="id", types={"weight": "integer"},
        rows=[{"id": "A", "bin": "a", "weight": 50}, {"id": "B", "bin": "b", "weight": 0},
              {"id": "C", "bin": "c", "weight": 5}, {"id": "D", "bin": "d", "weight": 1},
              {"id": "E", "bin": "d", "weight": 0}])

    def chart(kind: str) -> Module:
        built = Module(api, f"Chart XY zeroes {kind}", beside=mod)
        built.define({
            "format": 2,
            "layout": layout({"chart": {"resolvedName": "CanvasChart", "props": {
                "objectSetVariable": "v_set", "kind": kind, "dimension": "bin",
                "aggregate": "avg", "measure": "weight", "scaleType": "log",
                "sort": "keyAsc"}}}),
            "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Bins",
                                    "object_set": object_set(type_id)}},
            "events": {},
        })
        return built

    open_module(page, chart("bar"))
    expect(page.get_by_test_id("chart-undrawn")).to_have_text(
        "1 value is zero or below, which a logarithmic axis cannot draw.")
    # A tick below 1 reads as itself, not as two decimals.
    eventually(lambda: value_ticks(page), lambda got: got == ["0.1", "1", "10", "100"],
               what="small log ticks")
    # Three bars, and all four categories still named under the axis.
    expect(page.locator("svg[aria-label='Bar chart'] rect")).to_have_count(3)
    names = page.locator("svg[aria-label='Bar chart'] text").all_text_contents()
    assert {"a", "b", "c", "d"} <= set(names), names
    open_module(page, chart("line"))
    expect(page.get_by_test_id("chart-undrawn")).to_be_visible()
    # a, b, c, d in order: `b` cannot be drawn, so the line breaks there
    # rather than joining a to c across a reading it does not have.
    path = page.locator("svg[aria-label='Line chart'] path").get_attribute("d") or ""
    assert path.count("M") == 2 and path.count("L") == 1, path
    expect(page.locator("svg[aria-label='Line chart'] circle")).to_have_count(3)


def test_axis_titles_default_to_what_is_plotted_and_can_be_overridden(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY titles", {
        "aggregate": "sum", "measure": "capacity",
        "showCategoryTitle": True, "showValueTitle": True})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-category-title")).to_have_text("status")
    expect(page.get_by_test_id("chart-value-title")).to_have_text("Sum of capacity")
    mod = build(api, sites, "Chart XY own titles", {
        "orientation": "horizontal", "showCategoryTitle": True, "categoryTitle": "State",
        "showValueTitle": True, "valueTitle": "Sites"})
    open_module(page, mod)
    chart = page.locator("svg[aria-label='Horizontal bar chart']")
    expect(chart.get_by_test_id("chart-category-title")).to_have_text("State")
    expect(chart.get_by_test_id("chart-value-title")).to_have_text("Sites")
    # Turned: the categories run down the left, so their title stands up the
    # left edge and the values' lies along the bottom.
    category, value = box(chart.get_by_test_id("chart-category-title")), box(
        chart.get_by_test_id("chart-value-title"))
    assert category["height"] > category["width"], category
    assert value["y"] > category["y"] + category["height"] / 2, (category, value)
    mod = build(api, sites, "Chart XY no titles", {"categoryTitle": "Unshown"})
    open_module(page, mod)
    expect(page.locator("svg[aria-label='Bar chart'] rect")).to_have_count(2)
    expect(page.get_by_test_id("chart-category-title")).to_have_count(0)
    expect(page.get_by_test_id("chart-value-title")).to_have_count(0)


def test_a_segmented_chart_takes_titles_and_keeps_a_calculated_axis(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY segmented titles", {
        "segmentBy": "region", "showCategoryTitle": True, "showValueTitle": True,
        "scaleType": "log", "maxBound": 1})
    open_module(page, mod)
    expect(page.get_by_test_id("chart-category-title")).to_have_text("status")
    expect(page.get_by_test_id("chart-value-title")).to_have_text("Count")
    assert value_ticks(page)[-1] == "3", value_ticks(page)
    expect(page.get_by_test_id("chart-axis-problem")).to_have_count(0)


def test_the_panel_sets_the_axis(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY axis panel", {})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Chart").first.click()
    page.get_by_test_id("chart-scale-type").select_option("log")
    page.get_by_test_id("chart-min-bound").fill("0")
    expect(page.get_by_test_id("chart-axis-problem-hint")).to_contain_text("above 0")
    page.get_by_test_id("chart-min-bound").fill("0.5")
    page.get_by_test_id("chart-max-bound").fill("20")
    expect(page.get_by_test_id("chart-axis-problem-hint")).to_have_count(0)
    page.get_by_test_id("chart-show-value-title").check()
    expect(page.get_by_test_id("chart-value-title-input")).to_have_attribute(
        "placeholder", "Count")
    page.get_by_test_id("chart-value-title-input").fill("Sites")
    page.get_by_test_id("chart-show-category-title").check()
    save(page)
    props = mod.definition()["layout"]["chart"]["props"]
    got = {k: props.get(k) for k in (
        "scaleType", "minBound", "maxBound", "showValueTitle", "valueTitle",
        "showCategoryTitle", "categoryTitle")}
    assert got == {"scaleType": "log", "minBound": 0.5, "maxBound": 20, "showValueTitle": True,
                   "valueTitle": "Sites", "showCategoryTitle": True, "categoryTitle": ""}, got
    page.get_by_test_id("chart-max-bound").fill("")
    # A second save: "saved" is already on the page, so wait on the document.
    page.get_by_role("button", name="Save", exact=True).click()
    eventually(lambda: mod.definition()["layout"]["chart"]["props"].get("maxBound", "absent"),
               lambda got: got in (None, "absent"), what="an emptied bound saved as calculated")


def test_the_panel_holds_a_segmented_axis(page, api, sites) -> None:
    mod = build(api, sites, "Chart XY segmented panel", {"segmentBy": "region"})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Chart").first.click()
    expect(page.get_by_test_id("chart-axis-segmented")).to_be_visible()
    expect(page.get_by_test_id("chart-scale-type")).to_have_count(0)
