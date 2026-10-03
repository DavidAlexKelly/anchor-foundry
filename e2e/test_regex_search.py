"""`ontology` p.130-131's regular expression search in Workshop's Filter List
(§728).

> "You can search in the Ontology from Workshop using the filter list or
> Object Explorer from the search bar." (p.130)
> "String properties must be indexed for regex search." (p.130)

The language is `test_regex_search.py` (API) and `regex-query.test.ts`; both
stores' reading of it is `test_instance_store.py`. What needs a browser is the
filter applying a pattern once it is one, the whole value and not a part, and
the panel offering it only on a property indexed for it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import open_builder, open_module, save, settled
from test_filter_list import build, one, rows_are

ROWS = [
    {"id": "A1", "code": "SN-0042", "name": "Pump"},
    {"id": "A2", "code": "SN-7", "name": "Valve"},
    {"id": "A3", "code": "XN-0042", "name": "Gauge"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Regex search")
    mod.site_type_id = mod.object_type(
        columns=["id", "code", "name"], rows=ROWS, key="id", title="name",
        hints={"code": ["searchable", "regex"]},
    )
    return mod


def test_a_regular_expression_matches_whole_values(page, api, sites) -> None:
    mod = build(api, sites, "Regex filter",
                {"filters": [{**one("keyword", "code"), "syntax": "regex"}]})
    open_module(page, mod)
    rows_are(page, ["A1", "A2", "A3"], "every row first")
    box = page.get_by_test_id("filter-keyword-regex")
    box.fill(r"SN-\d{4}")
    rows_are(page, ["A1"], "a four-digit serial")
    # The whole value, not a part of it (p.130).
    box.fill(r"\d+")
    rows_are(page, [], "no code is only digits")
    box.fill(r".N-.*")
    rows_are(page, ["A1", "A2", "A3"], "any letter before N")
    # Not a pattern yet: said, and the last one stays applied.
    box.fill("SN-[0-9")
    expect(page.get_by_test_id("filter-keyword-problem")).to_contain_text("has no closing ]")
    rows_are(page, ["A1", "A2", "A3"], "still the last pattern")
    box.fill("^SN.*")
    expect(page.get_by_test_id("filter-keyword-problem")).to_contain_text("anchors are not supported")


def test_the_panel_offers_it_only_on_a_property_indexed_for_it(page, api, sites) -> None:
    mod = build(api, sites, "Regex panel", {"filters": [one("keyword", "name"),
                                                        one("keyword", "code", "f_2")]})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Sites").first.click()
    expect(page.get_by_test_id("filter-syntax-f_1").locator("option")).to_have_text(
        ["Starts with", "Advanced syntax"])
    page.get_by_test_id("filter-syntax-f_2").select_option("regex")
    save(page)
    filters = mod.definition()["layout"]["fl"]["props"]["filters"]
    assert filters[1] == {**one("keyword", "code", "f_2"), "syntax": "regex"}, filters
