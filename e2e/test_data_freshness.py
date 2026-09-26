"""p.399–401's Data Freshness widget (parity `workshop.md` §10; §469).

> "The Data Freshness widget enables users to track data freshness directly
> within their application by displaying the Last Updated timestamp
> corresponding to the most recent index time for configured object types and
> datasources." (p.399)
>
> "If the last index time exceeds 24 hours, the timestamp renders an absolute
> format ( Thu, Jul 17, 2025, 1:52 PM ). If the last index time is within 24
> hours, the timestamp renders a relative format ( 2 hours ago or 30 min
> ago )." (p.400)

The formats are `data-freshness.test.ts`; what the server answers is
`test_freshness.py`. What needs a browser is that the times on screen are the
type's and each source's own, and that an old one reads as p.400 says.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import ADMIN_DSN, open_builder, open_module, save, settled
from ontology_page import pick_type

ABSOLUTE = re.compile(r"^\w{3}, \w{3} \d{1,2}, \d{4}, \d{1,2}:\d{2} (AM|PM)$")
RELATIVE = re.compile(r"^(just now|\d+ min ago|\d+ hours? ago)$")


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Data freshness")
    mod.site_type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "S1", "name": "One"}], key="id", title="name")
    [known] = api.call("POST", f"/workspaces/{mod.workspace_id}/object-types/freshness",
                       {"object_type_ids": [mod.site_type_id]})["types"]
    mod.type_name = known["display_name"]
    mod.dataset_id = known["sources"][0]["dataset_id"]
    mod.dataset_name = known["sources"][0]["dataset_name"]
    return mod


def build(api, sites, name: str, items: list) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({"format": 2, "layout": layout({
        "fresh": {"resolvedName": "CanvasDataFreshness", "props": {"items": items}}}),
        "variables": {}, "events": {}})
    return mod


def times(page, test_id: str):
    return page.get_by_test_id(test_id).locator(".canvas-freshness-time").first


def test_a_type_and_its_source_say_how_recently_they_were_indexed(page, api, sites) -> None:
    mod = build(api, sites, "Freshness recent", [
        {"id": "d_1", "objectTypeId": sites.site_type_id,
         "sources": [{"datasetId": sites.dataset_id, "name": "Site feed"}]}])
    open_module(page, mod)
    item = page.get_by_test_id("freshness-d_1")
    expect(item.locator(".canvas-freshness-name").first).to_have_text(sites.type_name)
    expect(times(page, "freshness-d_1")).to_have_text(RELATIVE)
    source = page.get_by_test_id(f"freshness-source-{sites.dataset_id}")
    # p.401's Override resource name, in place of the dataset's.
    expect(source.locator(".canvas-freshness-name")).to_have_text("Site feed")
    expect(source.locator(".canvas-freshness-time")).to_have_text(RELATIVE)
    expect(source.locator(".canvas-freshness-time--stale")).to_have_count(0)


def test_past_a_day_the_time_is_absolute_and_marked(page, api) -> None:
    """Its own type, aged directly in the database: a sync stamps now, and
    nothing through the API can make an index time old."""
    mod = Module(api, "Freshness old")
    type_id = mod.object_type(columns=["id", "name"], rows=[{"id": "S1", "name": "One"}],
                              key="id", title="name")
    mod.spread_updated_at(ADMIN_DSN, {"S1": datetime.now(timezone.utc) - timedelta(days=2)})
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE object_type_sources SET last_synced_at = now() - interval '3 days'"
            " WHERE object_type_id = %s", (type_id,))
    [known] = api.call("POST", f"/workspaces/{mod.workspace_id}/object-types/freshness",
                       {"object_type_ids": [type_id]})["types"]
    dataset = known["sources"][0]["dataset_id"]
    mod.define({"format": 2, "layout": layout({
        "fresh": {"resolvedName": "CanvasDataFreshness", "props": {"items": [
            {"id": "d_1", "objectTypeId": type_id, "sources": [{"datasetId": dataset}]}]}}}),
        "variables": {}, "events": {}})
    open_module(page, mod)
    stamp = times(page, "freshness-d_1")
    expect(stamp).to_have_text(ABSOLUTE)
    expect(stamp).to_have_class(re.compile("canvas-freshness-time--stale"))
    source = page.get_by_test_id(f"freshness-source-{dataset}")
    expect(source.locator(".canvas-freshness-time")).to_have_text(ABSOLUTE)
    # The source's own time, not the type's: they were aged differently.
    assert source.locator(".canvas-freshness-time").text_content() != stamp.text_content()
    # The dataset's own name when there is no override.
    expect(source.locator(".canvas-freshness-name")).to_have_text(known["sources"][0]["dataset_name"])


def test_a_source_that_is_not_the_types_says_so(page, api, sites) -> None:
    mod = build(api, sites, "Freshness wrong source", [
        {"id": "d_1", "objectTypeId": sites.site_type_id,
         "sources": [{"datasetId": "00000000-0000-0000-0000-000000000000", "name": "Gone"}]}])
    open_module(page, mod)
    expect(page.get_by_text("Not a source of this type")).to_be_visible()


def test_the_panel_adds_a_type_and_chooses_its_sources(page, api, sites) -> None:
    mod = build(api, sites, "Freshness panel", [])
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Data freshness").first.click()
    pick_type(page, "freshness-add-type", {"id": sites.site_type_id,
                                           "api_name": sites.type_name})
    toggle = page.get_by_test_id(f"freshness-source-toggle-{sites.dataset_id}")
    toggle.check()
    page.get_by_test_id(f"freshness-source-name-{sites.dataset_id}").fill("Feed")
    save(page)
    items = mod.definition()["layout"]["fresh"]["props"]["items"]
    assert items == [{"id": "d_1", "objectTypeId": sites.site_type_id,
                      "sources": [{"datasetId": sites.dataset_id, "name": "Feed"}]}], items
