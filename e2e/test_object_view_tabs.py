"""Tabs on a configured full Object View (§695; `object-views` p.34-35,
`workshop` p.262-263).

> "Each tab corresponds to a single workshop module. If only one tab is
> configured, the tab title will be hidden when viewing the Object View …
> Selecting the gear icon opens a dialog that allows you to add, reorder,
> rename, and delete Object View tabs." (object-views p.35)

Which tab shows and when the strip is drawn is
`apps/web/src/lib/object-view-tabs.test.ts`; the saved list is
`apps/api/tests/test_object_view_tabs.py`. What needs a browser is each tab's
module rendering with the object in it, and the widget's three settings.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from ontology_page import find_type_row
from test_configured_object_view import ROWS, open_first_object
from conftest import WEB_BASE, eventually, open_builder, open_module


def reader(api, host, name: str, prefix: str, prop: str) -> Module:
    """A published module showing one property of the object it receives."""
    mod = Module(api, name, beside=host)
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText",
                                  "props": {"tag": "p", "text": f"{prefix}: {{{{v_value}}}}"}}}),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The customer"},
            "v_value": {"id": "v_value", "kind": "string", "label": "Value",
                        "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                                       "config": {"property": prop}}},
        },
        "events": {},
    })
    api.call("PUT", f"{mod.base}/canvas-apps/{mod.app_id}/publish", {"scope": "workspace"})
    return mod


@pytest.fixture(scope="module")
def tabbed(api):
    host = Module(api, "Object view tabs")
    type_id = host.object_type(columns=["id", "name", "region"], rows=ROWS, key="id",
                               title="name")
    summary = reader(api, host, "Tabs summary", "Summary", "region")
    details = reader(api, host, "Tabs details", "Details", "name")
    view = api.call("PUT", f"/workspaces/{host.workspace_id}/object-types/{type_id}/view/tabs", {
        "tabs": [
            {"title": "Summary", "canvas_app_id": summary.app_id, "subject_variable": "v_obj"},
            {"title": "Details", "canvas_app_id": details.app_id, "subject_variable": "v_obj"},
        ]})
    host.type_id = type_id
    host.summary, host.details = summary, details
    host.tab_ids = [t["id"] for t in view["tabs"]]
    return host


def shown(page):
    return page.get_by_test_id("configured-object-view")


def test_each_tab_is_its_module_with_the_object_in_it(page, tabbed) -> None:
    open_first_object(page, tabbed)
    strip = page.get_by_role("tablist", name="Object view tabs")
    expect(strip.get_by_role("tab")).to_have_text(["Summary", "Details"])
    expect(strip.get_by_role("tab", name="Summary")).to_have_attribute("aria-selected", "true")
    eventually(lambda: shown(page).inner_text(), lambda t: "Summary: north" in t,
               what="the first tab's module")
    strip.get_by_role("tab", name="Details").click()
    eventually(lambda: shown(page).inner_text(), lambda t: "Details: Alpha customer" in t,
               what="the second tab's module")
    expect(shown(page)).to_have_attribute("data-app", tabbed.details.app_id)
    expect(shown(page)).to_have_count(1)


def test_the_gear_dialog_adds_reorders_and_renames_tabs(page, api) -> None:
    host = Module(api, "Object view tab dialog")
    type_id = host.object_type(columns=["id", "name", "region"], rows=ROWS, key="id",
                               title="name")
    first = reader(api, host, "Dialog first", "First", "region")
    second = reader(api, host, "Dialog second", "Second", "name")
    api.call("PUT", f"/workspaces/{host.workspace_id}/object-types/{type_id}/view",
             {"canvas_app_id": first.app_id, "subject_variable": "v_obj"})

    page.goto(f"{WEB_BASE}/{host.workspace_slug}/{host.project_slug}/objects")
    find_type_row(page, f"seed_{host.tag}")
    row = page.locator("tr", has_text=f"Seed {host.tag}").filter(
        has=page.get_by_role("button", name="View"))
    row.get_by_role("button", name="View").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Tab 1 module")).to_have_value(first.app_id)
    expect(dialog.get_by_role("button", name="Move Tab 1 up")).to_have_count(0)

    dialog.get_by_role("button", name="Add tab").click()
    save = dialog.get_by_role("button", name="Save", exact=True)
    expect(save).to_be_disabled()
    dialog.get_by_label("Tab 2 module").select_option(first.app_id)
    dialog.get_by_label("Tab 2 subject variable").select_option("v_obj")
    # Another module's variable belongs to that module, so changing the
    # module clears it.
    dialog.get_by_label("Tab 2 module").select_option(second.app_id)
    expect(dialog.get_by_label("Tab 2 subject variable")).to_have_value("")
    dialog.get_by_label("Tab 2 subject variable").select_option("v_obj")
    # A tab after the first needs a title.
    expect(dialog.get_by_test_id("object-view-tabs-problem")).to_have_text("Give tab 2 a title")
    dialog.get_by_label("Tab 2 title").fill("Names")
    dialog.get_by_label("Tab 1 title").fill("Regions")
    dialog.get_by_role("button", name="Move Tab 2 up").click()
    expect(dialog.get_by_label("Tab 1 title")).to_have_value("Names")
    save.click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    view = api.call("GET", f"/workspaces/{host.workspace_id}/object-types/{type_id}/view")
    assert [(t["title"], t["canvas_app_id"]) for t in view["tabs"]] == [
        ("Names", second.app_id), ("Regions", first.app_id)]

    # Deleted back down to one.
    row.get_by_role("button", name="View").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_label("Tab 2 title")).to_have_value("Regions")
    dialog.get_by_role("button", name="Delete Tab 1").click()
    expect(dialog.get_by_label("Tab 2 title")).to_have_count(0)
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    view = api.call("GET", f"/workspaces/{host.workspace_id}/object-types/{type_id}/view")
    assert [t["title"] for t in view["tabs"]] == ["Regions"]
    assert view["canvas_app_id"] == first.app_id


def widget(api, host, name: str, props: dict) -> Module:
    """An Object View widget over whichever object a dropdown picks."""
    mod = Module(api, name, beside=host)
    mod.define({
        "format": 2,
        "layout": layout({
            "dd": {"resolvedName": "CanvasObjectDropdown", "props": {
                "objectSetVariable": "v_all", "selectedVariable": "v_picked",
                "sortProperty": "id"}},
            "ov": {"resolvedName": "CanvasObjectViewWidget", "props": {
                "objectSetVariable": "v_chosen", "viewMode": "configured", **props}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(host.type_id)},
            "v_picked": {"id": "v_picked", "kind": "object_set_filter", "label": "Picked"},
            "v_chosen": {"id": "v_chosen", "kind": "object_set", "label": "Chosen",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_picked"]}},
        },
        "events": {},
    })
    return mod


def pick(page, name: str) -> None:
    dropdown = page.get_by_test_id("object-dropdown")
    dropdown.get_by_test_id("dropdown-toggle").click()
    dropdown.get_by_test_id("dropdown-option").filter(has_text=name).click()


def test_the_widget_opens_on_its_initial_tab(page, api, tabbed) -> None:
    """workshop p.263: "This controls the tab that will initially display when
    the object view is first opened." """
    open_module(page, widget(api, tabbed, "Tabs initial", {"initialTabId": tabbed.tab_ids[1]}))
    expect(page.get_by_role("tab", name="Details")).to_have_attribute("aria-selected", "true")
    eventually(lambda: shown(page).inner_text(), lambda t: "Details: Alpha customer" in t,
               what="the initial tab")


