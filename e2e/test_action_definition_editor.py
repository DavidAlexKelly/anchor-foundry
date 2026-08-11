"""Editing an action's parameters, rules and criteria (decision 0007; p.25, p.49–56).

The last piece of decision 0007 a person could not reach. The model (§127), the
criteria (§128) and the API (§129) all landed first, so until this dialog
existed the only way to declare a hidden parameter or a submission criterion
was a `psql` prompt.

Two things are worth a browser here, and they are the two the API tests cannot
see: that the dialog **round-trips** a definition through the same PUT the API
tests exercise, and that the refusal which names a Workshop module **reaches
the person editing** rather than disappearing into a rejected promise.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def build(api, name: str) -> Module:
    """An object type with an action over it, and nothing else."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status"],
        rows=[{"ticket_id": "1", "status": "open"}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"close_{uuid.uuid4().hex[:8]}",
            "display_name": "Close ticket",
            "editable_properties": ["status"],
        },
    )
    mod.type_id = type_id
    mod.action = action
    return mod


def definition(api, mod: Module) -> dict:
    return api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )


def open_editor(page, mod: Module) -> None:
    """Open the dialog for *this* action.

    **By api_name, never by display name.** The Actions table is workspace-wide
    and the dev database has carried "Close ticket" since August: matching on it
    picked a stranger's action from a previous session, and the first version of
    these tests was quietly editing that instead - one of them then failed with
    a refusal naming a Workshop module nobody in this file had created. The same
    trap §122 hit by clicking the first row of 2,219 accumulated objects.
    """
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_the_dialog_saves_a_hidden_parameter_and_a_criterion(page, api):
    """The round trip. Both of these were database-only until now, and both are
    what the rest of decision 0007 was built for."""
    mod = build(api, "Action editor")
    open_editor(page, mod)

    page.get_by_label("Parameter 1 hidden").check()
    page.get_by_role("button", name="Add a criterion").click()
    page.get_by_label("Criterion 1 message").fill("A status is required.")
    page.get_by_label("Criterion 1 parameter").select_option("status")

    # **Typed, then cleared**, and not for the sake of it: p.55's "no value" is
    # a different question from "equals the empty string" - it asks whether the
    # left side is empty, and it is the only way to say "must be filled in".
    # Leaving the box untouched would never run the handler that decides which
    # of the two gets stored, and a mutation that stored `{"value": ""}`
    # instead passed the first version of this test.
    value = page.get_by_label("Criterion 1 value")
    value.fill("closed")
    value.fill("")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert [p["hidden"] for p in stored["parameters"]] == [True]
    assert [c["message"] for c in stored["criteria"]] == ["A status is required."]
    assert stored["criteria"][0]["config"]["right"] == {"kind": "none"}
    # And the rule is untouched, because a save is the whole document and the
    # dialog sent back what it was given.
    assert [r["config"]["property"] for r in stored["rules"]] == ["status"]


def test_a_rename_a_module_depends_on_is_refused_in_the_dialog(page, api):
    """§129's refusal, seen by the person who caused it.

    The server names the parameter *and* the module. A dialog that swallowed
    that would leave somebody with a Save button that does nothing and no way
    to find out why - which is the whole reason the refusal carries names.
    """
    mod = build(api, "Action editor refusal")
    mod.define({
        "format": 2,
        "layout": {"ROOT": {"type": {"resolvedName": "CanvasContainer"}, "isCanvas": True,
                            "props": {}, "nodes": ["btn"], "linkedNodes": {}},
                   "btn": {"type": {"resolvedName": "CanvasButton"}, "props": {"label": "Close"},
                           "parent": "ROOT", "nodes": [], "linkedNodes": {}}},
        "variables": {"v_row": {"id": "v_row", "kind": "single_object", "label": "Row"}},
        "events": {"e1": {"id": "e1", "trigger": {"node": "btn", "on": "click"},
                          "effects": [{"type": "run_action",
                                       "config": {"action": mod.action["id"],
                                                  "subject": "v_row",
                                                  "values": {"status": "closed"}}}]}},
    })

    open_editor(page, mod)
    page.get_by_label("Parameter 1 name").fill("new_status")
    page.get_by_role("button", name="Save", exact=True).click()

    error = page.get_by_test_id("definition-error")
    expect(error).to_contain_text("'status'")
    expect(error).to_contain_text(f"App {mod.tag}")   # the module by name
    # The dialog stays open, holding the edit, so it can be undone rather than
    # retyped.
    expect(page.get_by_role("dialog")).to_be_visible()
    assert [p["api_name"] for p in definition(api, mod)["parameters"]] == ["status"]


