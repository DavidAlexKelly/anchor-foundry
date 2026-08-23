"""Action type statuses in the Ontology Manager (parity
`docs/parity/ontology.md` §1.3; Foundry `object-link-types` p.253-256).

§174 built the rules; this is the row they show up on. Two claims need a
browser rather than a test client.

**Delete explains itself.** p.256 refuses to delete an `active` resource, and a
disabled button with the server's own sentence in its tooltip turns a rejected
request into a control that says why. A button that vanished would teach
nothing; a button that failed would teach it too late.

**And the refusal that is not about the action at all.** Deleting an *object
type* is refused while an `active` action hangs off it, because the cascade
would otherwise delete that action without ever demoting it. That refusal
arrives on a different screen from the thing causing it, which is exactly the
kind of message worth reading once in a real browser.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

ROWS = [
    {"id": "R1", "name": "Ada", "state": "open"},
    {"id": "R2", "name": "Grace", "state": "closed"},
]


@pytest.fixture(scope="module")
def module(api):
    things = Module(api, "ActionStatuses")
    things.object_type(
        columns=["id", "name", "state"], rows=ROWS, key="id", title="name",
    )
    return things


@pytest.fixture
def action(api, module):
    """A fresh action per test, so a status change cannot leak sideways."""
    return api.call(
        "POST", f"/workspaces/{module.workspace_id}/action-types",
        {
            "object_type_id": module.object_type_id,
            "api_name": f"close_{uuid.uuid4().hex[:6]}",
            "display_name": "Close it",
            "editable_properties": ["state"],
        },
    )


def open_objects(page, module) -> None:
    """Open the project's Objects page and wait for the Actions section.

    **`exact=True`, and it is load-bearing.** `get_by_role(name=…)` matches by
    case-insensitive *substring*, and this file's fixture names its project
    "ActionStatuses …" — whose first seven letters are "actions". So the page
    carries two matching headings, its own `<h2>Actions</h2>` and the project
    name, and the locator is a strict-mode violation the moment both have
    rendered. It passed for as long as the assertion happened to resolve before
    the project name arrived.

    Third time for this exact shape (§186 twice, here once), and the tell is
    always the same: a failure that says "resolved to 2 elements" rather than
    "not found".
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(
        page.get_by_role("heading", name="Actions", exact=True)
    ).to_be_visible(timeout=30000)


def action_row(page, action):
    row = page.locator("tbody tr").filter(has_text=action["api_name"]).first
    expect(row).to_be_visible(timeout=30000)
    return row


def test_a_status_can_be_set_from_the_row(page, module, action, api) -> None:
    """p.256's dropdown. Read back through the API so this is a claim about
    what was stored, not about what the select is showing."""
    open_objects(page, module)
    with page.expect_response(
        lambda r: "/action-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        action_row(page, action).get_by_test_id(
            f"action-status-{action['api_name']}"
        ).select_option("active")
    assert saved.value.ok, saved.value.text()

    after = api.call(
        "GET", f"/workspaces/{module.workspace_id}/action-types/{action['id']}"
    )
    assert after["status"] == "active", after

    # And it is *visible* on the row, not only stored. p.253 says statuses
    # exist so somebody reading the ontology knows what is relied on, which
    # is a claim about the listing rather than about the database. The badge
    # deliberately draws nothing for `experimental` (§171), so this can only
    # be asserted once the status is something else.
    open_objects(page, module)
    expect(
        action_row(page, action).get_by_test_id("status-badge-active")
    ).to_be_visible(timeout=15000)


def test_promoted_is_not_offered(page, module, action) -> None:
    """p.255 names action types among the kinds `promoted` does not apply to,
    so offering it would be offering a save that fails."""
    open_objects(page, module)
    options = action_row(page, action).get_by_test_id(
        f"action-status-{action['api_name']}"
    ).locator("option")
    expect(options).to_have_count(4)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Promoted" not in labels, labels


def test_delete_says_why_it_is_unavailable(page, module, action, api) -> None:
    """p.256 refuses this on the server; the tooltip is the server's own
    words, so somebody who reads it and somebody who reaches the refusal are
    not told two different things."""
    api.call(
        "PATCH", f"/workspaces/{module.workspace_id}/action-types/{action['id']}",
        {"status": "active"},
    )
    open_objects(page, module)

    delete = action_row(page, action).get_by_role("button", name="Delete")
    expect(delete).to_be_disabled()
    assert "mark it deprecated" in (delete.get_attribute("title") or "")


def test_an_active_action_blocks_deleting_its_object_type(
    page, module, action, api
) -> None:
    """**The refusal that arrives on somebody else's screen.**

    `action_types.object_type_id` cascades (db 0013), so deleting the object
    type would delete this action whatever its status - p.256's protection
    bypassed without ever demoting the thing p.256 protects. The object type
    here is `experimental`, so it is deletable on its own terms; the only thing
    in the way is what the delete would take with it.
    """
    api.call(
        "PATCH", f"/workspaces/{module.workspace_id}/action-types/{action['id']}",
        {"status": "active"},
    )

    refused = None
    try:
        api.call(
            "DELETE",
            f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
        )
    except Exception as exc:  # ApiError carries the body
        refused = str(exc)
    assert refused is not None, "the object type was deleted with an active action on it"
    assert action["api_name"] in refused, refused

    # And the ontology is intact: the object type and its action both still
    # there, which is the half a "refused" status code does not prove.
    open_objects(page, module)
    expect(action_row(page, action)).to_be_visible()
