"""Link constraints on interfaces, from the Ontology Manager (§760; decision
0024; `ontology` p.60, `action-types` p.63-64).

The model and its refusals are `apps/api/tests/test_interface_links.py`', and
the dialog's sentences `apps/web/src/lib/interfaces.test.ts`'. What needs a
browser is the round trip: a link declared in the interface's dialog is the
promise the implementation dialog then asks to be kept, offering only the
link types that would keep it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import pick_type


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Interface links")
    tag = mod.tag
    desks = mod.object_type(columns=["id", "name"],
                            rows=[{"id": "D1", "name": "Window"}, {"id": "D2", "name": "Door"}],
                            key="id", title="name", slug=f"desk_{tag}")
    offices = mod.object_type(
        columns=["id", "name", "desk_ref", "next_ref"],
        rows=[{"id": "O1", "name": "North", "desk_ref": "D1", "next_ref": "O1"}],
        key="id", title="name", slug=f"office_{tag}")
    sits = api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"sits_at_{tag}", "display_name": "Sits at",
        "from_type_id": offices, "to_type_id": desks, "cardinality": "one_to_many",
        "from_property": "desk_ref", "to_property": "$primary_key"})
    # A link that goes somewhere else, which must not be offered.
    nxt = api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"next_{tag}", "display_name": "Next office",
        "from_type_id": offices, "to_type_id": offices, "cardinality": "one_to_many",
        "from_property": "next_ref", "to_property": "$primary_key"})
    return {"mod": mod, "desks": desks, "offices": offices, "sits": sits, "next": nxt}


def open_objects(page, mod) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    expect(page.get_by_test_id("new-interface")).to_be_visible(timeout=30000)


def test_a_link_declared_on_an_interface_is_kept_by_an_implementation(page, api, world) -> None:
    mod = world["mod"]
    name = f"Seated {uuid.uuid4().hex[:4]}"
    open_objects(page, mod)
    page.get_by_test_id("new-interface").click()
    page.get_by_test_id("iface-name").fill(name)
    expect(page.get_by_test_id("iface-no-links")).to_be_visible()
    page.get_by_test_id("iface-add-link").click()
    page.get_by_role("textbox", name="Link 1 name").fill("Desk")
    # Not saveable until it says what it links to.
    expect(page.get_by_test_id("iface-problem")).to_have_text("Choose what desk links to.")
    expect(page.get_by_test_id("iface-save")).to_be_disabled()
    page.get_by_role("combobox", name="Link 1 links to").select_option("object_type")
    pick_type(page, "iface-link-1-type", {"id": world["desks"], "api_name": f"desk_{mod.tag}"})
    api_name = page.get_by_test_id("iface-api-name").input_value()
    page.get_by_test_id("iface-save").click()
    expect(page.get_by_test_id("iface-table")).to_contain_text(api_name, timeout=15000)

    found = next(i for i in api.call("GET", f"/workspaces/{mod.workspace_id}/interfaces")
                 if i["api_name"] == api_name)
    detail = api.call("GET", f"/workspaces/{mod.workspace_id}/interfaces/{found['id']}")
    assert [(c["api_name"], c["target_object_type_id"], c["required"])
            for c in detail["link_constraints"]] == [("desk", world["desks"], True)]

    # Reopened, the dialog shows it as saved.
    page.get_by_role("button", name=f"Edit {api_name}").click()
    expect(page.get_by_role("textbox", name="Link 1 API name")).to_have_value("desk", timeout=15000)
    expect(page.get_by_role("combobox", name="Link 1 links to")).to_have_value("object_type")
    page.get_by_role("button", name="Cancel").click()

    page.get_by_role("button", name=f"Implement {api_name}").click()
    pick_type(page, "impl-type", {"id": world["offices"], "api_name": f"office_{mod.tag}"})
    kept = page.get_by_test_id("impl-link-desk")
    expect(kept.get_by_role("checkbox")).to_have_count(1, timeout=15000)
    expect(kept).to_contain_text("Sits at")
    expect(kept).not_to_contain_text("Next office")
    # A required link nothing keeps yet holds the save.
    expect(page.get_by_test_id("impl-unkept")).to_contain_text("desk")
    expect(page.get_by_test_id("impl-save")).to_be_disabled()
    kept.get_by_role("checkbox", name=f"Keep desk with sits_at_{mod.tag}").check()
    expect(page.get_by_test_id("impl-unkept")).to_have_count(0)
    page.get_by_test_id("impl-save").click()
    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_have_text(
        "1 object type", timeout=15000)

    impls = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{world['offices']}/interfaces")
    mine = next(i for i in impls if i["interface_id"] == found["id"])
    assert mine["link_mapping"] == {"desk": [world["sits"]["id"]]}

    # Opened again, the dialog holds what was kept.
    page.get_by_role("button", name=f"Implement {api_name}").click()
    pick_type(page, "impl-type", {"id": world["offices"], "api_name": f"office_{mod.tag}"})
    expect(page.get_by_test_id("impl-link-desk").get_by_role("checkbox")).to_be_checked(
        timeout=15000)


def test_an_action_on_the_interface_links_through_it(page, api, world) -> None:
    """p.63's Create interface link, set up in the action editor (§762) and
    run (§761): choosing the link generates the parameter for its other end,
    named after it, as p.63 says, and the run writes the office's own key."""
    mod = world["mod"]
    wid = mod.workspace_id
    tag = uuid.uuid4().hex[:6]
    iface = api.call("POST", f"/workspaces/{wid}/interfaces", {
        "api_name": f"Desked{tag}", "display_name": f"Desked {tag}",
        "properties": [{"api_name": "code", "data_type": "string"}],
        "link_constraints": [{"api_name": "desk", "display_name": "Desk",
                              "target_object_type_id": world["desks"]}]})
    api.call("PUT", f"/workspaces/{wid}/object-types/{world['offices']}/interfaces", [
        {"interface_id": iface["id"], "property_mapping": {"code": "name"},
         "link_mapping": {"desk": [world["sits"]["id"]]}}])
    action = api.call("POST", f"/workspaces/{wid}/action-types", {
        "interface_id": iface["id"], "api_name": f"seat_{tag}", "display_name": "Seat",
        "editable_properties": ["code"]})
    # An object parameter of another type, which is no desk and must not be
    # offered for the link's other end.
    api.call("PUT", f"/workspaces/{wid}/action-types/{action['id']}/definition", {
        "parameters": [{"api_name": "code", "display_name": "Code", "data_type": "string"},
                       {"api_name": "neighbour", "display_name": "Neighbour",
                        "data_type": "object", "object_type_id": world["offices"]}],
        "rules": [{"kind": "modify_object", "config": {"property": "code", "parameter": "code"}}],
        "criteria": []})

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=f"seat_{tag}")
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    # p.63-64's two, on an action on an interface (an object type's has seven).
    options = dialog.get_by_label("Rule 1 kind").locator("option").all_inner_texts()
    assert options[-2:] == ["Link through the interface", "Unlink through the interface"], options
    # The action's own rule becomes the link rule.
    dialog.get_by_label("Rule 1 kind").select_option("create_interface_link")
    dialog.get_by_label("Rule 1 interface link").select_option("desk")
    expect(dialog.get_by_label("Rule 1 other end")).to_have_value("desk")
    # Only a reference to the link's target is offered for its other end.
    expect(dialog.get_by_label("Rule 1 other end").locator("option")).to_have_text(
        ["Choose…", "desk"])
    dialog.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=15000)

    saved = api.call("GET", f"/workspaces/{wid}/action-types/{action['id']}")
    generated = next(p for p in saved["parameters"] if p["api_name"] == "desk")
    assert (generated["data_type"], generated["object_type_id"]) == ("object", world["desks"])
    assert [(r["kind"], r["config"]) for r in saved["rules"]] == [
        ("create_interface_link", {"link": "desk", "object": "desk"})]

    office = api.call("GET", f"/workspaces/{wid}/object-types/{world['offices']}/instances")["items"][0]
    desk = next(d for d in api.call(
        "GET", f"/workspaces/{wid}/object-types/{world['desks']}/instances")["items"]
        if d["primary_key"] == "D2")
    # The fixture's office points at D1; the run is what moves it.
    assert office["properties"]["desk_ref"] == "D1"
    result = api.call("POST", f"{mod.base}/actions/{action['id']}/execute",
                      {"instance_id": office["id"], "values": {"desk": desk["id"]}})
    assert result["ok"], result
    after = api.call("GET", f"/workspaces/{wid}/object-types/{world['offices']}/instances/{office['id']}")
    assert after["properties"]["desk_ref"] == desk["primary_key"]


