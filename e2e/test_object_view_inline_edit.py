"""Editing a property in place from the standard Object View (§595;
`action-types` p.135, `object-views` p.67, `workshop` p.266).

    "Inline edits are available in both Workshop and Object Explorer… Inline
     edits allow users to quickly edit values of an object in the Object
     Explorer results view or native Object View widgets." (p.135)

    "Make a property editable: If you wish to make a property editable, set up
     an action type or an inline action." (object-views p.67)

The same control as the Property List's (§594), in the view the Explorer
opens an object into: a property whose inline action is set shows Edit, the
save goes through the action, and the view shows what was saved. A reader who
cannot edit sees no editor.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

ROWS = [{"id": "V1", "name": "Valve", "status": "open", "site": "north"}]


@pytest.fixture(scope="module")
def valves(api):
    mod = Module(api, "Object view inline")
    mod.object_type_id = mod.object_type(
        columns=["id", "name", "status", "site"], rows=ROWS, key="id", title="name",
        visibility={"status": "prominent"})
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"edit_{mod.tag}",
        "display_name": "Edit valve", "editable_properties": ["status", "site"]})
    got = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")
    api.call("PATCH", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}", {
        "display_name": got["display_name"], "title_property": "name",
        "properties": [{"api_name": p["api_name"], "display_name": p["display_name"],
                        "data_type": p["data_type"], "visibility": p["visibility"],
                        "inline_action_type_id":
                            action["id"] if p["api_name"] in ("status", "site") else None}
                       for p in got["properties"]]})
    return mod


def open_object(page, mod) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 1, what="this type's one object")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_have_attribute(
        "data-state", "ready", timeout=30000)


def stored(api, mod):
    def read():
        found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": mod.object_type_id, "filters": []},
                          "limit": 5})["instances"]
        return found[0]["properties"]
    return read


def test_a_property_in_the_table_is_edited_in_place(page, api, valves) -> None:
    open_object(page, valves)
    view = page.get_by_test_id("standard-object-view")
    # Only the properties with an inline action.
    expect(view.get_by_role("button", name="Edit Name")).to_have_count(0)
    view.get_by_role("button", name="Edit Site").click()
    editing = view.get_by_test_id("property-inline-edit")
    editing.get_by_label("Site").fill("south")
    editing.get_by_role("button", name="Save").click()
    expect(editing).to_have_count(0)
    expect(view.locator('tr[data-property="site"]')).to_contain_text("south")
    eventually(stored(api, valves), lambda v: v.get("site") == "south",
               what="the edit saved to the object")


def test_a_prominent_property_is_edited_in_its_card(page, api, valves) -> None:
    open_object(page, valves)
    card = page.locator('.sov-card[data-property="status"]')
    card.get_by_role("button", name="Edit Status").click()
    card.get_by_label("Status").fill("shut")
    card.get_by_role("button", name="Save").click()
    expect(card).to_contain_text("shut")
    eventually(stored(api, valves), lambda v: v.get("status") == "shut",
               what="the edit saved to the object")


def test_a_reader_who_cannot_edit_sees_no_editor(viewer_page, valves) -> None:
    open_object(viewer_page, valves)
    view = viewer_page.get_by_test_id("standard-object-view")
    expect(view.locator('tr[data-property="site"]')).to_be_visible()
    expect(view.get_by_role("button", name="Edit Site")).to_have_count(0)


def test_the_workshop_object_view_widget_edits_in_a_running_module(page, api, valves) -> None:
    """p.135's "native Object View widgets": the same view, embedded."""
    from api import layout, object_set
    from conftest import open_builder, open_module, settled

    mod = Module(api, "Object view widget inline", beside=valves)
    mod.define({
        "format": 2,
        "layout": layout({"ov": {"resolvedName": "CanvasObjectViewWidget", "props": {
            "objectSetVariable": "v_set", "viewMode": "standard", "allowToggle": True,
            "hideHeader": False, "emptyMessage": ""}}}),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "The valve",
                                "object_set": object_set(valves.object_type_id)}},
        "events": {},
    })
    # Not while the page is being arranged.
    open_builder(page, mod)
    settled(page)
    view = page.get_by_test_id("standard-object-view")
    expect(view.locator('tr[data-property="site"]')).to_be_visible(timeout=30000)
    expect(view.get_by_role("button", name="Edit Site")).to_have_count(0)
    open_module(page, mod)
    view.get_by_role("button", name="Edit Site").click()
    view.get_by_test_id("property-inline-edit").get_by_label("Site").fill("east")
    view.get_by_role("button", name="Save").click()
    expect(view.locator('tr[data-property="site"]')).to_contain_text("east")
    eventually(stored(api, valves), lambda v: v.get("site") == "east",
               what="the edit saved to the object")
