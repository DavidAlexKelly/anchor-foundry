"""p.472's links in the Exploration Search Bar (§578).

> "The widget supports both filtering on properties on the object type and
> filtering with linked object types and their properties." (p.472)
> "Link types available: Define which link types to display in the dropdown
> menu. Options include All (Including hidden), Prominent, Visible, Custom
> list, or None." (p.473)

The set is employees, and the link is the issues each has raised
(`test_filter_list_links.py`'s world). Linus has raised none, so "has any"
has someone to leave out; Ada and Grace have two each, and a filter on the
issues' titles picks between them.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled, stays
from test_filter_list_links import world  # noqa: F401

EVERYONE = ["E1", "E2", "E3"]


def build(api, world, name: str, **props) -> Module:
    mod = Module(api, name, beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "bar": {"resolvedName": "CanvasSearchBar", "props": {
                "objectSetVariable": "v_picked", "variable": "v_clauses", **props}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everyone",
                      "object_set": object_set(world.employee_type)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Filters"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Narrowed",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_clauses"]}},
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


def entry(page, kind: str, text: str = ""):
    return page.locator(f"[data-testid='search-bar-option'][data-kind='{kind}']",
                        has_text=text).first


def pick_link(page) -> None:
    field(page).fill("raised")
    entry(page, "link", "Raised by").click()
    expect(page.get_by_test_id("search-bar-picked-link")).to_have_text("Raised by")


def test_has_any_leaves_out_who_has_none(page, api, world) -> None:
    open_module(page, build(api, world, "Search bar has link"))
    rows_are(page, EVERYONE, "everyone")
    pick_link(page)
    entry(page, "has_link").click()
    rows_are(page, ["E1", "E2"], "those who raised an issue")
    expect(page.get_by_test_id("filter-pill-text")).to_have_text("Has Raised by")


def test_a_linked_property_filters_by_its_value(page, api, world) -> None:
    open_module(page, build(api, world, "Search bar linked value"))
    rows_are(page, EVERYONE, "everyone")
    pick_link(page)
    field(page).fill("tit")
    entry(page, "far_property", "title").click()
    # The suggestions are the linked type's own values.
    field(page).fill("VPN")
    entry(page, "value", "VPN down (1)").click()
    rows_are(page, ["E1"], "whoever raised the VPN issue")
    expect(page.get_by_test_id("filter-pill-text")).to_have_text(
        "Has Raised by where title is VPN down")


def test_two_filters_on_one_link_hold_of_one_linked_object(page, api, world) -> None:
    """Both filters go into the link's one clause, so the same issue must meet
    both: Ada raised a printer issue and the VPN one, but no one issue is both."""
    open_module(page, build(api, world, "Search bar linked pair"))
    rows_are(page, EVERYONE, "everyone")
    pick_link(page)
    field(page).fill("title")
    entry(page, "far_property", "title").click()
    page.get_by_test_id("search-bar-op").select_option("starts_with")
    field(page).fill("Printer")
    field(page).press("Enter")
    rows_are(page, ["E1", "E2"], "whoever raised a printer issue")
    pick_link(page)
    field(page).fill("title")
    entry(page, "far_property", "title").click()
    field(page).fill("VPN down")
    field(page).press("Enter")
    rows_are(page, [], "nobody: no one issue is both")
    expect(page.get_by_test_id("filter-pill")).to_have_count(1)


def test_backspace_steps_back_out_of_a_link(page, api, world) -> None:
    open_module(page, build(api, world, "Search bar link back"))
    rows_are(page, EVERYONE, "everyone")
    pick_link(page)
    field(page).press("Backspace")
    expect(page.get_by_test_id("search-bar-picked-link")).to_have_count(0)
    field(page).fill("raised")
    expect(entry(page, "link", "Raised by")).to_be_visible()


def test_no_links_when_p473_says_none(page, api, world) -> None:
    open_module(page, build(api, world, "Search bar no links", linkScope="none"))
    rows_are(page, EVERYONE, "everyone")
    field(page).fill("raised")
    stays(lambda: page.locator("[data-testid='search-bar-option'][data-kind='link']").count(),
          lambda n: n == 0, what="no link offered", for_ms=2000)


def test_the_panel_lists_the_links_to_offer(page, api, world) -> None:
    mod = build(api, world, "Search bar link panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Exploration search bar").first.click()
    page.get_by_test_id("search-bar-link-scope").select_option("custom")
    box = page.locator("[data-testid^='search-bar-custom-link-']").first
    box.check()
    save(page)
    props = mod.definition()["layout"]["bar"]["props"]
    assert props["linkScope"] == "custom"
    assert props["customLinks"] == [world.link]
