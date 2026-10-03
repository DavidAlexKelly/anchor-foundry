"""p.322's Create annotations via actions or events (§638).

> "Configure actions or events to create new annotation objects when text is
> highlighted within the widget. … Interaction: Configure an action or event
> which can be triggered on the highlighted text. Highlighted text: A special
> action parameter value that can be used to reference text highlighted
> within the widget." (p.322)

That the server takes each action as a click item and refuses a bare click
is `test_workshop_variables.py`. What needs a browser is that the actions
appear when text is highlighted and not before, and that one runs its events
with the highlighted text and where it is.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, settled
from test_markdown_selection import SELECT

TEXT = "I *think* this **sentence** is ~pretty good~"


def build(api, name: str, icon: str | None = None) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown", "props": {
                "text": TEXT, "highlightActions": [
                    {"id": "h_1", "label": "Annotate", **({"icon": icon} if icon else {})}]}},
            "out": {"resolvedName": "CanvasText", "props": {
                "tag": "p", "text": "LAST=[{{v_last}}]"}},
        }),
        "variables": {"v_last": {"id": "v_last", "kind": "string", "label": "Last",
                                 "default": "none"}},
        "events": {"e_1": {"id": "e_1", "trigger": {"node": "md", "on": "click", "item": "h_1"},
                           "effects": [{"type": "set_variable", "config": {
                               "variable": "v_last", "value": "{{value}}@{{start}}-{{end}}"}}]}},
    })
    return mod


def test_an_action_runs_on_the_highlighted_text(page, api) -> None:
    open_module(page, build(api, "Markdown highlight actions"))
    expect(page.get_by_test_id("markdown")).to_contain_text("sentence", timeout=20000)
    expect(page.get_by_test_id("markdown-highlight-action")).to_have_count(0)
    page.evaluate(SELECT, ["think", "sentence", 8])
    action = page.get_by_test_id("markdown-highlight-action")
    expect(action).to_have_text("Annotate")
    action.click()
    expect(page.get_by_text("LAST=[think* this **sentence@3-25]")).to_be_visible()


def test_an_action_with_an_icon_draws_it_and_keeps_its_title(page, api) -> None:
    """p.323's Icon: "Set the icon displayed on text highlighting. … The title
    appears on hover over the icon." (§707)"""
    open_module(page, build(api, "Markdown highlight icon", icon="edit"))
    expect(page.get_by_test_id("markdown")).to_contain_text("sentence", timeout=20000)
    page.evaluate(SELECT, ["think", "sentence", 8])
    action = page.get_by_role("button", name="Annotate")
    expect(action.locator("svg")).to_have_attribute("data-icon", "edit")
    expect(action).to_have_text("")
    action.click()
    expect(page.get_by_text("LAST=[think* this **sentence@3-25]")).to_be_visible()


def test_the_panel_chooses_an_action_s_icon(page, api) -> None:
    mod = build(api, "Markdown highlight icon panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Markdown").first.click()
    page.get_by_test_id("markdown-highlight-icon-0-name").select_option("flag")
    save(page)
    actions = mod.definition()["layout"]["md"]["props"]["highlightActions"]
    assert actions == [{"id": "h_1", "label": "Annotate", "icon": "flag"}], actions


def test_the_events_panel_offers_each_action(page, api) -> None:
    mod = build(api, "Markdown highlight actions panel")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Markdown").first.click()
    page.get_by_role("button", name="Events (1)").click()
    page.get_by_role("button", name="New event").click()
    when = page.locator(".canvas-event.on select").nth(1)
    expect(when.locator("option")).to_have_text(
        ["Highlighted text or hover action", "Reference or annotation selected"])
    expect(page.get_by_test_id("event-item")).to_have_value("h_1")
