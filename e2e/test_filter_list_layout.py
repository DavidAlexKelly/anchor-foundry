"""p.449's Allow user to add and remove filters, and its Pills layout (parity
`workshop.md` §10's Filter List row; §464).

> "Allow user to add and remove filters: If enabled, users will see an Add
> filter button within the widget and will be able to add and remove
> filterable properties." (p.449)
>
> "Pills layout: This option will layout all the filters horizontally within
> an interactive pill. Once selected, the pill opens a popover with filter
> configuration UI." (p.449)

What a pill says and what removing a filter takes with it are
`filter-list.test.ts`. What needs a browser is that a removed filter stops
narrowing the table, that a viewer's filters are theirs and not the module's,
and that a pill opens onto a component that works.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import open_builder, open_module, save, settled
from test_filter_list import EVERY, NORTH, SOUTH, build, one, rows_are, sites  # noqa: F401


def test_a_viewer_adds_a_filter_and_uses_it(page, api, sites) -> None:
    mod = build(api, sites, "Filter list user add", {
        "filters": [one("keyword", "name")], "userEditable": True})
    open_module(page, mod)
    rows_are(page, EVERY, "every row first")
    add = page.get_by_role("combobox", name="Add filter")
    # What is already shown is not offered again.
    expect(add.locator("option")).not_to_contain_text(["Name"])
    add.select_option("region")
    page.locator(".canvas-filter-bar", has_text="south").get_by_role("checkbox").check()
    rows_are(page, SOUTH, "the viewer's own filter narrowing")
    # A date is added as a date range, not a histogram of instants.
    add.select_option("at")
    expect(page.get_by_label("At from")).to_be_visible()
    # And a viewer's own filter is removed as a configured one is, clause and all.
    page.get_by_role("button", name="Remove the Region filter").click()
    expect(page.locator(".canvas-filter-bar")).to_have_count(0)
    rows_are(page, EVERY, "every row once the viewer's filter is gone")


def test_removing_a_filter_takes_its_clause_with_it(page, api, sites) -> None:
    """A filter removed while its clause stayed would go on narrowing the set
    with nothing on screen to say so, or to undo."""
    mod = build(api, sites, "Filter list user remove", {
        "filters": [one("histogram")], "userEditable": True})
    open_module(page, mod)
    page.locator(".canvas-filter-bar", has_text="north").get_by_role("checkbox").check()
    rows_are(page, NORTH, "north")
    page.get_by_role("button", name="Remove the Region filter").click()
    expect(page.locator(".canvas-filter-bar")).to_have_count(0)
    rows_are(page, EVERY, "every row once the filter is gone")


def test_a_viewers_filters_are_not_saved_into_the_module(page, api, sites) -> None:
    """Runtime state (decision 0002 §3): the next reader gets the module's
    filters, not the last reader's."""
    mod = build(api, sites, "Filter list user runtime", {
        "filters": [one("histogram")], "userEditable": True})
    open_module(page, mod)
    page.get_by_role("button", name="Remove the Region filter").click()
    page.get_by_role("combobox", name="Add filter").select_option("name")
    expect(page.get_by_role("group", name="Name")).to_be_visible()
    open_module(page, mod)
    expect(page.locator(".canvas-filter-bar", has_text="north")).to_be_visible()
    expect(page.get_by_role("group", name="Name")).to_have_count(0)
    assert mod.definition()["layout"]["fl"]["props"]["filters"] == [one("histogram")]


def test_without_the_setting_there_is_nothing_to_add_or_remove(page, api, sites) -> None:
    mod = build(api, sites, "Filter list fixed", {"filters": [one("histogram")]})
    open_module(page, mod)
    # Positive first (§318): the widget has drawn.
    expect(page.locator(".canvas-filter-bar", has_text="north")).to_be_visible()
    expect(page.get_by_role("combobox", name="Add filter")).to_have_count(0)
    expect(page.get_by_role("button", name="Remove the Region filter")).to_have_count(0)


def test_pills_open_a_popover_and_say_what_is_applied(page, api, sites) -> None:
    mod = build(api, sites, "Filter list pills", {
        "filters": [one("multiSelect"), one("keyword", "name", fid="f_2")],
        "layout": "pills"})
    open_module(page, mod)
    rows_are(page, EVERY, "every row first")
    region = page.get_by_role("button", name="Region", exact=True)
    # Closed, a pill is only its name: nothing is drawn until it is opened.
    expect(page.get_by_role("combobox", name="Add to Region")).to_have_count(0)
    region.click()
    expect(region).to_have_attribute("aria-expanded", "true")
    page.get_by_role("combobox", name="Add to Region").select_option("south")
    rows_are(page, SOUTH, "south, chosen from the pill")
    page.keyboard.press("Escape")
    expect(page.get_by_role("combobox", name="Add to Region")).to_have_count(0)
    # And, closed again, says what it applies.
    expect(page.get_by_role("button", name="Region: south")).to_be_visible()

    page.get_by_role("button", name="Name", exact=True).click()
    page.get_by_role("searchbox", name="Name").fill("south 2")
    rows_are(page, ["S2"], "the keyword too")
    # A click elsewhere closes it.
    page.locator(".data-grid").click()
    expect(page.get_by_role("searchbox", name="Name")).to_have_count(0)
    expect(page.get_by_role("button", name="Name: starts with “south 2”")).to_be_visible()


def test_the_panel_sets_the_layout_and_the_viewer_setting(page, api, sites) -> None:
    mod = build(api, sites, "Filter list layout panel", {"filters": [one("histogram")]})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Filter list").first.click()
    page.get_by_test_id("filter-layout").select_option("pills")
    page.get_by_test_id("filter-user-editable").check()
    save(page)
    props = mod.definition()["layout"]["fl"]["props"]
    assert props["layout"] == "pills" and props["userEditable"] is True, props
