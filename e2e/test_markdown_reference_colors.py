"""p.320's Highlight color on the Markdown widget's references (§664).

> "Highlight color: Select a static color, inherit colors from a property with
>  Ontology formatting, or define custom rules to determine color." (p.320)

Three ships of three ranks. The rank property's Ontology rules paint a high
one red and a low one blue; the builder's own rules paint a low one green. A
ship nothing paints keeps the static colour.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, settled

ROWS = [{"id": "S1", "name": "Endeavour", "rank": "high"},
        {"id": "S2", "name": "Resolution", "rank": "low"},
        {"id": "S3", "name": "Discovery", "rank": "none"}]
RANK_RULES = [
    {"comparison": "string", "operator": "is_exactly", "value": "high", "background": "#dc2626"},
    {"comparison": "string", "operator": "is_exactly", "value": "low", "background": "#2563eb"},
]
STATIC = "#999999"


def build(api, name: str, **colour) -> Module:
    mod = Module(api, name)
    mod.object_type(columns=["id", "name", "rank"], rows=ROWS, key="id", title="name",
                    rules={"rank": RANK_RULES})
    api_name = f"seed_{mod.tag}"
    ref = lambda text, key: (  # noqa: E731
        f':objectreference[{text}]{{objectType="{api_name}" primaryKey="{key}"}}')
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": f"Ships: {ref('First', 'S1')}, {ref('Second', 'S2')} and {ref('Third', 'S3')}.",
                "tagType": "inline_reference",
                "referenceTypes": [{"objectType": api_name, "color": STATIC, **colour}],
            }},
        }),
        "variables": {},
        "events": {},
    })
    return mod


def colour_of(page, text: str):
    return page.get_by_test_id("markdown-ref").filter(has_text=text)


def test_a_property_s_ontology_formatting_colours_each_reference(page, api) -> None:
    open_module(page, build(api, "Markdown colours by property", colorMode="property",
                            colorProperty="rank"))
    expect(colour_of(page, "First")).to_have_attribute("data-color", "#dc2626")
    expect(colour_of(page, "Second")).to_have_attribute("data-color", "#2563eb")
    expect(colour_of(page, "Third")).to_have_attribute("data-color", STATIC)
    expect(colour_of(page, "First")).to_have_css("--ref-color", "#dc2626")


def test_the_builder_s_own_rules_colour_each_reference(page, api) -> None:
    open_module(page, build(api, "Markdown colours by rules", colorMode="rules", colorRules=[
        {"kind": "standard", "property": "rank", "comparison": "string", "operator": "is_exactly",
         "value": "low", "background": "#16a34a"}]))
    expect(colour_of(page, "Second")).to_have_attribute("data-color", "#16a34a")
    expect(colour_of(page, "First")).to_have_attribute("data-color", STATIC)


def test_a_static_colour_reads_no_objects(page, api) -> None:
    mod = build(api, "Markdown colours static")
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "object-sets/evaluate" in r.url else None)
    open_module(page, mod)
    expect(colour_of(page, "First")).to_have_attribute("data-color", STATIC)
    assert asked == []


def test_the_panel_sets_where_a_colour_comes_from(page, api) -> None:
    mod = build(api, "Markdown colours panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Markdown").first.click()
    page.get_by_label("Object type 1 colour from").select_option("property")
    page.get_by_label("Object type 1 colour property").select_option("rank")
    page.get_by_role("button", name="Save", exact=True).click()
    settled(page)
    eventually(lambda: mod.definition()["layout"]["md"]["props"]["referenceTypes"][0],
               lambda t: (t.get("colorMode"), t.get("colorProperty")) == ("property", "rank"),
               what="the colour's source, saved")
