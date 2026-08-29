"""p.224's Object Table Selection block (parity `workshop.md` §10).

> "**Active object**: This is the first of two output variables in the Object
> Table and outputs an object set of the currently active / highlighted
> object… **Disable active object auto-selection**: By default, the first row in
> the table is automatically set as the active object at load time… Note that
> auto-selection only triggers when the widget is visible; if the Object Table
> is within a collapsed section, auto-selection will not occur until the section
> is expanded and the widget becomes visible." (p.224)

The clause arithmetic is in
`apps/web/src/components/canvas/object-table-selection.test.ts`, mutation-tested
without a browser.

**What needs one is the whole chain**: a click writes clauses, the server
resolves a `narrow_set` derivation from them, and a second widget shows the
result. Every test here reads a *downstream* table rather than the selected row,
because the row can look right while the set behind it is wrong — and the set is
what the rest of the module acts on.

The variable graph under test:

    v_all       (object_set)  the whole set
    v_active    (array)       what the table writes for the highlighted row
    v_active_s  (object_set)  narrow_set(v_all, v_active)
    v_selected  (array)       what the checkboxes write
    v_sel_s     (object_set)  narrow_set(v_all, v_selected)
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "S1", "region": "north", "name": "Alpha"},
    {"id": "S2", "region": "north", "name": "Bravo"},
    {"id": "S3", "region": "south", "name": "Charlie"},
]


def build(api, name: str, table_props: dict | None = None, *, collapsed: bool = False):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name"], rows=ROWS, key="id", title="name"
    )
    table = {
        "resolvedName": "CanvasObjectTable",
        "props": {
            "objectSetVariable": "v_all", "columns": "id,name", "pageSize": 25,
            "activeVariable": "v_active", "autoSelect": True,
            "multiSelect": False, "selectedVariable": None,
            **(table_props or {}),
        },
    }
    nodes: dict = {}
    if collapsed:
        # p.224's own example of "not visible". A collapsed section keeps its
        # children **mounted**, so the table inside is running - which is
        # exactly why this needs saying.
        nodes["sec"] = {
            "resolvedName": "CanvasSection", "isCanvas": True,
            "props": {"direction": "rows", "gap": 12, "title": "Folded",
                      "collapsible": True, "collapsedByDefault": True},
            "nodes": ["tbl"],
        }
        nodes["tbl"] = {**table, "parent": "sec"}
    else:
        nodes["tbl"] = table
    # The two downstream readers. These are the assertion surface: what the
    # module *acts on*, not what the clicked row looks like.
    nodes["act"] = {
        "resolvedName": "CanvasObjectTable",
        "props": {"objectSetVariable": "v_active_s", "columns": "id,name",
                  "pageSize": 25, "activeVariable": None, "autoSelect": False},
    }
    nodes["sel"] = {
        "resolvedName": "CanvasObjectTable",
        "props": {"objectSetVariable": "v_sel_s", "columns": "id,name",
                  "pageSize": 25, "activeVariable": None, "autoSelect": False},
    }
    mod.define({
        "format": 2,
        "layout": layout(nodes),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
            "v_active": {"id": "v_active", "kind": "array", "label": "Active clauses"},
            "v_active_s": {
                "id": "v_active_s", "kind": "object_set", "label": "Active object",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_active"]},
            },
            "v_selected": {"id": "v_selected", "kind": "array", "label": "Selected clauses"},
            "v_sel_s": {
                "id": "v_sel_s", "kind": "object_set", "label": "Selected objects",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_selected"]},
            },
        },
        "events": {},
    })
    return mod


def table(page, index: int):
    """The nth Object Table on the page, in document order.

    **`> .data-grid`, and the child combinator is the point.** The ROOT
    `CanvasContainer` renders a `.canvas-block` of its own, so a plain
    `.canvas-block` index is off by one — and it fails in the worst way:
    `nth(0)` is the container, which *contains* every row on the page, so an
    assertion like "one row is active" passes against it whichever table the
    row is in. The first version of this file had exactly that, and the passing
    assertion hid the off-by-one in every other one.

    A table's grid is a direct child of its own block and only a descendant of
    the container's, which tells them apart. Indices settle once each table has
    loaded, and every assertion here goes through `expect_set`, which retries.
    """
    return page.locator(".canvas-block:has(> .data-grid)").nth(index)


def rows_of(page, index: int):
    return table(page, index).locator("tbody tr")


def expect_set(page, index: int, keys: list[str]) -> None:
    """Assert what a table's object set contains, **with a clock**.

    The count line is the clock. It is only rendered once the fetch has come
    back, so reading `0` from it means the set is empty — where an empty row
    list means "empty, or not loaded yet", and an assertion that cannot tell
    those apart passes for the wrong reason on every one of these tests (§202).
    """
    expect(table(page, index).locator(".canvas-widget-empty").first).to_have_text(
        re.compile(rf"^{len(keys)}\b")
    )
    rows = rows_of(page, index)
    expect(rows).to_have_count(len(keys))
    for position, key in enumerate(keys):
        expect(rows.nth(position).locator("td").first).to_have_text(key)


def test_the_first_row_is_active_at_load(page, api) -> None:
    """p.224: "By default the first row in the table is automatically set as
    the active object at load time." Asserted through the derivation, so this
    is a claim about the object set the rest of the module sees."""
    mod = build(api, "Table active default")
    open_module(page, mod)
    settled(page)

    expect(table(page, 0).locator("tr.row-active")).to_have_count(1)
    expect_set(page, 1, ["S1"])


def test_clicking_a_row_moves_the_active_object(page, api) -> None:
    mod = build(api, "Table active click")
    open_module(page, mod)
    settled(page)
    expect_set(page, 1, ["S1"])

    table(page, 0).locator("tbody tr", has_text="Charlie").click()
    expect_set(page, 1, ["S3"])


def test_disabling_auto_selection_leaves_an_empty_active_object(page, api) -> None:
    """**The test the whole unit turns on.** p.224: disabling auto-selection
    "results in an empty active object at load time".

    An *empty* one — not an absent one. A variable this widget has never
    written holds no clauses, and no clauses means no narrowing, so the
    downstream set would be the **whole table**: every consumer acting on three
    objects because none was chosen. So the widget writes `$primary_key in []`
    explicitly, which is why the server had to be taught that an empty `in`
    list is the empty set rather than a refusal.
    """
    mod = build(api, "Table no auto select", {"autoSelect": False})
    open_module(page, mod)
    settled(page)

    expect(rows_of(page, 0)).to_have_count(len(ROWS))
    expect(table(page, 0).locator("tr.row-active")).to_have_count(0)
    # Empty, and emphatically not all three. Through the clock, because "no
    # rows" is also what a table that has not loaded looks like — and this is
    # precisely the test that would pass for that reason.
    expect_set(page, 1, [])


def test_a_collapsed_section_defers_auto_selection_until_it_is_opened(page, api) -> None:
    """p.224: "auto-selection only triggers when the widget is visible; if the
    Object Table is within a collapsed section, auto-selection will not occur
    until the section is expanded and the widget becomes visible."

    **Not free.** A collapsed section keeps its children mounted — deliberately,
    so a table inside one does not refetch every time somebody folds it away —
    so the table is running, has its rows, and would happily select one for a
    viewer who cannot see it. Then the drawer p.224 describes opens on a row
    nobody chose.
    """
    mod = build(api, "Table collapsed", collapsed=True)
    open_module(page, mod)
    settled(page)

    # Folded: the downstream set is empty rather than whole. Index 1 and 2 are
    # the two readers; the folded table is index 0 and is not rendering.
    expect_set(page, 1, [])

    page.get_by_role("button", name="Folded").click()
    # Now visible, so p.224's default applies and the first row is taken.
    expect_set(page, 1, ["S1"])


def test_multi_select_writes_the_checked_rows(page, api) -> None:
    mod = build(api, "Table multi", {
        "multiSelect": True, "selectedVariable": "v_selected",
    })
    open_module(page, mod)
    settled(page)
    # p.224: the Selected objects variable is empty until something is checked.
    expect_set(page, 2, [])

    table(page, 0).get_by_label("Select S1").check()
    table(page, 0).get_by_label("Select S3").check()
    expect_set(page, 2, ["S1", "S3"])


def test_unchecking_everything_selects_nothing_rather_than_everything(page, api) -> None:
    """**The inverse of the auto-selection test, and the same rule.** Going back
    to nothing checked must not quietly hand every downstream widget the whole
    table — which is what an empty clause list would do."""
    mod = build(api, "Table uncheck", {
        "multiSelect": True, "selectedVariable": "v_selected",
    })
    open_module(page, mod)
    settled(page)

    table(page, 0).get_by_label("Select S2").check()
    expect_set(page, 2, ["S2"])
    table(page, 0).get_by_label("Select S2").uncheck()
    expect_set(page, 2, [])


def test_select_all_covers_the_page_it_is_showing(page, api) -> None:
    mod = build(api, "Table select all", {
        "multiSelect": True, "selectedVariable": "v_selected",
    })
    open_module(page, mod)
    settled(page)

    table(page, 0).get_by_test_id("table-select-all").check()
    expect_set(page, 2, [r["id"] for r in ROWS])
    table(page, 0).get_by_test_id("table-select-all").uncheck()
    expect_set(page, 2, [])


def test_checking_a_box_does_not_change_the_active_object(page, api) -> None:
    """Two outputs, two gestures. Without a `stopPropagation` on the checkbox
    one click would do both — and would fire the row's events as a side effect
    of ticking a box, which is p.224's "On active object selection" going off
    for something that is not one."""
    mod = build(api, "Table check vs click", {
        "multiSelect": True, "selectedVariable": "v_selected",
    })
    open_module(page, mod)
    settled(page)
    expect_set(page, 1, ["S1"])

    # **The check is the clock for the claim below.** Waiting for the selected
    # set to land proves a write to the *active* variable would have landed
    # too, so "unchanged" is a fact rather than a race (§202, §203) — and the
    # two variables are independent, so the clock cannot erase its evidence.
    table(page, 0).get_by_label("Select S3").check()
    expect_set(page, 2, ["S3"])
    # The active object is still the first row, not the one that was ticked.
    expect_set(page, 1, ["S1"])


def test_the_active_row_is_announced_and_not_only_coloured(page, api) -> None:
    """A highlight nobody can hear is not a selection."""
    mod = build(api, "Table active aria")
    open_module(page, mod)
    settled(page)

    expect(table(page, 0).locator('tbody tr[aria-current="true"]')).to_have_count(1)
    expect(table(page, 0).locator('tbody tr[aria-current="true"]')).to_contain_text("Alpha")


def test_the_selected_objects_setting_appears_only_with_multi_select(page, api) -> None:
    """p.224: "this output variable will only be in use and populated if the
    Enable multi-select toggle is set to true" — so a control for it before
    then is a control that does nothing."""
    mod = build(api, "Table selection settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-active-variable")).to_be_visible()
    expect(page.get_by_test_id("table-selected-variable")).to_have_count(0)

    page.get_by_test_id("table-multi-select").check()
    expect(page.get_by_test_id("table-selected-variable")).to_be_visible()


def test_the_output_pickers_offer_the_clause_variables(page, api) -> None:
    """`array`, not `object_set`. p.224 calls these outputs object sets and they
    end up as ones — but what the widget *writes* is the clause list the
    `narrow_set` derivation reads, so the variable to bind is the array in the
    middle. Offering the derived set would invite binding it and overwriting the
    thing that derives it."""
    mod = build(api, "Table output kinds")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    picker = page.get_by_test_id("table-active-variable")
    labels = [picker.locator("option").nth(i).inner_text()
              for i in range(picker.locator("option").count())]
    assert "Active clauses" in labels, labels
    assert "Active object" not in labels, labels
    assert "All sites" not in labels, labels


def test_the_variable_a_table_writes_counts_as_a_usage(page, api) -> None:
    """§191's drift guard from the other side: `activeVariable` is a **write**,
    and a widget that produces a variable is as much a usage as one that reads
    it. Without the entry the panel would offer to delete a variable the table
    goes on writing to."""
    mod = build(api, "Table output usage")
    open_builder(page, mod)
    settled(page)

    page.get_by_role("button", name="Variables", exact=False).first.click()
    row = page.locator(".vars-row", has_text="Active clauses").first
    expect(row.locator(".vars-usage")).not_to_have_text("unused")
