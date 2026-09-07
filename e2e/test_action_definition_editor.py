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

import os
import uuid

import pytest
from playwright.sync_api import expect

# **Addressed by test id rather than by label** for the two object-type
# dropdowns. They are `TypePicker`s since §256, and a picker that needs a
# search draws an input labelled "Search Rule 1 object type" beside the select
# - which `get_by_label` matches too, because an accessible name matches by
# substring. The id is the unambiguous handle and the one this suite already
# uses for exactly this reason.

from api import Module
from conftest import WEB_BASE
from ontology_page import pick_type


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
    name = page.get_by_label("Parameter 1 name")
    name.fill("new_status")

    # **This assertion has failed three times in full runs (§233, §243, §244)
    # and never once in isolation, and the first diagnosis was wrong.** §243
    # read it as a save round trip exceeding Playwright's old 5s `expect`
    # default and widened the budget suite-wide; §244's call log shows the new
    # 15s budget applied and the element still absent, so that was not it.
    #
    # What the §244 snapshot did say is that **no dialog was open** — and this
    # dialog closes on success only. A closed dialog means the save was
    # *accepted*, which is a different failure from a slow one and has two
    # causes the snapshot cannot tell apart: the rename never reached the PUT,
    # or it did and the server found no module using the parameter. So the
    # test records what it sent, what came back, and what the server ended up
    # holding, and the next occurrence answers that question instead of costing
    # a fourth investigation. §240's rule — instrument rather than guess —
    # applied one guess later than that entry says it should have been.
    saves: list[str] = []

    def _record(response) -> None:
        if response.request.method == "PUT" and "/action-types/" in response.url:
            saves.append(
                f"{response.status} sent={response.request.post_data!r} "
                f"back={response.text()[:300]!r}"
            )

    page.on("response", _record)
    typed = name.input_value()
    page.get_by_role("button", name="Save", exact=True).click()

    error = page.get_by_test_id("definition-error")
    try:
        expect(error).to_contain_text("'status'")
    except AssertionError:
        raise AssertionError(
            "the refusal never appeared. "
            f"in the box before Save: {typed!r}; "
            f"dialogs open now: {page.get_by_role('dialog').count()}; "
            f"parameters the server now holds: "
            f"{[p['api_name'] for p in definition(api, mod)['parameters']]}; "
            f"the save round trips: {saves}"
        ) from None
    expect(error).to_contain_text(f"App {mod.tag}")   # the module by name
    # The dialog stays open, holding the edit, so it can be undone rather than
    # retyped.
    expect(page.get_by_role("dialog")).to_be_visible()
    assert [p["api_name"] for p in definition(api, mod)["parameters"]] == ["status"]


