"""p.322's annotation Highlight color by rules and On hover interactions on
the Markdown widget (§669).

> "On hover interactions: Configure on-hover interactions such as actions and
> events, which will be displayed in the on-hover tooltip of an annotation
> object. … Hovered object: A special action parameter value that can be used
> to reference the hovered annotation object." (p.322)
>
> "Highlight color: Set the color used to display the annotation. A custom
> color may be statically defined or conditional formatting rules may be
> set." (p.322)

How a layer's rules paint an annotation, and that hover interactions are
`hover_N` click items, is `markdown-annotations.test.ts`; that the server
takes them as clicks is `test_workshop_variables.py`. What needs a browser is
the colours on the words, and the hover card offering each interaction and
running it with the hovered annotation.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

TEXT = "Newark airport has rarely seen flight issues in May"
NOTES = [
    {"id": "N1", "start": 0, "end": 6, "author": "Ada", "severity": "high"},
    {"id": "N2", "start": 19, "end": 25, "author": "Grace", "severity": "low"},
]
STATIC = "#999999"
RULES = [{"kind": "standard", "property": "severity", "comparison": "string", "operator": "is_exactly",
          "value": "high", "background": "#dc2626"}]


def build(api, name: str, layer: dict | None = None, **props) -> Module:
    mod = Module(api, name)
    type_id = mod.object_type(columns=["id", "start", "end", "author", "severity"], rows=NOTES,
                              key="id", title="author", types={"start": "integer", "end": "integer"})
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": TEXT, "tagType": "annotation",
                "annotationLayers": [{"name": "Notes", "objectSetVariable": "v_notes",
                                      "startProperty": "start", "endProperty": "end",
                                      "color": STATIC, **(layer or {})}],
                "annotationTooltip": "author", **props}},
            "out": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "LAST={{v_last}}"}},
        }),
        "variables": {
            "v_notes": {"id": "v_notes", "kind": "object_set", "label": "Notes",
                        "object_set": object_set(type_id)},
            "v_last": {"id": "v_last", "kind": "string", "label": "Last", "default": "none"},
        },
        "events": {"e_resolve": {"id": "e_resolve",
                                 "trigger": {"node": "md", "on": "click", "item": "hover_1"},
                                 "effects": [{"type": "set_variable", "config": {
                                     "variable": "v_last", "value": "{{primary_key}} in {{layer}}"}}]}}
        if props.get("hoverActions") else {},
    })
    return mod


def test_a_layer_s_rules_colour_each_annotation(page, api) -> None:
    open_module(page, build(api, "Annotation colours", {"colorMode": "rules", "colorRules": RULES}))
    marks = page.get_by_test_id("markdown-annotation")
    expect(marks).to_have_text(["Newark", "rarely"], timeout=20000)
    expect(marks.first).to_have_attribute("data-color", "#dc2626")
    expect(marks.first).to_have_css("--annotation-color", "#dc2626")
    # No rule matches a low one: the static colour.
    expect(marks.nth(1)).to_have_attribute("data-color", STATIC)


def test_a_static_layer_keeps_its_colour_whatever_its_rules(page, api) -> None:
    open_module(page, build(api, "Annotation colours static", {"colorRules": RULES}))
    marks = page.get_by_test_id("markdown-annotation")
    expect(marks).to_have_text(["Newark", "rarely"], timeout=20000)
    expect(marks.first).to_have_attribute("data-color", STATIC)


def test_a_hover_interaction_runs_on_the_hovered_annotation(page, api) -> None:
    open_module(page, build(api, "Annotation hover", hoverActions=[{"id": "hover_1", "label": "Resolve"}]))
    marks = page.get_by_test_id("markdown-annotation")
    expect(marks).to_have_text(["Newark", "rarely"], timeout=20000)
    card = page.get_by_test_id("markdown-annotation-hover")
    expect(card).to_have_count(0)
    # The card is the tooltip now, so the words carry no title of their own.
    expect(marks.first).not_to_have_attribute("title", "author: Ada")
    marks.nth(1).hover()
    expect(card).to_contain_text("author: Grace")
    card.get_by_role("button", name="Resolve").click()
    expect(page.get_by_text("LAST=N2 in Notes")).to_be_visible()
    marks.first.hover()
    expect(card).to_contain_text("author: Ada")
    card.get_by_role("button", name="Resolve").click()
    expect(page.get_by_text("LAST=N1 in Notes")).to_be_visible()
    # Leaving the widget puts the card away.
    page.get_by_text("LAST=N1 in Notes").hover()
    expect(card).to_have_count(0)


def test_no_hover_card_without_interactions(page, api) -> None:
    open_module(page, build(api, "Annotation no hover"))
    marks = page.get_by_test_id("markdown-annotation")
    expect(marks.first).to_have_attribute("title", "author: Ada", timeout=20000)
    marks.first.hover()
    expect(page.get_by_test_id("markdown-annotation-hover")).to_have_count(0)


def test_the_panel_sets_the_colour_rules_and_interactions(page, api) -> None:
    mod = build(api, "Annotation hover panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Markdown").first.click()
    page.get_by_label("Layer 1 colour from").select_option("rules")
    expect(page.get_by_test_id("markdown-annotation-rules")).to_be_enabled()
    page.get_by_test_id("markdown-hover-add").click()
    page.get_by_label("Hover interaction 1 title").fill("Resolve")
    page.get_by_role("button", name="Save", exact=True).click()
    settled(page)
    eventually(lambda: mod.definition()["layout"]["md"]["props"],
               lambda p: (p["annotationLayers"][0].get("colorMode"), p.get("hoverActions"))
               == ("rules", [{"id": "hover_1", "label": "Resolve"}]),
               what="the colour's source and the interaction, saved")
    # The Events panel offers the interaction as one of the widget's clicks.
    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    expect(page.get_by_test_id("event-item").locator("option", has_text="On hover: Resolve")).to_have_count(1)
