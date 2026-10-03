"""p.73's function-backed variables (§772; decision 0018 option B).

> "Function: For function-backed, dynamically computed variables"
> (`workshop` p.73)

The call is `apps/api/tests/test_function_variables.py`'s and the panel's rules
`function-variables.test.ts`'. What needs a browser: a number and an object set
read from functions reaching a heading and a table, each following the input a
Numeric Input writes, and a function variable built in the panel.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module, settled

ROWS = [
    {"id": "S1", "region": "north", "capacity": "10"},
    {"id": "S2", "region": "south", "capacity": "30"},
    {"id": "S3", "region": "north", "capacity": "20"},
]


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Function variables")
    slug = f"vsite_{mod.tag}"
    sites = mod.object_type(columns=["id", "region", "capacity"], rows=ROWS, key="id",
                            title="id", slug=slug, types={"capacity": "integer"})
    wid = mod.workspace_id
    minimum = [{"api_name": "minimum", "data_type": "integer"}]
    total = api.call("POST", f"/workspaces/{wid}/functions", {
        "api_name": f"beds_{mod.tag}", "display_name": "Beds",
        "version": {"version": "1.0.0", "inputs": [sites], "parameters": minimum,
                    "output": {"kind": "value", "data_type": "integer"},
                    "sql": (f"SELECT coalesce(sum(capacity), 0) FROM {slug} "
                            "WHERE capacity >= $minimum")}})
    big = api.call("POST", f"/workspaces/{wid}/functions", {
        "api_name": f"big_{mod.tag}", "display_name": "Big sites",
        "version": {"version": "1.0.0", "inputs": [sites], "parameters": minimum,
                    "output": {"kind": "object_set", "object_type_id": sites},
                    "sql": f"SELECT __primary_key FROM {slug} WHERE capacity >= $minimum"}})
    return {"api": api, "mod": mod, "sites": sites, "total": total, "big": big}


def called(fn: dict, kind: str, vid: str) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(), "derivation": {
        "transform": "function", "inputs": ["v_min"],
        "config": {"function_id": fn["id"], "version": None, "parameters": ["minimum"],
                   "values": {}}}}


def build(world, name: str) -> Module:
    mod = Module(world["api"], name, beside=world["mod"])
    mod.define({
        "format": 2,
        "layout": layout({
            "num": {"resolvedName": "CanvasNumericInput",
                    "props": {"name": "v_min", "label": "Minimum", "grouping": False,
                              "allowReset": False, "prefix": "", "suffix": "none",
                              "suffixText": ""}},
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "h2", "text": "{{beds}} beds"}},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "big", "columns": "id,capacity",
                              "pageSize": 25, "activeVariable": None, "autoSelect": False}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(world["sites"])},
            "v_min": {"id": "v_min", "kind": "number", "label": "Minimum", "default": 15},
            "beds": called(world["total"], "number", "beds"),
            "big": called(world["big"], "object_set", "big"),
            "spare": {"id": "spare", "kind": "number", "label": "Spare"},
            "pick": {"id": "pick", "kind": "single_object", "label": "Pick"},
        },
        "events": {},
    })
    return mod


def test_a_number_and_a_set_from_functions_follow_their_input(page, world) -> None:
    mod = build(world, "Function variables read")
    open_module(page, mod)
    # 30 and 20 are at least 15; the table shows the same two sites.
    expect(page.get_by_role("heading", name="50 beds")).to_be_visible(timeout=20000)
    expect(page.locator("tbody tr")).to_have_count(2)
    expect(page.locator("tbody")).not_to_contain_text("S1")
    page.get_by_role("textbox", name="Minimum").fill("25")
    page.get_by_role("textbox", name="Minimum").press("Tab")
    expect(page.get_by_role("heading", name="30 beds")).to_be_visible(timeout=15000)
    expect(page.locator("tbody tr")).to_have_count(1)
    expect(page.locator("tbody tr").first).to_contain_text("S2")


def test_the_panel_builds_a_function_variable(page, world) -> None:
    mod = build(world, "Function variables panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Spare").first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("function")
    expect(page.get_by_test_id("variable-function-problem")).to_have_text(
        "Choose the function this variable calls.")
    # Its inputs are its parameters, so no slot of the transform before it.
    expect(page.locator(".vars-derivation select", has=page.locator(
        "option", has_text="choose a variable…"))).to_have_count(0)
    # A set function is offered and refused for a number, by what it returns.
    page.get_by_test_id("variable-function").select_option(world["big"]["id"])
    expect(page.get_by_test_id("variable-function-problem")).to_have_text(
        f"big_{world['mod'].tag} returns object set, and a number variable takes value.",
        timeout=15000)
    page.get_by_test_id("variable-function").select_option(world["total"]["id"])
    expect(page.get_by_test_id("variable-function-problem")).to_have_text(
        "minimum needs a value or a variable.", timeout=15000)
    # Every variable but this one, unsaved ones included, from the panel's list.
    sources = page.get_by_label("Function minimum from").locator("option")
    expect(sources.filter(has_text="minimum: Minimum")).to_have_count(1)
    expect(sources.filter(has_text="Spare")).to_have_count(0)
    page.get_by_label("Function minimum from").select_option("v_min")
    expect(page.get_by_test_id("variable-function-problem")).to_have_count(0)
    page.get_by_test_id("variable-function-version").select_option("1.0.0")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["spare"].get("derivation"),
               lambda d: d == {"transform": "function", "inputs": ["v_min"], "config": {
                   "function_id": world["total"]["id"], "version": "1.0.0",
                   "parameters": ["minimum"], "values": {}}},
               what="the function call, saved")

    # p.80's mapping has no row for an object, so a function is not offered.
    page.locator(".vars-row", has_text="Pick").first.click()
    page.get_by_role("button", name="Make this derived").click()
    kinds = page.get_by_label("Computed by").locator("option")
    expect(kinds.filter(has_text="Join text")).to_have_count(1)
    expect(kinds.filter(has_text="A function")).to_have_count(0)


def test_a_set_from_a_function_is_built_in_the_panel(page, world) -> None:
    mod = build(world, "Function set panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Every site").first.click()
    page.get_by_test_id("set-source").select_option("function")
    expect(page.get_by_test_id("set-source")).to_have_value("function")
    page.get_by_test_id("variable-function").select_option(world["big"]["id"])
    expect(page.get_by_test_id("variable-function-problem")).to_have_text(
        "minimum needs a value or a variable.", timeout=15000)
    expect(page.get_by_label("Function minimum from").locator(
        "option", has_text="Every site")).to_have_count(0)
    page.get_by_label("Function minimum value").fill("25")
    expect(page.get_by_test_id("variable-function-problem")).to_have_count(0)
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    eventually(lambda: mod.definition()["variables"]["v_all"],
               lambda v: v.get("derivation") == {"transform": "function", "inputs": [],
                                                 "config": {
                   "function_id": world["big"]["id"], "version": None,
                   "parameters": [], "values": {"minimum": 25}}} and "object_set" not in v,
               what="the set's function, saved with its fixed minimum")
