"""A time series formula over several series (§561; `foundry_workshop` p.586).

    "Using the Add input button, users can add new input time series - either
     time series properties or the outputs from other transforms - to the
     transform, and then build formulas using variable references to these
     inputs." (p.586)

Two sensors picked in two tables, each a time series set variable; the chart
draws the first minus the second. S1 reads 10, 20, 30, 40 on the 1st to the
4th and S2 900 on the 1st and 2nd only, so from the 3rd S2's latest reading
stands in - the as-of rule `time_series._transform_sql` states.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import layout
from conftest import WEB_BASE, eventually, open_module, settled
from test_series_variable import CHART_TITLE, build_module, caption, pick


def with_reference(api, name: str, formula: dict | None):
    """`test_series_variable`'s module, plus a second table and a second
    series variable over the sensor picked in it."""
    mod = build_module(api, name)
    definition = mod.definition()
    table = {"objectSetVariable": "v_all", "columns": "id,name", "pageSize": 25}
    definition["layout"] = layout({
        "tbl": {"resolvedName": "CanvasObjectTable", "props": table},
        "ref": {"resolvedName": "CanvasObjectTable", "props": table},
        "cht": {"resolvedName": "CanvasChart",
                "props": {"kind": "bar", "title": CHART_TITLE, "seriesVariable": "v_series"}},
    })
    definition["variables"]["v_ref"] = {"id": "v_ref", "kind": "single_object",
                                        "label": "Reference sensor"}
    definition["variables"]["v_ref_series"] = {
        "id": "v_ref_series", "kind": "time_series_set", "label": "Reference readings",
        "derivation": {"transform": "object_series", "inputs": ["v_ref"],
                       "config": {"property": "readings", "interval": "day",
                                  "aggregate": "avg"}}}
    if formula is not None:
        series = definition["variables"]["v_series"]["derivation"]
        series["inputs"] = ["v_picked", "v_ref_series"]
        series["config"]["transforms"] = [formula]
    definition["events"]["e_ref"] = {
        "id": "e_ref", "trigger": {"node": "ref", "on": "row_select"},
        "effects": [{"type": "set_variable", "config": {"variable": "v_ref", "from": "object"}}]}
    mod.define(definition)
    return mod


def pick_reference(page, name: str) -> None:
    page.locator("table").nth(1).locator("tbody tr").filter(has_text=name).first.click()


def test_a_formula_reads_a_second_series_as_of_each_point(page, api) -> None:
    mod = with_reference(api, "Series two inputs", {
        "kind": "formula", "expression": "x - y", "inputs": {"y": "v_ref_series"}})
    open_module(page, mod)
    # One series picked is half a formula, and nothing is drawn from half.
    pick(page, "North sensor")
    expect(page.get_by_test_id("chart-series-caption")).to_have_count(0)
    with page.expect_response(lambda r: "/series/readings/points" in r.url) as asked:
        pick_reference(page, "South sensor")
    assert [p["value"] for p in asked.value.json()["points"]] == [-890, -880, -870, -860]
    eventually(lambda: caption(page), lambda t: "x, y → x - y" in t,
               what="the caption naming both inputs")


def test_an_input_added_in_the_panel_is_saved_as_the_variables_input(page, api) -> None:
    mod = with_reference(api, "Series add input", None)
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("Readings", exact=True).first.click()
    transforms = page.get_by_test_id("series-transforms")
    transforms.get_by_label("Add a transform").select_option("formula")
    transforms.get_by_label("Add an input to transform 1").click()
    expect(page.get_by_test_id("series-transforms-problem")).to_have_text(
        "Transform 1: Choose a series for y.")
    # The variable being edited is not among the series it may read.
    options = transforms.get_by_label("Transform 1 input y").locator("option")
    expect(options).to_have_text(["Choose a series…", "Reference readings"])
    transforms.get_by_label("Transform 1 input y").select_option("v_ref_series")
    transforms.get_by_label("Transform 1 formula").fill("x - y")
    expect(page.get_by_test_id("series-transforms-problem")).to_have_count(0)
    # The object picked again keeps the series after it.
    slot = page.get_by_role("combobox", name=re.compile(r"^Object"))
    slot.select_option("")
    slot.select_option("v_picked")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    derivation = mod.definition()["variables"]["v_series"]["derivation"]
    assert derivation["inputs"] == ["v_picked", "v_ref_series"]
    assert derivation["config"]["transforms"] == [
        {"kind": "formula", "expression": "x - y", "inputs": {"y": "v_ref_series"}}]


def test_a_linear_aggregation_is_set_up_in_the_panel(page, api) -> None:
    """p.393's Linear aggregation (§653), in the transform editor: another
    series and the aggregate, and no unit to set."""
    mod = with_reference(api, "Series linear aggregation", None)
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("Readings", exact=True).first.click()
    transforms = page.get_by_test_id("series-transforms")
    transforms.get_by_label("Add a transform").select_option("linear_aggregate")
    expect(transforms.get_by_label("Transform 1 unit")).to_have_count(0)
    transforms.get_by_label("Transform 1 combine by").select_option("sum")
    transforms.get_by_label("Transform 1 input y").select_option("v_ref_series")
    expect(page.get_by_test_id("series-transforms-problem")).to_have_count(0)
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    derivation = mod.definition()["variables"]["v_series"]["derivation"]
    assert derivation["config"]["transforms"] == [
        {"kind": "linear_aggregate", "aggregate": "sum", "inputs": {"y": "v_ref_series"}}]
    assert "v_ref_series" in derivation["inputs"]
