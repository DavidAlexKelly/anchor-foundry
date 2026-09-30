"""p.466's Markdown format for the Text Input (§582).

> "Formatting toolbar: Apply bold, italic, code, and other formatting using
> toolbar controls without needing to know Markdown syntax. Rich text and raw
> Markdown views: Toggle between a rich text view … and a raw Markdown view …
> Auto-sizing: Enable the editor to expand automatically based on content
> length." (p.466)

What the toolbar writes is checked in `markdown-editor.test.ts`; here, that
it is written into the variable the widget is bound to, and that the preview
draws it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, settled


def build(api, name: str, **props) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_note", "label": "Note", "placeholder": "Write here",
                              "format": "markdown", "rows": 4, **props}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "stored: [{{v_note}}]"}},
        }),
        "variables": {"v_note": {"id": "v_note", "kind": "string", "label": "Note"}},
        "events": {},
    })
    return mod


def area(page):
    return page.get_by_test_id("text-input")


def select(page, start: int, end: int) -> None:
    area(page).evaluate(f"(el) => {{ el.focus(); el.setSelectionRange({start}, {end}); }}")


def stored(page):
    return page.locator(".canvas-block", has_text="stored:").last


def test_the_toolbar_writes_markdown_into_the_variable(page, api) -> None:
    open_module(page, build(api, "Markdown toolbar"))
    area(page).fill("hello world")
    select(page, 6, 11)
    page.get_by_test_id("md-bold").click()
    expect(area(page)).to_have_value("hello **world**")
    expect(stored(page)).to_contain_text("stored: [hello **world**]")
    # Pressed again over the same selection, the bold comes off.
    page.get_by_test_id("md-bold").click()
    expect(area(page)).to_have_value("hello world")
    select(page, 0, 11)
    page.get_by_test_id("md-bullets").click()
    expect(area(page)).to_have_value("- hello world")


def test_the_preview_draws_what_was_written(page, api) -> None:
    open_module(page, build(api, "Markdown preview"))
    area(page).fill("plain and bold")
    select(page, 10, 14)
    page.get_by_test_id("md-bold").click()
    page.get_by_test_id("md-view").click()
    rich = page.get_by_test_id("md-rich")
    expect(rich.locator("strong")).to_have_text("bold")
    expect(area(page)).to_have_count(0)
    # The toolbar formats the Markdown, so it waits for the Markdown view.
    expect(page.get_by_test_id("md-bold")).to_be_disabled()
    page.get_by_test_id("md-view").click()
    expect(area(page)).to_have_value("plain and **bold**")


def test_an_empty_preview_says_so(page, api) -> None:
    open_module(page, build(api, "Markdown empty"))
    page.get_by_test_id("md-view").click()
    expect(page.get_by_test_id("md-rich")).to_contain_text("Write here")


def test_the_editor_grows_with_what_is_written(page, api) -> None:
    open_module(page, build(api, "Markdown grows"))
    expect(area(page)).to_have_attribute("rows", "3")
    area(page).fill("a\nb\nc\nd\ne")
    expect(area(page)).to_have_attribute("rows", "6")


def test_without_auto_sizing_the_editor_keeps_its_height(page, api) -> None:
    open_module(page, build(api, "Markdown fixed", autoSize=False))
    area(page).fill("a\nb\nc\nd\ne\nf\ng\nh\ni\nj")
    expect(area(page)).to_have_attribute("rows", "8")


def test_the_panel_offers_auto_sizing_for_markdown_only(page, api) -> None:
    mod = build(api, "Markdown panel", format="line")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Text input").first.click()
    expect(page.get_by_test_id("text-auto-size")).to_have_count(0)
    page.get_by_test_id("text-format").select_option("markdown")
    page.get_by_test_id("text-auto-size").uncheck()
    save(page)
    props = mod.definition()["layout"]["txt"]["props"]
    assert (props["format"], props["autoSize"]) == ("markdown", False)