def test_the_editor_offers_the_rule_kinds_that_execute(page, api):
    """All seven, now that all seven run (§138, §258, §262).

    `delete_object` was held out of this list while the executor refused it -
    an editor must not let somebody save an action that fails the first time it
    is clicked - and arrived the day it ran. `notify` is the same story one
    unit later: §257 built the rule and the delivery and left it reachable only
    by posting JSON, so the list said five while the executor ran six. The list
    is asserted rather than its length, so a kind added here without an
    executor turns this red - and one the executor gained without the editor
    stays visible as the gap it is.
    """
    mod = build(api, "Action editor kinds")
    open_editor(page, mod)

    kinds = page.get_by_label("Rule 1 kind")
    options = kinds.locator("option").all_inner_texts()
    assert options == [
        "Set a property", "Create an object", "Link to an object", "Remove a link",
        "Delete an object", "Send a notification", "Call a webhook",
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

    pick_type(page, "rule-1-object-type", team)
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

    pick_type(page, "rule-1-object-type", team)
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

    pick_type(page, "rule-1-object-type", team)
    page.get_by_label("Rule 1 which object").select_option("team")
    page.get_by_test_id("rule-1-object-type").select_option("")
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
    pick_type(page, "rule-1-object-type", team)
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


# ---- the notification rule (`action-types` p.89-101; §258) ---------------------
def add_notify_rule(page) -> None:
    """A second rule, switched to `notify`. The first stays the property setter
    the action was created with, so what this file saves is still a definition
    that runs."""
    page.get_by_role("button", name="Add a rule").click()
    page.get_by_label("Rule 2 kind").select_option("notify")


def test_the_people_offered_are_not_the_membership_table(page, api):
    """**The picker's set is `effective_workspace_role`, not `workspace_members`.**

    §258's first version read the member list, and this browser is signed in as
    the organisation's owner - who is a member of nothing and can see
    everything. So the one account certain to be a valid recipient here was the
    one account the form would not offer, and a rule written through it could
    never notify the person writing it.

    Asserted against the member list rather than as a bare presence check: that
    the person *is* offered says little on its own, and that they are offered
    **while absent from the members** is the whole claim.
    """
    mod = build(api, "Action editor notify people")
    me = api.call("GET", "/auth/me")
    members = api.call("GET", f"/workspaces/{mod.workspace_id}/members")
    assert me["email"] not in {m["email"] for m in members}, (
        "this test is vacuous unless the signed-in account is a non-member; "
        f"members are {[m['email'] for m in members]}"
    )

    open_editor(page, mod)
    add_notify_rule(page)
    expect(page.get_by_label(f"Notify {me['email']}")).to_be_visible(timeout=15000)


def test_a_notification_typed_in_the_dialog_saves_and_is_delivered(page, api):
    """The round trip §258 exists for: a rule written entirely through the form
    reaches the executor and puts something in the recipient's bar.

    The recipient is the account this browser is signed in as, which is also
    the one the API call runs as - so what the form saved is checked at the far
    end of the wire rather than in the row it was written to.
    """
    mod = build(api, "Action editor notify saves")
    me = api.call("GET", "/auth/me")
    open_editor(page, mod)
    add_notify_rule(page)

    page.get_by_label(f"Notify {me['email']}").check()
    page.get_by_test_id("rule-2-subject").fill(f"Ticket touched {mod.tag}")
    # p.94's button rather than typed braces, because two braces are not a
    # reference and typing three is the mistake it exists to prevent.
    page.get_by_test_id("rule-2-body").fill("It is now ")
    page.get_by_test_id("rule-2-body-insert-status").click()
    expect(page.get_by_test_id("rule-2-body")).to_have_value("It is now {{{status}}}")

    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert [r["kind"] for r in stored["rules"]] == ["modify_object", "notify"]
    assert stored["rules"][1]["config"]["recipients"] == {
        "kind": "static", "user_ids": [me["user_id"]]
    }
    # p.96's default came from the form without anybody choosing it, and it is
    # the strict one - a blank here would be a rule that quietly sends data to
    # somebody who may not read it.
    assert stored["rules"][1]["config"]["permissions"] == "all"

    instance = api.call(
        "GET",
        f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances",
    )["items"][0]
    result = api.call(
        "POST", f"{mod.base}/actions/{mod.action['id']}/execute",
        {"instance_id": instance["id"], "values": {"status": "closed"}},
    )
    assert result["ok"], result

    page.goto(f"{WEB_BASE}/home")
    page.get_by_test_id("notification-bell").click()
    panel = page.get_by_test_id("notification-panel")
    expect(panel).to_be_visible(timeout=15000)
    # **Scoped to this run's notification**, not read off the whole panel: the
    # bar shows everything the account has ever been sent, and every other test
    # in the suite that runs a notifying action leaves one there. A body
    # assertion against the panel would eventually match a stranger's.
    # `.first` is the *outermost* div holding the subject — the notification's
    # own block. `.last` is the innermost, which is the header row carrying the
    # subject and nothing else.
    mine = panel.locator("div").filter(has_text=f"Ticket touched {mod.tag}").first
    expect(mine).to_be_visible(timeout=15000)
    # The reference the button generated, substituted with what was submitted.
    expect(mine).to_contain_text("It is now closed")


def test_the_form_names_what_is_missing_before_a_save(page, api):
    """The refusal, said where the form still is.

    The server refuses this too - a notify rule with no recipients never
    saves - but that refusal arrives about a form somebody has already left.
    Both halves are checked: that it is said, and that filling the thing in
    takes it away, because a message that never clears is a message nobody
    reads.
    """
    mod = build(api, "Action editor notify problem")
    me = api.call("GET", "/auth/me")
    open_editor(page, mod)
    add_notify_rule(page)

    said = page.get_by_test_id("rule-2-problem")
    expect(said).to_contain_text("at least one person", timeout=15000)
    page.get_by_label(f"Notify {me['email']}").check()
    # Now the subject is what is missing, and the message moved on rather than
    # going away - p.89 needs recipients *and* content.
    expect(said).to_contain_text("subject")
    page.get_by_test_id("rule-2-subject").fill("Anything")
    expect(said).to_have_count(0)


def test_a_reference_to_a_parameter_that_is_gone_is_named_in_the_form(page, api):
    """The case a reference inserter makes easy to reach: insert
    `{{{status}}}`, then rename the parameter it points at.

    The template still holds the old name, and nothing about the text says so -
    which is why this check reads the template against the parameter list
    rather than trusting that a generated reference stays correct.
    """
    mod = build(api, "Action editor notify stale ref")
    me = api.call("GET", "/auth/me")
    open_editor(page, mod)
    add_notify_rule(page)

    page.get_by_label(f"Notify {me['email']}").check()
    page.get_by_test_id("rule-2-subject").fill("About ")
    page.get_by_test_id("rule-2-subject-insert-status").click()
    expect(page.get_by_test_id("rule-2-problem")).to_have_count(0)

    page.get_by_label("Parameter 1 name").fill("state")
    said = page.get_by_test_id("rule-2-problem")
    expect(said).to_contain_text("status", timeout=15000)
    expect(said).to_contain_text("not a parameter")


def test_unchecking_somebody_takes_them_off_the_list(page, api):
    """**Both directions, because only one of them is the default.**

    A checkbox list built by appending on change looks right the whole time
    somebody is adding people and silently keeps everybody they take off. The
    rule would still save, and would notify somebody who was explicitly
    removed - which is the one mistake a recipient list must not make.
    """
    mod = build(api, "Action editor notify uncheck")
    me = api.call("GET", "/auth/me")
    others = [
        r for r in api.call(
            "GET", f"/workspaces/{mod.workspace_id}/notification-recipients")
        if r["id"] != me["user_id"]
    ]
    assert others, "this test needs a second person in the workspace"
    other = others[0]

    open_editor(page, mod)
    add_notify_rule(page)
    page.get_by_label(f"Notify {me['email']}").check()
    page.get_by_label(f"Notify {other['email']}").check()
    page.get_by_label(f"Notify {other['email']}").uncheck()
    page.get_by_test_id("rule-2-subject").fill("Only one of them")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert stored["rules"][1]["config"]["recipients"]["user_ids"] == [me["user_id"]]


def test_an_insert_button_writes_the_reference_name_not_its_label(page, api):
    """p.101's two user references are the only place the two differ.

    A parameter's button is labelled with the parameter's own name, so a form
    that inserted the *label* would be right about every parameter and wrong
    about `Current user` - which renders as nothing and would look like a
    template that simply did not substitute.
    """
    mod = build(api, "Action editor notify user ref")
    me = api.call("GET", "/auth/me")
    open_editor(page, mod)
    add_notify_rule(page)

    page.get_by_label(f"Notify {me['email']}").check()
    page.get_by_test_id("rule-2-subject").fill("For ")
    page.get_by_test_id("rule-2-subject-insert-recipient").click()
    page.get_by_test_id("rule-2-body").fill("By ")
    page.get_by_test_id("rule-2-body-insert-current_user").click()
    expect(page.get_by_test_id("rule-2-subject")).to_have_value("For {{{recipient}}}")
    expect(page.get_by_test_id("rule-2-body")).to_have_value("By {{{current_user}}}")
    # And the form is happy with them, because p.101's two are references
    # without being parameters.
    expect(page.get_by_test_id("rule-2-problem")).to_have_count(0)


def test_changing_the_recipient_kind_forgets_the_old_ones_fields(page, api):
    """The three recipient shapes have nothing in common.

    A `parameter` left behind on a static list is a field the server refuses,
    and the refusal names something that is no longer on screen - the same
    argument the rule-kind select makes one file over. Asserted as the *whole*
    config rather than as an absent key, so a third field arriving later is
    checked by this too.
    """
    mod = build(api, "Action editor notify kind switch")
    me = api.call("GET", "/auth/me")
    open_editor(page, mod)
    add_notify_rule(page)

    page.get_by_label("Rule 2 recipient kind").select_option("parameter")
    page.get_by_label("Rule 2 recipient parameter").select_option("status")
    page.get_by_label("Rule 2 recipient kind").select_option("static")
    page.get_by_label(f"Notify {me['email']}").check()
    page.get_by_test_id("rule-2-subject").fill("Nothing left behind")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert stored["rules"][1]["config"]["recipients"] == {
        "kind": "static", "user_ids": [me["user_id"]]
    }


# ---- the webhook rule (`action-types` p.105-116; §262) --------------------------
WEBHOOK_SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "apps", "api", "tests", "webhook_fixture_server.py",
)


