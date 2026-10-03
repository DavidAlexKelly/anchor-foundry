"""p.261-263's panel form factor on the Object View widget, and `object-views`
p.37-41's default panels (§694).

> "Form factor: Controls whether the full or panel object view is displayed."
> (p.261) "Panel behavior: Controls how the panel displays objects based on
> the input object set. … Object instance … Adaptive … Object set" (p.263)

> "The default object instance panel view shows a single Property List widget
> that displays prominent properties … The default object set panel provides
> a tabbed layout with two interfaces to explore object collections: The
> Charts tab displays up to five XY Charts … The List tab shows an Object List
> widget" (`object-views` p.41)

Which panel each behaviour picks and which properties each draws are
`lib/object-panels.test.ts`. What needs a browser is the panels themselves.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "C1", "name": "Alpha", "region": "north", "status": "open"},
    {"id": "C2", "name": "Beta", "region": "south", "status": "open"},
    {"id": "C3", "name": "Gamma", "region": "north", "status": "closed"},
]


@pytest.fixture(scope="module")
def customers(api):
    mod = Module(api, "Object view panels")
    mod.type_id = mod.object_type(
        columns=["id", "name", "region", "status"], rows=ROWS, key="id", title="name",
        visibility={"region": "prominent"})
    return mod


def build(api, host, name: str, who: list[str], props: dict):
    mod = Module(api, name, beside=host)
    filters = [{"property": "id", "op": "in", "value": who}]
    mod.define({
        "format": 2,
        "layout": layout({"ov": {"resolvedName": "CanvasObjectViewWidget", "props": {
            "objectSetVariable": "v_set", "viewMode": "configured", "allowToggle": True,
            "hideHeader": False, "emptyMessage": "", "formFactor": "panel", **props}}}),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "The set",
                                "object_set": object_set(host.type_id, filters)}},
        "events": {},
    })
    return mod


def test_an_instance_panel_shows_the_prominent_properties(page, api, customers) -> None:
    mod = build(api, customers, "Panel instance", ["C1", "C2"], {"panelBehavior": "instance"})
    open_module(page, mod)
    panel = page.get_by_test_id("standard-panel-view")
    expect(panel.get_by_test_id("panel-title")).to_have_text("Alpha")
    # The type's mark, with the named icon its type holds by default (§705).
    expect(panel.locator(".sov-type svg")).to_have_attribute("data-icon", "cube")
    expect(panel.get_by_test_id("panel-properties")).to_contain_text("north")
    # p.41: prominent properties, so not the others.
    expect(panel).not_to_contain_text("open")
    expect(page.get_by_test_id("standard-object-view")).to_have_count(0)


def test_adaptive_shows_one_object_or_the_set(page, api, customers) -> None:
    one = build(api, customers, "Panel adaptive one", ["C3"], {"panelBehavior": "adaptive"})
    open_module(page, one)
    expect(page.get_by_test_id("standard-panel-view")).to_contain_text("Gamma")
    several = build(api, customers, "Panel adaptive several", ["C1", "C2", "C3"],
                    {"panelBehavior": "adaptive"})
    open_module(page, several)
    panel = page.get_by_test_id("object-set-panel")
    # Charts by region and by status - not by name, the title.
    expect(panel.get_by_test_id("panel-chart").locator("figcaption")).to_have_text(
        ["Region", "Status"])
    expect(panel.get_by_test_id("panel-chart").first.locator("rect title")).to_have_text(
        ["north: 2", "south: 1"])
    none = build(api, customers, "Panel adaptive none", ["nobody"], {"panelBehavior": "adaptive"})
    open_module(page, none)
    page.get_by_test_id("object-set-panel").get_by_role("tab", name="List").click()
    expect(page.get_by_test_id("panel-list-empty")).to_be_visible()


def test_the_set_panel_lists_its_objects(page, api, customers) -> None:
    mod = build(api, customers, "Panel set", ["C2"], {"panelBehavior": "set"})
    open_module(page, mod)
    panel = page.get_by_test_id("object-set-panel")
    panel.get_by_role("tab", name="List").click()
    items = panel.get_by_test_id("panel-list-item")
    expect(items).to_have_count(1)
    expect(items.first).to_contain_text("Beta")
    expect(items.first).to_contain_text("south")


def test_a_configured_panel_view_is_used(page, api, customers) -> None:
    view = Module(api, "Panel view module", beside=customers)
    view.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText",
                                  "props": {"tag": "p", "text": "Panel: {{v_region}}"}}}),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The customer"},
            "v_region": {"id": "v_region", "kind": "string", "label": "Region",
                         "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                                        "config": {"property": "region"}}},
        },
        "events": {},
    })
    api.call("PUT", f"{view.base}/canvas-apps/{view.app_id}/publish", {"scope": "workspace"})
    api.call("PUT", f"/workspaces/{view.workspace_id}/object-types/{customers.type_id}/view",
             {"canvas_app_id": view.app_id, "subject_variable": "v_obj", "form_factor": "panel"})
    try:
        mod = build(api, customers, "Panel configured", ["C2"], {"panelBehavior": "instance"})
        open_module(page, mod)
        expect(page.get_by_test_id("configured-object-view")).to_contain_text("Panel: south")
    finally:
        api.call("DELETE", f"/workspaces/{view.workspace_id}/object-types/{customers.type_id}/view"
                 "?form_factor=panel")


def test_the_panel_offers_the_form_factor_and_behavior(page, api, customers) -> None:
    mod = build(api, customers, "Panel settings", ["C1"], {"formFactor": "full"})
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Object view").first.click()
    expect(page.get_by_test_id("object-view-panel-behavior")).to_have_count(0)
    page.get_by_test_id("object-view-form-factor").select_option("panel")
    behavior = page.get_by_test_id("object-view-panel-behavior")
    expect(behavior.locator("option")).to_have_text(["Object instance", "Adaptive", "Object set"])
