"""p.449's Filter components on the Filter List (parity `workshop.md` §10's
Filter List row; §463).

> "Filter component: This option determines how each property is visualized
> within the Filter List. Options include keyword, histogram, single- and
> multi-select dropdowns, distribution chart, single- and multi-date pickers,
> and timeline displays." (p.449)

The clauses each component writes are `filter-list.test.ts`. What needs a
browser is that they **reach somewhere**, asserted through a table reading the
narrowed set, because a component showing the right choice while writing the
wrong clause looks perfect from outside; and that components sharing one
variable leave each other's clauses standing.

    v_all      (object_set)   every site
    v_clauses  (array)        what the Filter List writes
    v_picked   (object_set)   narrow_set(v_all, v_clauses)
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

# `at` is a timestamp so the range's last day is a real question: N3 is on the
# evening of the 31st, which `lte 2024-03-31` (midnight) would drop.
ROWS = [
    {"id": "N1", "region": "north", "name": "North 1", "at": "2024-03-01T09:00:00Z"},
    {"id": "N2", "region": "north", "name": "North 2", "at": "2024-03-15T09:00:00Z"},
    {"id": "N3", "region": "north", "name": "North 3", "at": "2024-03-31T18:00:00Z"},
    {"id": "N4", "region": "north", "name": "North 4", "at": "2024-04-01T00:00:00Z"},
    {"id": "S1", "region": "south", "name": "South 1", "at": "2024-02-29T23:00:00Z"},
    {"id": "S2", "region": "south", "name": "South 2", "at": "2024-03-10T12:00:00Z"},
    {"id": "E1", "region": "east", "name": "East 1", "at": "2024-05-05T12:00:00Z"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Filter list")
    mod.site_type_id = mod.object_type(
        columns=["id", "region", "name", "at"], rows=ROWS, key="id", title="name",
        types={"at": "timestamp"},
    )
    return mod


def build(api, sites, name: str, props: dict, default: list | None = None):
    """The Filter List, plus a table reading the narrowed set."""
    mod = Module(api, name, beside=sites)
    clauses = {"id": "v_clauses", "kind": "array", "label": "Filters"}
    if default is not None:
        clauses["default"] = default
    mod.define({
        "format": 2,
        "layout": layout({
            "fl": {"resolvedName": "CanvasFilterList",
                   "props": {"objectSetVariable": "v_all", "variable": "v_clauses",
                             "title": "Sites", **props}},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_picked", "columns": "id,region",
                              "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            "v_clauses": clauses,
            "v_picked": {
                "id": "v_picked", "kind": "object_set", "label": "Narrowed",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_clauses"]},
            },
        },
        "events": {},
    })
    return mod


def shown(page) -> list[str]:
    # One read of every cell: counting and then reading each races a table
    # that is still redrawing.
    cells = page.locator(".data-grid tbody tr td:first-child").all_text_contents()
    return sorted(c.strip() for c in cells)


def rows_are(page, ids: list[str], what: str) -> None:
    eventually(lambda: shown(page), lambda got: got == sorted(ids), what=what)


def one(component: str, prop: str = "region", fid: str = "f_1") -> dict:
    return {"id": fid, "property": prop, "component": component}


EVERY = [r["id"] for r in ROWS]
NORTH = ["N1", "N2", "N3", "N4"]
SOUTH = ["S1", "S2"]


def test_a_histogram_draws_each_value_as_a_bar_and_filters(page, api, sites) -> None:
    mod = build(api, sites, "Filter list histogram", {"filters": [one("histogram")]})
    open_module(page, mod)
    rows_are(page, EVERY, "every row before anything is ticked")
    bar = page.locator(".canvas-filter-bar")
    expect(bar).to_have_count(3)
    # p.446's "most common property values", as bars of their share of the largest.
    north = bar.filter(has_text="north")
    expect(north).to_have_attribute("style", "--bar: 100%;")
    expect(bar.filter(has_text="south")).to_have_attribute("style", "--bar: 50%;")
    expect(north.locator(".canvas-filter-count")).to_have_text("4")
    # Headed by the property's display name, not its api_name.
    expect(page.get_by_test_id("filter-f_1").locator("legend")).to_have_text("Region")

    north.get_by_role("checkbox").check()
    rows_are(page, NORTH, "the northern rows")
    bar.filter(has_text="south").get_by_role("checkbox").check()
    rows_are(page, NORTH + SOUTH, "north and south together")


def test_a_filter_list_saved_before_components_is_histograms(page, api, sites) -> None:
    """A comma-separated `properties` is what every Filter List before §463
    has. It keeps drawing, as histograms - and Craft filling the new `filters`
    from its default must not replace it with nothing."""
    mod = build(api, sites, "Filter list legacy", {"properties": "region"})
    open_module(page, mod)
    page.locator(".canvas-filter-bar", has_text="south").get_by_role("checkbox").check()
    rows_are(page, SOUTH, "the southern rows")


def test_a_single_select_dropdown_picks_one_value(page, api, sites) -> None:
    mod = build(api, sites, "Filter list single", {"filters": [one("singleSelect")]})
    open_module(page, mod)
    rows_are(page, EVERY, "every row first")
    pick = page.get_by_role("combobox", name="Region", exact=True)
    expect(pick.locator("option")).to_have_text(["Any", "north (4)", "south (2)", "east (1)"])
    pick.select_option("south")
    rows_are(page, SOUTH, "south alone")
    pick.select_option("north")
    rows_are(page, NORTH, "north instead of south, not as well")
    pick.select_option("")
    rows_are(page, EVERY, "every row again on Any")


def test_a_multi_select_dropdown_adds_and_removes_values(page, api, sites) -> None:
    mod = build(api, sites, "Filter list multi", {"filters": [one("multiSelect")]})
    open_module(page, mod)
    rows_are(page, EVERY, "every row first")
    add = page.get_by_role("combobox", name="Add to region")
    add.select_option("north")
    rows_are(page, NORTH, "north")
    # What is chosen is not offered again.
    expect(add.locator("option")).to_have_text(["Add a value…", "south (2)", "east (1)"])
    add.select_option("east")
    rows_are(page, NORTH + ["E1"], "north and east")
    page.get_by_role("button", name="Remove north").click()
    rows_are(page, ["E1"], "east alone")


def test_a_keyword_filters_on_what_a_value_starts_with(page, api, sites) -> None:
    mod = build(api, sites, "Filter list keyword", {"filters": [one("keyword", "name")]})
    open_module(page, mod)
    rows_are(page, EVERY, "every row first")
    page.get_by_role("searchbox", name="name").fill("sou")
    rows_are(page, SOUTH, "the names starting sou")
    page.get_by_role("searchbox", name="name").fill("")
    rows_are(page, EVERY, "every row once it is cleared")


def test_a_date_range_includes_both_of_its_days(page, api, sites) -> None:
    """March, inclusive: N3 is the evening of the 31st, which a range written as
    `lte 2024-03-31` would drop; N4 is midnight on 1 April and S1 the last hour
    of February, which it must not take in."""
    mod = build(api, sites, "Filter list dates", {"filters": [one("dateRange", "at")]})
    open_module(page, mod)
    rows_are(page, EVERY, "every row first")
    page.get_by_label("at from").fill("2024-03-01")
    rows_are(page, ["N1", "N2", "N3", "N4", "S2", "E1"], "from 1 March on")
    page.get_by_label("at to").fill("2024-03-31")
    rows_are(page, ["N1", "N2", "N3", "S2"], "March, both ends in")
    # The table's caption says what the range is, rather than "at = 2024-03-01".
    expect(page.get_by_text("at is at least 2024-03-01 and at is less than 2024-04-01")) \
        .to_be_visible()


def test_components_on_one_variable_keep_each_others_clauses(page, api, sites) -> None:
    """A keyword and a histogram on the same property, and a default someone
    else set: each click replaces only its own clause. The widget used to
    rebuild the list from its checkboxes, which turned a prefix into an equality
    and dropped whatever it did not draw."""
    mod = build(api, sites, "Filter list sharing", {"filters": [
        one("histogram", fid="f_1"), one("keyword", "name", fid="f_2"),
    ]}, default=[{"property": "id", "op": "in", "value": ["N1", "N2", "S1", "E1"]}])
    open_module(page, mod)
    rows_are(page, ["N1", "N2", "S1", "E1"], "the default applied")
    page.get_by_role("searchbox", name="name").fill("n")
    rows_are(page, ["N1", "N2"], "the default and the keyword")
    page.locator(".canvas-filter-bar", has_text="north").get_by_role("checkbox").check()
    rows_are(page, ["N1", "N2"], "all three together")
    page.locator(".canvas-filter-bar", has_text="north").get_by_role("checkbox").uncheck()
    expect(page.get_by_role("searchbox", name="name")).to_have_value("n")
    rows_are(page, ["N1", "N2"], "the keyword and the default, still")
    page.get_by_role("searchbox", name="name").fill("")
    rows_are(page, ["N1", "N2", "S1", "E1"], "the default, still")


def test_the_panel_adds_filters_and_chooses_components(page, api, sites) -> None:
    """p.449's Add filter and Filter component. The date range is offered only
    on a date, since on anything else it writes a comparison the server refuses."""
    mod = build(api, sites, "Filter list panel", {"filters": []})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Filter list").first.click()
    add = page.get_by_test_id("filter-add")
    add.select_option("region")
    component = page.get_by_test_id("filter-component-f_1")
    expect(component.locator("option")).to_have_text(
        ["Histogram", "Single-select dropdown", "Multi-select dropdown", "Keyword"])
    component.select_option("multiSelect")
    add.select_option("at")
    expect(page.get_by_test_id("filter-component-f_2").locator("option")).to_contain_text(
        ["Date range"])
    page.get_by_test_id("filter-component-f_2").select_option("dateRange")
    save(page)
    assert mod.definition()["layout"]["fl"]["props"]["filters"] == [
        one("multiSelect"), one("dateRange", "at", fid="f_2")]
    # A date range moved onto a property that is not a date falls back. Read
    # from the document: the select would show its first option either way,
    # since a date range is no longer among them.
    page.get_by_test_id("filter-property-f_2").select_option("name")
    save(page)
    eventually(lambda: mod.definition()["layout"]["fl"]["props"]["filters"][1],
               lambda got: got == one("histogram", "name", fid="f_2"),
               what="the moved filter as a histogram")
