"""p.243's Custom right-click menu on the Object Table (§613).

> "Adding custom row actions to the right-click menu allows users to run
> actions or events on an object that is right-clicked from the object table.
> … enable the Customize right-click menu toggle … Setting this toggle to true
> will prompt you to create a right-clicked object which outputs the currently
> right-clicked object in the table. You can then add custom items to the menu
> by selecting Add item." (p.243)

What the server accepts - an item the table has, and no click without one -
is `test_workshop_variables.py`. What needs a browser is the chain: a
right-click writes the right-clicked object, which a `narrow_set` derivation
turns into a set a second table shows; an item fires its own events with the
row as the selection; and the builder can switch the menu on and aim an event
at an item.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

ROWS = [{"id": f"S{i}", "name": f"Site {i}"} for i in range(1, 4)]


def setting(item: str, value: str) -> dict:
    return {"trigger": {"node": "tbl", "on": "click", "item": item}, "effects": [
        {"type": "set_variable", "config": {"variable": "v_note", "value": value}}]}


def build(api, name: str, *, custom: bool = True, export: bool = False):
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "name"], rows=ROWS, key="id", title="id")
    items = [{"id": "i_1", "label": "Note the name"}, {"id": "i_2", "label": "Note the key"}]
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_all", "columns": "name", "autoSelect": False,
                "customMenu": custom, "menuItems": items, "exportCsv": export,
                "rightClickedVariable": "v_rc",
            }},
            "down": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_rc_s", "columns": "name", "autoSelect": False,
            }},
            "note": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "NOTE={{v_note}}"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
            "v_rc": {"id": "v_rc", "kind": "array", "label": "Right-clicked clauses"},
            "v_rc_s": {
                "id": "v_rc_s", "kind": "object_set", "label": "Right-clicked object",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_rc"]},
            },
            "v_note": {"id": "v_note", "kind": "string", "label": "Note", "default": "none"},
        },
        # With the menu off its items are no clicks, and the server refuses an
        # event aimed at one - as it does for a Menu button switched to Inline.
        "events": {
            "e_name": {"id": "e_name", **setting("i_1", "{{name}}")},
            "e_key": {"id": "e_key", **setting("i_2", "{{primary_key}}")},
        } if custom else {},
    })
    return mod


def tables(page):
    return page.locator("table")


def test_an_item_fires_its_own_events_on_the_right_clicked_row(page, api) -> None:
    mod = build(api, "Row menu items")
    open_module(page, mod)
    rows = tables(page).first.locator("tbody tr")
    expect(rows).to_have_count(3, timeout=15000)
    expect(page.get_by_text("NOTE=none")).to_be_visible()

    rows.nth(1).click(button="right")
    menu = page.get_by_test_id("table-row-menu")
    expect(menu.get_by_role("menuitem")).to_have_text(["Note the name", "Note the key"])
    # Export is its own toggle, and off here.
    expect(page.get_by_test_id("table-export-csv")).to_have_count(0)
    # The right-click itself writes the right-clicked object, before any item.
    expect(tables(page).nth(1).locator("tbody tr")).to_have_count(1)
    expect(tables(page).nth(1).locator("tbody tr")).to_contain_text("Site 2")

    menu.get_by_role("menuitem", name="Note the name").click()
    expect(page.get_by_text("NOTE=Site 2")).to_be_visible()
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)

    # Another row, another item: each item fires only its own events.
    rows.nth(2).click(button="right")
    expect(tables(page).nth(1).locator("tbody tr")).to_contain_text("Site 3")
    page.get_by_test_id("table-row-item-i_2").click()
    expect(page.get_by_text("NOTE=S3")).to_be_visible()


def test_items_sit_beside_export_when_both_are_on(page, api) -> None:
    mod = build(api, "Row menu with export", export=True)
    open_module(page, mod)
    rows = tables(page).first.locator("tbody tr")
    expect(rows).to_have_count(3, timeout=15000)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu").get_by_role("menuitem")).to_have_text(
        ["Note the name", "Note the key", "Export to CSV"])


def test_no_menu_unless_the_toggle_is_on(page, api) -> None:
    """The items are kept while the toggle is off, and offered by nothing."""
    mod = build(api, "Row menu off", custom=False)
    open_module(page, mod)
    rows = tables(page).first.locator("tbody tr")
    expect(rows).to_have_count(3, timeout=15000)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)
    # Nor does the builder offer them to an event: with the toggle off, the
    # table's only trigger is its row selection, items or no items.
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    expect(when(page).locator("option")).to_have_text(["Row selected"])


def when(page):
    """The open event's trigger picker."""
    return page.locator(".canvas-event.on select").nth(1)


def test_the_builder_switches_the_menu_on_and_aims_an_event_at_an_item(page, api) -> None:
    mod = Module(api, "Row menu builder")
    type_id = mod.object_type(columns=["id", "name"], rows=ROWS, key="id", title="id")
    mod.define({
        "format": 2,
        "layout": layout({"tbl": {"resolvedName": "CanvasObjectTable", "props": {
            "objectSetVariable": "v_all", "columns": "name", "autoSelect": False}}}),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
            "v_rc": {"id": "v_rc", "kind": "array", "label": "Right-clicked clauses"},
        },
        "events": {},
    })
    open_builder(page, mod)
    settled(page)

    # Before the menu is customised a table's only trigger is its row
    # selection: a click would be an item it does not have.
    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    expect(when(page).locator("option")).to_have_text(["Row selected"])
    expect(page.get_by_test_id("event-item")).to_have_count(0)
    page.get_by_role("button", name="Widget", exact=True).click()

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-menu-items")).to_have_count(0)
    page.get_by_test_id("table-custom-menu-toggle").check()
    # Switched on, it starts with an item to rename.
    expect(page.get_by_test_id("table-menu-item-i_1")).to_have_value("Option 1")
    page.get_by_test_id("table-menu-item-i_1").fill("Flag")
    page.get_by_test_id("table-menu-add-item").click()
    expect(page.get_by_test_id("table-menu-item-i_2")).to_be_visible()
    page.get_by_role("button", name="Remove Option 2").click()
    expect(page.get_by_test_id("table-menu-item-i_2")).to_have_count(0)
    page.get_by_test_id("table-right-clicked-variable").select_option("v_rc")
    # The builder draws the table; a right-click there opens no reader's menu.
    page.locator("tbody tr").first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)

    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="New event").click()
    expect(when(page).locator("option")).to_have_text(["Right-click menu item", "Row selected"])
    expect(page.get_by_test_id("event-item").locator("option")).to_have_text(["Flag"])
    # A row selection comes from no item, so switching to it lets the item go.
    when(page).select_option("row_select")
    expect(page.get_by_test_id("event-item")).to_have_count(0)
    save(page)
    triggers = sorted((e["trigger"] for e in mod.definition()["events"].values()),
                      key=lambda t: sorted(t))
    assert triggers == [{"node": "tbl", "on": "row_select"}] * 2, triggers
    # And back: a click starts on the first item again.
    when(page).select_option("click")
    expect(page.get_by_test_id("event-item")).to_have_value("i_1")
    save(page)
    eventually(lambda: [e["trigger"] for e in mod.definition()["events"].values()],
               lambda got: sorted(got, key=len) == [
                   {"node": "tbl", "on": "row_select"},
                   {"node": "tbl", "on": "click", "item": "i_1"}],
               what="the event aimed at the item again")
    props = mod.definition()["layout"]["tbl"]["props"]
    assert props["customMenu"] is True
    assert props["menuItems"] == [{"id": "i_1", "label": "Flag"}]
    assert props["rightClickedVariable"] == "v_rc"
