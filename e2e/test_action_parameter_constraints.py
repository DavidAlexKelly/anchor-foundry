"""What values a parameter accepts (§584; db 0119; `action-types` p.8, p.45,
p.71).

> "Select the Priority parameter to limit the values it can take on. Change
>  the constraints from User input to Multiple choice… Add P0, P1 and P2 as
>  options. If you applied your action to an object now, you could change the
>  priority of a ticket to P0, P1, or P2." (p.8)

p.8's walkthrough, in the editor and then in the form: the constraint is set
where the parameter is, the form offers exactly its options, and a length
constraint is said beside the box and refused by the server in the same words.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_module, settled
from test_action_definition_editor import build as build_editor, definition, open_editor

ROWS = [
    {"ticket_id": "1", "title": "First", "priority": "P2", "labels": "[]"},
    {"ticket_id": "2", "title": "Second", "priority": "P2", "labels": "[]"},
    {"ticket_id": "3", "title": "Third", "priority": "P2", "labels": "[]"},
]


def test_p8s_walkthrough_in_the_editor(page, api) -> None:
    mod = build_editor(api, "Constraint editor")
    open_editor(page, mod)
    panel = page.locator('[data-parameter-constraint="status"]')
    kind = panel.get_by_test_id("constraint-kind")
    # p.8's starting point is "User input".
    expect(kind).to_have_value("")
    expect(kind.locator("option").first).to_have_text("User input")
    kind.select_option("enum")
    panel.get_by_test_id("constraint-enum").fill("P0\nP1\nP2")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, mod)["parameters"]
    assert parameter["value_constraint"]["values"] == ["P0", "P1", "P2"]
    assert parameter["constraint_summary"] == "one of P0, P1, P2"
    # Reopened, it is still there: the dialog saves parameters whole, so one
    # it did not load it would overwrite with nothing.
    open_editor(page, mod)
    expect(page.locator('[data-parameter-constraint="status"]')
           .get_by_test_id("constraint-enum")).to_have_value("P0\nP1\nP2")
    page.get_by_label("Parameter 1 label").fill("Priority")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert definition(api, mod)["parameters"][0]["value_constraint"] is not None
    # A change of type drops it, since P0-P2 mean nothing to a date.
    open_editor(page, mod)
    page.get_by_label("Parameter 1 type").select_option("date")
    expect(page.locator('[data-parameter-constraint="status"]')
           .get_by_test_id("constraint-kind")).to_have_value("")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert definition(api, mod)["parameters"][0]["value_constraint"] is None


def test_an_override_can_constrain_it_instead(page, api) -> None:
    """p.45: "An override can change the configuration of the parameter's
    constraints"."""
    mod = build_editor(api, "Constraint override")
    open_editor(page, mod)
    page.get_by_label("Add an override to status").click()
    page.get_by_label("status override 1 parameter").select_option(label="the current user")
    page.get_by_label("status override 1 value").fill("someone")
    page.get_by_label("status override 1 constraint", exact=True).select_option("set")
    block = page.locator('[data-override-constraint="0"]')
    block.get_by_test_id("constraint-kind").select_option("range")
    block.get_by_test_id("constraint-max").fill("4")
    expect(page.get_by_test_id("override-summary")).to_contain_text("change its constraint")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, mod)["parameters"]
    assert parameter["overrides"][0]["set_constraint"] == {"kind": "range", "maximum": 4}


@pytest.fixture(scope="module")
def tickets(api):
    mod = Module(api, "Constraint tickets")
    mod.type_id = mod.object_type(
        columns=["ticket_id", "title", "priority", "labels"], rows=ROWS, key="ticket_id",
        title="ticket_id", types={"labels": "array"}, array_of={"labels": "string"})
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"triage_{uuid.uuid4().hex[:8]}",
        "display_name": "Triage", "editable_properties": ["priority"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [
            {"api_name": "priority", "display_name": "Priority", "data_type": "string",
             "value_constraint": {"kind": "enum", "values": ["P0", "P1", "P2"]}},
            {"api_name": "title", "display_name": "Summary", "data_type": "string",
             "value_constraint": {"kind": "range", "minimum": 10, "maximum": 500}},
            {"api_name": "labels", "display_name": "Labels", "data_type": "array",
             "array_of": "string",
             "value_constraint": {"kind": "enum", "values": ["bug", "chore"]}},
        ],
        "rules": [{"kind": "modify_object", "config": {"property": p, "parameter": p}}
                  for p in ("priority", "title", "labels")],
        "criteria": [],
    })
    mod.action = action
    return mod


def build(api, tickets, name: str) -> Module:
    mod = Module(api, name, beside=tickets)
    mod.type_id = tickets.type_id
    mod.define({
        "format": 2,
        "layout": layout({"form": {"resolvedName": "CanvasActionForm", "props": {
            "actionTypeId": tickets.action["id"], "objectVariable": None}}}),
        "variables": {}, "events": {},
    })
    return mod


def field(page, name: str):
    return page.locator(f'[data-parameter="{name}"]')


def stored(api, mod, ticket: str, prop: str):
    def read():
        found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": mod.type_id, "filters": []},
                          "limit": 10})["instances"]
        return next(i for i in found
                    if i["properties"]["ticket_id"] == ticket)["properties"].get(prop)
    return read


def test_the_form_offers_exactly_the_options(page, api, tickets) -> None:
    mod = build(api, tickets, "Constraint form choice")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="1")
    choice = field(page, "priority").get_by_test_id("multiple-choice")
    expect(choice.locator("option")).to_have_text(["Choose…", "P0", "P1", "P2"])
    # A dropdown says what is allowed by what it offers, so no note.
    expect(field(page, "priority").get_by_test_id("constraint-note")).to_have_count(0)
    choice.select_option("P0")
    field(page, "title").locator("input").fill("A long enough summary")
    page.get_by_role("button", name="Submit").click()
    eventually(stored(api, mod, "1", "priority"), lambda v: v == "P0", what="P0 written")


def test_a_length_is_said_and_refused_in_the_same_words(page, api, tickets) -> None:
    mod = build(api, tickets, "Constraint form length")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="2")
    expect(field(page, "title").get_by_test_id("constraint-note")).to_have_text(
        "Allowed: between 10 and 500.")
    field(page, "title").locator("input").fill("too short")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("9 characters is below the minimum of 10")
    assert stored(api, mod, "2", "title")() == "Second"


def test_each_item_of_a_list_is_picked_from_the_options(page, api, tickets) -> None:
    """On an array parameter the constraint is each item's, so every row is
    p.8's dropdown."""
    mod = build(api, tickets, "Constraint form list")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="3")
    field(page, "priority").get_by_test_id("multiple-choice").select_option("P1")
    field(page, "title").locator("input").fill("A long enough summary")
    labels = field(page, "labels")
    labels.get_by_test_id("array-item-add").click()
    labels.get_by_test_id("array-item-add").click()
    rows = labels.get_by_test_id("array-item")
    expect(rows.nth(0).get_by_test_id("multiple-choice").locator("option")).to_have_text(
        ["Choose…", "bug", "chore"])
    rows.nth(0).get_by_test_id("multiple-choice").select_option("chore")
    rows.nth(1).get_by_test_id("multiple-choice").select_option("bug")
    page.get_by_role("button", name="Submit").click()
    eventually(stored(api, mod, "3", "labels"), lambda v: v == ["chore", "bug"],
               what="both labels written")