def test_a_type_switches_an_inherited_action_off_for_its_own_objects(page, api, world) -> None:
    """p.65's Interface action control (§763): from the object type's own
    editor, an action its interface carries is switched off for its objects,
    which takes it out of the type's actions."""
    from ontology_page import open_type_editor

    mod = world["mod"]
    wid = mod.workspace_id
    tag = uuid.uuid4().hex[:6]
    iface = api.call("POST", f"/workspaces/{wid}/interfaces", {
        "api_name": f"Controlled{tag}", "display_name": f"Controlled {tag}",
        "properties": [{"api_name": "code", "data_type": "string"}]})
    api.call("PUT", f"/workspaces/{wid}/object-types/{world['offices']}/interfaces", [
        {"interface_id": i["interface_id"], "property_mapping": i["property_mapping"]}
        for i in api.call("GET", f"/workspaces/{wid}/object-types/{world['offices']}/interfaces")
    ] + [{"interface_id": iface["id"], "property_mapping": {"code": "name"}}])
    action = api.call("POST", f"/workspaces/{wid}/action-types", {
        "interface_id": iface["id"], "api_name": f"rename_{tag}", "display_name": f"Rename {tag}",
        "editable_properties": ["code"]})

    def offered() -> bool:
        return action["id"] in {a["id"] for a in api.call(
            "GET", f"/workspaces/{wid}/action-types?object_type_id={world['offices']}")}

    assert offered()
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    open_type_editor(page, f"office_{mod.tag}")
    box = page.get_by_role("checkbox", name=f"Offer rename_{tag} for this type")
    expect(box).to_be_checked(timeout=15000)
    expect(page.get_by_test_id("interface-action-control")).to_contain_text(f"Controlled {tag}")
    # A click rather than `uncheck`: the box follows the saved state, which
    # arrives a moment after the click.
    box.click()
    expect(box).not_to_be_checked(timeout=15000)
    eventually(lambda: offered(), lambda on: on is False, what="the action switched off")
    box.click()
    expect(box).to_be_checked(timeout=15000)
    eventually(lambda: offered(), lambda on: on is True, what="the action switched back on")
