"""Geospatial operations on Workshop variables (§568; `foundry_workshop`
p.142).

    "Geohash from geopoint … Latitude from geopoint … Longitude from geopoint
     … MGRS from geopoint: Converts a given geopoint into an MGRS value as a
     string." (p.142)

The projection is `apps/api/tests/test_variable_geo.py`, held to GeoTrans.
What needs a browser is the panel building one and the answers reaching a
widget. The Eiffel Tower, typed as "lat,lon".
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled


def derived(vid: str, transform: str, kind="string", **config) -> dict:
    return {"id": vid, "kind": kind, "label": vid.capitalize(),
            "derivation": {"transform": transform, "inputs": ["at"], "config": config}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "grid {{grid}} | hash {{hash}} | lon {{lon}}"}}}),
        "variables": {
            "at": {"id": "at", "kind": "string", "label": "At", "default": "48.8583,2.2945"},
            "grid": derived("grid", "mgrs"),
            "hash": derived("hash", "geohash", precision=5),
            "lon": derived("lon", "longitude", kind="number"),
            "code": {"id": "code", "kind": "string", "label": "Area code"},
        },
        "events": {},
    })
    return mod


def test_geospatial_operations_reach_the_page(page, api) -> None:
    open_module(page, build(api, "Geo reach"))
    expect(page.get_by_text("grid 31UDQ4825111943 | hash u09tu | lon 2.2945")).to_be_visible(
        timeout=20000)


def test_the_panel_builds_a_geohash(page, api) -> None:
    mod = build(api, "Geo panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Area code").first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("geohash")
    page.get_by_role("combobox", name=re.compile(r"^Geopoint")).select_option("at")
    page.get_by_test_id("geohash-precision").fill("7")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["code"].get("derivation"),
               lambda d: d == {"transform": "geohash", "inputs": ["at"], "config": {"precision": 7}},
               what="the geohash, saved")
