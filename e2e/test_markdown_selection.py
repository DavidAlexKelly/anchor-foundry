"""p.317's User text selection on the Markdown widget (§636).

> "Output user selected raw text: Outputs the user selected text as a raw
> Markdown string. … Output user selected indices: Outputs the starting and
> ending indices of the user selected text as numeric variables." (p.317)

That every rendered run knows where it came from is
`markdown-selection.test.ts`, over every block kind. What needs a browser is
a real selection read back through the DOM: one across formatting, which
yields the raw Markdown between its ends, and one made by double-clicking a
word, as a reader would.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module

TEXT = "I *think* this **sentence** is ~pretty good~"


def build(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": TEXT, "selectedTextVariable": "v_text",
                "selectionStartVariable": "v_start", "selectionEndVariable": "v_end"}},
            "out": {"resolvedName": "CanvasText", "props": {
                "tag": "p", "text": "SEL=[{{v_text}}] {{v_start}}-{{v_end}}"}},
        }),
        "variables": {
            "v_text": {"id": "v_text", "kind": "string", "label": "Selected"},
            "v_start": {"id": "v_start", "kind": "number", "label": "Start"},
            "v_end": {"id": "v_end", "kind": "number", "label": "End"},
        },
        "events": {},
    })
    return mod


SELECT = """([from, to, end]) => {
  const runs = [...document.querySelectorAll("[data-testid=markdown] [data-at]")];
  const a = runs.find((r) => r.textContent === from);
  const b = runs.find((r) => r.textContent === to);
  const range = document.createRange();
  range.setStart(a.firstChild, 0);
  range.setEnd(b.firstChild, end);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
  document.querySelector("[data-testid=markdown]")
    .dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
}"""


def test_a_selection_across_formatting_is_its_raw_markdown(page, api) -> None:
    open_module(page, build(api, "Markdown selection"))
    expect(page.get_by_test_id("markdown")).to_contain_text("sentence", timeout=20000)
    page.evaluate(SELECT, ["think", "sentence", 8])
    expect(page.get_by_text("SEL=[think* this **sentence] 3-25")).to_be_visible()


def test_a_double_clicked_word_is_selected(page, api) -> None:
    open_module(page, build(api, "Markdown selection word"))
    word = page.get_by_test_id("markdown").locator("[data-at]", has_text="pretty")
    expect(word).to_be_visible(timeout=20000)
    word.dblclick(position={"x": 4, "y": 6})
    expect(page.get_by_text("SEL=[pretty] 32-38")).to_be_visible()
    # A click that selects nothing empties the outputs.
    page.get_by_test_id("markdown").locator("[data-at]", has_text="is").first.click()
    expect(page.get_by_text("SEL=[] -")).to_be_visible()
