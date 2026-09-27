"""String and boolean comparisons on Workshop variables (§566;
`foundry_workshop` p.142).

    "Contains: Runs a boolean check on if the second given string value(s)
     or variable(s) is a substring of the first given string value or
     variable. … Is false (NOT) … Is null …" (p.142)

The checks are `apps/api/tests/test_variable_checks.py`. What needs a
browser is the panel building one and the answers reaching a widget - and
Flag's "false", typed in the panel as text, being false to If / else too.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled


def derived(vid: str, transform: str, inputs: list[str], kind="boolean") -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": transform, "inputs": inputs, "config": {}}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "has {{has}} | off {{off}} | none {{none}} | shown {{pick}}"}}}),
        "variables": {
            "city": {"id": "city", "kind": "string", "label": "City", "default": "Paris, France"},
            "want": {"id": "want", "kind": "string", "label": "Want", "default": "France"},
            "flag": {"id": "flag", "kind": "boolean", "label": "Flag", "default": "false"},
            "unset": {"id": "unset", "kind": "string", "label": "Unset"},
            "yes": {"id": "yes", "kind": "string", "label": "Yes", "default": "yes"},
            "no": {"id": "no", "kind": "string", "label": "No", "default": "no"},
            "has": derived("has", "string_contains", ["city", "want"]),
            "off": derived("off", "is_false", ["flag"]),
            "none": derived("none", "is_null", ["unset"]),
            "pick": derived("pick", "if_else", ["flag", "yes", "no"], kind="string"),
            "check": {"id": "check", "kind": "boolean", "label": "Check"},
        },
        "events": {},
    })
    return mod


def test_checks_reach_the_page(page, api) -> None:
    open_module(page, build(api, "Checks reach"))
    expect(page.get_by_text("has true | off true | none true | shown no")).to_be_visible(
        timeout=20000)


def test_the_panel_builds_a_text_check(page, api) -> None:
    mod = build(api, "Checks panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("Check", exact=True).first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("string_starts_with")
    page.get_by_role("combobox", name=re.compile(r"^Text")).select_option("city")
    page.get_by_role("combobox", name=re.compile(r"^Compared with")).first.select_option("want")
    expect(page.get_by_role("combobox", name=re.compile(r"^Compared with"))).to_have_count(2)
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["check"].get("derivation"),
               lambda d: d == {"transform": "string_starts_with", "inputs": ["city", "want"],
                               "config": {}},
               what="the text check, saved")
