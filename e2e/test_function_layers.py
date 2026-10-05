"""Chart XY's function-backed layers (Workshop p.280, p.284; §771; decision
0018 option B).

> "The Function aggregation option allows a function that returns a 2D
> Aggregation or 3D Aggregation to be used as input." (p.280)

The buckets are `apps/api/tests/test_functions.py`'s and the layer's rules
`function-layers.test.ts`'. What needs a browser: a function's buckets drawn as
a layer beside the chart's own, its input following a module variable, a 3D
aggregation stacked by its segments, and the layer set up in the panel.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled
from test_chart_xy import ROWS, dot, segment


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Chart function layers")
    slug = f"csite_{mod.tag}"
    sites = mod.object_type(columns=["id", "status", "region", "capacity"], rows=ROWS,
                            key="id", title="id", slug=slug, types={"capacity": "integer"})
    wid = mod.workspace_id
    two = api.call("POST", f"/workspaces/{wid}/functions", {
        "api_name": f"capacity_{mod.tag}", "display_name": "Capacity by status",
        "version": {"version": "1.0.0", "inputs": [sites],
                    "parameters": [{"api_name": "minimum", "data_type": "integer"}],
                    "output": {"kind": "aggregation"},
                    "sql": (f"SELECT status, sum(capacity) FROM {slug} "
                            "WHERE capacity >= $minimum GROUP BY 1")}})
    # A newer version that doubles, so a layer pinned to 1.0.0 is told apart.
    api.call("POST", f"/workspaces/{wid}/functions/{two['id']}/versions", {
        "version": "1.1.0", "inputs": [sites],
        "parameters": [{"api_name": "minimum", "data_type": "integer"}],
        "output": {"kind": "aggregation"},
        "sql": (f"SELECT status, 2 * sum(capacity) FROM {slug} "
                "WHERE capacity >= $minimum GROUP BY 1")})
    three = api.call("POST", f"/workspaces/{wid}/functions", {
        "api_name": f"regions_{mod.tag}", "display_name": "Status by region",
        "version": {"version": "1.0.0", "inputs": [sites], "output": {"kind": "aggregation"},
                    "sql": f"SELECT status, region, count(*) FROM {slug} GROUP BY 1, 2"}})
    return {"api": api, "mod": mod, "sites": sites, "two": two, "three": three}


def build(world, name: str, series: list[dict]) -> Module:
    mod = Module(world["api"], name, beside=world["mod"])
    mod.define({
        "format": 2,
        "layout": layout({
            "num": {"resolvedName": "CanvasNumericInput",
                    "props": {"name": "v_min", "label": "Minimum", "grouping": False,
                              "allowReset": False, "prefix": "", "suffix": "none",
                              "suffixText": ""}},
            "chart": {"resolvedName": "CanvasChart", "props": {
                "objectSetVariable": "v_set", "kind": "bar", "dimension": "status",
                "series": series}},
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(world["sites"])},
            "v_min": {"id": "v_min", "kind": "number", "label": "Minimum", "default": 0},
        },
        "events": {},
    })
    return mod


def test_a_functions_buckets_are_a_layer_following_its_input(page, world) -> None:
    # A stale sum and measure beside the function, as a saved document may
    # hold: the function is what the layer reads.
    mod = build(world, "Function layer read", [{
        "aggregate": "sum", "measure": "capacity", "kind": "line", "name": "Capacity",
        "fn": {"function_id": world["two"]["id"], "version": "1.0.0",
               "inputs": {"minimum": {"variable": "v_min"}}}}])
    groups = []
    page.on("request", lambda r: groups.append(r) if "/object-sets/group" in r.url else None)
    open_module(page, mod)
    # The chart's own count as bars, the function's sums as a line over them,
    # met by their labels.
    expect(segment(page, "open", "Count")).to_have_count(1, timeout=20000)
    expect(dot(page, "Capacity", "open").locator("title")).to_have_text("open · Capacity: 30")
    expect(dot(page, "Capacity", "closed").locator("title")).to_have_text(
        "closed · Capacity: 90")
    # The layer reads its function and nothing else: one group read, the
    # chart's own.
    assert len(groups) == 1, [g.url for g in groups]
    # The input follows the variable a Numeric Input writes.
    page.get_by_role("textbox", name="Minimum").fill("50")
    page.get_by_role("textbox", name="Minimum").press("Tab")
    eventually(lambda: dot(page, "Capacity", "open").count(), lambda n: n == 0,
               what="the open sites' capacity falling below the minimum")
    expect(dot(page, "Capacity", "closed").locator("title")).to_have_text(
        "closed · Capacity: 90")


def test_a_three_dimensional_aggregation_is_stacked_by_its_segments(page, world) -> None:
    mod = build(world, "Function layer 3D", [{
        "aggregate": "count", "name": "Regions",
        "fn": {"function_id": world["three"]["id"], "version": None, "inputs": {}}}])
    open_module(page, mod)
    # The chart's own two bars, and the layer's open bar stacked north and
    # south (two north, one south) beside closed's east.
    expect(segment(page, "open", "Regions · north")).to_have_count(1, timeout=20000)
    expect(segment(page, "open", "Regions · south")).to_have_count(1)
    expect(segment(page, "closed", "Regions · east")).to_have_count(1)
    expect(segment(page, "open", "Count")).to_have_count(1)
    # Piled: north is twice south, in one bar.
    north = segment(page, "open", "Regions · north").bounding_box()
    south = segment(page, "open", "Regions · south").bounding_box()
    assert north and south and abs(north["x"] - south["x"]) < 1, (north, south)
    assert abs(north["height"] - 2 * south["height"]) < 2, (north, south)


def test_a_function_layer_set_up_in_the_panel(page, world) -> None:
    mod = build(world, "Function layer panel", [])
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Chart").first.click()
    page.get_by_test_id("chart-add-series").click()
    page.get_by_test_id("chart-series-set").select_option("__function")
    expect(page.get_by_test_id("chart-series-problem")).to_have_text(
        "Choose the function this layer draws.")
    # The set's own controls go with the set.
    expect(page.get_by_test_id("chart-series-aggregate")).to_have_count(0)
    page.get_by_label("Series 2 function").select_option(world["two"]["id"])
    expect(page.get_by_test_id("chart-series-problem")).to_have_text(
        "minimum needs a value or a variable.", timeout=15000)
    page.get_by_label("Series 2 minimum from").select_option("v_min")
    expect(page.get_by_test_id("chart-series-problem")).to_have_count(0)
    page.get_by_test_id("chart-series-name").fill("Capacity")
    save(page)
    series = mod.definition()["layout"]["chart"]["props"]["series"]
    assert series[0]["fn"] == {"function_id": world["two"]["id"], "version": None,
                               "inputs": {"minimum": {"variable": "v_min"}}}, series
    assert series[0]["objectSetVariable"] is None

    open_module(page, mod)
    expect(segment(page, "closed", "Capacity")).to_have_count(1, timeout=20000)
