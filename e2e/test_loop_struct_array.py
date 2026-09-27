"""A loop over an array of structs (§570; `foundry_workshop` p.132-134).

    "An array variable of any of the following types: string, number,
     boolean, date, timestamp, struct … If the array option is selected, the
     first configuration is the array to loop through variable input." (p.132-133)

    "the struct-typed interface variable renders the fields of each struct
     entry" (p.134)

Each copy receives one entry, a struct, in the child's struct variable, and
shows one field of it through `extract_struct_field`.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def child_module(api, name: str):
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"t": {"resolvedName": "CanvasText",
                                "props": {"tag": "p", "text": "crew:{{v_name}} ({{v_role}})"}}}),
        "variables": {
            "v_each": {"id": "v_each", "kind": "struct", "label": "Each",
                       "external_id": "each", "interface": {"required": False}},
            "v_name": {"id": "v_name", "kind": "string", "label": "Name", "derivation": {
                "transform": "extract_struct_field", "inputs": ["v_each"],
                "config": {"field": "name"}}},
            "v_role": {"id": "v_role", "kind": "string", "label": "Role", "derivation": {
                "transform": "extract_struct_field", "inputs": ["v_each"],
                "config": {"field": "role"}}},
        },
        "events": {},
    })
    return mod


def host_module(api, name: str, child, entries):
    mod = Module(api, name, beside=child)
    mod.define({
        "format": 2,
        "layout": layout({"loop": {"resolvedName": "CanvasLoopSection", "isCanvas": True, "props": {
            "source": "array", "arrayVariable": "v_crew", "moduleId": child.app_id,
            "itemVariable": "each", "paging": "limit", "maxItems": 12, "display": "list"}}}),
        "variables": {
            "v_crew": {"id": "v_crew", "kind": "array", "label": "Crew", "element": "struct",
                       "default": entries},
        },
        "events": {},
    })
    return mod


def copies(page):
    return page.locator(".canvas-loop-item")


def test_each_copy_gets_its_own_struct(page, api) -> None:
    child = child_module(api, "Struct loop child")
    mod = host_module(api, "Struct loop", child, [
        {"name": "Ada", "role": "pilot"}, {"name": "Grace", "role": "navigator"}])
    open_module(page, mod)
    expect(copies(page)).to_have_count(2, timeout=20000)
    expect(copies(page).nth(0)).to_contain_text("crew:Ada (pilot)")
    expect(copies(page).nth(1)).to_contain_text("crew:Grace (navigator)")


def test_an_array_typed_as_json_in_the_panel_loops_too(page, api) -> None:
    """The panel keeps a typed default as text; an array's is its JSON."""
    child = child_module(api, "Struct loop child typed")
    mod = host_module(api, "Struct loop typed", child,
                      '[{"name": "Linus", "role": "engineer"}]')
    open_module(page, mod)
    expect(copies(page)).to_have_count(1, timeout=20000)
    expect(copies(page).nth(0)).to_contain_text("crew:Linus (engineer)")


def test_the_panel_offers_struct_entries_and_takes_the_array_out_of_the_url(page, api) -> None:
    """An array in the URL is one query parameter per entry, which a struct
    has no text form for - so choosing struct entries takes it out."""
    from conftest import WEB_BASE, eventually, settled

    mod = Module(api, "Struct element panel")
    mod.define({
        "format": 2,
        "layout": layout({"t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "x"}}}),
        "variables": {
            "v_tags": {"id": "v_tags", "kind": "array", "label": "Tags list", "element": "string",
                       "external_id": "tags", "interface": {}, "url_behavior": "always"},
        },
        "events": {},
    })
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Tags list").first.click()
    page.get_by_test_id("variable-element").select_option("struct")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["v_tags"],
               lambda v: v.get("element") == "struct" and v.get("url_behavior") in (None, "never"),
               what="an array of structs, out of the URL")
