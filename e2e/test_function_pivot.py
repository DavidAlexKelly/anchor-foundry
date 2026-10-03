"""The Pivot Table's function-backed form (Workshop p.335-340; §774; decision
0018 option B).

> "A function-backed pivot table derives its data from the output of a
> function." (p.335) "To render a total, return a struct in your list that
> follows the guidelines below." (p.338)

The grid's rules are `function-pivot.test.ts`'. What needs a browser: a
function's table drawn as a pivot with p.338's totals, its input following a
module variable a Numeric Input writes, and the pivot set up in the panel.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, settled
from test_chart_xy import ROWS


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Function pivot")
    slug = f"psite_{mod.tag}"
    sites = mod.object_type(columns=["id", "status", "region", "capacity"], rows=ROWS,
                            key="id", title="id", slug=slug, types={"capacity": "integer"})
    fn = api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
        "api_name": f"pivot_{mod.tag}", "display_name": "Capacity pivot",
        "version": {
            "version": "1.0.0", "inputs": [sites],
            "parameters": [{"api_name": "minimum", "data_type": "integer"}],
            "output": {"kind": "table"},
            # p.338's totals are GROUPING SETS' rows with fields left out.
            "sql": (f"SELECT region, status, sum(capacity) AS total, count(*) AS n "
                    f"FROM {slug} WHERE capacity >= $minimum "
                    "GROUP BY GROUPING SETS ((region, status), (region), (status), ()) "
                    "ORDER BY region NULLS LAST, status NULLS LAST")}})
    # A newer version that doubles, so a pivot pinned to 1.0.0 is told apart.
    api.call("POST", f"/workspaces/{mod.workspace_id}/functions/{fn['id']}/versions", {
        "version": "1.1.0", "inputs": [sites],
        "parameters": [{"api_name": "minimum", "data_type": "integer"}],
        "output": {"kind": "table"},
        "sql": (f"SELECT region, status, 2 * sum(capacity) AS total, count(*) AS n "
                f"FROM {slug} WHERE capacity >= $minimum "
                "GROUP BY GROUPING SETS ((region, status), (region), (status), ()) "
                "ORDER BY region NULLS LAST, status NULLS LAST")})
    return {"api": api, "mod": mod, "fn": fn}


def build(world, name: str, pivot: dict) -> Module:
    mod = Module(world["api"], name, beside=world["mod"])
    mod.define({
        "format": 2,
        "layout": layout({
            "num": {"resolvedName": "CanvasNumericInput",
                    "props": {"name": "v_min", "label": "Minimum", "grouping": False,
                              "allowReset": False, "prefix": "", "suffix": "none",
                              "suffixText": ""}},
            "pivot": {"resolvedName": "CanvasPivotTable", "props": {
                "objectSetVariable": None, "rowProperty": None, "columnProperty": None,
                "drilldownVariable": None, "title": "Capacity", **pivot}},
        }),
        "variables": {"v_min": {"id": "v_min", "kind": "number", "label": "Minimum",
                                "default": 0}},
        "events": {},
    })
    return mod


def lines(page) -> list[list[str]]:
    grid = page.get_by_test_id("pivot-function-grid")
    return [row.locator("th, td").all_inner_texts()
            for row in grid.locator("tbody tr").all()]


def test_a_functions_table_is_a_pivot_with_its_totals(page, world) -> None:
    mod = build(world, "Function pivot read", {
        "fn": {"function_id": world["fn"]["id"], "version": None,
               "inputs": {"minimum": {"variable": "v_min"}}},
        "fnRows": "region", "fnColumn": "status", "fnValues": "total"})
    open_module(page, mod)
    expect(page.get_by_test_id("pivot-function-grid")).to_be_visible(timeout=20000)
    expect(page.get_by_role("heading", name="Capacity")).to_be_visible()
    grid = page.get_by_test_id("pivot-function-grid")
    expect(grid.locator("thead th")).to_have_text(["region", "closed", "open", "Total"])
    # The newest version, which doubles.
    assert lines(page) == [
        ["east", "180", "", "180"],
        ["north", "", "40", "40"],
        ["south", "", "20", "20"],
        ["Total", "180", "60", "240"],
    ]
    page.get_by_role("textbox", name="Minimum").fill("15")
    page.get_by_role("textbox", name="Minimum").press("Tab")
    # Only the east site holds 15 or more; its status is the one column left.
    expect(grid.locator("tbody tr")).to_have_count(2, timeout=15000)
    expect(grid.locator("thead th")).to_have_text(["region", "closed", "Total"])
    assert lines(page) == [["east", "180", "180"], ["Total", "180", "180"]]


def test_two_values_each_get_a_column(page, world) -> None:
    mod = build(world, "Function pivot two values", {
        "fn": {"function_id": world["fn"]["id"], "version": "1.0.0",
               "inputs": {"minimum": {"value": 0}}},
        "fnRows": "region", "fnColumn": "", "fnValues": "total, n"})
    open_module(page, mod)
    grid = page.get_by_test_id("pivot-function-grid")
    expect(grid).to_be_visible(timeout=20000)
    expect(grid.locator("thead tr").nth(1).locator("th")).to_have_text(["total", "n"])
    assert lines(page) == [
        ["east", "90", "1"], ["north", "20", "2"], ["south", "10", "1"],
        ["Total", "120", "4"]]


def test_one_value_without_a_column_field_is_headed_by_its_name(page, world) -> None:
    mod = build(world, "Function pivot one way", {
        "fn": {"function_id": world["fn"]["id"], "version": "1.0.0",
               "inputs": {"minimum": {"value": 0}}},
        "fnRows": "region", "fnColumn": "", "fnValues": "total"})
    open_module(page, mod)
    grid = page.get_by_test_id("pivot-function-grid")
    expect(grid.locator("thead th")).to_have_text(["region", "total"], timeout=20000)


def test_a_field_the_function_does_not_give_is_named(page, world) -> None:
    mod = build(world, "Function pivot wrong field", {
        "fn": {"function_id": world["fn"]["id"], "version": None,
               "inputs": {"minimum": {"value": 0}}},
        "fnRows": "site", "fnColumn": "status", "fnValues": "total"})
    open_module(page, mod)
    expect(page.get_by_test_id("pivot-function-problem")).to_have_text(
        "The function gives no field site.", timeout=20000)


def test_a_function_pivot_set_up_in_the_panel(page, world) -> None:
    mod = build(world, "Function pivot panel", {})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Pivot table").first.click()
    page.get_by_label("Pivot data from").select_option("function")
    expect(page.get_by_test_id("pivot-settings-problem")).to_have_text(
        "Choose the function this pivot reads.")
    page.get_by_label("Pivot function", exact=True).select_option(world["fn"]["id"])
    expect(page.get_by_test_id("pivot-settings-problem")).to_have_text(
        "minimum needs a value or a variable.", timeout=15000)
    page.get_by_label("Pivot minimum from").select_option("v_min")
    expect(page.get_by_test_id("pivot-settings-problem")).to_have_count(0)
    page.get_by_label("Pivot row fields").fill("region")
    page.get_by_label("Pivot column field").fill("status")
    page.get_by_label("Pivot value fields").fill("total")
    save(page)
    props = mod.definition()["layout"]["pivot"]["props"]
    assert props["fn"] == {"function_id": world["fn"]["id"], "version": None,
                           "inputs": {"minimum": {"variable": "v_min"}}}
    assert (props["fnRows"], props["fnColumn"], props["fnValues"]) == (
        "region", "status", "total")

    open_module(page, mod)
    expect(page.get_by_test_id("pivot-function-grid").locator("tbody tr")).to_have_count(
        4, timeout=20000)
