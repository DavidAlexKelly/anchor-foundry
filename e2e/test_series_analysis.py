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
    page.get_by_label(f"{derived} line").select_option("dashed")
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
