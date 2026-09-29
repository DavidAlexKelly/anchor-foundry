"""p.512's several actions in one Inline Action widget (§556).

    "Select an Action: Select Add item to include multiple actions, each
     requiring individual configuration. When multiple actions are
     implemented in the same widget frame, users will see a selection menu
     upfront." (p.512)

One ticket, two actions over it - Close and Annotate - in one widget. The menu
picks which form is drawn, each with its own title and fields, and the one
submitted is the one chosen. The list logic is `action-menu.test.ts`.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, save, settled


def an_action(api, mod: Module, name: str, parameter: str) -> dict:
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"{name}_{uuid.uuid4().hex[:8]}",
        "display_name": name.capitalize(), "editable_properties": [parameter]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [{"api_name": parameter, "display_name": parameter.capitalize(),
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": parameter, "parameter": parameter}}],
        "criteria": []})
    return action


def build(api, name: str, *, more: bool = True) -> Module:
    mod = Module(api, name)
    mod.type_id = mod.object_type(
        columns=["ticket_id", "status", "note"],
        rows=[{"ticket_id": "1", "status": "open", "note": "first"}],
        key="ticket_id", title="ticket_id")
    mod.close = an_action(api, mod, "close", "status")
    mod.annotate = an_action(api, mod, "annotate", "note")
    mod.define({
        "format": 2,
        "layout": layout({"frm": {"resolvedName": "CanvasActionForm", "props": {
            "actionTypeId": mod.close["id"],
            "actions": [{"actionTypeId": mod.annotate["id"], "title": "Add a note"}]
            if more else []}}}),
        "variables": {}, "events": {},
    })
    return mod


def field(page, name: str):
    return page.locator(f"[data-parameter='{name}'] input")


def test_the_menu_picks_which_action_is_drawn_and_submitted(page, api) -> None:
    mod = build(api, "Action menu")
    open_module(page, mod)
    menu = page.get_by_test_id("action-form-menu")
    expect(menu.locator("option")).to_have_text(["Close", "Add a note"])
    expect(page.get_by_test_id("action-form-title")).to_have_text("Close")

    # The record first, then the other action: a different form over the same
    # object starts at what the object says, not at the last form's values.
    page.locator("form select").select_option(index=1)
    expect(field(page, "status")).to_have_value("open")
    menu.select_option(label="Add a note")
    expect(page.get_by_test_id("action-form-title")).to_have_text("Add a note")
    expect(field(page, "note")).to_have_value("first")
    expect(field(page, "status")).to_have_count(0)
    field(page, "note").fill("seen by ops")
    page.get_by_role("button", name="Submit").click()
    eventually(lambda: api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"][0]["properties"], lambda p: p["note"] == "seen by ops" and p["status"] == "open",
               what="the note written by the chosen action, and nothing else")


def test_one_action_has_no_menu(page, api) -> None:
    open_module(page, build(api, "Action menu single", more=False))
    expect(page.get_by_test_id("action-form-title")).to_have_text("Close")
    expect(page.get_by_test_id("action-form-menu")).to_have_count(0)


def test_the_panel_adds_an_action_with_its_own_title(page, api) -> None:
    mod = build(api, "Action menu panel", more=False)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Action form").first.click()
    page.get_by_test_id("action-form-add-item").click()
    page.get_by_label("Action 2", exact=True).select_option(mod.annotate["id"])
    page.get_by_label("Action 2 title").fill("Add a note")
    save(page)
    eventually(lambda: mod.definition()["layout"]["frm"]["props"].get("actions"),
               lambda got: got == [{"actionTypeId": mod.annotate["id"], "title": "Add a note"}],
               what="the second action, saved")
