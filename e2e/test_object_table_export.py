"""p.223's Object Table right-click menu: export to CSV (§611).

> "Enable export to CSV: When enabled, this toggle allows a user to export
> object table data to CSV format from a row's right-click menu. … capable of
> exporting up to 10,000 rows at a time." (p.223)

The file is §459's - `object-export.test.ts` and `test_export_event.py` hold
its bytes. What this checks is the table's half: the menu is there only when
the toggle is on, it exports the whole set rather than the page, and in the
columns the table shows.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [{"id": f"S{i}", "region": "north" if i % 2 else "south", "name": f"Site {i}",
         "note": "x"} for i in range(1, 4)]


def build(api, name: str, *, export: bool, over_set: bool = True):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name", "note"], rows=ROWS, key="id", title="id")
    props = {"columns": "name,region", "pageSize": 2, "activeVariable": None,
             "autoSelect": False, "exportCsv": export}
    if over_set:
        props["objectSetVariable"] = "v_all"
    else:
        props["objectTypeId"] = type_id
    mod.define({
        "format": 2,
        "layout": layout({"tbl": {"resolvedName": "CanvasObjectTable", "props": props}}),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def test_a_rows_right_click_exports_the_whole_set_in_the_columns_shown(page, api):
    mod = build(api, "Table export", export=True)
    open_module(page, mod)
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(2, timeout=15000)   # a page of two, of three

    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_be_visible()
    with page.expect_download() as waiting:
        page.get_by_test_id("table-export-csv").click()
    with open(waiting.value.path(), encoding="utf-8", newline="") as handle:
        lines = handle.read().splitlines()
    # The key first, then the table's own columns in its order - and all
    # three objects, not the two on the page.
    assert lines[0].lower() == "key,name,region", lines
    assert sorted(lines[1:]) == ["S1,Site 1,north", "S2,Site 2,south", "S3,Site 3,north"]
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)


def test_no_menu_unless_the_toggle_is_on(page, api):
    mod = build(api, "Table export off", export=False)
    open_module(page, mod)
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(2, timeout=15000)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)


def test_the_menu_closes_on_escape_and_on_a_press_elsewhere(page, api):
    mod = build(api, "Table export close", export=True)
    open_module(page, mod)
    rows = page.locator("tbody tr")
    expect(rows).to_have_count(2, timeout=15000)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_be_visible()
    page.mouse.click(5, 5)
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)


def test_a_table_over_a_type_has_no_set_to_export(page, api):
    """The toggle on, but the table reads a type narrowed by a search box: no
    set an export can name, so no menu - and the panel says why."""
    mod = build(api, "Table export type", export=True, over_set=False)
    open_module(page, mod)
    rows = page.locator("tbody tr")
    expect(rows.first).to_be_visible(timeout=15000)
    rows.first.click(button="right")
    expect(page.get_by_test_id("table-row-menu")).to_have_count(0)

    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-export-csv-hint")).to_contain_text(
        "Offered when the table reads an object set variable")
