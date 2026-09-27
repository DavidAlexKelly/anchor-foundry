"""p.472-473's Exploration Search Bar (§577).

> "Use the Exploration Search Bar widget to visualize and apply filters to an
> object set. The widget supports both filtering on properties on the object
> type and filtering with linked object types and their properties." (p.472)

The bar writes the clause list a `narrow_set` reads, and a table beside it
shows the set that makes: a filter the bar adds is checked by the rows it
leaves, not by what the bar says about itself.

    v_base     (object_set)   every site, filtered to band=new in its definition
    v_clauses  (array)        what the bar writes
    v_narrow   (object_set)   narrow_set(v_base, v_clauses)
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled, stays

ROWS = [
    {"id": "N1", "region": "north", "band": "new", "capacity": "10", "code": "x1"},
    {"id": "N2", "region": "north", "band": "new", "capacity": "40", "code": "x2"},
    {"id": "N3", "region": "north", "band": "old", "capacity": "25", "code": "x3"},
    {"id": "S1", "region": "south", "band": "new", "capacity": "30", "code": "x4"},
    {"id": "S2", "region": "south", "band": "new", "capacity": "5", "code": "x5"},
]
NEW = ["N1", "N2", "S1", "S2"]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Search bar")
    mod.site_type_id = mod.object_type(
        columns=["id", "region", "band", "capacity", "code"], rows=ROWS, key="id",
        title="id", types={"capacity": "integer"},
        visibility={"capacity": "prominent", "code": "hidden"},
    )
    return mod


def build(api, sites, name: str, **props) -> Module:
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "bar": {"resolvedName": "CanvasSearchBar", "props": {
                "objectSetVariable": "v_narrow", "variable": "v_clauses", **props}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_narrow", "columns": "id,region", "pageSize": 25}},
        }),
        "variables": {
            "v_base": {"id": "v_base", "kind": "object_set", "label": "New band",
                       "object_set": object_set(
                           sites.site_type_id,
                           filters=[{"property": "band", "op": "eq", "value": "new"}])},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Applied filters"},
            "v_narrow": {"id": "v_narrow", "kind": "object_set", "label": "What is shown",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_base", "v_clauses"]}},
        },
        "events": {},
    })
    return mod


def rows_are(page, ids: list[str], what: str) -> None:
    cells = page.locator(".data-grid tbody tr td:first-child")
    eventually(lambda: sorted(c.strip() for c in cells.all_text_contents()),
               lambda got: got == sorted(ids), what=what)


def field(page):
    return page.get_by_test_id("search-bar-input")


def option(page, text: str):
    return page.get_by_test_id("search-bar-option").filter(has_text=text).first


def property_option(page, text: str):
    return page.locator("[data-testid='search-bar-option'][data-kind='property']",
                        has_text=text).first


def options(page) -> list[str]:
    return [t.strip() for t in page.get_by_test_id("search-bar-option").all_text_contents()]


def test_a_word_typed_searches_a_text_property(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar keyword"))
    rows_are(page, NEW, "the new band")
    field(page).fill("nor")
    expect(option(page, 'Search "nor" in Region')).to_be_visible()
    option(page, 'Search "nor" in Region').click()
    rows_are(page, ["N1", "N2"], "the new band in the north")
    expect(page.get_by_test_id("filter-pill").filter(has_text="Region")).to_have_count(1)
    expect(field(page)).to_have_value("")
    # p.452's query: one property holds one search, so a second replaces it.
    field(page).fill("north OR south")
    option(page, 'Search "north OR south" in Region').click()
    rows_are(page, NEW, "the new band, north or south")


def test_a_property_is_filtered_on_a_value_it_suggests(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar values"))
    rows_are(page, NEW, "the new band")
    field(page).fill("reg")
    property_option(page, "egion").click()
    expect(page.get_by_test_id("search-bar-picked")).to_contain_text("Region")
    field(page).click()
    # The set's own values, counted: the new band's two regions.
    expect(option(page, "south (2)")).to_be_visible()
    field(page).fill("sou")
    assert options(page) == ["south (2)"]
    option(page, "south (2)").click()
    rows_are(page, ["S1", "S2"], "the new band in the south")


def test_a_value_typed_is_taken_as_typed(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar typed"))
    rows_are(page, NEW, "the new band")
    field(page).fill("capacity")
    property_option(page, "apacity").click()
    page.get_by_test_id("search-bar-op").select_option("gte")
    field(page).fill("30")
    field(page).press("Enter")
    rows_are(page, ["N2", "S1"], "a capacity of at least 30")
    # "1" is suggested as 10, and Enter without arrowing to it takes the 1.
    page.get_by_test_id("filter-pill-remove").click()
    rows_are(page, NEW, "the new band again")
    field(page).fill("capacity")
    property_option(page, "apacity").click()
    page.get_by_test_id("search-bar-op").select_option("gte")
    field(page).fill("1")
    expect(option(page, "10 (1)")).to_be_visible()
    field(page).press("Enter")
    expect(page.get_by_test_id("filter-pill").filter(has_text="1")).to_have_count(1)
    rows_are(page, NEW, "a capacity of at least 1: every new site")


def test_the_keyboard_moves_through_the_menu(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar keys", disableKeyword=True))
    rows_are(page, NEW, "the new band")
    field(page).click()
    # Visible properties only: code is hidden.
    eventually(lambda: [o.lower() for o in options(page)],
               lambda got: got == ["id", "region", "band", "capacity"],
               what="the visible properties")
    field(page).press("ArrowDown")
    field(page).press("Enter")
    expect(page.get_by_test_id("search-bar-picked")).to_contain_text("egion")
    # Nothing is chosen until the reader arrows, and the first arrow is the
    # first suggestion.
    first = page.get_by_test_id("search-bar-option").first
    expect(first).to_be_visible()
    selected = page.locator("[data-testid='search-bar-option'][aria-selected='true']")
    expect(selected).to_have_count(0)
    field(page).press("ArrowDown")
    expect(selected).to_have_count(1)
    expect(selected).to_have_text(first.text_content() or "")
    chosen = (selected.text_content() or "").split(" (")[0]
    field(page).press("Enter")
    rows_are(page, ["S1", "S2"] if chosen == "south" else ["N1", "N2"], f"region {chosen}")


def test_keyword_filtering_can_be_turned_off(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar no keyword", disableKeyword=True))
    rows_are(page, NEW, "the new band")
    field(page).fill("re")
    expect(page.get_by_test_id("search-bar-option").first).to_be_visible()
    kinds = page.get_by_test_id("search-bar-option").evaluate_all(
        "(els) => els.map((e) => e.dataset.kind)")
    assert set(kinds) == {"property"}, kinds


def test_autocomplete_can_be_turned_off(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar no suggestions", disableAutocomplete=True))
    rows_are(page, NEW, "the new band")
    field(page).fill("region")
    property_option(page, "egion").click()
    field(page).fill("so")
    # Kept looking at: a suggestion is a round trip away, so one read proves
    # nothing.
    stays(lambda: page.get_by_test_id("search-bar-menu").count(), lambda n: n == 0,
          what="no suggestions", for_ms=3000)
    field(page).fill("south")
    field(page).press("Enter")
    rows_are(page, ["S1", "S2"], "the new band in the south")


@pytest.mark.parametrize("scope, custom, offered", [
    ("prominent", [], ["capacity"]),
    ("all", [], ["id", "region", "band", "capacity", "code"]),
    ("custom", ["code", "region"], ["region", "code"]),
])
def test_the_properties_offered_follow_p473(page, api, sites, scope, custom, offered) -> None:
    open_module(page, build(api, sites, f"Search bar scope {scope}", propertyScope=scope,
                            customProperties=custom, disableKeyword=True))
    rows_are(page, NEW, "the new band")
    field(page).click()
    eventually(lambda: [o.lower() for o in options(page)], lambda got: got == offered,
               what=f"the properties {scope} offers")


def test_clear_removes_what_the_bar_added(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar clear"))
    rows_are(page, NEW, "the new band")
    expect(page.get_by_test_id("search-bar-clear")).to_have_count(0)
    field(page).fill("nor")
    option(page, 'Search "nor" in Region').click()
    rows_are(page, ["N1", "N2"], "the north")
    field(page).fill("N2")
    page.locator("[data-testid='search-bar-option'][data-kind='keyword']").first.click()
    rows_are(page, ["N2"], "the north, and N2")
    page.get_by_test_id("search-bar-clear").click()
    rows_are(page, NEW, "the new band again")
    # The base set's own filter is not the bar's to clear, and is still a pill.
    expect(page.get_by_test_id("filter-pill")).to_have_count(1)


def test_read_only_shows_the_filters_and_takes_none(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar read only", mode="read_only",
                            showTypePill=True, icon="🔎", placeholder="Find a site"))
    rows_are(page, NEW, "the new band")
    expect(page.get_by_test_id("filter-pill")).to_have_count(1)
    expect(page.get_by_test_id("filter-pill-remove")).to_have_count(0)
    expect(field(page)).to_have_count(0)
    expect(page.get_by_test_id("filter-pill-type")).to_be_visible()
    expect(page.get_by_test_id("search-bar-icon")).to_have_text("🔎")


def test_the_placeholder_and_help(page, api, sites) -> None:
    open_module(page, build(api, sites, "Search bar help", placeholder="Find a site",
                            showHelpIcon=True))
    expect(field(page)).to_have_attribute("placeholder", "Find a site")
    expect(page.get_by_test_id("search-bar-help-text")).to_have_count(0)
    page.get_by_test_id("search-bar-help").click()
    expect(page.get_by_test_id("search-bar-help-text")).to_contain_text("AND, OR and NOT")


def test_the_panel_sets_what_the_bar_offers(page, api, sites) -> None:
    mod = build(api, sites, "Search bar panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Exploration search bar").first.click()
    page.get_by_test_id("search-bar-scope").select_option("custom")
    page.get_by_test_id("search-bar-custom-code").check()
    page.get_by_test_id("search-bar-custom-region").check()
    page.get_by_test_id("search-bar-custom-region").uncheck()
    page.get_by_test_id("search-bar-placeholder").fill("Find a site")
    page.get_by_test_id("search-bar-disableKeyword").check()
    page.get_by_test_id("search-bar-showClearButton").uncheck()
    page.get_by_test_id("search-bar-mode").select_option("remove")
    save(page)
    props = mod.definition()["layout"]["bar"]["props"]
    assert props["propertyScope"] == "custom"
    assert props["customProperties"] == ["code"]
    assert props["placeholder"] == "Find a site"
    assert props["disableKeyword"] is True
    assert props["showClearButton"] is False
    assert props["mode"] == "remove"
