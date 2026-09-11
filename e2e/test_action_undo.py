"""p.154's Undo, in the success message (§319; `action-types` p.154-156).

    "You can revert an action by selecting Undo in the success message after
     any successful action application." (p.154)

    "The toast below is your only opportunity to revert the action." (p.155)

The refusals are decided by a pure function (`apps/api/tests/test_action_revert.py`)
and the writing is checked end to end against a real dataset
(`apps/api/tests/test_action_undo.py`, including that the undo survives a
re-sync). Neither can check the thing p.154 actually describes, which is a
claim about **where the button is**: the form that applied the action has
closed by the time anybody wants to take it back, so the undo has to outlive
it, and only a browser can show that it does.

The second claim here is p.155's, and it is the one that is easy to build
wrongly and impossible to notice: when the undo is *not* available, the toast
has to say so. A screen that silently omits the button is telling somebody
nothing at the one moment they could have acted — and two of the six reasons
are things they can do something about.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def tickets(api):
    """A type with two rows, and an action that edits one property of it.

    Two rows because one test edits the second one to take the first's undo
    away — p.156's rule is about *an object*, and a fixture with one row could
    not tell "this object was edited" from "anything was edited".
    """
    mod = Module(api, "Undo tickets")
    type_id = mod.object_type(
        columns=["ticket_id", "status"],
        rows=[{"ticket_id": "1", "status": "open"},
              {"ticket_id": "2", "status": "open"}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"set_status_{uuid.uuid4().hex[:8]}",
         "display_name": "Set status", "editable_properties": ["status"]},
    )
    mod.action_id = action["id"]
    return mod


def open_objects(page, module) -> None:
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}"
        f"/objects/{module.object_type_id}"
    )
    expect(page.get_by_role("table")).to_be_visible(timeout=30000)


def row_for(page, ticket: str):
    """The row for one ticket, matched on **an exact cell**.

    `filter(has_text="1")` matches the other row too — its `updated_at` cell
    reads "9/11/2026, 11:00:55", which contains a 1. A substring match against
    a table containing timestamps is a locator that will find the wrong row
    eventually and pass until it does.
    """
    return page.get_by_role("row").filter(
        has=page.get_by_role("cell", name=ticket, exact=True)
    )


def apply_to(page, ticket: str, status: str) -> None:
    """Run the action against one row, through the form a person would use."""
    row_for(page, ticket).get_by_role("button", name="Edit").first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=30000)
    dialog.get_by_label("status").fill(status)
    dialog.get_by_role("button", name="Save").click()
    # The dialog closing is the success, and it is **the positive wait every
    # assertion after it needs**: the toast is drawn in the same render, and an
    # absence checked before that render is an absence of something that has
    # not arrived (§318).
    expect(dialog).to_have_count(0, timeout=30000)


def test_the_success_message_offers_an_undo(page, tickets) -> None:
    """**p.154's sentence**, and the only place it can be checked.

    The form is gone by now — the toast is not inside it, and that is the
    claim.
    """
    open_objects(page, tickets)
    apply_to(page, "1", "closed")

    toast = page.get_by_test_id("undo-toast")
    expect(toast).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("undo-toast-message")).to_contain_text(
        "Set status applied"
    )
    expect(page.get_by_test_id("undo-action")).to_be_visible()


def test_pressing_undo_puts_the_value_back_on_the_row(page, tickets) -> None:
    """The whole point, on the table behind the toast.

    Asserted on the **row** rather than on the toast's own wording, because a
    toast that says "undone" over an unchanged object is exactly the failure
    this is for.
    """
    open_objects(page, tickets)
    apply_to(page, "1", "escalated")
    expect(row_for(page, "1")).to_contain_text("escalated")

    page.get_by_test_id("undo-action").click()
    expect(page.get_by_test_id("undo-toast-message")).to_contain_text(
        "Set status undone", timeout=30000
    )
    expect(row_for(page, "1")).not_to_contain_text("escalated", timeout=30000)


def test_the_undo_is_offered_once(page, tickets) -> None:
    """p.155 calls the toast "your only opportunity", so the button goes when
    it has been used — a second press would write the old values over whatever
    the first press left."""
    open_objects(page, tickets)
    apply_to(page, "2", "waiting")
    page.get_by_test_id("undo-action").click()
    expect(page.get_by_test_id("undo-toast-message")).to_contain_text(
        "undone", timeout=30000
    )
    # The message above is the positive wait; the absence below is then about
    # the product rather than about timing.
    expect(page.get_by_test_id("undo-action")).to_have_count(0)


def test_an_undo_that_is_not_available_says_why(page, tickets, api) -> None:
    """**p.155's other half**, and the reason the refusal is drawn rather than
    left as a missing button.

    Switching the toggle off is the refusal easiest to reach from a test and
    the one whose message a person can act on — but the shape is what matters:
    the toast appears, says the action was applied, and says in the same breath
    that it cannot be taken back.
    """
    api.call(
        "PATCH", f"/workspaces/{tickets.workspace_id}/action-types/{tickets.action_id}",
        {"allow_revert": False},
    )
    try:
        open_objects(page, tickets)
        apply_to(page, "2", "blocked")
        expect(page.get_by_test_id("undo-toast")).to_be_visible(timeout=30000)
        expect(page.get_by_test_id("undo-refusal")).to_contain_text("switched off")
        expect(page.get_by_test_id("undo-action")).to_have_count(0)
    finally:
        api.call(
            "PATCH",
            f"/workspaces/{tickets.workspace_id}/action-types/{tickets.action_id}",
            {"allow_revert": True},
        )


def test_the_toast_stays_until_it_is_dismissed(page, tickets) -> None:
    """**A deliberate divergence, asserted so it is a decision.**

    Foundry's toast fades, which is what makes p.156 need a section called
    "Undoing a delete action without the revert action toast" — and the two
    remediations it offers there do not exist here. A timer would leave
    somebody with no route at all, so it stays.
    """
    open_objects(page, tickets)
    apply_to(page, "1", "reopened")
    toast = page.get_by_test_id("undo-toast")
    expect(toast).to_be_visible(timeout=30000)
    page.wait_for_timeout(6000)
    expect(toast).to_be_visible()
    expect(page.get_by_test_id("undo-action")).to_be_visible()

    page.get_by_test_id("undo-toast-dismiss").click()
    expect(toast).to_have_count(0)