def test_the_editor_offers_the_rule_kinds_that_execute(page, api):
    """All five, now that all five run (§138).

    `delete_object` was held out of this list while the executor refused it -
    an editor must not let somebody save an action that fails the first time it
    is clicked - and arrived the day it ran. The list is asserted rather than
    its length, so a kind added here without an executor turns this red.
    """
    mod = build(api, "Action editor kinds")
    open_editor(page, mod)

    kinds = page.get_by_label("Rule 1 kind")
    options = kinds.locator("option").all_inner_texts()
    assert options == [
        "Set a property", "Create an object", "Link to an object", "Remove a link",
        "Delete an object",
    ]


def test_switching_a_rule_to_create_asks_for_a_primary_key(page, api):
    """The field that only a create needs, and the one my first design left
    out: an object's identity lives in a dataset column, which is frequently
    mapped to no property at all."""
    mod = build(api, "Action editor create")
    open_editor(page, mod)

    page.get_by_label("Rule 1 kind").select_option("create_object")
    expect(page.get_by_label("Rule 1 primary key")).to_be_visible()
    # And the modify-only fields are gone rather than left showing a stale
    # value the server would refuse for a reason nobody could see.
    expect(page.get_by_label("Rule 1 property")).to_have_count(0)


def test_a_create_rule_typed_in_the_dialog_saves_and_runs(page, api):
    """The round trip: what the dialog writes is what the executor reads."""
    mod = build(api, "Action editor create runs")
    open_editor(page, mod)

    page.get_by_role("button", name="Add a parameter").click()
    page.get_by_label("Parameter 2 name").fill("new_key")
    page.get_by_label("Parameter 2 label").fill("New ticket id")

    page.get_by_label("Rule 1 kind").select_option("create_object")
    page.get_by_label("Rule 1 primary key").select_option("new_key")
    page.get_by_label("Rule 1 creates property").select_option("status")
    page.get_by_label("Rule 1 creates from").select_option("status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert [r["kind"] for r in stored["rules"]] == ["create_object"]
    assert stored["rules"][0]["config"] == {
        "primary_key": "new_key", "properties": {"status": "status"}
    }


def second_type(api, mod: Module) -> dict:
    """Another object type in the same workspace, with its own property.

    No dataset: this file is about what the dialog can *say*, and saving a
    definition never needs one - only running it does, which the API suite
    covers. A type with a property the ticket type does not have is what makes
    "checked against the type it changes" observable.
    """
    return api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"team_{uuid.uuid4().hex[:8]}",
            "display_name": f"Team {mod.tag}",
            "properties": [{"api_name": "code", "display_name": "Code", "data_type": "string"}],
        },
    )


def test_a_rule_can_be_pointed_at_an_object_a_parameter_names(page, api):
    """§139–§142 gave the editing endpoint three ways to name a second object
    and gave the dialog none of them. This is the round trip for the first:
    pick the type, pick the parameter that holds the object, pick a property of
    **that** type - which is not a property of the action's own.
    """
    mod = build(api, "Action editor far object")
    team = second_type(api, mod)
    open_editor(page, mod)

    page.get_by_role("button", name="Add a parameter").click()
    page.get_by_label("Parameter 2 name").fill("team")
    page.get_by_label("Parameter 2 label").fill("Team")
    page.get_by_label("Parameter 2 type").select_option("object")

    page.get_by_label("Rule 1 object type").select_option(team["id"])
    page.get_by_label("Rule 1 which object").select_option("team")
    # `code` belongs to the Team type. Offering it at all is the point: before
    # this the dropdown could only ever list the action's own type's.
    page.get_by_label("Rule 1 property").select_option("code")
    page.get_by_label("Rule 1 parameter").select_option("status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert stored["rules"][0]["config"] == {
        "object_type": team["id"], "object": "team",
        "property": "code", "parameter": "status",
    }
    # And the far object's property is not one of *this* action's editable
    # properties - it belongs to a different row.
    assert stored["editable_properties"] == []