def test_hidden_tabs_leave_the_initial_tab_only(page, api, tabbed) -> None:
    """workshop p.262: "Users will be unable to navigate to different tabs of
    the object view when this option is selected." """
    open_module(page, widget(api, tabbed, "Tabs hidden",
                             {"hideTabs": True, "initialTabId": tabbed.tab_ids[1]}))
    eventually(lambda: shown(page).inner_text(), lambda t: "Details: Alpha customer" in t,
               what="the initial tab")
    expect(page.get_by_role("tablist", name="Object view tabs")).to_have_count(0)


def test_an_object_switch_can_go_back_to_the_initial_tab(page, api, tabbed) -> None:
    """workshop p.262: "Automatically navigates back to the initial tab when
    the displayed object changes." Without it the reader's tab is kept."""
    for setting, after in ((True, "Summary: south"), (False, "Details: Beta customer")):
        open_module(page, widget(api, tabbed, f"Tabs switch {setting}",
                                 {"goToInitialTab": setting}))
        eventually(lambda: shown(page).inner_text(), lambda t: "Summary: north" in t,
                   what="the first object on the first tab")
        page.get_by_role("tab", name="Details").click()
        eventually(lambda: shown(page).inner_text(), lambda t: "Details: Alpha customer" in t,
                   what="the reader's tab")
        pick(page, "Beta customer")
        eventually(lambda: shown(page).inner_text(), lambda t: after in t,
                   what=f"the second object, go-to-initial {setting}")


def test_the_widget_offers_the_tab_settings_for_a_view_of_several(page, api, tabbed) -> None:
    mod = widget(api, tabbed, "Tabs settings", {})
    open_builder(page, mod)
    page.locator(".canvas-tree-row", has_text="Object view").first.click()
    initial = page.get_by_test_id("object-view-initial-tab")
    expect(initial.locator("option")).to_have_text(["The first tab", "Summary", "Details"])
    expect(page.get_by_test_id("object-view-hide-tabs")).to_be_visible()
    expect(page.get_by_test_id("object-view-initial-on-switch")).to_be_visible()
