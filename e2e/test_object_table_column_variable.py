"""p.225's variable-backed column visibility on the Object Table (§610).

> "Variable-backed column visibility: When enabled, allows control over which
> columns are visible using a string array variable containing the API names
> of visible columns. This array variable also controls the order that columns
> appear in. If the string array is empty, all configured columns will be
> shown in the table." (p.225)

Which names show, in which order, is `column-visibility.test.ts`. What needs a
browser is that the table reads the variable and redraws when it changes -
here through a String selector writing the same array a reader would pick.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "S1", "region": "north", "name": "Alpha", "note": "first"},
    {"id": "S2", "region": "south", "name": "Bravo", "note": "second"},
]


def build(api, name: str, *, default, columns="region,name,note", picker=False):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name", "note"], rows=ROWS, key="id", title="id")
    variable = {"id": "v_cols", "kind": "array", "element": "string", "label": "Columns"}
    if default is not None:
        variable["default"] = default
    nodes = {}
    if picker:
        # A reader choosing columns: p.461's checkboxes writing the same
        # string array the table reads.
        nodes["sel"] = {"resolvedName": "CanvasStringSelector",
                        "props": {"name": "v_cols", "label": "Columns",
                                  "selection": "multiple", "display": "checkboxes",
                                  "optionSource": "static",
                                  "options": ["region", "name", "note"],
                                  "optionsVariable": "", "placeholder": "",
                                  "allowClearing": True, "layout": "vertical",
                                  "columns": 3}}
    mod.define({
        "format": 2,
        "layout": layout({
            **nodes,
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": columns,
                              "columnsVariable": "v_cols", "pageSize": 25,
                              "activeVariable": None, "autoSelect": False}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
            "v_cols": variable,
        },
        "events": {},
    })
    return mod


def headers(page) -> list[str]:
    """Lower-cased: the table upper-cases its headers in CSS. The key column
    is always first and is not one of the configured ones."""
    heads = page.locator("thead th")
    expect(heads.first).to_be_visible(timeout=15000)
    return [h.inner_text().strip().lower() for h in heads.all()][1:]


def test_the_variable_chooses_and_orders_the_columns(page, api):
    mod = build(api, "Column variable order", default=["note", "region"])
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == ["note", "region"]


def test_an_empty_variable_shows_every_configured_column(page, api):
    mod = build(api, "Column variable empty", default=[])
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == ["region", "name", "note"]


def test_the_variable_chooses_among_configured_columns_only(page, api):
    """A name the author did not configure stays out, and the builder says
    which names are not columns of this table."""
    mod = build(api, "Column variable configured", default=["id_card", "name"],
                columns="region,name")
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == ["name"]

    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-columns-variable")).to_have_value("v_cols")
    expect(page.get_by_test_id("table-columns-variable-unknown")).to_contain_text("id_card")


def test_with_no_columns_configured_it_chooses_among_every_property(page, api):
    mod = build(api, "Column variable all", default=["name"], columns="")
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == ["name"]


def test_the_table_redraws_as_a_reader_picks_columns(page, api):
    mod = build(api, "Column variable picked", default=None, picker=True)
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == ["region", "name", "note"]

    group = page.get_by_test_id("selector-options")
    group.get_by_role("checkbox", name="note").check()
    expect(page.locator("thead th")).to_have_count(2)
    assert headers(page) == ["note"]
    group.get_by_role("checkbox", name="region").check()
    expect(page.locator("thead th")).to_have_count(3)
    # The array's order - the order they were picked - not the configured one.
    assert headers(page) == ["note", "region"]
    # Unpicking them all is an empty array, which is every configured column.
    group.get_by_role("checkbox", name="note").uncheck()
    group.get_by_role("checkbox", name="region").uncheck()
    expect(page.locator("thead th")).to_have_count(4)


def test_a_variable_naming_no_column_here_shows_none(page, api):
    """Not a fallback to every column: the variable said which, and none of
    them is here. Only the key column is left."""
    mod = build(api, "Column variable none", default=["id_card"])
    open_module(page, mod)
    expect(page.locator("tbody tr")).to_have_count(2, timeout=15000)
    assert headers(page) == []
