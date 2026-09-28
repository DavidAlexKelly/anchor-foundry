"""p.321-322's annotations on the Markdown widget (§637).

> "Annotation objects capture selected text using zero-indexed numeric
> indices, with an inclusive start index and an exclusive end index … Display
> existing annotations … Selected annotation: Object set containing the
> currently selected annotation object. On select event … Properties to
> display in tooltip" (p.321-322)

How annotations split the text and which objects are readable is
`markdown-annotations.test.ts`. What needs a browser is that a layer's
objects are drawn over the words their indices name, that one is selected
into its output and fires its event, and that an unusable one is said.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_module

TEXT = "Newark airport has rarely seen flight issues in May"
NOTES = [
    {"id": "N1", "start": 0, "end": 6, "author": "Ada"},
    {"id": "N2", "start": 19, "end": 25, "author": "Grace"},
    # An end before its start is no range.
    {"id": "N3", "start": 9, "end": 2, "author": "Nobody"},
]


def build(api, name: str, **props) -> Module:
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "start", "end", "author"], rows=NOTES, key="id",
                              title="author", types={"start": "integer", "end": "integer"})
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": TEXT, "tagType": "annotation",
                "annotationLayers": [{"name": "Notes", "objectSetVariable": "v_notes",
                                      "startProperty": "start", "endProperty": "end",
                                      "color": "#16a34a"}],
                "selectedAnnotationVariable": "v_picked", "annotationTooltip": "author",
                **props}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_shown", "columns": "author", "autoSelect": False}},
            "out": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "LAST={{v_last}}"}},
        }),
        "variables": {
            "v_notes": {"id": "v_notes", "kind": "object_set", "label": "Notes",
                        "object_set": object_set(type_id)},
            "v_picked": {"id": "v_picked", "kind": "array", "label": "Picked"},
            "v_shown": {"id": "v_shown", "kind": "object_set", "label": "Shown",
                        "derivation": {"transform": "narrow_set",
                                       "inputs": ["v_notes", "v_picked"]}},
            "v_last": {"id": "v_last", "kind": "string", "label": "Last", "default": "none"},
        },
        "events": {"e_pick": {"id": "e_pick", "trigger": {"node": "md", "on": "row_select"},
                              "effects": [{"type": "set_variable", "config": {
                                  "variable": "v_last", "value": "{{primary_key}}"}}]}},
    })
    return mod


def test_annotations_are_drawn_selected_and_said(page, api) -> None:
    open_module(page, build(api, "Markdown annotations"))
    marks = page.get_by_test_id("markdown-annotation")
    expect(marks).to_have_text(["Newark", "rarely"], timeout=20000)
    expect(marks.first).to_have_attribute("title", "author: Ada")
    expect(marks.first).to_have_class("canvas-markdown-annotation fmt-highlight")
    expect(page.get_by_test_id("markdown-annotations-unreadable")).to_have_text(
        "1 annotation with no usable start and end")

    marks.nth(1).click()
    expect(page.get_by_text("LAST=N2")).to_be_visible()
    expect(marks.nth(1)).to_have_attribute("aria-pressed", "true")
    expect(marks.first).to_have_attribute("aria-pressed", "false")
    expect(page.locator("table tbody tr")).to_have_count(1)
    expect(page.locator("table tbody")).to_contain_text("Grace")


def test_the_formatting_is_the_builder_s(page, api) -> None:
    open_module(page, build(api, "Markdown annotations dashed", annotationFormat="dashed"))
    expect(page.get_by_test_id("markdown-annotation").first).to_have_class(
        "canvas-markdown-annotation fmt-dashed", timeout=20000)
