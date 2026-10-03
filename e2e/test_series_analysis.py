"""The Time Series Analysis widget (§647; `workshop` p.392-398).

> "Add time series data from the Ontology … then derive new plots by
> selecting New Plot. Plots can be organized across multiple canvases within
> the same analysis." (p.392)

Three sensors from `test_series_column`'s fixture are the analysis's root
plots, one each, with the Plots panel's statistics. A cumulative plot derived
from the North sensor adds its readings up (10, 30, 60, 100), and moved to a
canvas of its own it is the only line drawn there.
"""
from __future__ import annotations

import re

import pytest

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, _signed_in, open_builder, open_module, save, settled
from test_series_column import module  # noqa: F401


def build(api, module, name: str, **props) -> Module:
    mod = Module(api, name, beside=module)
    mod.define({
        "format": 2,
        "layout": layout({
            "tsa": {"resolvedName": "CanvasSeriesAnalysis", "props": {
                "objectSetVariable": "v_all", "property": "readings", "labelProperty": "name",
                "limit": 5, **props}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sensors",
                      "object_set": object_set(module.sensor_type)},
        },
        "events": {},
    })
    return mod


def plot_row(page, label: str):
    return page.locator(f"[data-testid='series-plots'] tbody tr[data-label='{label}']")


def stat(page, label: str, which: str):
    return plot_row(page, label).locator(f"td[data-stat='{which}']")


def test_each_object_is_a_plot_with_its_statistics(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis roots"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    expect(stat(page, "North sensor", "min")).to_have_text("10")
    expect(stat(page, "North sensor", "max")).to_have_text("40")
    expect(stat(page, "North sensor", "mean")).to_have_text("25")
    expect(stat(page, "South sensor", "mean")).to_have_text("900")
    # A reading with no value is a gap, not a zero.
    expect(stat(page, "Patchy sensor", "min")).to_have_text("5")
    expect(page.locator("[data-testid='series-canvas-1'] path[data-plot]")).to_have_count(3)
    # The object set controls the roots: they cannot be removed.
    expect(plot_row(page, "North sensor").get_by_role("button", name="Remove")).to_have_count(0)


def test_a_new_plot_is_derived_moved_and_removed(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis derive"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("cumulative")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_role("button", name="Add plot").click()
    derived = "Cumulative aggregate of North sensor"
    expect(stat(page, derived, "max")).to_have_text("100")
    expect(stat(page, derived, "min")).to_have_text("10")
    # A canvas of its own.
    page.get_by_role("button", name="New canvas").click()
    page.get_by_label(f"{derived} canvas").select_option("2")
    expect(page.locator("[data-testid='series-canvas-2'] path[data-plot]")).to_have_count(1)
    expect(page.locator("[data-testid='series-canvas-1'] path[data-plot]")).to_have_count(3)
    page.get_by_label(f"{derived} line", exact=True).select_option("dashed")
    expect(page.locator("[data-testid='series-canvas-2'] path[data-plot]")).to_have_attribute(
        "stroke-dasharray", "5 3")
    # A plot derived from the derived one goes with it.
    page.get_by_label("New plot").select_option("derivative")
    page.get_by_label("Input plot").select_option(label=derived)
    page.get_by_role("button", name="Add plot").click()
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(5)
    page.get_by_label(f"Remove {derived}").click()
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)


def test_the_plot_types_offered_are_the_builder_s(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis types", plotTypes=["derivative", "shift"]))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    options = page.get_by_label("New plot").locator("option")
    expect(options).to_have_text(["New plot…", "Derivative", "Shift time series"])


def test_the_panel_names_the_set_and_the_property(page, api, module) -> None:
    mod = build(api, module, "Analysis panel", objectSetVariable=None, property=None)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    page.get_by_label("Series object set").select_option("v_all")
    page.get_by_label("Series property").select_option("readings")
    page.get_by_test_id("series-plot-type-integral").uncheck()
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert (props["objectSetVariable"], props["property"]) == ("v_all", "readings")
    assert "integral" not in props["plotTypes"] and "derivative" in props["plotTypes"]


def test_a_filtered_and_a_sampled_plot(page, api, module) -> None:
    """p.393's Filter time series and Sample (§648). North reads 10, 20, 30
    and 40 on four days: kept above 15 it is 20 to 40, and sampled every twelve
    hours from the reading before, 10, 10, 20, 20, 30, 30, 40."""
    open_module(page, build(api, module, "Analysis filter sample"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("filter")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Transform 1 value").fill("15")
    page.get_by_role("button", name="Add plot").click()
    filtered = "Filter time series of North sensor"
    expect(stat(page, filtered, "min")).to_have_text("20")
    expect(stat(page, filtered, "max")).to_have_text("40")
    page.get_by_label("New plot").select_option("sample")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Transform 1 step").fill("12")
    page.get_by_role("button", name="Add plot").click()
    expect(stat(page, "Sample of North sensor", "mean")).to_have_text("22.857")


def test_bollinger_bands_around_a_moving_average(page, api, module) -> None:
    """p.393's Bollinger bands (§649), over two days: North's moving average
    is 10, 15, 20, 30, its standard deviation -, 7.07, 10, 10, so twice that
    either side puts the upper band at most 50 and the lower at least 0."""
    open_module(page, build(api, module, "Analysis bands"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("bollinger")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Bands window").fill("2")
    page.get_by_label("Bands unit").select_option("day")
    page.get_by_role("button", name="Add plot").click()
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(6)
    expect(stat(page, "Moving average of North sensor", "max")).to_have_text("30")
    expect(stat(page, "Upper Bollinger band of North sensor", "max")).to_have_text("50")
    expect(stat(page, "Upper Bollinger band of North sensor", "min")).to_have_text("29.142")
    expect(stat(page, "Lower Bollinger band of North sensor", "min")).to_have_text("0")


def test_two_sensors_combined_by_their_maximum(page, api, module) -> None:
    """p.393's Combine time series (§650). North reads 10-40 and South 900 on
    the first two days; where they meet the maximum is South's, and on the
    3rd and 4th only North reads."""
    open_module(page, build(api, module, "Analysis combine"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("combine")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Combine by").select_option("max")
    page.get_by_label("Combine with South sensor").check()
    page.get_by_role("button", name="Add plot").click()
    combined = "North sensor combined with South sensor"
    expect(stat(page, combined, "min")).to_have_text("30")
    expect(stat(page, combined, "max")).to_have_text("900")
    expect(stat(page, combined, "mean")).to_have_text("467.5")


def test_an_event_set_is_counted_and_highlighted(page, api, module) -> None:
    """p.392's Time series search and p.395's Event count and Event highlight
    (§651). North at least 25 is one run, its last two readings; below 25 is
    the other run; and South, flat at 900, is never above 1000."""
    open_module(page, build(api, module, "Analysis events"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)

    def add(plot: str, op: str, value: str) -> None:
        page.get_by_role("button", name="New event set").click()
        page.get_by_label("Event plot").select_option(label=plot)
        page.get_by_label("Event comparison").select_option(op)
        page.get_by_label("Event threshold").fill(value)
        page.get_by_role("button", name="Add event set").click()

    add("North sensor", "gte", "25")
    add("South sensor", "gt", "1000")
    # Not equal to 20 is two runs, the 10 and then the 30 and 40.
    add("North sensor", "neq", "20")
    sets = page.locator("[data-testid='series-event-sets'] tbody tr")
    expect(sets).to_have_count(3)
    count = lambda label: page.locator(  # noqa: E731
        f"[data-testid='series-event-sets'] tr[data-label='{label}'] td[data-stat='events']")
    expect(count("North sensor at least 25")).to_have_text("1")
    expect(count("South sensor above 1000")).to_have_text("0")
    expect(count("North sensor not equal to 20")).to_have_text("2")
    shaded = page.locator("[data-testid='series-canvas-1'] rect[data-event-set='events-1']")
    expect(shaded).to_have_count(1)
    assert float(shaded.get_attribute("width")) > 2
    page.get_by_label("Highlight North sensor at least 25").uncheck()
    expect(shaded).to_have_count(0)
    page.get_by_label("Remove South sensor above 1000").click()
    expect(sets).to_have_count(2)


def test_statistics_per_event(page, api, module) -> None:
    """p.393's Event statistics (§652). South is at least 900 on the 1st and
    2nd, one event; North's average over it is 15, its readings then being 10
    and 20."""
    open_module(page, build(api, module, "Analysis event statistics"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_role("button", name="New event set").click()
    page.get_by_label("Event plot").select_option(label="South sensor")
    page.get_by_label("Event comparison").select_option("gte")
    page.get_by_label("Event threshold").fill("900")
    page.get_by_role("button", name="Add event set").click()
    page.get_by_label("New plot").select_option("event_statistics")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Statistic").select_option("avg")
    page.get_by_role("button", name="Add plot").click()
    label = "avg of North sensor per event of South sensor at least 900"
    expect(stat(page, label, "mean")).to_have_text("15")
    expect(stat(page, label, "max")).to_have_text("15")


def test_a_linear_aggregation_lines_the_series_up(page, api, module) -> None:
    """p.393's Linear aggregation (§653). South shifted twelve hours later
    reads 900 at noon on the 1st and 2nd, between North's readings: North
    stands at 15 and 25 there on the line between its own, so the sum peaks at
    925 - where combining would only add the points that meet. Before South
    begins, midnight on the 1st is North's 10 alone."""
    open_module(page, build(api, module, "Analysis linear"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("shift")
    page.get_by_label("Input plot").select_option(label="South sensor")
    page.get_by_label("Transform 1 shift").fill("12")
    page.get_by_label("Transform 1 unit").select_option("hour")
    page.get_by_role("button", name="Add plot").click()
    shifted = "Shift time series of South sensor"
    expect(stat(page, shifted, "max")).to_have_text("900")
    page.get_by_label("New plot").select_option("linear_aggregate")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Combine by").select_option("sum")
    page.get_by_label(f"Combine with {shifted}").check()
    page.get_by_role("button", name="Add plot").click()
    lined = f"Linear aggregation of North sensor with {shifted}"
    expect(stat(page, lined, "max")).to_have_text("925")
    expect(stat(page, lined, "min")).to_have_text("10")


VISITS = (
    b"visit_id,sensor_id,began,ended\n"
    b"V1,S1,2026-01-02T00:00:00,2026-01-03T00:00:00\n"
    b"V2,S1,2026-01-04T00:00:00,\n"
    b"V3,S2,2026-01-01T00:00:00,2026-01-02T00:00:00\n"
    b"V4,S3,,2026-01-02T00:00:00\n"
)


def visit_type(mod, module) -> tuple[dict, dict]:
    """Visits to the sensors, each linked to its sensor, from `began` to
    `ended`."""
    visits = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"visits_{mod.tag}", VISITS)
    visit = mod.api.call("POST", f"/workspaces/{mod.workspace_id}/object-types", {
        "api_name": f"visit_{mod.tag}", "display_name": f"Visit {mod.tag}",
        "properties": [{"api_name": "sensor_id", "display_name": "Sensor", "data_type": "string"},
                       {"api_name": "began", "display_name": "Began", "data_type": "timestamp"},
                       {"api_name": "ended", "display_name": "Ended", "data_type": "timestamp"}]})
    source = mod.api.call("POST", f"{mod.base}/object-type-sources", {
        "object_type_id": visit["id"], "dataset_id": visits["id"], "primary_key_column": "visit_id",
        "column_mappings": {"sensor_id": "sensor_id", "began": "began", "ended": "ended"}})
    mod.api.call("POST", f"{mod.base}/object-type-sources/{source['id']}/sync", {})
    link = mod.api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"visited_{mod.tag}", "display_name": "Visited",
        "from_type_id": visit["id"], "to_type_id": module.sensor_type, "cardinality": "one_to_many",
        "from_property": "sensor_id", "to_property": "$primary_key",
        "from_side_name": "Visits", "to_side_name": "Sensor"})
    return visit, link


def test_a_linked_event_set_is_the_visits_to_a_sensor(page, api, module) -> None:
    """p.393's Linked event set (§654). Visits link to their sensor, each
    from its began to its ended timestamp: North has two - one a day long,
    one with no end, a moment - and South's is its own."""
    mod = build(api, module, "Analysis linked events")
    _, link = visit_type(mod, module)
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_role("button", name="New linked event set").click()
    page.get_by_label("Linked from plot").select_option(label="North sensor")
    page.get_by_label("Event link").select_option(f"{link['id']}:inbound")
    page.get_by_label("Event start").select_option("began")
    page.get_by_label("Event end").select_option("ended")
    page.get_by_role("button", name="Add linked event set").click()
    count = page.locator("[data-testid='series-event-sets'] tr[data-label='Visits of North sensor'] "
                         "td[data-stat='events']")
    expect(count).to_have_text("2")
    shaded = page.locator("[data-testid='series-canvas-1'] rect[data-event-set='events-1']")
    expect(shaded).to_have_count(2)
    # A day on a three-day axis is a third of it; the moment is the least drawn.
    widths = sorted(float(w) for w in shaded.evaluate_all("rs => rs.map(r => r.getAttribute('width'))"))
    assert widths[0] == 2 and widths[1] > 100
    # With no end, South's one visit is still one event, a moment.
    page.get_by_role("button", name="New linked event set").click()
    page.get_by_label("Linked from plot").select_option(label="South sensor")
    page.get_by_label("Event link").select_option(f"{link['id']}:inbound")
    page.get_by_label("Event start").select_option("began")
    page.get_by_role("button", name="Add linked event set").click()
    expect(page.locator("[data-testid='series-event-sets'] tr[data-label='Visits of South sensor'] "
                        "td[data-stat='events']")).to_have_text("1")
    # Event statistics aggregates over a search's events, not a linked set's.
    page.get_by_label("New plot").select_option("event_statistics")
    expect(page.get_by_test_id("series-event-statistics")).to_contain_text("Add an event set first")


def test_a_plot_s_line_gradient_and_points(page, api, module) -> None:
    """p.394's Display (§655): line width, gradient shading, and points by
    shape and size, with p.395's point fill and outline - each only offered
    where it applies."""
    open_module(page, build(api, module, "Analysis display"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    canvas = page.locator("[data-testid='series-canvas-1']")
    north_id = plot_row(page, "North sensor").get_attribute("data-plot")
    south_id = plot_row(page, "South sensor").get_attribute("data-plot")
    north = canvas.locator(f"path[data-plot='{north_id}']")
    page.get_by_label("North sensor line width").fill("4")
    expect(north).to_have_attribute("stroke-width", "4")
    expect(canvas.locator("[data-gradient]")).to_have_count(0)
    page.get_by_label("North sensor gradient").check()
    expect(canvas.locator(f"[data-gradient='{north_id}']")).to_have_count(1)
    assert canvas.locator(f"[data-gradient='{north_id}']").get_attribute("d").endswith("Z")
    # No points until a shape is chosen, and nothing of them to set.
    expect(canvas.locator("[data-points]")).to_have_count(0)
    expect(page.get_by_label("North sensor point size")).to_be_disabled()
    expect(page.get_by_label("North sensor point fill")).to_be_disabled()
    page.get_by_label("North sensor point shape").select_option("square")
    points = canvas.locator(f"path[data-points='{north_id}']")
    # Four readings, four squares.
    expect(points).to_have_attribute("d", re.compile(r"^(M[^M]*h[^M]*Z){4}$"))
    page.get_by_label("North sensor point size").fill("10")
    expect(points).to_have_attribute("d", re.compile(r"h10\.0v10\.0"))
    expect(page.get_by_label("North sensor point outline")).to_be_disabled()
    page.get_by_label("North sensor point fill").select_option("white")
    expect(points).to_have_attribute("fill", "#fff")
    page.get_by_label("North sensor point outline").fill("3")
    expect(points).to_have_attribute("stroke-width", "3")
    # Another plot is as it was.
    expect(canvas.locator(f"path[data-plot='{south_id}']")).to_have_attribute("stroke-width", "1.6")


def test_axes_their_range_scale_side_and_unit(page, api, module) -> None:
    """p.394-395's Axis options (§656). South, flat at 900, moved to an axis
    of its own on the right, leaves North's 10 to 40 the first axis; fixed at
    0 to 100 it reads 0, 50, 100 up, or down inverted, and 1 to 100 on a log
    scale is 10 half way."""
    open_module(page, build(api, module, "Analysis axes"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    axes = page.locator("[data-testid='series-axes'] tbody tr")
    expect(axes).to_have_count(1)
    canvas = page.locator("[data-testid='series-canvas-1']")
    page.get_by_label("South sensor axis").select_option("new")
    expect(axes).to_have_count(2)
    expect(canvas.locator("g[data-axis]")).to_have_count(2)
    # Two axes on the left, side by side, both on the canvas.
    beside = canvas.locator("g[data-axis='2'] text[data-tick='0']")
    expect(beside).to_have_attribute("x", "44")
    page.get_by_label("Canvas 1 axis 2 align").select_option("right")
    expect(beside).to_have_attribute("x", "596")
    expect(canvas.locator("g[data-axis='2']")).to_have_attribute("data-align", "right")
    page.get_by_label("Canvas 1 axis 2 unit").fill("kPa")
    expect(canvas.locator("g[data-axis='2'] text[data-unit]")).to_have_text("kPa")
    # A fixed range, and what it needs.
    first = canvas.locator("g[data-axis='1']")
    expect(page.get_by_label("Canvas 1 axis 1 min")).to_be_disabled()
    page.get_by_label("Canvas 1 axis 1 auto scale").uncheck()
    expect(page.get_by_test_id("series-axis-problem")).to_have_text(
        "An axis not scaled automatically needs a minimum and a maximum.")
    page.get_by_label("Canvas 1 axis 1 min").fill("0")
    page.get_by_label("Canvas 1 axis 1 max").fill("100")
    expect(page.get_by_test_id("series-axis-problem")).to_have_count(0)
    tick = lambda f: first.locator(f"text[data-tick='{f}']")  # noqa: E731
    expect(tick(0)).to_have_text("0")
    expect(tick(0.5)).to_have_text("50")
    expect(tick(1)).to_have_text("100")
    page.get_by_label("Canvas 1 axis 1 invert").check()
    expect(tick(1)).to_have_text("0")
    page.get_by_label("Canvas 1 axis 1 invert").uncheck()
    page.get_by_label("Canvas 1 axis 1 min").fill("1")
    page.get_by_label("Canvas 1 axis 1 log scale").check()
    expect(tick(0.5)).to_have_text("10")
    # South's own axis is untouched: flat at 900, padded either side.
    expect(canvas.locator("g[data-axis='2'] text[data-tick='0.5']")).to_have_text("900")


def test_an_axis_converts_its_readings_to_another_unit(page, api, module) -> None:
    """p.394's "Allows unit conversion (for example, meters to kilometers) or
    custom label overrides" (§733). South reads a flat 900; said to be metres
    and shown in kilometres, its axis, its line's scale and its statistics
    read 0.9 - and another plot's axis is untouched."""
    open_module(page, build(api, module, "Analysis units"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("South sensor axis").select_option("new")
    canvas = page.locator("[data-testid='series-canvas-1']")
    expect(stat(page, "South sensor", "max")).to_have_text("900")
    page.get_by_label("Canvas 1 axis 2 unit").fill("m")
    page.get_by_label("Canvas 1 axis 2 display as").fill("km")
    expect(canvas.locator("g[data-axis='2'] text[data-unit]")).to_have_text("km")
    expect(stat(page, "South sensor", "max")).to_have_text("0.9")
    expect(canvas.locator("g[data-axis='2'] text[data-tick='0.5']")).to_have_text("0.9")
    expect(stat(page, "North sensor", "max")).to_have_text("40")
    # Different kinds are said, and nothing converts.
    page.get_by_label("Canvas 1 axis 2 display as").fill("kg")
    expect(page.get_by_test_id("series-unit-problem")).to_have_text("m and kg measure different things.")
    expect(stat(page, "South sensor", "max")).to_have_text("900")
    expect(canvas.locator("g[data-axis='2'] text[data-unit]")).to_have_text("m")
    # A custom label converts nothing either, and says what conversion needs.
    page.get_by_label("Canvas 1 axis 2 unit").fill("widgets")
    expect(page.get_by_test_id("series-unit-problem")).to_contain_text("needs the readings' own unit")


def test_interpolation_inside_and_beyond_the_readings(page, api, module) -> None:
    """p.395's Interpolation (§657). North's four readings joined in steps
    turn at three more corners; held beyond them, the line runs from the
    canvas's left edge to its right; with no line, its readings are circles."""
    open_module(page, build(api, module, "Analysis interpolation"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    north_id = plot_row(page, "North sensor").get_attribute("data-plot")
    canvas = page.locator("[data-testid='series-canvas-1']")
    north = canvas.locator(f"path[data-plot='{north_id}']")
    corners = lambda: north.get_attribute("d").count("L")  # noqa: E731
    expect(north).to_have_attribute("d", re.compile(r"^M[^L]*(L[^L]*){3}$"))
    page.get_by_label("North sensor internal interpolation").select_option("previous")
    expect(north).to_have_attribute("d", re.compile(r"^M[^L]*(L[^L]*){6}$"))
    page.get_by_label("North sensor external interpolation").select_option("nearest")
    expect(north).to_have_attribute("d", re.compile(r"^M0\.0,.*L584\.0,[^L]*$"))
    assert corners() == 8
    page.get_by_label("North sensor internal interpolation").select_option("none")
    expect(north).to_have_attribute("d", "")
    expect(canvas.locator(f"path[data-points='{north_id}']")).to_have_attribute(
        "d", re.compile(r"^(M[^M]*a[^M]*Z){4}$"))


def with_visits(api, module, name: str, **props) -> Module:
    """`build`'s analysis, plus an object set of every visit, and `props`."""
    mod = build(api, module, name)
    visit, _ = visit_type(mod, module)
    definition = mod.definition()
    definition["variables"]["v_visits"] = {"id": "v_visits", "kind": "object_set", "label": "Visits",
                                           "object_set": object_set(visit["id"])}
    definition["layout"]["tsa"]["props"].update(props)
    mod.define(definition)
    return mod


def test_initial_event_sets_the_builder_gives(page, api, module) -> None:
    """p.396's Add initial event sets (§658): every visit with a start is an
    event - three of the four - shaded on every canvas; the reader can hide
    the set but not remove it."""
    mod = with_visits(api, module, "Analysis initial events", eventSets=[
        {"objectSetVariable": "v_visits", "start": "began", "end": "ended", "label": "All visits"}])
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    row = page.locator("[data-testid='series-event-sets'] tr[data-label='All visits']")
    expect(row.locator("td[data-stat='events']")).to_have_text("3")
    expect(row.get_by_role("button")).to_have_count(0)
    shaded = page.locator("[data-testid='series-canvas-1'] rect[data-event-set='initial-1']")
    expect(shaded).to_have_count(3)
    # On a new canvas too, once a plot is there: South reads on the 1st and
    # 2nd only, so the visit on the 4th is past its canvas's end.
    page.get_by_role("button", name="New canvas").click()
    page.get_by_label("South sensor canvas").select_option("2")
    expect(page.locator("[data-testid='series-canvas-2'] rect[data-event-set='initial-1']")).to_have_count(2)
    page.get_by_label("Highlight All visits").uncheck()
    expect(shaded).to_have_count(0)


def test_new_plots_placed_and_event_set_types_offered(page, api, module) -> None:
    """p.396's New plot placement and Customize available event set types
    (§658): a new plot goes on a canvas of its own, and only a time series
    search is offered."""
    open_module(page, build(api, module, "Analysis placement", newPlotCanvas="new",
                            eventSetTypes=["search"]))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    expect(page.get_by_role("button", name="New event set")).to_have_count(1)
    expect(page.get_by_role("button", name="New linked event set")).to_have_count(0)
    page.get_by_label("New plot").select_option("derivative")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_role("button", name="Add plot").click()
    expect(page.locator("[data-testid='series-canvas-2'] path[data-plot]")).to_have_count(1)


def test_the_panel_sets_the_plot_options(page, api, module) -> None:
    mod = with_visits(api, module, "Analysis plot options")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    page.get_by_label("New plot placement").select_option("3")
    page.get_by_label("Offer Linked event set").uncheck()
    page.get_by_role("button", name="Add initial event set").click()
    page.get_by_label("Initial event set 1 object set").select_option("v_visits")
    page.get_by_label("Initial event set 1 start").select_option("began")
    # Another set's type has other properties: its start is chosen afresh.
    page.get_by_label("Initial event set 1 object set").select_option("v_all")
    page.get_by_label("Initial event set 1 object set").select_option("v_visits")
    expect(page.get_by_label("Initial event set 1 start")).to_have_value("")
    page.get_by_label("Initial event set 1 start").select_option("began")
    page.get_by_label("Initial event set 1 label").fill("Visits")
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert props["newPlotCanvas"] == 3
    assert props["eventSetTypes"] == ["search"]
    assert props["eventSets"] == [
        {"objectSetVariable": "v_visits", "start": "began", "end": "", "label": "Visits"}]


def view_button(page, canvas: int, what: str):
    return page.get_by_label(f"Canvas {canvas} {what}")


def time_tick(page, canvas: int, f: str):
    return page.locator(f"[data-testid='series-canvas-{canvas}'] text[data-time='{f}']")


@pytest.fixture
def tokyo_page(browser, token: str, request):
    yield from _signed_in(browser, token, request, timezone_id="Asia/Tokyo")


def test_zooming_and_panning_narrow_the_statistics(tokyo_page, api, module) -> None:
    """p.395's statistics and event count are "within the current view
    range" (§659). North reads 10 to 40 on the 1st to the 4th: zoomed in on
    the middle it reads 20 and 30, and panned back half a view, 10 and 20.
    The times are the reader's own, here Tokyo's, nine hours ahead of UTC."""
    page = tokyo_page
    open_module(page, build(api, module, "Analysis view"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_role("button", name="New event set").click()
    page.get_by_label("Event plot").select_option(label="North sensor")
    page.get_by_label("Event comparison").select_option("gte")
    page.get_by_label("Event threshold").fill("25")
    page.get_by_role("button", name="Add event set").click()
    events = page.locator("[data-testid='series-event-sets'] tr[data-label='North sensor at least 25'] "
                          "td[data-stat='events']")
    expect(events).to_have_text("1")
    expect(time_tick(page, 1, "0")).to_have_text("2026-01-01")
    view_button(page, 1, "zoom in").click()
    expect(stat(page, "North sensor", "min")).to_have_text("20")
    expect(stat(page, "North sensor", "max")).to_have_text("30")
    # 18:00 UTC on the 1st.
    expect(time_tick(page, 1, "0")).to_have_text("01-02 03:00")
    # The value axis scales to what is in view: North's 20 to South's 900,
    # padded, where Patchy's 5 on the 1st at midnight is not.
    expect(page.locator("[data-testid='series-canvas-1'] g[data-axis='1'] text[data-tick='0']")).to_have_text("-24")
    expect(events).to_have_text("1")
    view_button(page, 1, "earlier").click()
    expect(stat(page, "North sensor", "min")).to_have_text("10")
    expect(stat(page, "North sensor", "max")).to_have_text("20")
    expect(events).to_have_text("0")
    view_button(page, 1, "reset view").click()
    expect(stat(page, "North sensor", "max")).to_have_text("40")
    view_button(page, 1, "zoom in").click()
    view_button(page, 1, "zoom out").click()
    expect(time_tick(page, 1, "0")).to_have_text("2026-01-01")
    # The reader's own time carries no UTC label.
    expect(time_tick(page, 1, "1")).to_have_text("2026-01-04")


def test_a_fixed_default_view_synced_across_canvases_in_utc(page, api, module) -> None:
    """p.396's Default view range from two variables, Sync X-axes across
    canvases, and Enable UTC time format (§659)."""
    mod = build(api, module, "Analysis fixed view")
    definition = mod.definition()
    definition["layout"]["tsa"]["props"].update(viewRange="fixed", windowStartVariable="v_from",
                                                windowEndVariable="v_to", syncXAxes=True, utc=True)
    definition["variables"].update({
        "v_from": {"id": "v_from", "kind": "timestamp", "label": "From", "default": "2026-01-02T00:00:00Z"},
        "v_to": {"id": "v_to", "kind": "timestamp", "label": "To", "default": "2026-01-03T00:00:00Z"}})
    mod.define(definition)
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    expect(stat(page, "North sensor", "min")).to_have_text("20")
    expect(stat(page, "North sensor", "max")).to_have_text("30")
    expect(time_tick(page, 1, "1")).to_have_text("01-03 00:00 UTC")
    page.get_by_role("button", name="New canvas").click()
    page.get_by_label("South sensor canvas").select_option("2")
    expect(time_tick(page, 2, "0")).to_have_text("01-02 00:00")
    view_button(page, 2, "zoom in").click()
    expect(time_tick(page, 1, "0")).to_have_text("01-02 06:00")
    expect(time_tick(page, 2, "0")).to_have_text("01-02 06:00")
    view_button(page, 1, "reset view").click()
    expect(time_tick(page, 2, "0")).to_have_text("01-02 00:00")


def test_the_panel_sets_the_view_options(page, api, module) -> None:
    mod = build(api, module, "Analysis view options")
    definition = mod.definition()
    definition["variables"]["v_from"] = {"id": "v_from", "kind": "date", "label": "From"}
    mod.define(definition)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    page.get_by_label("Default view range").select_option("relative")
    page.get_by_label("View range length").fill("3")
    page.get_by_label("View range unit").select_option("day")
    page.get_by_label("Default view range").select_option("fixed")
    page.get_by_label("View from variable").select_option("v_from")
    page.get_by_label("Sync X-axes across canvases").check()
    page.get_by_label("Enable UTC time format").check()
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert (props["viewRange"], props["windowStartVariable"], props["relativeAmount"],
            props["relativeUnit"], props["syncXAxes"], props["utc"]) == (
        "fixed", "v_from", 3, "day", True, True)


def point_at(page, canvas: int, x: float, y: float) -> None:
    """The pointer at (x, y) of the canvas's 640 by 200 drawing."""
    box = page.locator(f"[data-testid='series-canvas-{canvas}'] svg").bounding_box()
    page.mouse.move(box["x"] + box["width"] * x / 640, box["y"] + box["height"] * y / 200)


def test_the_tooltip_every_value_or_the_hovered_one(page, api, module) -> None:
    """p.396's Tooltip options (§660). A third of the way along, midnight on
    the 2nd, North reads 20 and South 900, and Patchy's nearest reading is
    its 5 of the 1st."""
    mod = build(api, module, "Analysis tooltip", utc=True)
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    tip = page.get_by_test_id("series-tooltip-1")
    expect(tip).to_have_count(0)
    # One left axis: the frame runs from 48 to 632.
    point_at(page, 1, 48 + 584 / 3, 100)
    expect(tip.locator("[data-time]")).to_have_text("01-02 00:00 UTC")
    expect(tip.locator("[data-plot]")).to_have_text(["■ North sensor: 20", "■ South sensor: 900", "■ Patchy sensor: 5"])
    page.mouse.move(0, 0)
    expect(tip).to_have_count(0)


def test_the_hovered_plot_s_value_alone_to_its_digits(page, api, module) -> None:
    mod = build(api, module, "Analysis tooltip hovered",
                tooltip={"values": "hovered", "digits": 1, "time": False})
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    tip = page.get_by_test_id("series-tooltip-1")
    # Near the top of the frame, where South's 900 is drawn.
    point_at(page, 1, 48 + 584 / 3, 12)
    expect(tip.locator("[data-plot]")).to_have_text(["■ South sensor: 900"])
    expect(tip.locator("[data-time]")).to_have_count(0)
    # Near the foot, North's 20 is drawn at about 169 and Patchy's 5 at about
    # 172, so above both it is North's; to one significant digit, 20.
    point_at(page, 1, 48 + 584 / 3, 165)
    expect(tip.locator("[data-plot]")).to_have_text(["■ North sensor: 20"])


def test_no_tooltip_when_the_builder_hides_it(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis tooltip hidden", tooltip={"show": False}))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    point_at(page, 1, 48 + 584 / 3, 100)
    page.wait_for_timeout(300)
    expect(page.get_by_test_id("series-tooltip-1")).to_have_count(0)
    expect(page.locator("[data-testid='series-canvas-1'] line[data-cursor]")).to_have_count(0)


def test_axes_overlaid_or_collapsed_with_their_boundaries(page, api, module) -> None:
    """p.396's Overlay Y-axes, Collapse Y-axes by default and Display Y-axes
    boundaries when collapsed (§660)."""
    open_module(page, build(api, module, "Analysis overlay", overlayYAxes=True))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    axis = page.locator("[data-testid='series-canvas-1'] g[data-axis='1']")
    expect(axis).to_have_attribute("data-overlay", "")
    # Over the frame, which starts at the edge's 8, facing in.
    expect(axis.locator("text[data-tick='0']")).to_have_attribute("x", "12")
    expect(axis.locator("text[data-tick='0']")).to_have_attribute("text-anchor", "start")
    open_module(page, build(api, module, "Analysis collapsed", collapseYAxes=True, collapsedBoundaries=True))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    expect(axis).to_have_attribute("data-collapsed", "")
    expect(axis.locator("text[data-tick]")).to_have_count(2)
    expect(axis.locator("text[data-tick='0.5']")).to_have_count(0)
    page.get_by_label("Canvas 1 expand axes").click()
    expect(axis.locator("text[data-tick]")).to_have_count(3)
    expect(axis).not_to_have_attribute("data-collapsed", "")
    page.get_by_label("Canvas 1 collapse axes").click()
    expect(axis.locator("text[data-tick]")).to_have_count(2)


def test_the_panel_sets_the_chart_options(page, api, module) -> None:
    mod = build(api, module, "Analysis chart options")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    expect(page.get_by_label("Display Y-axes boundaries when collapsed")).to_be_disabled()
    page.get_by_label("Collapse Y-axes by default").check()
    page.get_by_label("Display Y-axes boundaries when collapsed").check()
    page.get_by_label("Overlay Y-axes").check()
    page.get_by_label("Tooltip values").select_option("hovered")
    page.get_by_label("Tooltip wrap").check()
    page.get_by_label("Tooltip significant digits").fill("6")
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert (props["collapseYAxes"], props["collapsedBoundaries"], props["overlayYAxes"]) == (True, True, True)
    assert props["tooltip"] == {"show": True, "values": "hovered", "time": True, "wrap": True, "digits": 6}


def test_the_tooltip_s_significant_digits(page, api, module) -> None:
    """North over three is 6.666… on the 2nd, to two significant digits 6.7."""
    open_module(page, build(api, module, "Analysis tooltip digits", tooltip={"digits": 2}))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("formula")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_label("Transform 1 formula").fill("x / 3")
    page.get_by_role("button", name="Add plot").click()
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(4)
    point_at(page, 1, 48 + 584 / 3, 100)
    expect(page.get_by_test_id("series-tooltip-1").locator("[data-plot]").last).to_have_text(
        "■ Formula time series of North sensor: 6.7")


def test_a_reader_adds_any_object_s_series(page, api, module) -> None:
    """p.392's + Add Data (§661): with one sensor controlled by the set, the
    reader adds South's readings from the sensor type, and can remove what
    they added but not what the set gave."""
    open_module(page, build(api, module, "Analysis add data", limit=1, addData=True))
    rows = page.locator("[data-testid='series-plots'] tbody tr")
    expect(rows).to_have_count(1)
    page.get_by_role("button", name="Add data").click()
    page.get_by_label("Data source").select_option(module.sensor_type)
    page.get_by_label("Find an object").fill("sou")
    expect(page.get_by_label("Data object").locator("option")).to_have_text(["Object…", "South sensor"])
    page.get_by_label("Data object").select_option(label="South sensor")
    page.get_by_label("Data series").select_option("readings")
    page.get_by_role("button", name="Add series").click()
    expect(rows).to_have_count(2)
    expect(stat(page, "South sensor readings", "mean")).to_have_text("900")
    # Derived from like any plot.
    page.get_by_label("New plot").select_option("cumulative")
    page.get_by_label("Input plot").select_option(label="South sensor readings")
    page.get_by_role("button", name="Add plot").click()
    expect(stat(page, "Cumulative aggregate of South sensor readings", "max")).to_have_text("1800")
    expect(plot_row(page, rows.first.get_attribute("data-label")).get_by_role("button", name="Remove")).to_have_count(0)
    page.get_by_label("Remove South sensor readings").click()
    expect(rows).to_have_count(1)


def test_add_data_narrowed_to_the_builder_s_sets(page, api, module) -> None:
    """p.396's Add data options: "apply object set filters for each object
    type" - here a set of South alone."""
    mod = build(api, module, "Analysis add data sets", limit=1)
    definition = mod.definition()
    definition["variables"]["v_south"] = {
        "id": "v_south", "kind": "object_set", "label": "The south",
        "object_set": object_set(module.sensor_type, [{"property": "name", "op": "eq", "value": "South sensor"}])}
    definition["layout"]["tsa"]["props"].update(addData=True, addDataSets=[{"objectSetVariable": "v_south"}])
    mod.define(definition)
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(1)
    page.get_by_role("button", name="Add data").click()
    expect(page.get_by_label("Data source").locator("option")).to_have_text(["The south"])
    expect(page.get_by_label("Data object").locator("option")).to_have_text(["Object…", "South sensor"])


def test_no_add_data_unless_the_builder_allows_it(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis no add data"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    expect(page.get_by_role("button", name="Add data")).to_have_count(0)


def test_the_panel_sets_the_add_data_options(page, api, module) -> None:
    mod = build(api, module, "Analysis add data options")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    page.get_by_label("Enable add data").check()
    page.get_by_role("button", name="Restrict to an object set").click()
    page.get_by_label("Add data set 1", exact=True).select_option("v_all")
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert props["addData"] is True
    assert props["addDataSets"] == [{"objectSetVariable": "v_all"}]


def save_as(page, name: str, visibility: str = "private") -> None:
    page.get_by_role("button", name="Save as new analysis").click()
    page.get_by_label("Analysis name").fill(name)
    page.get_by_label("Analysis visibility").select_option(visibility)
    page.get_by_test_id("series-save-analysis").get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_test_id("series-analysis-open")).to_contain_text(name)


def test_an_analysis_saved_and_opened_again(page, api, module) -> None:
    """p.397's Enable analysis saving (§662): the view is saved - a derived
    plot, its canvas and an axis's scale - and opened again over the set."""
    mod = build(api, module, "Analysis saving", saving=True)
    open_module(page, mod)
    rows = page.locator("[data-testid='series-plots'] tbody tr")
    expect(rows).to_have_count(3)
    page.get_by_label("New plot").select_option("cumulative")
    page.get_by_label("Input plot").select_option(label="North sensor")
    page.get_by_role("button", name="Add plot").click()
    page.get_by_role("button", name="New canvas").click()
    page.get_by_label("Cumulative aggregate of North sensor canvas").select_option("2")
    page.get_by_label("Canvas 1 axis 1 log scale").check()
    name = f"Sensors {mod.tag}"
    save_as(page, name)
    expect(page.get_by_test_id("series-analysis-open")).to_have_text(f"{name} (private)")
    # A fresh page is the set's plots alone, until the analysis is opened.
    open_module(page, mod)
    expect(rows).to_have_count(3)
    page.get_by_role("button", name="Open analysis").click()
    page.get_by_label(f"Open {name}").click()
    expect(rows).to_have_count(4)
    expect(page.locator("[data-testid='series-canvas-2'] path[data-plot]")).to_have_count(1)
    expect(page.get_by_label("Canvas 1 axis 1 log scale")).to_be_checked()
    # Saved over: the derived plot removed, and gone when opened again.
    page.get_by_label("Remove Cumulative aggregate of North sensor").click()
    page.get_by_role("button", name="Save analysis").click()
    open_module(page, mod)
    page.get_by_role("button", name="Open analysis").click()
    page.get_by_label(f"Open {name}").click()
    expect(page.get_by_test_id("series-analysis-open")).to_have_text(f"{name} (private)")
    expect(rows).to_have_count(3)
    # One name once.
    save_as_button = page.get_by_role("button", name="Save as new analysis")
    save_as_button.click()
    page.get_by_label("Analysis name").fill(name)
    page.get_by_test_id("series-save-analysis").get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_test_id("series-save-analysis").get_by_role("alert")).to_contain_text("already have")


def test_a_public_analysis_another_reader_opens_but_cannot_save_over(page, viewer_page, api, module) -> None:
    mod = build(api, module, "Analysis shared", saving=True)
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    public, private = f"Shared {mod.tag}", f"Mine {mod.tag}"
    save_as(page, public, "public")
    # Saved over, it stays shared.
    page.get_by_role("button", name="Save analysis").click()
    expect(page.get_by_test_id("series-analysis-open")).to_have_text(f"{public} (public)")
    save_as(page, private)
    # A viewer has no builder to preview out of: the module's address is the app.
    viewer_page.goto(f"{WEB_BASE}{mod.url}")
    settled(viewer_page)
    viewer_page.get_by_role("button", name="Open analysis").click()
    listed = viewer_page.locator("[data-testid='series-open-analysis'] tbody tr")
    expect(listed.filter(has_text=public)).to_have_count(1)
    expect(listed.filter(has_text=private)).to_have_count(0)
    viewer_page.get_by_label(f"Open {public}").click()
    expect(viewer_page.get_by_test_id("series-analysis-open")).to_contain_text(f"{public} (public, by ")
    expect(viewer_page.get_by_role("button", name="Save analysis")).to_have_count(0)
    viewer_page.get_by_role("button", name="Save as new analysis").click()
    expect(viewer_page.get_by_label("Analysis name")).to_have_value(f"{public} copy")


def test_saving_over_does_not_close_a_save_as_new_opened_meanwhile(page, api, module) -> None:
    """A save over opens no draft, so it must not close one: finishing after
    "Save as new analysis" was opened used to clear that draft under the
    person typing into it (found as a CI flake, the Save button detaching).
    The save over is held until the draft is open, so the order is certain."""
    mod = build(api, module, "Analysis held save", saving=True)
    open_module(page, mod)
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    save_as(page, f"Held {mod.tag}")
    held = []
    page.route(re.compile(r".*/series-analyses/.*"),
               lambda route: held.append(route) if route.request.method == "PUT" else route.continue_())
    page.get_by_role("button", name="Save analysis").click()
    page.wait_for_timeout(300)
    page.get_by_role("button", name="Save as new analysis").click()
    expect(page.get_by_label("Analysis name")).to_be_visible()
    assert held, "the save over was not held"
    held[0].continue_()
    page.unroute(re.compile(r".*/series-analyses/.*"))
    page.wait_for_timeout(500)
    # Still open, and it saves.
    save_as_open = page.get_by_test_id("series-save-analysis")
    expect(save_as_open).to_be_visible()
    page.get_by_label("Analysis name").fill(f"Second {mod.tag}")
    save_as_open.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_test_id("series-analysis-open")).to_contain_text(f"Second {mod.tag}")


def test_no_saving_unless_the_builder_allows_it(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis not saved"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    expect(page.get_by_role("button", name="Open analysis")).to_have_count(0)
    expect(page.get_by_role("button", name="Save as new analysis")).to_have_count(0)


def test_a_fixed_save_location_offers_no_choice(page, api, module) -> None:
    open_module(page, build(api, module, "Analysis fixed location", saving=True, fixedSaveLocation=True))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_role("button", name="Save as new analysis").click()
    expect(page.get_by_label("Save location")).to_have_count(0)


def test_the_panel_sets_the_saving_options(page, api, module) -> None:
    mod = build(api, module, "Analysis saving options")
    definition = mod.definition()
    definition["variables"]["v_where"] = {"id": "v_where", "kind": "string", "label": "Where"}
    mod.define(definition)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    page.get_by_label("Enable analysis saving").check()
    page.get_by_label("Default save location variable").select_option("v_where")
    page.get_by_label("Don't allow users to choose save location").check()
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert (props["saving"], props["saveProjectVariable"], props["fixedSaveLocation"]) == (True, "v_where", True)


def saved_analysis(mod: Module, name: str, plots: list[dict], **extra) -> str:
    """An analysis saved through the API, as a reader's Save would."""
    made = mod.api.call("POST", f"{mod.base}/series-analyses",
                        {"name": name, "visibility": extra.pop("visibility", "private"),
                         "state": {"plots": plots, "canvases": extra.pop("canvases", 0), "eventSets": [],
                                   "axes": {}}})
    return made["id"]


def derived(plot_id: str, parent: str, label: str, kind: str, canvas: int = 1) -> dict:
    transform = {"kind": "cumulative", "aggregate": "sum"} if kind == "cumulative" else {"kind": kind, "unit": "day"}
    return {"id": plot_id, "label": label, "canvas": canvas, "style": "solid", "root": None, "parent": parent,
            "transforms": [transform]}


def with_autoload(api, module, name: str, rid, **props) -> tuple[Module, str, str]:
    """An analysis loading the RIDs a variable names, writing the open one's
    to `v_out`, with a button that names the second analysis instead."""
    mod = build(api, module, name)
    north = api.call("POST", "/workspaces/{}/object-sets/evaluate".format(mod.workspace_id),
                     {"definition": object_set(module.sensor_type), "limit": 5})
    ids = {i["properties"]["name"]: i["id"] for i in north["instances"]}
    first = saved_analysis(mod, f"First {mod.tag}", [
        derived("plot-4", f"root:{ids['North sensor']}", "Running North", "cumulative", 2)], canvases=2)
    second = saved_analysis(mod, f"Second {mod.tag}", [
        derived("plot-4", f"root:{ids['South sensor']}", "South change", "derivative")])
    definition = mod.definition()
    definition["layout"] = layout({
        "tsa": {"resolvedName": "CanvasSeriesAnalysis", "props": {
            **definition["layout"]["tsa"]["props"], "saving": True, "outputVariable": "v_out",
            "autoloadVariable": "v_rid", **props}},
        "out": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "OUT={{v_out}}"}},
        "next": {"resolvedName": "CanvasButton", "props": {"label": "Load the second"}},
    })
    definition["variables"].update({
        "v_out": {"id": "v_out", "kind": "string", "label": "Open analysis", "default": ""},
        "v_rid": {"id": "v_rid", "kind": "array" if isinstance(rid(first, second), list) else "string",
                  "label": "Analyses", "default": rid(first, second)},
    })
    definition["events"] = {"e_next": {"id": "e_next", "trigger": {"node": "next", "on": "click"},
                                       "effects": [{"type": "set_variable",
                                                    "config": {"variable": "v_rid", "value": second}}]}}
    mod.define(definition)
    return mod, first, second


def test_an_analysis_autoloaded_by_its_rid_and_written_out(page, api, module) -> None:
    """p.397's Autoload analyses and Output analysis RID (§663). The first
    analysis's running total of North opens on its own canvas, and its RID
    is written out; naming the second instead starts again from the set."""
    mod, first, second = with_autoload(api, module, "Analysis autoload", lambda a, b: a)
    open_module(page, mod)
    rows = page.locator("[data-testid='series-plots'] tbody tr")
    expect(rows).to_have_count(4)
    expect(plot_row(page, "Running North")).to_have_count(1)
    expect(page.locator("[data-testid='series-canvas-2'] path[data-plot]")).to_have_count(1)
    expect(page.get_by_text(f"OUT={first}")).to_be_visible()
    page.get_by_role("button", name="Load the second").click()
    expect(plot_row(page, "South change")).to_have_count(1)
    expect(plot_row(page, "Running North")).to_have_count(0)
    expect(rows).to_have_count(4)
    expect(page.get_by_text(f"OUT={second}")).to_be_visible()


def test_several_autoloaded_and_kept_on_load(page, api, module) -> None:
    """Two RIDs load both analyses together; with Don't clear on load, a new
    RID adds its analysis to what is there."""
    mod, first, second = with_autoload(api, module, "Analysis autoload two", lambda a, b: [a, b])
    open_module(page, mod)
    rows = page.locator("[data-testid='series-plots'] tbody tr")
    expect(rows).to_have_count(5)
    expect(plot_row(page, "Running North")).to_have_count(1)
    expect(plot_row(page, "South change")).to_have_count(1)
    mod2, first2, second2 = with_autoload(api, module, "Analysis kept", lambda a, b: a, keepOnLoad=True)
    open_module(page, mod2)
    expect(rows).to_have_count(4)
    page.get_by_role("button", name="Load the second").click()
    expect(rows).to_have_count(5)
    expect(plot_row(page, "Running North")).to_have_count(1)
    expect(plot_row(page, "South change")).to_have_count(1)


def test_the_panel_sets_the_autoload_options(page, api, module) -> None:
    mod = build(api, module, "Analysis autoload options")
    definition = mod.definition()
    definition["variables"].update({
        "v_out": {"id": "v_out", "kind": "string", "label": "Out"},
        "v_rids": {"id": "v_rids", "kind": "array", "label": "RIDs"}})
    mod.define(definition)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Time series analysis").first.click()
    page.get_by_label("Output analysis RID variable").select_option("v_out")
    page.get_by_label("Autoload analyses variable").select_option("v_rids")
    page.get_by_label("Don't clear on load").check()
    save(page)
    props = mod.definition()["layout"]["tsa"]["props"]
    assert (props["outputVariable"], props["autoloadVariable"], props["keepOnLoad"]) == ("v_out", "v_rids", True)


def test_a_dsp_filter_smooths_towards_the_middle(page, api, module) -> None:
    """p.393's DSP filter (§685). North's four readings rise 10 to 40; a
    low-pass filter keeps their middle (a symmetric smoothing of a straight
    line leaves its mean at 25) and pulls the ends in, which is what reducing
    noise does to a series this short."""
    open_module(page, build(api, module, "Analysis dsp"))
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(3)
    page.get_by_label("New plot").select_option("dsp")
    page.get_by_label("Input plot").select_option(label="North sensor")
    expect(page.get_by_label("Transform 1 ripple")).to_have_count(0)
    page.get_by_label("Transform 1 filter").select_option("chebyshev")
    expect(page.get_by_label("Transform 1 ripple")).to_have_value("1")
    page.get_by_label("Transform 1 filter").select_option("butterworth")
    page.get_by_label("Transform 1 cut-off").fill("0.2")
    page.get_by_role("button", name="Add plot").click()
    smoothed = "DSP filter of North sensor"
    expect(stat(page, smoothed, "mean")).to_have_text("25")
    low = float(stat(page, smoothed, "min").inner_text())
    high = float(stat(page, smoothed, "max").inner_text())
    # Pulled in from both ends by the same amount: a zero-phase filter does
    # not lag, so a line is smoothed symmetrically about its middle.
    assert 10 < low < 25 < high < 40, (low, high)
    assert abs(low + high - 50) < 0.01, (low, high)
    # And by how much the cut-off says: at 0.2 of Nyquist the ends move to
    # 21.088 and 28.912 (at the default 0.1 they would be 23.746 and 26.254).
    assert (low, high) == (21.088, 28.912), (low, high)
