"""Constraints on a struct parameter's fields (§585; db 0120; `action-types`
p.71-72).

> "Constraints can be configured individually for struct parameter fields, as
>  with regular parameters. For example, a string length constraint can be
>  defined on struct parameter fields of string types to only allow string
>  value that are between 10 and 500 characters long." (p.71)
> "A struct parameter value is only valid if all fields meet the defined
>  constraint." (p.72)

p.71's own example, set in the editor on the field it names, then met in the
form: a multiple-choice field is a dropdown, the length is said under the
struct, and a summary too short is refused in the same words.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_module, settled
from test_action_definition_editor import definition, open_editor

FIELDS = [
    {"api_name": "summary", "display_name": "Summary", "data_type": "string"},
    {"api_name": "outcome", "display_name": "Outcome", "data_type": "string"},
]


@pytest.fixture(scope="module")
def tickets(api):
    mod = Module(api, "Struct field constraints")
    mod.type_id = mod.object_type(
        columns=["ticket_id", "resolution"],
        rows=[{"ticket_id": f"f{n}", "resolution": ""} for n in range(1, 4)],
        key="ticket_id", title="ticket_id",
        types={"resolution": "struct"}, struct_fields={"resolution": FIELDS},
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"resolve_{uuid.uuid4().hex[:8]}",
        "display_name": "Resolve", "editable_properties": ["resolution"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [{"api_name": "resolution", "display_name": "Resolution",
                        "data_type": "struct"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "resolution", "parameter": "resolution"}}],
        "criteria": [],
    })
    mod.action = action
    return mod


def test_p71s_example_in_the_editor(page, api, tickets) -> None:
    open_editor(page, tickets)
    summary = page.locator('[data-parameter-constraint="resolution"] '
                           '[data-field-constraint="summary"]')
    summary.get_by_test_id("constraint-kind").select_option("range")
    summary.get_by_test_id("constraint-min").fill("10")
    summary.get_by_test_id("constraint-max").fill("500")
    outcome = page.locator('[data-parameter-constraint="resolution"] '
                           '[data-field-constraint="outcome"]')
    outcome.get_by_test_id("constraint-kind").select_option("enum")
    outcome.get_by_test_id("constraint-enum").fill("fixed\nwon't fix")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, tickets)["parameters"]
    assert parameter["field_constraints"]["summary"] == {
        "kind": "range", "minimum": 10, "maximum": 500}
    assert parameter["field_constraint_summaries"] == {
        "summary": "between 10 and 500", "outcome": "one of fixed, won't fix"}
    # Reopened, both are still there: the dialog saves parameters whole.
    open_editor(page, tickets)
    expect(page.locator('[data-field-constraint="summary"]')
           .get_by_test_id("constraint-min")).to_have_value("10")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert definition(api, tickets)["parameters"][0]["field_constraints"]["outcome"]


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


def stored(api, mod, ticket: str):
    def read():
        found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": mod.type_id, "filters": []},
                          "limit": 10})["instances"]
        return next(i for i in found
                    if i["properties"]["ticket_id"] == ticket)["properties"].get("resolution")
    return read


def test_the_form_meets_each_fields_constraint(page, api, tickets) -> None:
    api.call("PUT", f"/workspaces/{tickets.workspace_id}/action-types/"
                    f"{tickets.action['id']}/definition", {
        "parameters": [{"api_name": "resolution", "display_name": "Resolution",
                        "data_type": "struct", "field_constraints": {
                            "summary": {"kind": "range", "minimum": 10, "maximum": 500},
                            "outcome": {"kind": "enum", "values": ["fixed", "won't fix"]}}}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "resolution", "parameter": "resolution"}}],
        "criteria": [],
    })
    mod = build(api, tickets, "Struct field form")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="f2")
    field = page.locator('[data-parameter="resolution"]')
    outcome = field.get_by_label("Resolution — Outcome")
    expect(outcome.locator("option")).to_have_text(["Choose…", "fixed", "won't fix"])
    expect(field.get_by_test_id("field-constraint-note")).to_have_text(
        "Summary: between 10 and 500.")
    outcome.select_option("fixed")
    field.get_by_label("Resolution — Summary").fill("too short")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text(
        "field 'summary': 9 characters is below the minimum of 10")
    field.get_by_label("Resolution — Summary").fill("Cable reseated at the rack")
    page.get_by_role("button", name="Submit").click()
    eventually(stored(api, mod, "f2"),
               lambda v: v == {"summary": "Cable reseated at the rack", "outcome": "fixed"},
               what="the resolution written")
