"""p.7's Overview tab: renaming an action (§345; `action-types` p.7).

    "Enter a Display name for your action type." (p.7)

    "You can now see the full detailed view of your action type. You can make
     additional adjustments, like adding a Description in the Overview tab."
     (p.7)

**The gap §344 found, from the screen's side.** The creation wizard set an
action's name and description and *nothing* changed them afterwards — so an
ontology import could rename an action and a person could not, and an import
that renamed one reported the action as updated while the name stayed as it
was.

The wording and the "what would this send" arithmetic are in
`apps/web/src/lib/action-overview.test.ts`. What needs a browser is the join:
the dialog opens on the row it was pressed from, the save reaches the server,
and the listing everybody reads shows the new name afterwards.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

ROWS = [{"id": "R1", "name": "Ada", "state": "open"}]


@pytest.fixture(scope="module")
def module(api):
    things = Module(api, "Overviews")
    things.object_type(
        columns=["id", "name", "state"], rows=ROWS, key="id", title="name",
    )
    return things


@pytest.fixture
def action(api, module):
    """A fresh action per test, because every test here renames one."""
    return api.call(
        "POST", f"/workspaces/{module.workspace_id}/action-types",
        {
            "object_type_id": module.object_type_id,
            "api_name": f"named_{uuid.uuid4().hex[:6]}",
            "display_name": "Before the rename",
            "description": "The old description",
            "editable_properties": ["state"],
        },
    )


def open_objects(page, module) -> None:
    """`exact=True` for the reason `test_action_statuses` writes down: the
    project name and the section heading both match "Actions" by substring."""
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(
        page.get_by_role("heading", name="Actions", exact=True)
    ).to_be_visible(timeout=30000)


def action_row(page, action):
    row = page.locator("tbody tr").filter(has_text=action["api_name"]).first
    expect(row).to_be_visible(timeout=30000)
    return row


def open_overview(page, module, action):
    open_objects(page, module)
    action_row(page, action).get_by_test_id(
        f"action-overview-{action['api_name']}"
    ).click()
    expect(page.get_by_test_id("action-overview-name")).to_be_visible(
        timeout=15000)


def test_a_rename_reaches_the_ontology_and_the_listing(
    page, module, action, api
) -> None:
    """p.7's loop, end to end: open the Overview, change the name, save, and
    find it changed — in the ontology *and* on the row everybody reads.

    Both, because they fail differently: a save that never reached the server
    leaves the listing right until a reload, and a listing that never refreshed
    leaves the ontology right and the screen lying.
    """
    open_overview(page, module, action)
    page.get_by_test_id("action-overview-name").fill("After the rename")
    page.get_by_test_id("action-overview-description").fill("What it is for")
    with page.expect_response(
        lambda r: "/action-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.get_by_test_id("action-overview-save").click()
    assert saved.value.ok, saved.value.text()

    after = api.call(
        "GET", f"/workspaces/{module.workspace_id}/action-types/{action['id']}"
    )
    assert after["display_name"] == "After the rename", after
    assert after["description"] == "What it is for", after
    # And the api_name is untouched, which is what makes this a rename rather
    # than a different action: every saved module and every ontology file names
    # it by that.
    assert after["api_name"] == action["api_name"], after

    expect(action_row(page, action)).to_contain_text(
        "After the rename", timeout=15000)


def test_save_is_unpressable_until_something_changes(
    page, module, action
) -> None:
    """**A Save that would send an empty body is a button that does nothing.**

    And one that wrote back an untouched name would put an
    `action_type.rename` in the audit log that never happened — the PATCH
    treats a present field as a write.
    """
    open_overview(page, module, action)
    save = page.get_by_test_id("action-overview-save")
    expect(save).to_be_disabled()
    page.get_by_test_id("action-overview-name").fill("Something else")
    expect(save).to_be_enabled()
    # And back again: whitespace is not a change, because the server trims
    # before storing.
    page.get_by_test_id("action-overview-name").fill("  Before the rename  ")
    expect(save).to_be_disabled()


def test_a_name_the_server_would_refuse_is_refused_here_first(
    page, module, action
) -> None:
    """db 0013 checks `length(display_name) BETWEEN 1 AND 200`. A Save that
    posts a name the server is certain to reject is §214's control that looks
    like it works — and the request is watched rather than only the message,
    because "the page said so" and "the page said so *instead of* asking" are
    different claims and only the second one is this test's."""
    open_overview(page, module, action)
    posted: list[str] = []
    page.on("request", lambda r: posted.append(r.url)
            if r.method == "PATCH" else None)

    page.get_by_test_id("action-overview-name").fill("   ")
    expect(page.get_by_test_id("action-overview-refusal")).to_contain_text(
        "needs a name", timeout=15000)
    expect(page.get_by_test_id("action-overview-save")).to_be_disabled()

    # §318: the negative assertion follows a positive wait on a sibling. A
    # legal name saves, which proves the listener fires at all — so "no PATCH
    # was sent" above is a fact about the network and not about timing.
    page.get_by_test_id("action-overview-name").fill("A legal name")
    with page.expect_response(
        lambda r: "/action-types/" in r.url and r.request.method == "PATCH"
    ):
        page.get_by_test_id("action-overview-save").click()
    assert len(posted) == 1, posted
