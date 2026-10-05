"""An Object Table's function-backed columns (Workshop p.221; §770;
decision 0018 option B).

> "Choose Use a runtime input to pass only the objects currently displayed in
> the Object Table" … "Change what is displayed based on user input elsewhere
> in the Workshop module." (p.221)

The map and the call are `apps/api/tests/test_functions.py`'s, the column's
rules `function-columns.test.ts`'. What needs a browser is the seam: a column
on the module document becoming cells, two fields of one map from one call,
an input bound to a variable that a Numeric Input changes, and the column drawn
in the panel.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

SITES = [
    {"code": "S1", "region": "north", "capacity": "10"},
    {"code": "S2", "region": "north", "capacity": "30"},
    {"code": "S3", "region": "south", "capacity": "25"},
]


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Function columns")
    slug = f"fsite_{mod.tag}"
    sites = mod.object_type(columns=["code", "region", "capacity"], rows=SITES, key="code",
                            title="code", slug=slug, types={"capacity": "integer"})
    fn = api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
        "api_name": f"urgency_{mod.tag}", "display_name": "Urgency",
        "version": {
            "version": "1.0.0", "inputs": [sites],
            "parameters": [
                {"api_name": "shown", "data_type": "object_set", "object_type_id": sites},
                {"api_name": "cutoff", "data_type": "integer"}],
            "output": {"kind": "map", "object_type_id": sites},
            "sql": (f"SELECT __primary_key, CASE WHEN capacity > $cutoff THEN 'High' "
                    f"ELSE 'Low' END AS level, capacity * 2 AS doubled FROM {slug} "
                    "WHERE list_contains($shown, __primary_key)")}})
    # A newer version that says it louder, so a column pinned to 1.0.0 and one
    # calling the newest are told apart.
    api.call("POST", f"/workspaces/{mod.workspace_id}/functions/{fn['id']}/versions", {
        "version": "1.1.0", "inputs": [sites],
        "parameters": [
            {"api_name": "shown", "data_type": "object_set", "object_type_id": sites},
            {"api_name": "cutoff", "data_type": "integer"}],
        "output": {"kind": "map", "object_type_id": sites},
        "sql": (f"SELECT __primary_key, CASE WHEN capacity > $cutoff THEN 'HIGH' "
                f"ELSE 'LOW' END AS level FROM {slug} "
                "WHERE list_contains($shown, __primary_key)")})
    return {"api": api, "mod": mod, "sites": sites, "fn": fn}


def module(world, name: str, columns: str, declared: list | None, export: bool = False):
    mod = Module(world["api"], name, beside=world["mod"])
    definition = {
        "format": 2,
        "layout": layout({
            "num": {"resolvedName": "CanvasNumericInput",
                    "props": {"name": "v_cut", "label": "Cutoff", "grouping": False,
                              "allowReset": False, "prefix": "", "suffix": "none",
                              "suffixText": ""}},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": columns,
                              "pageSize": 25, "activeVariable": None, "autoSelect": False,
                              "exportCsv": export}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Sites",
                      "object_set": object_set(world["sites"])},
            "v_cut": {"id": "v_cut", "kind": "number", "label": "Cutoff", "default": 20},
            "v_north": {"id": "v_north", "kind": "object_set", "label": "North",
                        "object_set": object_set(world["sites"], [
                            {"property": "region", "op": "eq", "value": "north"}])},
        },
        "events": {},
    }
    if declared is not None:
        definition["derived_properties"] = {world["sites"]: declared}
    mod.define(definition)
    return mod


def column(world, api_name: str, field: str, version: str | None = "1.0.0") -> dict:
    return {"api_name": api_name, "kind": "function", "function_id": world["fn"]["id"],
            "version": version, "objects_parameter": "shown", "field": field,
            "inputs": {"cutoff": {"variable": "v_cut"}}}


def test_two_fields_of_one_map_from_one_call_following_a_variable(page, world):
    mod = module(world, "Function columns read", "code,level,doubled,newest",
                 [column(world, "level", "level"), column(world, "doubled", "doubled"),
                  column(world, "newest", "level", version=None)])
    calls = []
    page.on("request", lambda r: calls.append(r)
            if "/functions/" in r.url and r.url.endswith("/execute") else None)
    open_module(page, mod)
    expect(page.get_by_test_id("function-S2-level")).to_have_text("High", timeout=15000)
    expect(page.get_by_test_id("function-S1-level")).to_have_text("Low")
    expect(page.get_by_test_id("function-S3-doubled")).to_have_text("50")
    # The version a column names, and the newest when it names none (p.49).
    expect(page.get_by_test_id("function-S2-newest")).to_have_text("HIGH")
    # One call per version: the two 1.0.0 columns share theirs.
    assert len(calls) == 2, [c.url for c in calls]
    bodies = [json.loads(c.post_data or "{}") for c in calls]
    assert sorted(b["version"] or "newest" for b in bodies) == ["1.0.0", "newest"]
    assert sorted(bodies[0]["values"]["shown"]) == ["S1", "S2", "S3"]
    assert bodies[0]["values"]["cutoff"] == 20

    # p.221's "based on user input elsewhere in the Workshop module".
    page.get_by_role("textbox", name="Cutoff").fill("27")
    page.get_by_role("textbox", name="Cutoff").press("Tab")
    expect(page.get_by_test_id("function-S3-level")).to_have_text("Low", timeout=15000)
    expect(page.get_by_test_id("function-S2-level")).to_have_text("High")


def test_a_column_that_cannot_be_computed_is_blank_with_its_reason(page, world):
    mod = module(world, "Function columns broken", "code,level", [
        {**column(world, "level", "level"), "inputs": {}}])
    open_module(page, mod)
    cell = page.get_by_test_id("function-S1-level")
    expect(cell).to_have_attribute("title", "cutoff needs a value", timeout=15000)
    expect(page.locator("tbody tr").first).to_contain_text("S1")


def test_a_function_column_drawn_in_the_panel(page, world):
    mod = module(world, "Function columns panel", "code,lvl", None)
    open_builder(page, mod)
    settled(page)
    picker = page.get_by_test_id("derived-type")
    eventually(lambda: picker.locator("option").count(), lambda n: n >= 2,
               what="the object types this module reads")
    picker.select_option(world["sites"])
    page.get_by_test_id("derived-add-function").click()
    page.get_by_test_id("derived-name-1").fill("lvl")
    expect(page.get_by_test_id("derived-problem-1")).to_have_text(
        "Choose the function this column calls.")
    page.get_by_label("Derived property 1 function").select_option(world["fn"]["id"])
    expect(page.get_by_test_id("derived-problem-1")).to_have_text(
        "Choose the parameter that receives the table's objects, or feed it a set variable.",
        timeout=15000)
    # Only an object set of the table's type can take its objects.
    expect(page.get_by_label("Derived property 1 objects").locator("option")).to_have_text(
        ["The table's objects go to… (or a variable)", "shown"])
    page.get_by_label("Derived property 1 objects").select_option("shown")
    expect(page.get_by_test_id("derived-problem-1")).to_have_text(
        "cutoff needs a value or a variable.")
    page.get_by_label("Derived property 1 cutoff from").select_option("v_cut")
    expect(page.get_by_test_id("derived-problem-1")).to_have_count(0)
    page.get_by_label("Derived property 1 field").fill("level")
    page.get_by_label("Derived property 1 version").select_option("1.0.0")
    save(page)

    open_module(page, mod)
    expect(page.get_by_test_id("function-S2-lvl")).to_have_text("High", timeout=15000)
    expect(page.get_by_test_id("function-S1-lvl")).to_have_text("Low")


def test_a_function_column_is_in_the_tables_csv_export(page, world):
    """p.223: "Enable export to CSV … supports exporting function-backed
    columns" (§778) - every row's value, computed for the export, under the
    column's name, in the table's order."""
    mod = module(world, "Function columns export", "code,level,capacity",
                 [{**column(world, "level", "level"), "display_name": "Urgency"}], export=True)
    open_module(page, mod)
    expect(page.get_by_test_id("function-S2-level")).to_have_text("High", timeout=15000)
    page.locator("tbody tr").first.click(button="right")
    with page.expect_download() as waiting:
        page.get_by_test_id("table-export-csv").click()
    with open(waiting.value.path(), encoding="utf-8", newline="") as handle:
        assert handle.read() == (
            "Key,Code,Urgency,Capacity\r\n"
            "S1,S1,Low,10\r\nS2,S2,High,30\r\nS3,S3,High,25\r\n")


def test_a_set_variable_in_place_of_the_runtime_input(page, world):
    """p.221's "Use a variable" (§780): the function is given a module's set,
    whole, rather than the page's objects - so a row outside the set has no
    value, though the table shows it."""
    mod = module(world, "Function columns variable", "code,level", [
        {**column(world, "level", "level"), "objects_parameter": "",
         "inputs": {"cutoff": {"variable": "v_cut"}, "shown": {"variable": "v_north"}}}])
    open_module(page, mod)
    expect(page.get_by_test_id("function-S2-level")).to_have_text("High", timeout=15000)
    expect(page.get_by_test_id("function-S1-level")).to_have_text("Low")
    expect(page.get_by_test_id("function-S3-level")).to_have_text("No value")