def test_only_object_parameters_are_offered_as_the_object_to_change(page, api):
    """p.25's `object` type is what holds an instance. A string parameter would
    carry a primary key, which is not what the executor looks one up by, so
    offering it would be offering a definition that fails on the first click."""
    mod = build(api, "Action editor object params")
    team = second_type(api, mod)
    open_editor(page, mod)

    page.get_by_role("button", name="Add a parameter").click()
    page.get_by_label("Parameter 2 name").fill("team")
    page.get_by_label("Parameter 2 label").fill("Team")
    page.get_by_label("Parameter 2 type").select_option("object")

    page.get_by_label("Rule 1 object type").select_option(team["id"])
    options = page.get_by_label("Rule 1 which object").locator("option").all_inner_texts()
    # `status`, the string parameter this action was created with, is not here.
    assert options == ["Choose…", "team"]


def test_pointing_a_rule_back_at_this_object_forgets_what_it_named(page, api):
    """Both fields move together. An `object_type` left behind with no `object`
    names a *set*, which the server refuses; an `object` left behind would keep
    writing somewhere else while the dialog says "this object"."""
    mod = build(api, "Action editor retarget")
    team = second_type(api, mod)
    open_editor(page, mod)

    page.get_by_role("button", name="Add a parameter").click()
    page.get_by_label("Parameter 2 name").fill("team")
    page.get_by_label("Parameter 2 label").fill("Team")
    page.get_by_label("Parameter 2 type").select_option("object")

    page.get_by_label("Rule 1 object type").select_option(team["id"])
    page.get_by_label("Rule 1 which object").select_option("team")
    page.get_by_label("Rule 1 object type").select_option("")
    # The "which one" picker goes with it - there is nothing left to ask.
    expect(page.get_by_label("Rule 1 which object")).to_have_count(0)

    page.get_by_label("Rule 1 property").select_option("status")
    page.get_by_label("Rule 1 parameter").select_option("status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    assert definition(api, mod)["rules"][0]["config"] == {
        "property": "status", "parameter": "status"
    }


def test_a_delete_rule_can_name_an_object_too(page, api):
    """The same control on the other kind, and the hint about the subject goes
    when the rule stops meaning the subject."""
    mod = build(api, "Action editor far delete")
    team = second_type(api, mod)
    open_editor(page, mod)

    page.get_by_role("button", name="Add a parameter").click()
    page.get_by_label("Parameter 2 name").fill("team")
    page.get_by_label("Parameter 2 label").fill("Team")
    page.get_by_label("Parameter 2 type").select_option("object")

    page.get_by_label("Rule 1 kind").select_option("delete_object")
    expect(page.get_by_text("Deletes the object the action was run against")).to_be_visible()
    page.get_by_label("Rule 1 object type").select_option(team["id"])
    page.get_by_label("Rule 1 which object").select_option("team")
    expect(page.get_by_text("Deletes the object the action was run against")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert stored["rules"][0]["kind"] == "delete_object"
    assert stored["rules"][0]["config"] == {"object_type": team["id"], "object": "team"}


def test_a_link_rule_from_the_far_side_asks_which_object_to_link(page, api):
    """§142's shape, and the one place the dialog asks a different question
    depending on which end of a link this action's type is.

    From the side that holds the join property the input is *which object to
    point at*; from the other side there is no column of its own, so the input
    is *which object to link* and the value comes from this object. Offering
    `target` here would offer a field the server refuses.
    """
    mod = build(api, "Action editor far link")
    team = second_type(api, mod)
    api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/link-types",
        {
            "api_name": f"handles_{uuid.uuid4().hex[:8]}",
            "display_name": "Handles",
            "from_type_id": team["id"],
            "to_type_id": mod.type_id,
            "cardinality": "one_to_many",
            "from_property": "code",
            "to_property": "status",
        },
    )
    open_editor(page, mod)

    page.get_by_role("button", name="Add a parameter").click()
    page.get_by_label("Parameter 2 name").fill("team")
    page.get_by_label("Parameter 2 label").fill("Team")
    page.get_by_label("Parameter 2 type").select_option("object")

    page.get_by_label("Rule 1 kind").select_option("create_link")
    # The link is offered at all, which it was not before §142: its from side
    # is the Team type, not this action's.
    page.get_by_label("Rule 1 link").select_option(label="Handles → Seed " + mod.tag)
    expect(page.get_by_label("Rule 1 link object")).to_be_visible()
    expect(page.get_by_label("Rule 1 target")).to_have_count(0)
    page.get_by_label("Rule 1 link object").select_option("team")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert stored["rules"][0]["kind"] == "create_link"
    assert set(stored["rules"][0]["config"]) == {"link_type", "object"}
    assert stored["rules"][0]["config"]["object"] == "team"
