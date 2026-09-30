"""p.30's related resources, on the object type being looked at (§603;
`ontology-manager` p.30).

    "Hovering over the Back home button will also bring up quick links to
     recently edited object types, link types, and action types, as well as
     all resources that are related to the one you are currently viewing."

§317 built the first half in the search box. The second is on the object
type's own dialog, because that dialog covers the search box while it is
open. What the browser has to show is that **each entry arrives**: a list of
names that cannot be followed would be a second copy of facts the dialog
already has. Which entries appear is `apps/web/src/lib/related-resources.test.ts`.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE
from ontology_page import find_type_row


@pytest.fixture(scope="module")
def world(api):
    """A type related five ways: a link to a second type, an action, an
    interface, a group — and the second type carries a shared property."""
    mod = Module(api, "Related resources")
    mod.object_type(columns=["id", "town"], rows=[{"id": "1", "town": "Ely"}],
                    key="id", title="town")
    ws = f"/workspaces/{mod.workspace_id}"
    tag = uuid.uuid4().hex[:8]
    mod.rtag = tag
    shared = api.call("POST", f"{ws}/shared-properties", {
        "api_name": f"related_region_{tag}", "display_name": f"Related region {tag}",
        "data_type": "string"})
    mod.shared_api_name = shared["api_name"]
    # Workspace-wide, like the group below, and not swept by `api.cleanup`: a
    # leftover is the first row another file's table test picks up.
    made = [f"{ws}/shared-properties/{shared['id']}"]
    far = api.call("POST", f"{ws}/object-types", {
        "api_name": f"far_{tag}", "display_name": f"Far {tag}",
        "properties": [
            {"api_name": "code", "display_name": "Code", "data_type": "string",
             "required": True},
            {"api_name": "region", "display_name": "Region", "data_type": "string",
             "shared_property_id": shared["id"]},
        ]})
    mod.far_name = f"Far {tag}"
    api.call("POST", f"{ws}/link-types", {
        "api_name": f"lk_{tag}", "display_name": f"Reaches {tag}",
        "from_type_id": mod.object_type_id, "to_type_id": far["id"],
        "cardinality": "one_to_many", "from_property": "id", "to_property": "code"})
    mod.link_name = f"Reaches {tag}"
    action = api.call("POST", f"{ws}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"rename_{tag}",
        "display_name": f"Rename {tag}", "editable_properties": ["town"]})
    mod.action_api_name = action["api_name"]
    mod.action_name = f"Rename {tag}"
    iface = api.call("POST", f"{ws}/interfaces", {
        "api_name": f"Placed{tag}", "display_name": f"Placed {tag}",
        "properties": [{"api_name": "place", "display_name": "Place",
                        "data_type": "string", "required": True}]})
    api.call("PUT", f"{ws}/object-types/{mod.object_type_id}/interfaces",
             [{"interface_id": iface["id"], "property_mapping": {"place": "town"}}])
    mod.iface_api_name = iface["api_name"]
    mod.iface_name = f"Placed {tag}"
    group = api.call("POST", f"{ws}/object-type-groups", {
        "api_name": f"towns_{tag}", "display_name": f"Towns {tag}", "description": ""})
    api.call("PUT", f"{ws}/object-types/{mod.object_type_id}/groups",
             {"group_ids": [group["id"]]})
    mod.group_name = f"Towns {tag}"
    made.append(f"{ws}/object-type-groups/{group['id']}")
    yield mod
    # The type carrying the shared property goes first, so nothing still uses
    # it; best effort, as `api.cleanup` is.
    for path in [f"{ws}/object-types/{far['id']}", *made]:
        try:
            api.call("DELETE", path)
        except Exception:
            pass


def open_type(page, mod) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    find_type_row(page, f"seed_{mod.tag}").get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("type-related")).to_be_visible(timeout=15000)


def related(page, label: str):
    return page.get_by_test_id(f"type-related-{label}")


def test_a_link_type_opens_the_type_at_its_other_end(page, world):
    open_type(page, world)
    name = page.get_by_label("Display name")
    home = name.input_value()
    link = related(page, world.link_name)
    expect(link).to_contain_text(f"to {world.far_name}")
    link.click()
    # The same slot, now holding the other type — and its own related list
    # names the way back, and the shared property it carries.
    expect(page.get_by_role("heading", name=f"Edit {world.far_name}")).to_be_visible(timeout=15000)
    expect(name).to_have_value(world.far_name)
    expect(related(page, world.link_name)).to_contain_text(f"from {home}")

    # And back. The first type is cached by now, so it arrives in the same
    # render - which is when a dialog seeded from the type it was mounted with
    # would still be showing this one's fields under that one's title.
    related(page, world.link_name).click()
    expect(page.get_by_role("heading", name=f"Edit {home}")).to_be_visible(timeout=15000)
    expect(name).to_have_value(home)
    related(page, world.link_name).click()
    expect(name).to_have_value(world.far_name, timeout=15000)

    shared = related(page, world.shared_api_name)
    # The property shows the shared display name (p.178), which is what
    # names it here.
    expect(shared).to_contain_text(f"as Related region {world.rtag}")
    shared.click()
    expect(page.get_by_role("heading", name=f"Edit {world.shared_api_name}")).to_be_visible(timeout=15000)


def test_an_action_opens_its_overview(page, world):
    open_type(page, world)
    related(page, world.action_name).click()
    expect(
        page.get_by_role("heading", name=f"Overview · {world.action_api_name}")
    ).to_be_visible(timeout=15000)
    # One dialog at a time: the type's closed as the action's opened.
    expect(page.get_by_test_id("type-related")).to_have_count(0)


def test_an_interface_and_a_group_open_themselves(page, world):
    open_type(page, world)
    related(page, world.iface_name).click()
    expect(page.get_by_role("heading", name=f"{world.iface_api_name} objects")).to_be_visible(timeout=15000)

    open_type(page, world)
    related(page, world.group_name).click()
    expect(page.get_by_role("heading", name=f"Object types in {world.group_name}")).to_be_visible(timeout=15000)


def test_an_unsaved_edit_holds_the_links(page, world):
    """Going somewhere else closes the dialog, and an edit nobody saved would
    go with it — so the links wait, and say why."""
    open_type(page, world)
    expect(page.get_by_test_id("type-related-unsaved")).to_have_count(0)
    expect(related(page, world.link_name)).to_be_enabled()

    page.get_by_label("Description").fill("changed, not saved")
    expect(page.get_by_test_id("type-related-unsaved")).to_be_visible()
    expect(related(page, world.link_name)).to_be_disabled()
    expect(related(page, world.group_name)).to_be_disabled()


def test_the_two_separate_writes_count_as_unsaved_too(page, world):
    """Groups and edit history are saved by writes of their own, and are just
    as lost by leaving."""
    open_type(page, world)
    page.get_by_test_id(f"type-group-towns_{world.rtag}").click()
    expect(page.get_by_test_id("type-related-unsaved")).to_be_visible()
    expect(related(page, world.link_name)).to_be_disabled()
    # Put back as it was, the dialog has nothing to lose again.
    page.get_by_test_id(f"type-group-towns_{world.rtag}").click()
    expect(page.get_by_test_id("type-related-unsaved")).to_have_count(0)

    page.get_by_test_id("type-track-edit-history").click()
    expect(page.get_by_test_id("type-related-unsaved")).to_be_visible()
    expect(related(page, world.link_name)).to_be_disabled()
