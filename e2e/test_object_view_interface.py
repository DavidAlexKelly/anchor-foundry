"""p.263's Interface configuration on the Object View widget (§710).

> "Interface configuration: Defines a mapping from the current module's
> variables to an object view tab's module interface. Start by adding an
> object type to the mapping, then select a tab that has a module interface
> defined and populate the interface. For more details, visit the interface
> configuration section for embedded modules." (p.263)

Which keys bind which variables is `object-view-tabs.test.ts`; that a mapped
host variable is a usage is `test_workshop_variables.py`. What needs a browser
is the value crossing into the view, beating the view module's own default,
and coming back out when the view writes it - p.127's "any change to a
variable value in either the child or parent module will be reflected in all
modules where the variable is mapped" - and the panel that sets it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, save, settled

ROWS = [{"id": "C1", "name": "Alpha customer", "region": "north"}]


@pytest.fixture(scope="module")
def view(api):
    """An object type whose configured view publishes one interface variable,
    `note`, shows it, and can write it."""
    mod = Module(api, "Object view interface")
    type_id = mod.object_type(columns=["id", "name", "region"], rows=ROWS, key="id", title="name")
    mod.define({
        "format": 2,
        "layout": layout({
            "shown": {"resolvedName": "CanvasText",
                      "props": {"tag": "p", "text": "IN VIEW: {{v_note}}"}},
            "where": {"resolvedName": "CanvasText",
                      "props": {"tag": "p", "text": "VIEW REGION: {{v_region}}"}},
            "edit": {"resolvedName": "CanvasTextInput",
                     "props": {"name": "v_note", "label": "Note", "placeholder": "",
                               "format": "line", "rows": 1}},
        }),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The customer"},
            "v_note": {"id": "v_note", "kind": "string", "label": "Note",
                       "default": "the view's own", "external_id": "note",
                       "interface": {"display_name": "Note to show"}},
            # Derived from the object, so only the precedence rule (p.122,
            # p.127: a mapped variable's own definition stands aside) lets the
            # host's value through.
            "v_region": {"id": "v_region", "kind": "string", "label": "Region",
                         "external_id": "region", "interface": {"display_name": "Region"},
                         "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                                        "config": {"property": "region"}}},
            # An external ID without the interface toggle: not published.
            "v_secret": {"id": "v_secret", "kind": "string", "label": "Secret",
                         "default": "", "external_id": "secret"},
        },
        "events": {},
    })
    api.call("PUT", f"{mod.base}/canvas-apps/{mod.app_id}/publish", {"scope": "workspace"})
    saved = api.call(
        "PUT", f"/workspaces/{mod.workspace_id}/object-types/{type_id}/view",
        {"canvas_app_id": mod.app_id, "subject_variable": "v_obj"},
    )
    mod.view_type_id = type_id
    mod.tab_id = saved["tabs"][0]["id"]
    return mod


def host(api, view, name: str, mapping: dict | None) -> Module:
    mod = Module(api, name, beside=view)
    mod.define({
        "format": 2,
        "layout": layout({
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "IN HOST: {{h_note}}"}},
            "ov": {"resolvedName": "CanvasObjectViewWidget",
                   "props": {"objectSetVariable": "v_set", "viewMode": "configured",
                             "allowToggle": True, "hideHeader": False, "emptyMessage": "",
                             **({"viewInterface": mapping} if mapping is not None else {})}},
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "The customer",
                      "object_set": object_set(view.view_type_id,
                                               [{"property": "id", "op": "eq", "value": "C1"}])},
            "h_note": {"id": "h_note", "kind": "string", "label": "Host note",
                       "default": "from the host"},
            "h_region": {"id": "h_region", "kind": "string", "label": "Host region",
                         "default": "the host's region"},
        },
        "events": {},
    })
    return mod


def test_a_mapped_variable_crosses_into_the_view_and_back(page, api, view) -> None:
    mod = host(api, view, "Object view interface mapped", {
        f"{view.tab_id}:note": "h_note", f"{view.tab_id}:region": "h_region"})
    open_module(page, mod)
    settled(page)
    # The host's value, not the view module's own default or derivation
    # (p.122, p.127).
    expect(page.get_by_text("IN VIEW: from the host")).to_be_visible(timeout=30000)
    expect(page.get_by_text("VIEW REGION: the host's region")).to_be_visible()
    # And back: the view writes it, and the host sees it.
    field = page.get_by_test_id("configured-object-view").get_by_test_id("text-input")
    field.fill("changed in the view")
    expect(page.get_by_text("IN HOST: changed in the view")).to_be_visible()
    expect(page.get_by_text("IN VIEW: changed in the view")).to_be_visible()


def test_without_a_mapping_the_view_keeps_its_own(page, api, view) -> None:
    mod = host(api, view, "Object view interface unmapped", None)
    open_module(page, mod)
    settled(page)
    expect(page.get_by_text("IN VIEW: the view's own")).to_be_visible(timeout=30000)
    expect(page.get_by_text("VIEW REGION: north")).to_be_visible()
    expect(page.get_by_text("IN HOST: from the host")).to_be_visible()


def test_the_panel_maps_a_tab_s_interface(page, api, view) -> None:
    """p.263: "select a tab that has a module interface defined and populate
    the interface"."""
    mod = host(api, view, "Object view interface panel", None)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object view").first.click()
    section = page.get_by_test_id("object-view-interface")
    expect(section).to_contain_text("Note to show", timeout=30000)
    # Published variables only, and never the subject, which the object fills.
    expect(page.get_by_test_id("object-view-map-region")).to_be_visible()
    expect(page.get_by_test_id("object-view-map-secret")).to_have_count(0)
    page.get_by_test_id("object-view-map-note").select_option("h_note")
    save(page)
    props = mod.definition()["layout"]["ov"]["props"]
    assert props["viewInterface"] == {f"{view.tab_id}:note": "h_note"}, props
