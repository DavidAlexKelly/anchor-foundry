"""The object set filter variable kind (§590; `workshop` p.75, p.146).

> "Object set filter: Stores a set of property type / property value pairs
>  used to filter object set variables." (p.75)
> "An object set filter variable is used to track the filter state of an
>  object set, often output by widgets such as the Filter List... A default
>  state for the filter can also be specified" (p.146)

The Filter List writes into one, a table reads the narrowed set, and a
default filter applies on load - the same path an array has always been, under
the kind's own name. And the builder offers the kind and a Filter List output
picker that lists it.
"""
from __future__ import annotations

import json

from playwright.sync_api import expect

from conftest import open_builder, open_module, settled
from test_filter_list import NORTH, SOUTH, EVERY, build, one, rows_are, sites  # noqa: F401


def as_filter(api, mod) -> None:
    """The module `build` made, with its clauses variable as the new kind."""
    document = mod.definition()
    document["variables"]["v_clauses"]["kind"] = "object_set_filter"
    mod.define(document)


def test_a_filter_list_writes_an_object_set_filter(page, api, sites) -> None:
    mod = build(api, sites, "Object set filter kind", {"filters": [one("histogram")]})
    as_filter(api, mod)
    open_module(page, mod)
    rows_are(page, EVERY, "every row before anything is ticked")
    page.locator(".canvas-filter-bar", has_text="south").get_by_role("checkbox").check()
    rows_are(page, SOUTH, "the southern rows")


def test_its_default_filter_applies_on_load(page, api, sites) -> None:
    """p.146's default state, typed as JSON clauses."""
    mod = build(api, sites, "Object set filter default", {"filters": [one("histogram")]},
                default=json.dumps([{"property": "region", "op": "eq", "value": "north"}]))
    as_filter(api, mod)
    open_module(page, mod)
    rows_are(page, NORTH, "the default filter's rows")


def test_the_builder_offers_the_filter_as_the_lists_output(page, api, sites) -> None:
    mod = build(api, sites, "Object set filter builder", {"filters": [one("histogram")]})
    as_filter(api, mod)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Filter list").first.click()
    output = page.get_by_label("Writes its filters to")
    if not output.count():
        page.get_by_role("tab", name="Outputs").click()
    expect(output).to_have_value("v_clauses")
    expect(output.locator("option", has_text="Filters")).to_have_count(1)


def test_the_panel_makes_one_with_a_default(page, api, sites) -> None:
    """p.75's kind in the panel's list, and p.146's default typed as clauses."""
    mod = build(api, sites, "Object set filter panel", {"filters": [one("histogram")]})
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.get_by_role("button", name="New", exact=True).click()
    page.get_by_label("Label").fill("Region filter")
    page.get_by_test_id("variable-kind").select_option("object_set_filter")
    default = page.get_by_test_id("variable-default")
    expect(default).to_have_attribute("placeholder", '[{"property": "region", "op": "eq", "value": "north"}]')
    default.fill('[{"property": "region", "op": "eq", "value": "south"}]')
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")
    [made] = [v for v in mod.definition()["variables"].values() if v["label"] == "Region filter"]
    assert made["kind"] == "object_set_filter"
    assert json.loads(made["default"]) == [{"property": "region", "op": "eq", "value": "south"}]
