"""p.224-225's Object Table Display & formatting block (parity `workshop.md` §10).

> "**Number of lines to display per row**: This number controls the height of
> each table row. **Enable value wrapping**: When enabled, allows text content
> to wrap within cells… **Number of frozen columns**: This number determines the
> number of frozen columns that are anchored to the left of the table and will
> remain visible when a user scrolls to the right." (p.224)

The arithmetic and the defaults are in
`apps/web/src/components/canvas/object-table-display.test.ts`, mutation-tested
without a browser.

**Every one of these settings is a claim about layout**, and layout is the one
thing a pure function cannot check: a class that no rule matches, a `min-height`
the spec says a table cell ignores, a sticky column with no offset — each of
those passes every unit test there is and is visibly wrong on screen. So the
assertions here are on *computed* styles and measured positions rather than on
the props that were set.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set

from conftest import open_builder, open_module, settled

LONG = ("Alpha " * 40).strip()

ROWS = [
    {"id": "S1", "region": "north", "name": LONG, "note": ""},
    {"id": "S2", "region": "south", "name": "Bravo", "note": "ok"},
]


def build(api, name: str, props: dict | None = None):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name", "note"], rows=ROWS, key="id", title="id"
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_all", "columns": "region,name,note",
                    "pageSize": 25, "activeVariable": None, "autoSelect": False,
                    **(props or {}),
                },
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def build_empty(api, name: str, props: dict | None = None):
    """A table whose set is empty, for p.224's Empty state message."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name", "note"], rows=ROWS, key="id", title="id"
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_none", "columns": "region,name",
                          "pageSize": 25, "activeVariable": None, "autoSelect": False,
                          **(props or {})},
            },
        }),
        "variables": {
            "v_none": {
                "id": "v_none", "kind": "object_set", "label": "None",
                "object_set": object_set(
                    type_id, [{"property": "region", "op": "eq", "value": "nowhere"}]
                ),
            },
        },
        "events": {},
    })
    return mod


def grid(page):
    return page.locator(".canvas-block:has(> .data-grid) .data-grid")


def cells(page):
    """The first row's cells: **Key, region, name, note.**

    The key column is always drawn first, so the configured `columns` start at
    index 1 — the kind of off-by-one that reads as a broken feature.
    """
    return grid(page).locator("tbody tr").first.locator("td")


NAME = 2   # the long value
NOTE = 3   # the empty one


def test_a_row_is_one_line_tall_by_default(page, api) -> None:
    mod = build(api, "Table lines default")
    open_module(page, mod)
    settled(page)

    expect(cells(page).first).to_be_visible()
    height = cells(page).first.evaluate("e => e.getBoundingClientRect().height")
    assert 18 <= height <= 34, height


def test_more_lines_make_a_taller_row(page, api) -> None:
    """p.224: the number "controls the height of each table row".

    **Asserted as a measurement, not as a prop.** `min-height` is ignored on a
    table cell per spec, so the obvious implementation sets a property that does
    nothing — and every unit test still passes, because the arithmetic was
    right and the CSS was not.
    """
    one = build(api, "Table lines one", {"lines": 1})
    open_module(page, one)
    settled(page)
    expect(cells(page).first).to_be_visible()
    short = cells(page).first.evaluate("e => e.getBoundingClientRect().height")

    many = build(api, "Table lines four", {"lines": 4})
    open_module(page, many)
    settled(page)
    expect(cells(page).first).to_be_visible()
    tall = cells(page).first.evaluate("e => e.getBoundingClientRect().height")

    assert tall > short + 30, f"one line {short}, four lines {tall}"


def test_value_wrapping_lets_a_long_value_break(page, api) -> None:
    """p.224's "Enable value wrapping". The name column holds a long run of
    words; off it stays on one line, on it fills the lines it is given."""
    off = build(api, "Table wrap off", {"lines": 4, "valueWrap": False})
    open_module(page, off)
    settled(page)
    expect(cells(page).nth(NAME)).to_be_visible()
    assert off_wrap(page) == "nowrap"

    on = build(api, "Table wrap on", {"lines": 4, "valueWrap": True})
    open_module(page, on)
    settled(page)
    expect(cells(page).nth(NAME)).to_be_visible()
    assert off_wrap(page) == "normal"


def off_wrap(page) -> str:
    return cells(page).nth(NAME).locator("div").first.evaluate(
        "e => getComputedStyle(e).whiteSpace"
    )


def test_a_wrapped_value_is_clamped_to_the_line_count(page, api) -> None:
    """Wrapping without a clamp is a row as tall as its longest value, which is
    a table that jumps every time a filter changes."""
    mod = build(api, "Table wrap clamp", {"lines": 2, "valueWrap": True})
    open_module(page, mod)
    settled(page)

    inner = cells(page).nth(NAME).locator("div").first
    expect(inner).to_be_visible()
    assert inner.evaluate("e => getComputedStyle(e).webkitLineClamp") == "2"


def test_a_frozen_column_stays_put_when_the_grid_scrolls(page, api) -> None:
    """p.224: frozen columns "will remain visible when a user scrolls to the
    right".

    **The measurement is the point.** A sticky column with no `left` offset
    scrolls away like any other, and every unit test of the offsets still
    passes — the arithmetic was never the part at risk.
    """
    mod = build(api, "Table frozen", {"frozenColumns": 2, "fitColumns": False})
    open_module(page, mod)
    settled(page)

    first = cells(page).first
    expect(first).to_be_visible()
    before = first.evaluate("e => e.getBoundingClientRect().left")
    grid(page).evaluate("e => { e.scrollLeft = e.scrollWidth; }")
    page.wait_for_timeout(150)
    after = first.evaluate("e => e.getBoundingClientRect().left")
    assert abs(after - before) < 2, f"moved from {before} to {after}"


