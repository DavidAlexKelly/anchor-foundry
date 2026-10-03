"""p.489-490's Function-backed export (§775; decision 0018 option B).

> "Function-backed exports take a Function and its inputs, and download the
> output into a specified file type." (p.489) "Text-based formats … a plain
> string representing the file content. Binary formats … a base64-encoded
> string of the file bytes." (p.490)

What the runner hands over is `events.test.ts`, the file's rules
`function-export.test.ts`, what the server accepts `test_workshop_variables.py`.
What needs a browser is the file arriving: a text file and a binary one from
a click, an input read from a module variable, a refusal said in the strip,
and the effect set up in the panel.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, settled
from test_chart_xy import ROWS


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Function export")
    slug = f"xsite_{mod.tag}"
    sites = mod.object_type(columns=["id", "status", "region", "capacity"], rows=ROWS,
                            key="id", title="id", slug=slug, types={"capacity": "integer"})
    wid = mod.workspace_id

    def fn(name: str, sql: str, parameters=None, data_type: str = "string") -> dict:
        return api.call("POST", f"/workspaces/{wid}/functions", {
            "api_name": f"{name}_{mod.tag}", "display_name": name,
            "version": {"version": "1.0.0", "inputs": [sites], "parameters": parameters or [],
                        "output": {"kind": "value", "data_type": data_type}, "sql": sql}})

    return {
        "api": api, "mod": mod,
        "csv": fn("sites_csv",
                  "SELECT 'id,capacity' || chr(10) || string_agg(__primary_key || ',' || "
                  f"capacity, chr(10) ORDER BY __primary_key) FROM {slug} WHERE region = $region",
                  [{"api_name": "region", "data_type": "string"}]),
        "pdf": fn("sites_pdf", "SELECT base64('%PDF-1.4 hi'::BLOB)"),
        "prefixed": fn("sites_prefixed", "SELECT 'data:application/pdf;base64,JVBERg=='"),
        "count": fn("sites_count", f"SELECT count(*) FROM {slug}", data_type="integer"),
    }


def build(world, name: str, config: dict) -> Module:
    mod = Module(world["api"], name, beside=world["mod"])
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Export"}},
        }),
        "variables": {"v_region": {"id": "v_region", "kind": "string", "label": "Region",
                                   "default": "north"}},
        "events": {"e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                           "effects": [{"type": "export_function", "config": config}]}},
    })
    return mod


def status(page):
    return page.locator(".canvas-action-status")


def test_a_text_file_from_a_function_reading_a_variable(page, world) -> None:
    mod = build(world, "Function export csv", {
        "function_id": world["csv"]["id"], "file_type": "csv", "file_name": "north",
        "inputs": {"region": {"variable": "v_region"}}})
    open_module(page, mod)
    with page.expect_download() as waiting:
        page.get_by_role("button", name="Export", exact=True).click()
    download = waiting.value
    assert download.suggested_filename == "north.csv"
    with open(download.path(), encoding="utf-8", newline="") as handle:
        assert handle.read() == "id,capacity\nS1,10\nS3,10"
    expect(status(page)).to_contain_text("Exported north.csv.")


def test_a_binary_file_is_the_bytes_its_base64_names(page, world) -> None:
    mod = build(world, "Function export pdf", {
        "function_id": world["pdf"]["id"], "version": "1.0.0", "file_type": "pdf"})
    open_module(page, mod)
    with page.expect_download() as waiting:
        page.get_by_role("button", name="Export", exact=True).click()
    download = waiting.value
    assert download.suggested_filename == "export.pdf"
    with open(download.path(), "rb") as handle:
        assert handle.read() == b"%PDF-1.4 hi"


def test_a_mime_prefix_is_refused_as_p490_says(page, world) -> None:
    mod = build(world, "Function export prefixed", {
        "function_id": world["prefixed"]["id"], "file_type": "pdf"})
    open_module(page, mod)
    page.get_by_role("button", name="Export", exact=True).click()
    expect(status(page)).to_contain_text(
        'Return the PDF bytes as base64 without a "data:" prefix (Workshop p.490).')


def test_the_builder_configures_a_function_backed_export(page, world) -> None:
    mod = build(world, "Function export panel", {"function_id": world["pdf"]["id"]})
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="Button · Export Clicked · 1 effect").click()
    page.get_by_label("Export function", exact=True).select_option(world["count"]["id"])
    expect(page.get_by_test_id("effect-export-function-problem")).to_have_text(
        f"sites_count_{world['mod'].tag} must return a string to export (Workshop p.490).",
        timeout=15000)
    page.get_by_label("Export function", exact=True).select_option(world["csv"]["id"])
    expect(page.get_by_test_id("effect-export-function-problem")).to_have_text(
        "region needs a value or a variable.", timeout=15000)
    page.get_by_label("Export region from").select_option("v_region")
    expect(page.get_by_test_id("effect-export-function-problem")).to_have_count(0)
    page.get_by_label("Export file type").select_option("txt")
    page.get_by_label("Export file name").fill("sites")
    save(page)
    effect = mod.definition()["events"]["e_1"]["effects"][0]
    assert effect == {"type": "export_function", "config": {
        "function_id": world["csv"]["id"], "version": None, "file_type": "txt",
        "file_name": "sites", "inputs": {"region": {"variable": "v_region"}}}}, effect
