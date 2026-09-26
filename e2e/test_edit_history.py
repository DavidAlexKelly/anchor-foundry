"""p.402's Track user edit history, and the Edit History widget (parity
`workshop.md` §10, `ontology.md`; §470, §471).

> "The Edit History widget displays the list of user edits made to an object's
> properties after Track user edit history has been enabled for the object type
> within Ontology Manager." (p.402)

What is recorded is `apps/api/tests/test_object_edits.py`, which drives the
three action paths. What needs a browser is the switch an author finds in the
type's editor, and what a reader sees.
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, open_builder, open_module, save, settled
from ontology_page import find_type_row, save_type


@pytest.fixture(scope="module")
def people(api):
    mod = Module(api, "Edit history")
    mod.object_type(
        columns=["id", "name", "email"],
        rows=[{"id": "p1", "name": "Ada", "email": "ada@example.com"},
              {"id": "p2", "name": "Grace", "email": "grace@example.com"}],
        key="id", title="name",
    )
    return mod


def setting(api, mod) -> str | None:
    return api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}/edit-history",
    )["since"]


def test_the_type_editor_switches_tracking_on_and_off(page, api, people) -> None:
    """p.402's "within Ontology Manager": the type's own editor, saved with
    the rest of it, and read back from the API rather than from the dialog."""
    assert setting(api, people) is None
    page.goto(f"{WEB_BASE}/{people.workspace_slug}/{people.project_slug}/objects")
    find_type_row(page, f"seed_{people.tag}").get_by_role("button", name="Edit").click()
    box = page.get_by_test_id("type-track-edit-history")
    expect(box).to_be_enabled()
    expect(box).not_to_be_checked()
    box.check()
    save_type(page)
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert setting(api, people) is not None

    find_type_row(page, f"seed_{people.tag}").get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("type-track-edit-history")).to_be_checked()
    expect(page.get_by_text("Tracked since")).to_be_visible()
    page.get_by_test_id("type-track-edit-history").uncheck()
    save_type(page)
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert setting(api, people) is None


# ---- the widget (§471) ---------------------------------------------------------
@pytest.fixture(scope="module")
def edited(api):
    """A tracked type whose `p1` was edited twice through an action, and whose
    `p2` never was."""
    mod = Module(api, "Edit history widget")
    mod.object_type(
        columns=["id", "name", "email"],
        rows=[{"id": "p1", "name": "Ada", "email": "ada@example.com"},
              {"id": "p2", "name": "Grace", "email": "grace@example.com"}],
        key="id", title="name",
    )
    base = f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}"
    api.call("PUT", f"{base}/edit-history", {"enabled": True})
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"fix_{uuid.uuid4().hex[:8]}",
        "display_name": "Fix", "editable_properties": ["name", "email"]})
    ada = next(i for i in api.call("GET", f"{base}/instances")["items"]
               if i["primary_key"] == "p1")
    for values in ({"email": "ada@lovelace.test"}, {"name": "Ada King"}):
        result = api.call("POST", f"{mod.base}/actions/{action['id']}/execute",
                          {"instance_id": ada["id"], "values": values})
        assert result["ok"], result
    return mod


def build(api, edited, name: str, key: str, props: dict | None = None) -> Module:
    mod = Module(api, name, beside=edited)
    mod.define({"format": 2, "layout": layout({
        "hist": {"resolvedName": "CanvasEditHistory",
                 "props": {"objectSetVariable": "v_one", **(props or {})}}}),
        "variables": {"v_one": {
            "id": "v_one", "kind": "object_set", "label": "One person",
            "object_set": object_set(edited.object_type_id,
                                     [{"property": "id", "op": "eq", "value": key}])}},
        "events": {}})
    return mod


def summaries(page) -> list[str]:
    return page.locator("[data-testid='edit-history-entry'] .canvas-edit-summary") \
        .all_text_contents()


def test_the_widget_lists_an_objects_edits_newest_first(page, api, edited) -> None:
    open_module(page, build(api, edited, "History newest", "p1"))
    expect(page.get_by_test_id("edit-history-entry")).to_have_count(2)
    # Display names, not api_names; and who made each edit.
    assert summaries(page) == [
        "Name: Ada → Ada King", "Email: ada@example.com → ada@lovelace.test"]
    expect(page.get_by_test_id("edit-history-entry").first).to_contain_text(re.compile("owner", re.I))


def test_the_order_and_the_properties_are_the_authors(page, api, edited) -> None:
    """p.403's Edits sort order and Property configuration."""
    open_module(page, build(api, edited, "History oldest", "p1", {"order": "oldest"}))
    expect(page.get_by_test_id("edit-history-entry")).to_have_count(2)
    assert summaries(page)[0].startswith("Email:")
    open_module(page, build(api, edited, "History email", "p1", {"properties": "email"}))
    expect(page.get_by_test_id("edit-history-entry")).to_have_count(1)
    assert summaries(page) == ["Email: ada@example.com → ada@lovelace.test"]


def test_an_unedited_object_and_an_untracked_type_say_different_things(
    page, api, edited, people
) -> None:
    open_module(page, build(api, edited, "History none", "p2"))
    expect(page.get_by_test_id("edit-history-empty")).to_be_visible()
    # `people`'s tracking was switched off again by the first test in this file.
    mod = Module(api, "History untracked", beside=people)
    mod.define({"format": 2, "layout": layout({
        "hist": {"resolvedName": "CanvasEditHistory", "props": {"objectSetVariable": "v"}}}),
        "variables": {"v": {"id": "v", "kind": "object_set", "label": "People",
                            "object_set": object_set(people.object_type_id)}},
        "events": {}})
    open_module(page, mod)
    expect(page.get_by_test_id("edit-history-untracked")).to_be_visible()


def test_the_panel_sets_the_order_and_properties(page, api, edited) -> None:
    mod = build(api, edited, "History panel", "p1")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Edit history").first.click()
    page.get_by_test_id("edit-history-order").select_option("oldest")
    page.get_by_test_id("edit-history-properties").fill("email")
    save(page)
    props = mod.definition()["layout"]["hist"]["props"]
    assert (props["order"], props["properties"]) == ("oldest", "email"), props
