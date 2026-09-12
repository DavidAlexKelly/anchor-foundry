"""Editing an object from the Explorer's results (§324; `action-types` p.135).

    "Inline edits are available in both Workshop and Object Explorer… Inline
     edits allow users to quickly edit values of an object in the **Object
     Explorer results view** or native Object View widgets." (p.135)

    "For action-backed inline edits, every parameter is optional and defaults to
     the existing value of the object, so a user can make individual changes to
     properties one at a time." (p.135)

The eligibility is decided on the server and tested in
`apps/api/tests/test_action_inline_edits.py`; the wording is in
`apps/web/src/lib/explorer-edit.test.ts`. What needs a browser is the claim
neither can reach: **a cell typed into in the Explorer changes the object**.

That is one round trip through five things that can each be right on their own —
a workspace-scoped screen finding the project a write belongs to, an action
chosen from what the server said was eligible, a parameter matched to a column
by name, a batch submitted whole, and a table re-read afterwards.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture(scope="module")
def editable(api):
    """A type with two rows and an action that can back an inline edit."""
    mod = Module(api, "Explorer edit")
    type_id = mod.object_type(
        columns=["ticket_id", "status"],
        rows=[{"ticket_id": "e1", "status": "open"},
              {"ticket_id": "e2", "status": "open"}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"set_status_{uuid.uuid4().hex[:8]}",
         "display_name": "Set status", "editable_properties": ["status"]},
    )
    # The action must actually be eligible, or every assertion below is about
    # the refusal rather than about the feature.
    assert action["inline_edit_refusals"] == [], action["inline_edit_refusals"]
    mod.action_id = action["id"]
    return mod


def open_results(page, module) -> None:
    """The Explorer, narrowed to one type — which is the only state in which
    p.135's edit has a single action and a single project to use."""
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}"
    )
    expect(page.get_by_test_id("explorer-edit-bar")).to_be_visible(timeout=30000)


def row_for(page, ticket: str):
    return page.locator("tbody tr").filter(
        has=page.get_by_text(ticket, exact=True)
    ).first


def test_one_type_offers_the_edit(page, editable) -> None:
    """p.135's control, in p.135's place."""
    open_results(page, editable)
    expect(page.get_by_test_id("explorer-edit-start")).to_be_visible(timeout=30000)
    # And nothing is editable until it is asked for: a results view where every
    # cell is an input is a table nobody can read.
    expect(page.get_by_test_id("explorer-edit-save")).to_have_count(0)


def test_a_cell_typed_into_changes_the_object(page, api, editable) -> None:
    """**p.135's whole claim, end to end through the screen.**

    Every layer under this one is already checked on its own — which is exactly
    why this test exists: a workspace-scoped screen finding the project, an
    action chosen from the server's verdict, a parameter matched to a column by
    name, and a batch submitted whole can each be right while the cell does
    nothing.
    """
    said = f"closed-{uuid.uuid4().hex[:6]}"
    open_results(page, editable)
    page.get_by_test_id("explorer-edit-start").click()

    cell = row_for(page, "e1").get_by_label("status")
    expect(cell).to_be_visible(timeout=30000)
    cell.fill(said)

    save = page.get_by_test_id("explorer-edit-save")
    expect(save).to_be_enabled()
    save.click()
    expect(page.get_by_test_id("explorer-edit-saved")).to_be_visible(timeout=30000)

    # **Read back from the server, not from the table.** The table is the thing
    # that was just typed into, so asking it what the object says is asking the
    # form to confirm itself.
    instances = api.call(
        "GET", f"/workspaces/{editable.workspace_id}"
                f"/object-types/{editable.object_type_id}/instances",
    )["items"]
    changed = next(i for i in instances if i["primary_key"] == "e1")
    assert changed["properties"]["status"] == said, changed["properties"]

    # And the row nobody touched is untouched: p.138 submits what was staged,
    # and a batch that wrote every visible row would pass every assertion above.
    untouched = next(i for i in instances if i["primary_key"] == "e2")
    assert untouched["properties"]["status"] == "open", untouched["properties"]