@pytest.fixture(scope="module")
def webhook_target():
    import socket
    import subprocess
    import sys
    import time

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    proc = subprocess.Popen(
        [sys.executable, WEBHOOK_SERVER, str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover - environment guard
        proc.terminate()
        pytest.skip("fixture server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


def make_webhook(api, mod: Module, target: str, **over) -> dict:
    connection = api.call(
        "POST", f"{mod.base}/connections",
        {"name": f"Target {uuid.uuid4().hex[:6]}", "source_type": "rest",
         "scope": "project",
         "config": {"base_url": target, "allow_insecure_http": True},
         "secret": {}},
    )
    payload = {
        "connection_id": connection["id"],
        "api_name": f"hook_{uuid.uuid4().hex[:8]}",
        "display_name": f"Modify ticket {mod.tag}",
        "method": "POST", "path": "echo",
        "inputs": [{"api_name": "priority"}],
        "body": {"priority": "{{{priority}}}"},
    }
    payload.update(over)
    return api.call("POST", f"{mod.base}/webhooks", payload)


def add_webhook_rule(page) -> None:
    page.get_by_role("button", name="Add a rule").click()
    page.get_by_label("Rule 2 kind").select_option("webhook")


def test_the_editor_offers_the_webhook_rule(page, api):
    """p.113: "select Add new rule, then select Webhook". The sixth kind, and
    the last one the executor ran without the editor offering it."""
    mod = build(api, "Action editor webhook kind")
    open_editor(page, mod)
    options = page.get_by_label("Rule 1 kind").locator("option").all_inner_texts()
    assert options[-1] == "Call a webhook"


def test_a_webhook_rule_typed_in_the_dialog_saves_and_runs(page, api, webhook_target):
    """The round trip §262 exists for, checked at the far end of the wire.

    The fixture's `/echo` answers with what it received, so this asserts the
    *request* the executor made — a rule that saved correctly and mapped its
    input wrongly would pass a check that only read the definition back.
    """
    mod = build(api, "Action editor webhook runs")
    hook = make_webhook(api, mod, webhook_target)
    open_editor(page, mod)
    add_webhook_rule(page)

    page.get_by_test_id("rule-2-webhook").select_option(hook["id"])
    # The default mode is p.114's, and it is the one that cannot break an
    # action — so it is asserted rather than chosen.
    expect(page.get_by_test_id("rule-2-webhook-mode")).to_have_value("side_effect")
    page.get_by_label("Rule 2 priority parameter").select_option("status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert [r["kind"] for r in stored["rules"]] == ["modify_object", "webhook"]
    assert stored["rules"][1]["config"] == {
        "webhook": hook["id"], "mode": "side_effect",
        "inputs": {"priority": {"parameter": "status"}},
    }

    instance = api.call(
        "GET",
        f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances",
    )["items"][0]
    result = api.call(
        "POST", f"{mod.base}/actions/{mod.action['id']}/execute",
        {"instance_id": instance["id"], "values": {"status": "closed"}},
    )
    assert result["ok"], result
    runs = api.call("GET", f"{mod.base}/webhooks/{hook['id']}/runs")["items"]
    assert runs and runs[0]["request_body"]["body"] == {"priority": "closed"}


def test_a_required_input_with_no_source_is_named_before_a_save(page, api, webhook_target):
    """p.107: "you must populate all of its required input parameters."

    Said where the form still is, and the message names the *input* — the
    server's refusal names it too, but arrives about a form somebody has left.
    """
    mod = build(api, "Action editor webhook input")
    hook = make_webhook(api, mod, webhook_target)
    open_editor(page, mod)
    add_webhook_rule(page)

    page.get_by_test_id("rule-2-webhook").select_option(hook["id"])
    said = page.get_by_test_id("rule-2-webhook-problem")
    expect(said).to_contain_text("priority")
    page.get_by_label("Rule 2 priority parameter").select_option("status")
    expect(said).to_have_count(0)


def test_a_static_value_is_offered_beside_a_parameter(page, api, webhook_target):
    """p.107's other source: "a static value". Its own check because a form
    that only offered parameters would look complete."""
    mod = build(api, "Action editor webhook static")
    hook = make_webhook(api, mod, webhook_target)
    open_editor(page, mod)
    add_webhook_rule(page)

    page.get_by_test_id("rule-2-webhook").select_option(hook["id"])
    page.get_by_label("Rule 2 priority source").select_option("value")
    page.get_by_label("Rule 2 priority value").fill("fixed")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    assert definition(api, mod)["rules"][1]["config"]["inputs"] == {
        "priority": {"value": "fixed"}
    }


def test_a_second_writeback_is_refused_beside_the_save_button(page, api, webhook_target):
    """p.106: "you can only configure a single webhook as a writeback".

    **Beside Save rather than on a rule**, because the rule that breaks it is
    the second one and neither is wrong on its own. Both halves: the message
    appears, and Save stops working — a refusal beside a button that still
    works is a refusal about nothing.
    """
    mod = build(api, "Action editor two writebacks")
    first = make_webhook(api, mod, webhook_target)
    second = make_webhook(api, mod, webhook_target)
    open_editor(page, mod)

    add_webhook_rule(page)
    page.get_by_test_id("rule-2-webhook").select_option(first["id"])
    page.get_by_test_id("rule-2-webhook-mode").select_option("writeback")
    page.get_by_role("button", name="Add a rule").click()
    page.get_by_label("Rule 3 kind").select_option("webhook")
    page.get_by_test_id("rule-3-webhook").select_option(second["id"])
    page.get_by_test_id("rule-3-webhook-mode").select_option("writeback")

    expect(page.get_by_test_id("definition-rules-problem")).to_contain_text(
        "only one writeback"
    )
    expect(page.get_by_role("button", name="Save", exact=True)).to_be_disabled()


def test_a_writebacks_outputs_are_offered_only_to_rules_below_it(page, api, webhook_target):
    """p.110's word is **subsequent**, and the dropdown is where that becomes
    visible rather than a refusal.

    Both directions in one test, because either alone passes against an
    implementation that offers the outputs everywhere or nowhere.
    """
    mod = build(api, "Action editor webhook outputs")
    hook = make_webhook(
        api, mod, webhook_target, method="GET", path="created", body=None,
        inputs=[], outputs=[{"api_name": "unique_id", "path": "results.unique_id"}],
    )
    open_editor(page, mod)
    add_webhook_rule(page)
    page.get_by_test_id("rule-2-webhook").select_option(hook["id"])
    page.get_by_test_id("rule-2-webhook-mode").select_option("writeback")

    # Rule 1 is above it, so its parameter picker must not offer the output.
    above = page.get_by_label("Rule 1 parameter").locator("option").all_inner_texts()
    assert "webhook.unique_id" not in above

    # A third rule below it must.
    page.get_by_role("button", name="Add a rule").click()
    below = page.get_by_label("Rule 3 parameter").locator("option").all_inner_texts()
    assert "webhook.unique_id" in below


def test_changing_the_webhook_forgets_the_old_ones_inputs(page, api, webhook_target):
    """Inputs are keyed by the *previous* webhook's input names.

    A leftover key is a field the server refuses for a reason nobody could see
    on screen — the same argument the rule-kind select makes, and the same one
    §258 made for the notify rule's recipient kinds. Asserted as the whole
    inputs map rather than as an absent key, so a third field arriving later is
    checked by this too.
    """
    mod = build(api, "Action editor webhook reselect")
    first = make_webhook(api, mod, webhook_target)
    second = make_webhook(
        api, mod, webhook_target,
        inputs=[{"api_name": "note"}], body={"note": "{{{note}}}"},
    )
    open_editor(page, mod)
    add_webhook_rule(page)

    page.get_by_test_id("rule-2-webhook").select_option(first["id"])
    page.get_by_label("Rule 2 priority parameter").select_option("status")
    page.get_by_test_id("rule-2-webhook").select_option(second["id"])
    page.get_by_label("Rule 2 note parameter").select_option("status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    assert definition(api, mod)["rules"][1]["config"]["inputs"] == {
        "note": {"parameter": "status"}
    }


def test_switching_an_inputs_source_forgets_the_other_one(page, api, webhook_target):
    """An input holding both a parameter and a fixed value is refused by the
    server and by the form.

    The path that produces one is *switching*, which no other check here walks:
    fill one in, change your mind, fill the other in. A version that merged
    rather than replaced would look right the whole time and save something
    neither the form nor the server accepts.
    """
    mod = build(api, "Action editor webhook switch")
    hook = make_webhook(api, mod, webhook_target)
    open_editor(page, mod)
    add_webhook_rule(page)

    page.get_by_test_id("rule-2-webhook").select_option(hook["id"])
    page.get_by_label("Rule 2 priority parameter").select_option("status")
    page.get_by_label("Rule 2 priority source").select_option("value")

    # **Saved without typing into the new box**, and that is the whole test.
    # The first version filled it in, and `setInput` *replaces* the source — so
    # the leftover `parameter` was overwritten a moment later and the mutant
    # survived a check that walked the exact path it breaks. The state right
    # after the switch is the only place the difference exists.
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    assert definition(api, mod)["rules"][1]["config"]["inputs"] == {
        "priority": {"value": ""}
    }
