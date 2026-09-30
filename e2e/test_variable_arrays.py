"""Array operations and checks on Workshop variables (§567;
`foundry_workshop` p.142-143).

    "Compose: Returns an array containing all values of the given arrays.
     Intersection … Get element at: Returns a value corresponding to the
     element at a specified index within the given array … Length …"
     (p.142-143)

The operations are `apps/api/tests/test_variable_arrays.py`. What needs a
browser is the panel building one with its index, and the answers reaching
a widget. A's default is typed JSON, as the panel keeps it.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled


def derived(vid: str, transform: str, inputs: list[str], kind="array", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": transform, "inputs": inputs, "config": config}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "second {{second}} | count {{count}} | has {{has}}"}}}),
        "variables": {
            "a": {"id": "a", "kind": "array", "label": "A", "default": '["red", "green"]'},
            "b": {"id": "b", "kind": "array", "label": "B", "default": ["green", "blue"]},
            "both": derived("both", "array_compose", ["a", "b"]),
            "second": derived("second", "array_get_element", ["both"], kind="string", index=1),
            "count": derived("count", "array_length", ["both"], kind="number"),
            "has": derived("has", "array_is_subset_of", ["a", "both"], kind="boolean"),
            "pick": {"id": "pick", "kind": "string", "label": "Chosen entry"},
        },
        "events": {},
    })
    return mod


def test_array_operations_reach_the_page(page, api) -> None:
    open_module(page, build(api, "Arrays reach"))
    expect(page.get_by_text("second green | count 4 | has true")).to_be_visible(timeout=20000)


def test_the_panel_builds_get_element_at_an_index(page, api) -> None:
    mod = build(api, "Arrays panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Chosen entry").first.click()
    page.get_by_role("button", name="Make this derived").click()
    # Compose takes as many arrays as are wanted: choosing one opens another.
    page.get_by_label("Computed by").select_option("array_compose")
    page.get_by_role("combobox", name=re.compile(r"^Array 1")).select_option("a")
    expect(page.get_by_role("combobox", name=re.compile(r"^Array 2"))).to_have_count(1)
    page.get_by_label("Computed by").select_option("array_get_element")
    page.get_by_role("combobox", name=re.compile(r"^Array")).select_option("both")
    page.get_by_test_id("array-index").fill("3")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["pick"].get("derivation"),
               lambda d: d == {"transform": "array_get_element", "inputs": ["both"],
                               "config": {"index": 3}},
               what="the element at 3, saved")
