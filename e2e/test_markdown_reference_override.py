"""p.320's per-type Override event on selection on the Markdown widget (§665).

> "Override event on selection: Configure Workshop events to trigger for the
>  specified object type. These will override any other event on selection."
>  (p.320)

A ship reference with its type's own event runs that one and not the
widget's; with the override off, the widget's runs.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, settled

ROWS = [{"id": "S1", "name": "Endeavour"}]


def build(api, name: str, *, override: bool, with_id: bool = True) -> Module:
    mod = Module(api, name)
    mod.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    api_name = f"seed_{mod.tag}"
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": f':objectreference[First]{{objectType="{api_name}" primaryKey="S1"}}',
                "tagType": "inline_reference",
                "referenceTypes": [{"objectType": api_name, "overrideSelection": override,
                                    **({"id": "rt_1"} if with_id else {})}],
            }},
            "note": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "NOTE={{v_note}}"}},
        }),
        "variables": {"v_note": {"id": "v_note", "kind": "string", "label": "Note", "default": "none"}},
        "events": {
            "e_any": {"id": "e_any", "trigger": {"node": "md", "on": "row_select"},
                      "effects": [{"type": "set_variable",
                                   "config": {"variable": "v_note", "value": "any:{{primary_key}}"}}]},
            **({"e_ship": {"id": "e_ship", "trigger": {"node": "md", "on": "row_select", "item": "rt_1"},
                           "effects": [{"type": "set_variable",
                                        "config": {"variable": "v_note", "value": "ship:{{primary_key}}"}}]}}
               if override else {}),
        },
    })
    return mod


def test_a_type_s_own_event_overrides_the_widget_s(page, api) -> None:
    open_module(page, build(api, "Markdown override on", override=True))
    expect(page.get_by_text("NOTE=none")).to_be_visible()
    page.get_by_test_id("markdown-ref").filter(has_text="First").click()
    expect(page.get_by_text("NOTE=ship:S1")).to_be_visible()


def test_without_the_override_the_widget_s_event_runs(page, api) -> None:
    open_module(page, build(api, "Markdown override off", override=False))
    page.get_by_test_id("markdown-ref").filter(has_text="First").click()
    expect(page.get_by_text("NOTE=any:S1")).to_be_visible()


def test_the_events_panel_offers_the_overriding_type(page, api) -> None:
    mod = build(api, "Markdown override panel", override=True)
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Events (2)").click()
    page.get_by_role("button", name="New event").click()
    # The Markdown widget is the one widget here with a trigger, so the new
    # event starts on it, on its one trigger: a reference selected.
    item = page.locator(".canvas-event.on").get_by_test_id("event-item")
    expect(item.locator("option")).to_have_text(["Every other object type", f"seed_{mod.tag}"])


def test_the_panel_turns_a_type_s_override_on(page, api) -> None:
    # No id yet: the panel gives one as the override goes on.
    mod = build(api, "Markdown override toggle", override=False, with_id=False)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Markdown").first.click()
    page.get_by_label("Object type 1 override event on selection").check()
    page.get_by_role("button", name="Save", exact=True).click()
    settled(page)
    eventually(lambda: mod.definition()["layout"]["md"]["props"]["referenceTypes"][0],
               lambda t: t.get("overrideSelection") is True and str(t.get("id", "")).startswith("rt_"),
               what="the type's override, saved")
