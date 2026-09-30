"""Casts to dates, timestamps and geopoints on Workshop variables (§569;
`foundry_workshop` p.138-139).

    "String → Date: … if passing in a string variable with the value
     06/26/24, select M/dd/yyyy as the corresponding parser format to cast to
     a date type. … Date → Timestamp: … converted to a timestamp
     representing start of day at the specified timezone." (p.138-139)

The parsing and zones are `apps/api/tests/test_variable_casts.py`. What
needs a browser is the panel setting a parser and a zone, and the answers
reaching a widget.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled


def cast(vid: str, source: str, kind: str, **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": "cast", "inputs": [source], "config": config}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "day {{day}} | start {{start}} | lat {{lat}}"}}}),
        "variables": {
            "typed": {"id": "typed", "kind": "string", "label": "Typed", "default": "06/26/24"},
            "where": {"id": "where", "kind": "string", "label": "Where",
                      "default": "40.782142,-73.96596"},
            "day": cast("day", "typed", "date", to="date", format="M/dd/yyyy"),
            "start": cast("start", "day", "timestamp", to="timestamp", timezone="Europe/Paris"),
            "point": cast("point", "where", "string", to="geopoint"),
            "lat": {"id": "lat", "kind": "number", "label": "Lat", "derivation": {
                "transform": "latitude", "inputs": ["point"], "config": {}}},
            "when": {"id": "when", "kind": "date", "label": "When it was"},
            "zone": {"id": "zone", "kind": "string", "label": "Zone", "default": "Europe/Oslo"},
        },
        "events": {},
    })
    return mod


def test_casts_reach_the_page(page, api) -> None:
    open_module(page, build(api, "Casts reach"))
    expect(page.get_by_text("day 2024-06-26 | start 2024-06-25T22:00:00Z | lat 40.782142")).to_be_visible(
        timeout=20000)


def test_the_panel_sets_a_parser_and_a_zone(page, api) -> None:
    mod = build(api, "Casts panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="When it was").first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("cast")
    page.get_by_role("combobox", name=re.compile(r"^Value")).select_option("typed")
    expect(page.get_by_test_id("cast-format")).to_have_count(0)
    page.get_by_label("Convert to").select_option("date")
    page.get_by_test_id("cast-format").fill("M/dd/yyyy")
    page.get_by_test_id("cast-timezone").fill("Asia/Tokyo")
    page.get_by_test_id("cast-zone-variable").select_option("zone")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["when"].get("derivation"),
               lambda d: d == {"transform": "cast", "inputs": ["typed", "zone"], "config": {
                   "to": "date", "format": "M/dd/yyyy", "timezone": "Asia/Tokyo"}},
               what="the cast, saved")
