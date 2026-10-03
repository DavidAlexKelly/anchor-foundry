"""p.217's per-side visibility of a link type (§714; db 0138).

> "Visibility: An indication to user applications for how prominently to
> display the side of the link type (referring to links to the object type on
> that side). A prominent side of a link type will lead applications to show
> this side of the link type first to users. A hidden side of a link type will
> not appear in user applications." (`object-link-types` p.217)

The order and the filter are `apps/api/tests/test_link_traversal.py`'s. What
needs a browser is the dialog that sets each side, and a user application -
the Links widget - showing the prominent side first and the hidden one not at
all.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module, settled

PEOPLE = [{"id": "P1", "name": "Ada", "manager_id": ""},
          {"id": "P2", "name": "Grace", "manager_id": "P1"}]


@pytest.fixture
def people(api):
    mod = Module(api, "Link visibility")
    mod.person_type = mod.object_type(columns=["id", "name", "manager_id"], rows=PEOPLE,
                                      key="id", title="name")
    tag = uuid.uuid4().hex[:6]
    mod.link = api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"reports_to_{tag}", "display_name": f"Reports to {tag}",
        "from_type_id": mod.person_type, "to_type_id": mod.person_type,
        "cardinality": "one_to_many", "from_property": "manager_id",
        "to_property": "$primary_key",
        "from_side_name": "Direct reports", "to_side_name": "Manager"})
    return mod


def links_widget(api, people, name: str) -> Module:
    mod = Module(api, name, beside=people)
    mod.define({
        "format": 2,
        "layout": layout({"lw": {"resolvedName": "CanvasLinksWidget", "props": {
            "objectSetVariable": "v_set", "linkMode": "all", "links": [], "defaultExpand": 0}}}),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Grace",
                                "object_set": object_set(people.person_type, [
                                    {"property": "id", "op": "eq", "value": "P2"}])}},
        "events": {},
    })
    return mod


def labels(page) -> list[str]:
    return [(t or "").strip() for t in page.get_by_test_id("link-label").all_text_contents()]


def test_the_dialog_sets_each_side(page, api, people) -> None:
    page.goto(f"{WEB_BASE}/{people.workspace_slug}/{people.project_slug}/objects")
    row = page.locator("tr", has_text=people.link["display_name"])
    row.get_by_role("button", name="Edit join").click()
    expect(page.get_by_test_id("link-to-visibility")).to_have_value("normal", timeout=30000)
    page.get_by_test_id("link-to-visibility").select_option("hidden")
    page.get_by_test_id("link-from-visibility").select_option("prominent")
    page.get_by_role("button", name="Save join").click()
    expect(page.get_by_test_id("link-to-visibility")).to_have_count(0)
    stored = next(link for link in api.call(
        "GET", f"/workspaces/{people.workspace_id}/link-types")
        if link["id"] == people.link["id"])
    assert (stored["from_visibility"], stored["to_visibility"]) == ("prominent", "hidden")


def test_a_user_application_shows_the_prominent_side_first_and_not_the_hidden(
    page, api, people
) -> None:
    mod = links_widget(api, people, "Link visibility widget")
    open_module(page, mod)
    settled(page)
    # p.217's default: both sides normal, Manager first by the server's order.
    eventually(lambda: labels(page), lambda got: got == ["Manager", "Direct reports"],
               what="both sides, in the server's order")

    api.call("PATCH", f"/workspaces/{people.workspace_id}/link-types/{people.link['id']}", {
        "from_property": "manager_id", "to_property": "$primary_key",
        "from_visibility": "prominent"})
    open_module(page, mod)
    settled(page)
    eventually(lambda: labels(page), lambda got: got == ["Direct reports", "Manager"],
               what="the prominent side first")

    api.call("PATCH", f"/workspaces/{people.workspace_id}/link-types/{people.link['id']}", {
        "from_property": "manager_id", "to_property": "$primary_key",
        "to_visibility": "hidden"})
    open_module(page, mod)
    settled(page)
    eventually(lambda: labels(page), lambda got: got == ["Direct reports"],
               what="the hidden side gone")
