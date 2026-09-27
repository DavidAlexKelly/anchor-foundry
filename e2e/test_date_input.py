"""p.444's Date Input, a single date or a range (§513).

> "Date Input: Allow the user to enter a single data or date range." (p.444)

Days, order and the wording are `apps/web/src/components/canvas/date-input.test.ts`'s.
What needs a browser is that the controls reach the variables, that a range
picked backwards is **stored** in order (the mirror shows the variables, not
the inputs), and that the builder asks for the end only when there is one.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str, props: dict):
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "di": {"resolvedName": "CanvasDateInput",
                   "props": {"name": "v_from", "endVariable": "", "label": "When",
                             "mode": "single", **props}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "from: [{{v_from}}] to: [{{v_to}}]"}},
        }),
        "variables": {
            "v_from": {"id": "v_from", "kind": "date", "label": "From"},
            "v_to": {"id": "v_to", "kind": "date", "label": "To"},
            "v_note": {"id": "v_note", "kind": "string", "label": "Note"},
        },
        "events": {},
    })
    return mod


def echo(page):
    return page.locator(".canvas-block", has_text="from:").first


def test_a_single_date_writes_its_variable(page, api) -> None:
    mod = module_with(api, "Date single", {})
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("date-input").fill("2026-03-01")
    expect(echo(page)).to_contain_text("from: [2026-03-01] to: []")
    page.get_by_test_id("date-input").fill("")
    expect(echo(page)).to_contain_text("from: [] to: []")


def test_a_range_writes_both_ends_in_order(page, api) -> None:
    mod = module_with(api, "Date range", {"mode": "range", "endVariable": "v_to"})
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("date-range-start").fill("2026-03-10")
    expect(echo(page)).to_contain_text("from: [2026-03-10] to: []")
    expect(page.get_by_test_id("date-range-text")).to_have_text("From 2026-03-10, no end")
    # An end before the start: stored in order, not backwards.
    page.get_by_test_id("date-range-end").fill("2026-03-01")
    expect(echo(page)).to_contain_text("from: [2026-03-01] to: [2026-03-10]")
    expect(page.get_by_test_id("date-range-text")).to_have_text("10 days, 2026-03-01 to 2026-03-10")
    expect(page.get_by_test_id("date-range-start")).to_have_value("2026-03-01")
    expect(page.get_by_test_id("date-range-end")).to_have_value("2026-03-10")


def test_the_builder_asks_for_an_end_only_for_a_range(page, api) -> None:
    mod = module_with(api, "Date settings", {})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Date input").first.click()
    picker = page.get_by_test_id("date-input-variable")
    labels = [picker.locator("option").nth(i).inner_text()
              for i in range(picker.locator("option").count())]
    assert "From" in labels and "To" in labels and "Note" not in labels, labels
    expect(page.get_by_test_id("date-input-end-variable")).to_have_count(0)
    page.get_by_test_id("date-input-mode").select_option("range")
    expect(page.get_by_test_id("date-input-end-variable")).to_be_visible()
    # Unbound, the canvas says what is missing.
    expect(page.get_by_text("Date range - bind a start and an end date variable in Settings")).to_be_visible()
