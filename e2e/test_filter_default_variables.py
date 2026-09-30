"""An object set filter's default whose values are variables (§592;
`workshop` p.146-148).

> "The values can be specified inline, or as variables." (p.146)
> "When the filter value is updated to a filter that matches the shape of the
>  default filter, the value for each variable in the configured default will
>  be updated to the extracted value from the filter." (p.148)

A text input sets the region the default filter reads, so the table follows
it; then a Filter List's bar sets the filter, and p.148 writes the chosen
region back into the variable, which the text shows.

    v_all      (object_set)          every site
    v_region   (string)              read by the default, written back
    v_clauses  (object_set_filter)   default region = {v_region}
    v_picked   (object_set)          narrow_set(v_all, v_clauses)
"""
from __future__ import annotations

import json

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled
from test_filter_list import EVERY, NORTH, SOUTH, one, rows_are, sites  # noqa: F401

DEFAULT = [{"property": "region", "op": "eq", "value": {"variable": "v_region"}}]


def build(api, sites, name: str, update: bool = True) -> Module:
    mod = Module(api, name, beside=sites)
    clauses = {"id": "v_clauses", "kind": "object_set_filter", "label": "Filters",
               "default": json.dumps(DEFAULT)}
    if update:
        clauses["update_used_variables"] = True
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_region", "label": "Region", "placeholder": "",
                              "format": "line", "rows": 1}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "region: [{{v_region}}]"}},
            "fl": {"resolvedName": "CanvasFilterList",
                   "props": {"objectSetVariable": "v_all", "variable": "v_clauses",
                             "title": "Sites", "filters": [one("histogram")]}},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_picked", "columns": "id,region",
                              "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            "v_region": {"id": "v_region", "kind": "string", "label": "Region",
                         "default": "north"},
            "v_clauses": clauses,
            "v_picked": {
                "id": "v_picked", "kind": "object_set", "label": "Narrowed",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_clauses"]},
            },
        },
        "events": {},
    })
    return mod


def test_p146_the_default_reads_the_variable_as_it_is(page, api, sites) -> None:
    mod = build(api, sites, "Filter default reads a variable")
    open_module(page, mod)
    rows_are(page, NORTH, "the default filter, reading north")
    page.get_by_label("Region").fill("south")
    rows_are(page, SOUTH, "the default filter, reading what was typed")
    # Emptied, the clause is left out: nothing typed is no filter.
    page.get_by_label("Region").fill("")
    rows_are(page, EVERY, "no region, no filter")


def test_p148_a_matching_filter_writes_its_value_back(page, api, sites) -> None:
    mod = build(api, sites, "Filter default writes back")
    open_module(page, mod)
    rows_are(page, NORTH, "the default filter")
    # The list starts from the filter it is shown, the default's north.
    north = page.locator(".canvas-filter-bar", has_text="north").get_by_role("checkbox")
    expect(north).to_be_checked()
    north.uncheck()
    rows_are(page, EVERY, "no filter")
    # Not the default's shape (one region), so nothing is written.
    expect(page.get_by_text("region: [north]")).to_be_visible()
    page.locator(".canvas-filter-bar", has_text="south").get_by_role("checkbox").check()
    rows_are(page, SOUTH, "the filter the bar set")
    expect(page.get_by_text("region: [south]")).to_be_visible()
    expect(page.get_by_label("Region")).to_have_value("south")
    # Two regions are not the default's shape (one region), so the variable
    # keeps what it last took.
    page.locator(".canvas-filter-bar", has_text="east").get_by_role("checkbox").check()
    rows_are(page, SOUTH + ["E1"], "both regions")
    expect(page.get_by_text("region: [south]")).to_be_visible()


def test_without_the_setting_nothing_is_written(page, api, sites) -> None:
    mod = build(api, sites, "Filter default leaves it", update=False)
    open_module(page, mod)
    rows_are(page, NORTH, "the default filter")
    page.locator(".canvas-filter-bar", has_text="north").get_by_role("checkbox").uncheck()
    page.locator(".canvas-filter-bar", has_text="south").get_by_role("checkbox").check()
    rows_are(page, SOUTH, "the filter the bar set")
    expect(page.get_by_text("region: [north]")).to_be_visible()


def test_the_panel_names_the_references_and_offers_the_setting(page, api, sites) -> None:
    mod = build(api, sites, "Filter default panel", update=False)
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Filters").first.click()
    reads = page.get_by_test_id("filter-default-reads")
    expect(reads).to_contain_text('Region {"variable": "v_region"}')
    reads.get_by_test_id("filter-update-used").check()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")
    eventually(lambda: mod.definition()["variables"]["v_clauses"].get("update_used_variables"),
               lambda on: on is True, what="the setting saved")
