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


# ---- p.130's "Object Explorer from the search bar" (§729) --------------------
def test_the_explorer_s_property_filter_takes_a_regular_expression(page, sites) -> None:
    from urllib.parse import quote

    from conftest import WEB_BASE

    base = f"{WEB_BASE}/{sites.workspace_slug}/explore?type={sites.site_type_id}"
    page.goto(base)
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(3, timeout=30000)
    page.get_by_label("Property name").fill("code")
    # Controlled by the URL, so it is checked once the link says so.
    page.get_by_test_id("explorer-regex").click()
    expect(page.get_by_test_id("explorer-regex")).to_be_checked()
    page.get_by_label("Property value").fill("SN-[0-9")
    # Not a pattern yet: said, and not sent.
    expect(page.get_by_test_id("explorer-regex-problem")).to_contain_text("has no closing ]")
    expect(rows).to_have_count(3)
    page.get_by_label("Property value").fill(r"SN-\d{4}")
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text("A1")
    # The link carries it, so the question can be sent on.
    assert "match=regex" in page.url
    # And a saved search keeps it: saved, cleared, opened again.
    import uuid

    name = f"Serials {uuid.uuid4().hex[:6]}"
    page.get_by_role("button", name="Save this search").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_contain_text(r"code ~ SN-\d{4}")
    dialog.get_by_label("Name").fill(name)
    dialog.get_by_role("button", name="Save search").click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=30000)
    saved = page.get_by_label("Saved searches")
    # Marked as the search on screen, which compares the match too.
    expect(saved.locator("li.on").filter(has_text=name)).to_have_count(1, timeout=30000)
    expect(saved.locator("li").filter(has_text=name)).to_contain_text(r"code ~ SN-\d{4}")
    page.get_by_role("button", name="Clear", exact=True).click()
    expect(page.get_by_test_id("explorer-regex")).to_have_count(0)
    saved.locator(".ox-saved-open").filter(has_text=name).click()
    expect(page.get_by_test_id("explorer-regex")).to_be_checked(timeout=30000)
    expect(rows).to_have_count(1)
    # The same words as an exact match are a different question, and the
    # saved search is no longer the one on screen.
    page.get_by_test_id("explorer-regex").click()
    expect(page.get_by_test_id("explorer-regex")).not_to_be_checked()
    expect(saved.locator("li.on").filter(has_text=name)).to_have_count(0)
    page.goto(f"{base}&property=code&value={quote(r'.N-.*')}&match=regex")
    expect(rows).to_have_count(3, timeout=30000)
    # A property not indexed for it is refused with p.130's reason.
    page.goto(f"{base}&property=name&value={quote('P.*')}&match=regex")
    expect(page.get_by_text("not indexed for regex search")).to_be_visible(timeout=30000)
