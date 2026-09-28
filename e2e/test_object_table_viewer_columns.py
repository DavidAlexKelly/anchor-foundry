"""p.222's viewer-side Configure columns, and p.225's switch that hides it (§612).

> "Users in View mode can also choose to configure the columns shown to them.
> By selecting Configure columns from the arrow next to a column header,
> viewers can choose the columns and the order to display them in the Object
> Table." (p.222)

> "Hide column configuration: When enabled, hides the Configure columns option
> present in view mode from the table's header menu." (p.225)

The rules are `viewer-columns.test.ts`. What needs a browser is that the
choice redraws the table, survives a reload in the viewer's own browser, and
never reaches the builder or the document.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "S1", "region": "north", "name": "Alpha", "note": "first"},
    {"id": "S2", "region": "south", "name": "Bravo", "note": "second"},
]


def build(api, name: str, *, hide: bool = False):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name", "note"], rows=ROWS, key="id", title="id")
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "region,name,note",
                              "pageSize": 25, "activeVariable": None, "autoSelect": False,
                              "hideColumnConfig": hide}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def headers(page) -> list[str]:
    heads = page.locator("thead th")
    expect(heads.first).to_be_visible(timeout=15000)
    return [h.inner_text().replace("▾", "").strip().lower() for h in heads.all()][1:]


def panel(page):
    return page.get_by_test_id("table-columns-panel")


def open_panel(page) -> None:
    page.get_by_test_id("table-configure-columns").click()
    expect(panel(page)).to_be_visible()


def test_a_viewer_chooses_and_orders_their_columns(page, api):
    mod = build(api, "Viewer columns")
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == ["region", "name", "note"]

    open_panel(page)
    panel(page).get_by_test_id("table-column-region").get_by_role("checkbox").uncheck()
    expect(page.locator("thead th")).to_have_count(3)
    assert headers(page) == ["name", "note"]
    panel(page).get_by_test_id("table-column-note-up").click()
    expect(page.locator("thead th").nth(1)).to_contain_text("note", ignore_case=True)
    assert headers(page) == ["note", "name"]

    # The viewer's own browser keeps it, across a fresh load of the module.
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    expect(page.locator("thead th")).to_have_count(3)
    assert headers(page) == ["note", "name"]

    open_panel(page)
    page.get_by_test_id("table-columns-reset").click()
    expect(page.locator("thead th")).to_have_count(4)
    assert headers(page) == ["region", "name", "note"]


def test_the_last_column_cannot_be_unchecked(page, api):
    mod = build(api, "Viewer columns last")
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    open_panel(page)
    for name in ("region", "name"):
        panel(page).get_by_test_id(f"table-column-{name}").get_by_role("checkbox").uncheck()
    last = panel(page).get_by_test_id("table-column-note").get_by_role("checkbox")
    expect(last).to_be_checked()
    expect(last).to_be_disabled()
    assert headers(page) == ["note"]


def test_the_panel_closes_on_escape_and_outside(page, api):
    mod = build(api, "Viewer columns close")
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    open_panel(page)
    page.keyboard.press("Escape")
    expect(panel(page)).to_have_count(0)
    open_panel(page)
    page.mouse.click(5, 5)
    expect(panel(page)).to_have_count(0)


def test_the_builder_sees_the_table_as_configured(page, api):
    """A viewer's choice is theirs: the builder has no caret, and draws the
    configured columns whatever the same browser chose as a reader."""
    mod = build(api, "Viewer columns builder")
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    open_panel(page)
    panel(page).get_by_test_id("table-column-region").get_by_role("checkbox").uncheck()
    assert headers(page) == ["name", "note"]

    open_builder(page, mod)
    settled(page)
    expect(page.get_by_test_id("table-configure-columns")).to_have_count(0)
    assert headers(page) == ["region", "name", "note"]


def test_hiding_column_configuration_removes_the_arrow(page, api):
    mod = build(api, "Viewer columns hidden", hide=True)
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    expect(page.get_by_test_id("table-configure-columns")).to_have_count(0)
