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
    # p.136: "Select a property and navigate to Inline edit … select one of
    # the available action types" (§600) - the Explorer edits a column
    # through its property's own action.
    set_inline_action(api, mod, {"status": action["id"]})
    return mod


def set_inline_action(api, mod, chosen: dict) -> None:
    got = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")
    api.call("PATCH", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}", {
        "display_name": got["display_name"],
        "title_property": next((p["api_name"] for p in got["properties"]
                                if p["id"] == got.get("title_property_id")), None),
        "properties": [{"api_name": p["api_name"], "display_name": p["display_name"],
                        "data_type": p["data_type"], "visibility": p["visibility"],
                        "inline_action_type_id": chosen.get(p["api_name"])}
                       for p in got["properties"]]})


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
    # The label counts what is about to change, so this is also the check that
    # exactly one row is staged.
    expect(save).to_have_text("Save 1 object")
    save.click()
    saved = page.get_by_test_id("explorer-edit-saved")
    expect(saved).to_be_visible(timeout=30000)
    # **And the server agrees about how many.** This is the assertion that
    # catches a submission sending every visible row rather than the staged
    # ones — a mutant doing exactly that survived the first sweep, because
    # p.135 makes every parameter default to the object's existing value, so an
    # untouched row submitted with no values changes nothing and the
    # "unchanged" assertion below stays true. What it *does* change is the
    # record: a run is opened for an object nobody edited, and p.242's cap is
    # counted against rows that were never staged.
    expect(saved).to_have_text("Saved 1 object.")

    # **Read back from the server, not from the table.** The table is the thing
    # that was just typed into, so asking it what the object says is asking the
    # form to confirm itself.
    instances = api.call(
        "GET", f"/workspaces/{editable.workspace_id}"
                f"/object-types/{editable.object_type_id}/instances",
    )["items"]
    changed = next(i for i in instances if i["primary_key"] == "e1")
    assert changed["properties"]["status"] == said, changed["properties"]

    # And the row nobody touched is untouched.
    untouched = next(i for i in instances if i["primary_key"] == "e2")
    assert untouched["properties"]["status"] == "open", untouched["properties"]

    # **One run, for the one object that was edited.** The property check above
    # cannot see the difference — an untouched row submitted with no values
    # writes its existing value back — so the count of runs is what says the
    # submission carried what was staged and nothing else.
    runs = api.call(
        "GET", f"/workspaces/{editable.workspace_id}"
                f"/action-types/{editable.action_id}/runs",
    )
    latest = max(runs, key=lambda r: r["started_at"])
    same_batch = [r for r in runs if r["batch_id"] == latest["batch_id"]]
    assert len(same_batch) == 1, (
        f"one row was staged; the submission opened {len(same_batch)} runs"
    )


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
    expect(why).to_contain_text("No property of")
    expect(why).to_contain_text("inline action")
    expect(page.get_by_test_id("explorer-edit-start")).to_have_count(0)


def test_an_eligible_action_no_property_names_edits_nothing(page, api) -> None:
    """p.136 configures an inline edit per property (§600): an action that
    could back one is not an editor until a property names it."""
    mod = Module(api, "Explorer edit unnamed")
    mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "u1", "status": "open"}],
        key="ticket_id", title="ticket_id",
    )
    api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"set_{uuid.uuid4().hex[:8]}",
        "display_name": "Set status", "editable_properties": ["status"]})
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    expect(page.get_by_test_id("explorer-edit-why")).to_contain_text(
        "inline action", timeout=30000)


def test_p136_each_property_edits_through_its_own_action(page, api) -> None:
    """"You can use the same action type as an inline edit for multiple
    properties, or you can have separate action types for different
    properties" (p.136): one Save, a batch for each action."""
    mod = Module(api, "Explorer edit two actions")
    mod.object_type(
        columns=["ticket_id", "status", "priority"],
        rows=[{"ticket_id": "t1", "status": "open", "priority": "low"}],
        key="ticket_id", title="ticket_id",
    )
    made = {}
    for prop in ("status", "priority"):
        made[prop] = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
            "object_type_id": mod.object_type_id, "api_name": f"set_{prop}_{mod.tag}",
            "display_name": f"Set {prop}", "editable_properties": [prop]})["id"]
    # A parameter named otherwise than its property: the cell is the
    # property's, what is submitted is the action's parameter.
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{made['status']}/definition", {
        "parameters": [{"api_name": "new_status", "display_name": "New status",
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "status", "parameter": "new_status"}}],
        "criteria": []})
    set_inline_action(api, mod, made)
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    page.get_by_test_id("explorer-edit-start").click(timeout=30000)
    row = row_for(page, "t1")
    row.get_by_label("status").fill("closed")
    row.get_by_label("priority").fill("high")
    page.get_by_test_id("explorer-edit-save").click()
    expect(page.get_by_test_id("explorer-edit-saved")).to_have_text("Saved 1 object.")

    def stored():
        found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": mod.object_type_id, "filters": []},
                          "limit": 5})["instances"]
        return found[0]["properties"]
    eventually(stored, lambda v: (v["status"], v["priority"]) == ("closed", "high"),
               what="both properties, each through its own action")


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


def test_a_refused_batch_says_so_and_saves_nothing_after_it(page, api) -> None:
    """p.138's refusal, from one of the actions a Save submits through."""
    mod = Module(api, "Explorer edit refused")
    mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "r1", "status": "open"}],
        key="ticket_id", title="ticket_id",
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"set_{mod.tag}",
        "display_name": "Set status", "editable_properties": ["status"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
        "rules": [{"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}],
        "criteria": [{"message": "that is not a status this workspace uses", "config": {
            "left": {"kind": "parameter", "parameter": "status"},
            "operator": "is_included_in", "right": {"kind": "value", "value": ["allowed"]}}}]})
    set_inline_action(api, mod, {"status": action["id"]})
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    page.get_by_test_id("explorer-edit-start").click(timeout=30000)
    row_for(page, "r1").get_by_label("status").fill("nope")
    page.get_by_test_id("explorer-edit-save").click()
    expect(page.get_by_test_id("explorer-edit-error")).to_contain_text(
        "that is not a status this workspace uses")
    expect(page.get_by_test_id("explorer-edit-saved")).to_have_count(0)


def test_a_batch_that_fails_while_writing_is_not_reported_saved(page, api) -> None:
    """p.138: a batch that fails whole comes back as a failure, not an error -
    the key its rows are written by is gone - and Save says so rather than
    moving on to report the rest as saved."""
    import psycopg
    from conftest import ADMIN_DSN

    mod = Module(api, "Explorer edit fails")
    mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "f1", "status": "open"}],
        key="ticket_id", title="ticket_id",
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"set_{mod.tag}",
        "display_name": "Set status", "editable_properties": ["status"]})
    set_inline_action(api, mod, {"status": action["id"]})
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    page.get_by_test_id("explorer-edit-start").click(timeout=30000)
    row_for(page, "f1").get_by_label("status").fill("closed")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("UPDATE object_type_sources SET primary_key_column = 'gone'"
                   " WHERE object_type_id = %s", (mod.object_type_id,))
        try:
            page.get_by_test_id("explorer-edit-save").click()
            expect(page.get_by_test_id("explorer-edit-error")).to_be_visible()
            expect(page.get_by_test_id("explorer-edit-saved")).to_have_count(0)
        finally:
            db.execute("UPDATE object_type_sources SET primary_key_column = 'ticket_id'"
                       " WHERE object_type_id = %s", (mod.object_type_id,))
