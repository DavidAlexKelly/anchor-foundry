"""A property's inline action, set in the Ontology Manager and used by the
Property List (§594; `workshop` p.266).

> "To enable inline editing for a property, configure an inline action for the
>  property in the Ontology Manager. Once the inline action is configured,
>  users can edit property values directly within the Property List widget."
>  (p.266)

Which actions may be one is `test_property_inline_actions.py`. What needs a
browser is both ends: the Ontology Manager offering the action and saving it,
and a running module's Property List editing the value in place and showing
what was saved.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled
from test_object_type_editor_carry import open_type_editor

ROWS = [{"id": "T1", "name": "Pump fault", "status": "open"}]


@pytest.fixture(scope="module")
def tickets(api):
    mod = Module(api, "Inline property")
    mod.object_type_id = mod.object_type(columns=["id", "name", "status"], rows=ROWS,
                                         key="id", title="name")
    mod.action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"set_status_{mod.tag}",
        "display_name": "Set status", "editable_properties": ["status"]})
    return mod


def detail(api, mod) -> dict:
    return api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")


def inline_of(api, mod) -> dict:
    return {p["api_name"]: p["inline_action_type_id"] for p in detail(api, mod)["properties"]}


def test_the_ontology_manager_sets_a_property_s_inline_action(page, api, tickets) -> None:
    open_type_editor(page, tickets)
    names = [page.get_by_role("textbox", name=f"Property {i} name").input_value()
             for i in (1, 2, 3)]
    index = names.index("status") + 1
    choice = page.get_by_label(f"Property {index} inline action")
    # Offered only where the action writes the property.
    expect(choice.locator("option")).to_have_text(["Not editable in place", "Edit with Set status"])
    expect(page.get_by_label(f"Property {names.index('name') + 1} inline action")
           .locator("option")).to_have_text(["Not editable in place"])
    choice.select_option(label="Edit with Set status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    eventually(lambda: inline_of(api, tickets)["status"],
               lambda got: got == tickets.action["id"], what="the inline action saved")


def with_inline_action(api, mod) -> None:
    got = detail(api, mod)
    api.call("PATCH", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}", {
        "display_name": got["display_name"], "title_property": "name",
        "properties": [{"api_name": p["api_name"], "display_name": p["display_name"],
                        "data_type": p["data_type"],
                        "inline_action_type_id":
                            mod.action["id"] if p["api_name"] == "status" else None}
                       for p in got["properties"]]})


def test_p266_the_property_list_edits_it_in_place(page, api, tickets) -> None:
    # A parameter named otherwise than the property, so what is submitted is
    # the parameter the rule reads rather than a name that happens to match.
    api.call("PUT", f"/workspaces/{tickets.workspace_id}/action-types/{tickets.action['id']}"
                    "/definition", {
        "parameters": [{"api_name": "new_status", "display_name": "New status",
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "status", "parameter": "new_status"}}],
        "criteria": []})
    with_inline_action(api, tickets)
    mod = Module(api, "Inline property list", beside=tickets)
    mod.define({
        "format": 2,
        "layout": layout({"pl": {"resolvedName": "CanvasPropertyList", "props": {
            "objectSetVariable": "v_set", "layout": "adjacent", "properties": "",
            "columns": 1, "hideNull": False}}}),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Tickets",
                                "object_set": object_set(tickets.object_type_id)}},
        "events": {},
    })
    # An author arranging the page is not editing the object.
    open_builder(page, mod)
    settled(page)
    expect(page.get_by_test_id("property-row")).to_have_count(3)
    expect(page.get_by_role("button", name="Edit Status")).to_have_count(0)
    open_module(page, mod)
    row = page.get_by_test_id("property-row").filter(has_text="open")
    expect(row).to_have_count(1)
    # Only the property with an inline action has an editor.
    expect(page.get_by_role("button", name="Edit Name")).to_have_count(0)
    page.get_by_role("button", name="Edit Status").click()
    editing = page.get_by_test_id("property-inline-edit")
    editing.get_by_label("Status").fill("closed")
    editing.get_by_role("button", name="Save").click()
    expect(editing).to_have_count(0)
    expect(page.get_by_test_id("property-row").filter(has_text="closed")).to_have_count(1)

    def status():
        found = api.call("POST", f"/workspaces/{tickets.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": tickets.object_type_id,
                                         "filters": []}, "limit": 5})["instances"]
        return found[0]["properties"]["status"]
    eventually(status, lambda s: s == "closed", what="the edit saved to the object")


def test_an_action_that_no_longer_writes_it_draws_no_editor(page, api, tickets) -> None:
    """Re-read where it is used: the action changed after it was chosen."""
    with_inline_action(api, tickets)
    api.call("PUT", f"/workspaces/{tickets.workspace_id}/action-types/{tickets.action['id']}"
                    "/definition", {
        "parameters": [{"api_name": "name", "display_name": "Name", "data_type": "string"}],
        "rules": [{"kind": "modify_object", "config": {"property": "name", "parameter": "name"}}],
        "criteria": []})
    mod = Module(api, "Inline property stale", beside=tickets)
    mod.define({
        "format": 2,
        "layout": layout({"pl": {"resolvedName": "CanvasPropertyList", "props": {
            "objectSetVariable": "v_set", "layout": "adjacent", "properties": "",
            "columns": 1, "hideNull": False}}}),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Tickets",
                                "object_set": object_set(tickets.object_type_id)}},
        "events": {},
    })
    open_module(page, mod)
    expect(page.get_by_test_id("property-row")).to_have_count(3)
    expect(page.get_by_role("button", name="Edit Status")).to_have_count(0)