def test_an_unfrozen_column_does_scroll_away(page, api) -> None:
    """The control for the test above: without it, a grid that cannot scroll at
    all would satisfy "the column did not move"."""
    mod = build(api, "Table unfrozen", {"frozenColumns": 0, "fitColumns": False})
    open_module(page, mod)
    settled(page)

    first = cells(page).first
    expect(first).to_be_visible()
    before = first.evaluate("e => e.getBoundingClientRect().left")
    grid(page).evaluate("e => { e.scrollLeft = e.scrollWidth; }")
    page.wait_for_timeout(150)
    after = first.evaluate("e => e.getBoundingClientRect().left")
    assert after < before - 10, f"did not scroll: {before} to {after}"


def test_an_empty_cell_says_p224s_words(page, api) -> None:
    """p.224: "By default, 'No value' will be displayed." A divergence resolved
    in Foundry's favour, and scoped to this widget — `∅` stays everywhere
    else."""
    mod = build(api, "Table no value")
    open_module(page, mod)
    settled(page)

    expect(cells(page).nth(NOTE)).to_have_text("No value")


def test_a_custom_no_value_display_overrides_it(page, api) -> None:
    mod = build(api, "Table custom no value", {
        "customNoValue": True, "noValueText": "—",
    })
    open_module(page, mod)
    settled(page)

    expect(cells(page).nth(NOTE)).to_have_text("—")


def test_an_empty_no_value_display_shows_nothing(page, api) -> None:
    """An empty string is a real answer, not a missing one."""
    mod = build(api, "Table blank no value", {
        "customNoValue": True, "noValueText": "",
    })
    open_module(page, mod)
    settled(page)

    expect(cells(page).nth(NOTE)).to_have_text("")


def test_an_empty_table_says_so_in_p224s_words(page, api) -> None:
    mod = build_empty(api, "Table empty default")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("table-empty-state")).to_have_text("No objects found")


def test_a_custom_empty_message_replaces_it(page, api) -> None:
    mod = build_empty(api, "Table empty custom", {
        "emptyMode": "custom", "emptyMessage": "Nothing to review today",
    })
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("table-empty-state")).to_have_text("Nothing to review today")


def test_narrow_headers_are_shorter(page, api) -> None:
    """p.225's toggle, asserted as the *relation* it describes rather than as
    its pixel values — ours were never 50 to begin with."""
    wide = build(api, "Table headers wide", {"narrowHeaders": False})
    open_module(page, wide)
    settled(page)
    expect(grid(page).locator("th").first).to_be_visible()
    tall = grid(page).locator("th").first.evaluate("e => e.getBoundingClientRect().height")

    narrow = build(api, "Table headers narrow", {"narrowHeaders": True})
    open_module(page, narrow)
    settled(page)
    expect(grid(page).locator("th").first).to_be_visible()
    short = grid(page).locator("th").first.evaluate("e => e.getBoundingClientRect().height")

    assert short < tall, f"narrow {short} is not shorter than wide {tall}"


def build_short(api, name: str, props: dict | None = None):
    """A table of short values, so the two column widths can differ.

    **The long-value fixture cannot show this setting at all**: `width: 100%` on
    a table is a floor, not a cap, so content wider than the container overflows
    under either setting and the two measure the same. The difference only
    exists when the natural width is *narrower* than the space available.
    """
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region"], rows=[{"id": "S1", "region": "north"}],
        key="id", title="id",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "region",
                              "pageSize": 25, "activeVariable": None,
                              "autoSelect": False, **(props or {})}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def test_fitting_columns_fills_the_width(page, api) -> None:
    """p.225: "columns will auto-resize to fill the current width of the
    table"."""
    fit = build_short(api, "Table fit", {"fitColumns": True})
    open_module(page, fit)
    settled(page)
    expect(grid(page).locator("table")).to_be_visible()
    filled = grid(page).evaluate(
        "e => e.querySelector('table').getBoundingClientRect().width"
        " / e.getBoundingClientRect().width"
    )
    assert filled > 0.95, filled

    loose = build_short(api, "Table no fit", {"fitColumns": False})
    open_module(page, loose)
    settled(page)
    expect(grid(page).locator("table")).to_be_visible()
    natural = grid(page).evaluate(
        "e => e.querySelector('table').getBoundingClientRect().width"
        " / e.getBoundingClientRect().width"
    )
    assert natural < 0.9, f"natural width {natural} did not shrink (fit was {filled})"


def test_the_custom_fields_appear_only_with_their_toggles(page, api) -> None:
    """A control that does nothing under the current setting is a control that
    lies about it — the rule §203, §204 and §207 each landed on."""
    mod = build(api, "Table display settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-empty-message")).to_have_count(0)
    expect(page.get_by_test_id("table-no-value-text")).to_have_count(0)

    page.get_by_test_id("table-empty-mode").select_option("custom")
    expect(page.get_by_test_id("table-empty-message")).to_be_visible()

    page.get_by_test_id("table-custom-no-value").check()
    expect(page.get_by_test_id("table-no-value-text")).to_be_visible()
