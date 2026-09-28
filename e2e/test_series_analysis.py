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

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, save, settled
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
)


def test_a_linked_event_set_is_the_visits_to_a_sensor(page, api, module) -> None:
    """p.393's Linked event set (§654). Visits link to their sensor, each
    from its began to its ended timestamp: North has two - one a day long,
    one with no end, a moment - and South's is its own."""
    mod = build(api, module, "Analysis linked events")
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
