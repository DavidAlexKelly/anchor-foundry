"""p.170's Column math, declared at the module level (parity `workshop.md` §9;
Foundry workshop p.168-172).

> "Derived properties are defined at the module level and per object type."
> (p.168)

> "Column math: Combine values from multiple properties on a single object
> type." (p.170)

The arithmetic, the null rules and p.170's reference restriction are
`column-math.test.ts`, which is where a parser belongs. **What needs a browser
is the seam**: a declaration on the module document becoming a column of
numbers in a table that the ontology has never heard of.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

# `cost` is missing on the third row on purpose: `Number(null)` is 0, so a
# build that coerced would report the whole revenue as margin — a number that
# looks perfectly reasonable and is wrong.
ROWS = [
    {"id": "R1", "revenue": "100", "cost": "40"},
    {"id": "R2", "revenue": "250", "cost": "50"},
    {"id": "R3", "revenue": "70", "cost": ""},
]


def build(api, name: str, *, columns="id,revenue,cost,margin", declared=None):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "revenue", "cost"], rows=ROWS, key="id", title="id",
        types={"revenue": "integer", "cost": "integer"},
    )
    mod.type_id = type_id
    definition = {
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": columns,
                              "pageSize": 25}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All rows",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    }
    if declared is not None:
        definition["derived_properties"] = {type_id: declared}
    mod.define(definition)
    return mod


MARGIN = [{"api_name": "margin", "kind": "column_math",
           "expression": "revenue - cost"}]


def header_texts(page):
    """Lower-cased on the way out.

    The table upper-cases its headers in CSS, so `inner_text()` gives "MARGIN"
    and matching the api name verbatim finds nothing — which is how this first
    failed, on a column that was rendering perfectly. The same mistake §406's
    picker test made against title-cased display names.
    """
    return [h.inner_text().strip().lower() for h in page.locator("thead th").all()]


def cell(page, row_id: str, column: str):
    return (page.locator("tbody tr").filter(has_text=row_id).first
            .locator(f'[data-derived="{column}"]'))


def test_a_declared_column_is_calculated_for_every_row(page, api):
    """p.170's sentence, end to end. The column exists nowhere in the ontology
    — the object type has `revenue` and `cost` and nothing else — so a number
    in this cell can only have come from the module's own declaration."""
    mod = build(api, "Derived column", declared=MARGIN)
    open_module(page, mod)
    eventually(lambda: page.locator("tbody tr").count(), lambda n: n == len(ROWS),
               what="the table's rows")

    assert "margin" in header_texts(page), header_texts(page)
    expect(cell(page, "R1", "margin")).to_have_text("60")
    # **A second row with different inputs**, so the column cannot pass by
    # rendering one number everywhere.
    expect(cell(page, "R2", "margin")).to_have_text("200")


def test_a_missing_input_is_nothing_rather_than_the_other_number(page, api):
    """**The trap this shares with §149 and §226, and it compounds here.**

    R3 has a revenue of 70 and no cost. `Number(null)` is `0`, so a build that
    coerced would put `70` in this cell — the whole revenue reported as margin,
    a figure that looks entirely reasonable and is wrong.
    """
    mod = build(api, "Derived column empty", declared=MARGIN)
    open_module(page, mod)
    eventually(lambda: page.locator("tbody tr").count(), lambda n: n == len(ROWS),
               what="the table's rows")

    got = cell(page, "R3", "margin").inner_text().strip()
    assert got != "70", "a missing cost was read as zero"
    assert got != "0", "a missing cost was read as zero"
    # And the rows that *do* have both are unaffected, so this is emptiness
    # reaching one cell rather than the column failing.
    expect(cell(page, "R1", "margin")).to_have_text("60")


def test_a_column_nobody_asked_for_is_not_added(page, api):
    """A derived property is the module's, not the ontology's. A table left on
    its default of "show every property" is showing everything the *type* has —
    adding columns a builder never named would be the module reaching into a
    widget that never mentioned it."""
    mod = build(api, "Derived column unnamed", columns="", declared=MARGIN)
    open_module(page, mod)
    eventually(lambda: page.locator("tbody tr").count(), lambda n: n == len(ROWS),
               what="the table's rows")
    assert "margin" not in header_texts(page), header_texts(page)
    expect(page.locator('[data-derived="margin"]')).to_have_count(0)


def test_an_expression_that_cannot_be_read_leaves_the_column_blank(page, api):
    """§212: a document can hold an expression this build cannot parse. The
    column is still there — it was named in the column list — and its cells are
    empty rather than the table failing to render."""
    mod = build(api, "Derived column junk", declared=[
        {"api_name": "margin", "kind": "column_math", "expression": "revenue +"},
    ])
    open_module(page, mod)
    eventually(lambda: page.locator("tbody tr").count(), lambda n: n == len(ROWS),
               what="the table's rows")
    assert "margin" in header_texts(page), header_texts(page)
    assert cell(page, "R1", "margin").inner_text().strip() != "60"


def test_the_panel_declares_one_and_the_reader_sees_it(page, api):
    """The chain a browser has to make: p.168's per-type declaration written in
    the Settings panel, saved, and calculated for a reader."""
    mod = build(api, "Derived column panel", declared=None)
    open_builder(page, mod)
    settled(page)

    # p.168: the object type comes first — an expression is checked against
    # one type's properties, so there is nothing to add until one is named.
    picker = page.get_by_test_id("derived-type")
    eventually(lambda: picker.locator("option").count(), lambda n: n >= 2,
               what="the object types this module reads")
    picker.select_option(index=1)

    page.get_by_test_id("derived-add").click()
    page.get_by_test_id("derived-name-1").fill("margin")
    page.get_by_test_id("derived-expression-1").fill("revenue - cost")
    # No complaint, because both names are properties of the chosen type.
    expect(page.get_by_test_id("derived-problem-1")).to_have_count(0)

    save(page)
    open_module(page, mod)
    eventually(lambda: page.locator("tbody tr").count(), lambda n: n == len(ROWS),
               what="the viewer's rows")
    expect(cell(page, "R1", "margin")).to_have_text("60")


def test_the_panel_names_a_property_the_type_does_not_have(page, api):
    """The refusal in the one place the answer can still be changed. The same
    function the table would come up empty on, so a column that shows a
    sentence here never reaches a reader as a blank."""
    mod = build(api, "Derived column problem", declared=None)
    open_builder(page, mod)
    settled(page)

    picker = page.get_by_test_id("derived-type")
    eventually(lambda: picker.locator("option").count(), lambda n: n >= 2,
               what="the object types this module reads")
    picker.select_option(index=1)
    page.get_by_test_id("derived-add").click()
    page.get_by_test_id("derived-expression-1").fill("revenue - profit")
    expect(page.get_by_test_id("derived-problem-1")).to_contain_text(
        "no property called profit"
    )
