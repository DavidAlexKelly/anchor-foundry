"""p.73's Object set aggregation variable (§617).

> "Object set aggregation: For variables derived from an aggregation of an
> object set" (`workshop` p.73)

The resolution is `apps/api/tests/test_variable_aggregates.py`, against the
store. What needs a browser is that a number read this way reaches something
other than a Metric Card - a heading, which had no way to read an aggregate
before - that it follows the set as a viewer narrows it, and that the panel
builds one.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module, settled

ROWS = [
    {"id": "S1", "region": "north", "capacity": 10},
    {"id": "S2", "region": "south", "capacity": 30},
    {"id": "S3", "region": "north", "capacity": 20},
]


def aggregate(vid: str, source: str, aggregation: str, prop: str | None = None) -> dict:
    return {"id": vid, "kind": "number", "label": vid.capitalize(), "derivation": {
        "transform": "object_set_aggregation", "inputs": [source],
        "config": {"aggregation": aggregation, **({"property": prop} if prop else {})}}}


def build(api, name: str) -> Module:
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "region", "capacity"], rows=ROWS, key="id",
                              title="id", types={"capacity": "integer"})
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText", "props": {
                "tag": "h2", "text": "{{count}} sites, {{total}} beds"}},
            # A Filter List narrowing the set the numbers are of.
            "filter": {"resolvedName": "CanvasFilterList", "props": {
                "objectSetVariable": "v_all", "variable": "v_clauses", "title": "Sites",
                "filters": [{"id": "f_1", "property": "region",
                             "component": "singleSelect"}]}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Filters"},
            "v_shown": {"id": "v_shown", "kind": "object_set", "label": "Shown",
                        "derivation": {"transform": "narrow_set",
                                       "inputs": ["v_all", "v_clauses"]}},
            "count": aggregate("count", "v_shown", "count"),
            "total": aggregate("total", "v_shown", "sum", "capacity"),
            "spare": {"id": "spare", "kind": "number", "label": "Spare"},
        },
        "events": {},
    })
    return mod


def test_a_heading_reads_an_aggregate_of_the_set_as_it_is_narrowed(page, api) -> None:
    mod = build(api, "Aggregate heading")
    open_module(page, mod)
    expect(page.get_by_role("heading", name="3 sites, 60 beds")).to_be_visible(timeout=20000)
    page.get_by_role("combobox", name="Region", exact=True).select_option("north")
    expect(page.get_by_role("heading", name="2 sites, 30 beds")).to_be_visible()
    page.get_by_role("combobox", name="Region", exact=True).select_option("south")
    expect(page.get_by_role("heading", name="1 sites, 30 beds")).to_be_visible()


def test_the_panel_builds_an_aggregation(page, api) -> None:
    mod = build(api, "Aggregate panel")
    page.goto(f"{WEB_BASE}{mod.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(timeout=30000)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Spare").first.click()
    page.get_by_role("button", name="Make this derived").click()
    page.get_by_label("Computed by").select_option("object_set_aggregation")
    # It starts as a count, which needs no property.
    expect(page.get_by_test_id("vars-aggregation")).to_have_value("count")
    expect(page.get_by_test_id("vars-aggregation-property")).to_have_count(0)
    page.get_by_role("combobox", name=re.compile(r"^Object set")).select_option("v_all")
    # Saved as it starts - a count, which the server accepts as it stands.
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as first:
        page.get_by_role("button", name="Save", exact=True).click()
    assert first.value.ok, first.value.status
    eventually(lambda: mod.definition()["variables"]["spare"].get("derivation"),
               lambda d: d == {"transform": "object_set_aggregation", "inputs": ["v_all"],
                               "config": {"aggregation": "count"}},
               what="a count of every site, saved")
    page.get_by_test_id("vars-aggregation").select_option("max")
    page.get_by_test_id("vars-aggregation-property").fill("capacity")
    with page.expect_response(
        lambda r: "/definition" in r.url and r.request.method in ("PUT", "POST")
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.status
    settled(page)
    eventually(lambda: mod.definition()["variables"]["spare"].get("derivation"),
               lambda d: d == {"transform": "object_set_aggregation", "inputs": ["v_all"],
                               "config": {"aggregation": "max", "property": "capacity"}},
               what="the largest capacity, saved")