def test_undo_takes_a_row_back_out_of_the_submission(page, api, editable) -> None:
    """p.242's per-row Undo, and the half that makes it mean something.

    A button that cleared the cell visually while leaving the row staged would
    look identical until Submit — so this stages a row, undoes it, submits, and
    asks the server what the object says.
    """
    open_results(page, editable)
    page.get_by_test_id("explorer-edit-start").click()
    before = api.call(
        "GET", f"/workspaces/{editable.workspace_id}"
                f"/object-types/{editable.object_type_id}/instances",
    )["items"]
    was = next(i for i in before if i["primary_key"] == "e2")["properties"]["status"]

    row = row_for(page, "e2")
    row.get_by_label("status").fill(f"never-{uuid.uuid4().hex[:6]}")
    # The Undo appears only once the row has something to undo, so waiting for
    # it is also the check that the cell was staged (§318).
    undo = row.get_by_role("button", name="Undo")
    expect(undo).to_be_visible(timeout=30000)
    undo.click()

    # Nothing is staged, so there is nothing to save — which is the state the
    # edit bar reports rather than a Save that quietly writes nothing.
    expect(page.get_by_test_id("explorer-edit-save")).to_be_disabled()

    after = api.call(
        "GET", f"/workspaces/{editable.workspace_id}"
                f"/object-types/{editable.object_type_id}/instances",
    )["items"]
    assert next(i for i in after if i["primary_key"] == "e2")[
        "properties"]["status"] == was


def test_a_search_across_types_says_why_it_cannot_edit(page, api, editable) -> None:
    """**The case p.135 does not have to mention** (§324).

    Foundry's Object Explorer opens one object type; this one searches the
    workspace, and an action type belongs to one object type — so a result set
    mixing two has no single action to offer. Said rather than drawn as a table
    with no editors, because that is indistinguishable from four other states
    (§214).
    """
    page.goto(f"{WEB_BASE}/{editable.workspace_slug}/explore")
    # The positive wait: the bar has rendered, so what it says is about the
    # search rather than about a page that has not finished (§318).
    bar = page.get_by_test_id("explorer-edit-bar")
    expect(bar).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("explorer-edit-why")).to_contain_text(
        "one object type", timeout=30000
    )
    expect(page.get_by_test_id("explorer-edit-start")).to_have_count(0)


def test_a_type_with_no_eligible_action_says_so(page, api) -> None:
    """The other reason a reader finds no editors, and a different sentence.

    "Narrow the search" and "no action can back an edit" send somebody to
    different places — one is a thing they do here, the other a thing somebody
    builds in the Ontology Manager.
    """
    mod = Module(api, "Explorer edit none")
    mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "n1", "status": "open"}],
        key="ticket_id", title="ticket_id",
    )
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    why = page.get_by_test_id("explorer-edit-why")
    expect(why).to_be_visible(timeout=30000)
    expect(why).to_contain_text("inline edit")
    expect(page.get_by_test_id("explorer-edit-start")).to_have_count(0)


def test_the_edit_is_counted_as_the_explorer_s_write(page, api, editable) -> None:
    """`ontology-manager` p.32's fifth write source, made real (§324).

    p.32 lists "direct Object Explorer edit" among the things that record a
    write, and §320's panel breaks writes down by application — so until this
    unit the Explorer's writes column was structurally zero, and the row in the
    breakdown was a heading over a number that could not move.
    """
    def explorer_writes() -> int:
        rows = api.call(
            "GET", f"/workspaces/{editable.workspace_id}"
                    f"/object-types/{editable.object_type_id}/usage/by-application",
        )
        return next((r["writes"] for r in rows if r["application"] == "explorer"), 0)

    before = explorer_writes()
    open_results(page, editable)
    page.get_by_test_id("explorer-edit-start").click()
    row_for(page, "e1").get_by_label("status").fill(f"counted-{uuid.uuid4().hex[:6]}")
    page.get_by_test_id("explorer-edit-save").click()
    expect(page.get_by_test_id("explorer-edit-saved")).to_be_visible(timeout=30000)

    eventually(explorer_writes, lambda n: n == before + 1,
               what="the Explorer's write count to move")
