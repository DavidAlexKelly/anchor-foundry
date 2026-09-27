"""Date and time math and comparisons on Workshop variables (§565;
`foundry_workshop` p.140-141).

    "Relative date: Returns a calculated date given a numeric value or
     variable, specifying the number of days, weeks, months or years to add
     or subtract, and a date value or variable. … Between dates … Current
     date …" (p.140)

The calendar arithmetic is `apps/api/tests/test_variable_dates.py`. What
needs a browser is the panel building one, with its unit and direction, and
the result reaching a widget.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled


def derived(vid: str, transform: str, inputs: list[str], kind="date", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": transform, "inputs": inputs, "config": config}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "due {{due}} | gap {{gap}} | late {{late}}"}}}),
        "variables": {
            "start": {"id": "start", "kind": "date", "label": "Start", "default": "2026-01-31"},
            "n": {"id": "n", "kind": "number", "label": "N", "default": "1"},
            "due": derived("due", "relative_date", ["start", "n"], unit="months"),
            "gap": derived("gap", "between_dates", ["start", "due"], kind="number"),
            "late": derived("late", "date_is_after", ["due", "start"], kind="boolean"),
            "when": {"id": "when", "kind": "date", "label": "When"},
        },
        "events": {},
    })
    return mod


def test_date_math_reaches_the_page(page, api) -> None:
    """A month after 31 January is the last day of February."""
    open_module(page, build(api, "Dates reach"))
    expect(page.get_by_text("due 2026-02-28 | gap 28 | late true")).to_be_visible(timeout=20000)


def test_the_panel_builds_a_relative_date(page, api) -> None:
    mod = build(api, "Dates panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_text("When", exact=True).first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("current_date")
    # Current date reads nothing.
    expect(page.get_by_role("combobox", name=re.compile(r"^(Date|By|Value|Part)"))).to_have_count(0)
    page.get_by_label("Computed by").select_option("relative_date")
    page.get_by_role("combobox", name=re.compile(r"^Date")).select_option("start")
    page.get_by_role("combobox", name=re.compile(r"^By")).select_option("n")
    page.get_by_test_id("date-unit").select_option("weeks")
    page.get_by_test_id("date-direction").select_option("subtract")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["when"].get("derivation"),
               lambda d: d == {"transform": "relative_date", "inputs": ["start", "n"],
                               "config": {"unit": "weeks", "direction": "subtract"}},
               what="the relative date, saved")
