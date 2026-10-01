"""p.319-320's inline references on the Markdown widget (§632).

> "The format for creating one of these anchors is as follows:
> :objectreference[$text_to_display]{objectType="$object_type_id"
> primaryKey="$obj…"} … each of the Flight Alert objects reference below is
> individually selectable by a user and will then become the output selected
> object set of the Markdown widget." (p.319)

The syntax, the configured types and the three selection behaviours are
`markdown-references.test.ts`. What needs a browser is that an anchor is a
control, that selecting one narrows what reads the output, that its event
runs with the object it names, and that a type nobody configured stays text.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

ROWS = [{"id": "S1", "name": "Endeavour"}, {"id": "S2", "name": "Resolution"},
        {"id": "S3", "name": "Discovery"}]


def build(api, name: str, *, behavior: str = "last") -> Module:
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    api_name = f"seed_{mod.tag}"
    ref = lambda text, key: (  # noqa: E731 - the syntax, spelled once
        f':objectreference[{text}]{{objectType="{api_name}" primaryKey="{key}"}}')
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": (f"Ships: {ref('First', 'S1')}, **{ref('Second', 'S2')}** and "
                         f"{ref('Again', 'S1')}; "
                         ':objectreference[Ghost]{objectType="nope" primaryKey="X"}.'),
                "tagType": "inline_reference", "selectedVariable": "v_picked",
                "referenceTypes": [{"objectType": api_name, "color": "#dc2626"}],
                "selectionBehavior": behavior,
            }},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_shown", "columns": "name", "autoSelect": False}},
            "note": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "NOTE={{v_note}}"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Ships",
                      "object_set": object_set(type_id)},
            "v_picked": {"id": "v_picked", "kind": "array", "label": "Picked"},
            "v_shown": {"id": "v_shown", "kind": "object_set", "label": "Shown",
                        "derivation": {"transform": "narrow_set",
                                       "inputs": ["v_all", "v_picked"]}},
            "v_note": {"id": "v_note", "kind": "string", "label": "Note", "default": "none"},
        },
        "events": {"e_pick": {"id": "e_pick",
                              "trigger": {"node": "md", "on": "row_select"},
                              "effects": [{"type": "set_variable", "config": {
                                  "variable": "v_note", "value": "{{primary_key}}"}}]}},
    })
    return mod


def anchor(page, text: str):
    return page.get_by_test_id("markdown-ref").filter(has_text=text)


def names(page) -> list[str]:
    return sorted(page.locator("table tbody tr td").all_text_contents())


def test_an_anchor_selects_its_object_and_runs_the_event(page, api) -> None:
    mod = build(api, "Markdown references")
    open_module(page, mod)
    expect(page.get_by_test_id("markdown-ref")).to_have_count(3, timeout=20000)
    # A type nobody configured is its words, not an anchor (p.320).
    expect(page.get_by_test_id("markdown")).to_contain_text("Ghost.")
    expect(anchor(page, "Ghost")).to_have_count(0)
    # Formatting inside the text is kept.
    expect(page.locator("strong [data-testid='markdown-ref']")).to_have_text("Second")

    anchor(page, "Second").click()
    expect(page.get_by_text("NOTE=S2")).to_be_visible()
    expect(page.locator("table tbody tr")).to_have_count(1)
    shown = names(page)
    assert "Resolution" in shown and "Endeavour" not in shown, shown
    expect(anchor(page, "Second")).to_have_attribute("aria-pressed", "true")
    expect(anchor(page, "First")).to_have_attribute("aria-pressed", "false")

    # "Highlight last selected": the anchor clicked, not every one naming it.
    anchor(page, "Again").click()
    expect(page.get_by_text("NOTE=S1")).to_be_visible()
    expect(anchor(page, "Again")).to_have_attribute("aria-pressed", "true")
    expect(anchor(page, "First")).to_have_attribute("aria-pressed", "false")
    expect(anchor(page, "Second")).to_have_attribute("aria-pressed", "false")


def test_highlight_selected_reference_follows_the_set(page, api) -> None:
    mod = build(api, "Markdown references selected", behavior="selected")
    open_module(page, mod)
    anchor(page, "Again").click()
    # Both anchors naming S1, however it was chosen.
    expect(anchor(page, "First")).to_have_attribute("aria-pressed", "true")
    expect(anchor(page, "Again")).to_have_attribute("aria-pressed", "true")
    expect(anchor(page, "Second")).to_have_attribute("aria-pressed", "false")


def test_standard_markdown_shows_the_syntax_as_text(page, api) -> None:
    mod = build(api, "Markdown references off")
    mod.define({**mod.definition(), "layout": {
        **mod.definition()["layout"],
        "md": {**mod.definition()["layout"]["md"], "props": {
            **mod.definition()["layout"]["md"]["props"], "tagType": "standard"}}}})
    open_module(page, mod)
    expect(page.get_by_test_id("markdown")).to_contain_text(":objectreference[First]")
    expect(page.get_by_test_id("markdown-ref")).to_have_count(0)


def test_the_panel_turns_references_on(page, api) -> None:
    mod = build(api, "Markdown references panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Markdown").first.click()
    expect(page.get_by_test_id("markdown-tag-type")).to_have_value("inline_reference")
    expect(page.get_by_test_id("markdown-ref-selected")).to_have_value("v_picked")
    expect(page.get_by_test_id("markdown-ref-type-name")).to_have_value(f"seed_{mod.tag}")
    page.get_by_test_id("markdown-ref-new-type").fill("port")
    page.get_by_test_id("markdown-ref-new-type").press("Enter")
    page.get_by_test_id("markdown-ref-behavior").select_option("none")
    page.get_by_role("button", name="Save", exact=True).click()
    settled(page)
    eventually(lambda: mod.definition()["layout"]["md"]["props"],
               lambda p: p.get("selectionBehavior") == "none"
               and [t["objectType"] for t in p["referenceTypes"]] == [f"seed_{mod.tag}", "port"],
               what="the new type and behaviour, saved")
    # Its event is offered as the widget's own.
    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="New event").click()
    # The open event's trigger picker, as `test_object_table_row_menu` reads it.
    expect(page.locator(".canvas-event.on select").nth(1).locator("option")).to_have_text(
        ["Reference selected"])
