"""p.36's ObjectReference list parameter, on the screen (§581).

    "The starting set could also be set to an ObjectReference list
     parameter." (p.36)

A team of employees chosen in one box, and the next box offers every issue
any of them raised. The walk and its refusals are tested in
`apps/api/tests/test_action_object_lists.py`; what needs a browser is the
list being chosen, the issues following it, and the submission carrying both.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module
from ontology_page import pick_type
from test_action_definition_editor import definition, open_editor
from test_action_search_arounds import EMPLOYEES, ISSUES, picker


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Object list")
    tag = uuid.uuid4().hex[:8]
    employee_type = mod.object_type(columns=["id", "name"], rows=EMPLOYEES, key="id",
                                    title="name", slug=f"emp_{tag}")
    issue_type = mod.object_type(columns=["id", "employee_id", "title"], rows=ISSUES,
                                 key="id", title="title", slug=f"iss_{tag}")
    ticket_type = mod.object_type(columns=["id", "note"], rows=[{"id": "T1", "note": ""}],
                                  key="id", title="id", slug=f"tkt_{tag}")
    link = api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"raised_by_{tag}", "display_name": "Raised by",
        "from_type_id": issue_type, "to_type_id": employee_type,
        "cardinality": "one_to_many",
        "from_property": "employee_id", "to_property": "$primary_key"})
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": ticket_type, "api_name": f"assign_{tag}",
        "display_name": "Assign ticket", "editable_properties": ["note"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [
            {"api_name": "team", "display_name": "Team", "data_type": "array",
             "array_of": "object", "object_type_id": employee_type, "required": True},
            {"api_name": "issue", "display_name": "Issue", "data_type": "object",
             "object_type_id": issue_type,
             "dropdown_search_around": {
                 "start": {"kind": "parameter", "object_type_id": employee_type,
                           "parameter": "team"},
                 "hops": [{"link_type_id": link["id"]}]}},
        ],
        "rules": [{"kind": "modify_object", "config": {"property": "note", "parameter": "issue"}}],
        "criteria": []})
    mod.define({
        "format": 2,
        "layout": layout({"frm": {"resolvedName": "CanvasActionForm",
                                  "props": {"actionTypeId": action["id"]}}}),
        "variables": {}, "events": {},
    })
    mod.type_id = ticket_type
    mod.employee_type = employee_type
    mod.issue_type = issue_type
    mod.action = action
    return mod


def team(page):
    return page.get_by_test_id("object-list-parameter")


def choose_the_ticket(page) -> None:
    page.locator("form > label select").first.select_option(index=1)
    expect(team(page)).to_have_count(1)


def issues_offered(page) -> list[str]:
    return [t.strip() for t in picker(page, "issue").locator("option").all_inner_texts()]


def test_a_team_chosen_offers_every_issue_its_members_raised(page, world):
    open_module(page, world)
    choose_the_ticket(page)
    expect(team(page).locator("option")).to_have_text(["Ada", "Grace"], timeout=30000)
    team(page).select_option(label=["Ada"])
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one", "Ada two"], timeout=30000)
    assert not any("Grace" in o for o in issues_offered(page))
    team(page).select_option(label=["Ada", "Grace"])
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Ada one", "Ada two", "Grace one", "Grace two"], timeout=30000)


def test_before_the_team_is_chosen_the_issues_wait_for_it(page, world):
    open_module(page, world)
    choose_the_ticket(page)
    expect(page.get_by_test_id("choices-waiting")).to_contain_text("Team", timeout=30000)
    submit = page.get_by_role("button", name="Submit")
    expect(submit).to_be_disabled()


def test_the_submission_carries_the_team_and_the_issue(page, api, world):
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.post_data or "")
            if "/execute" in r.url else None)
    open_module(page, world)
    choose_the_ticket(page)
    expect(team(page).locator("option")).to_have_text(["Ada", "Grace"], timeout=30000)
    team(page).select_option(label=["Ada", "Grace"])
    expect(picker(page, "issue").locator("option")).to_contain_text(
        ["Choose", "Grace one"], timeout=30000)
    picker(page, "issue").select_option(label="Grace one")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")
    assert len(sent) == 1, sent
    employees = api.call(
        "GET", f"/workspaces/{world.workspace_id}/object-types/{world.employee_type}/instances",
    )["items"]
    ids = {e["properties"]["name"]: e["id"] for e in employees}
    assert sorted(json.loads(sent[0])["values"]["team"]) == sorted([ids["Ada"], ids["Grace"]])


def test_the_editor_declares_a_list_of_objects(page, api):
    from test_action_definition_editor import build as build_editor

    mod = build_editor(api, "Object list editor")
    open_editor(page, mod)
    page.get_by_label("Parameter 1 type").select_option("array")
    page.get_by_label("Parameter 1 element type").select_option("object")
    block = page.locator('[data-object-parameter="status"]')
    expect(block.get_by_test_id("parameter-untyped")).to_contain_text(
        "cannot be saved without one")
    # A list's objects are its whole type: no interface, walk or filters.
    expect(page.get_by_label("Parameter 1 interface")).to_have_count(0)
    pick_type(page, "parameter-1-object-type", {"id": mod.type_id, "api_name": f"seed_{mod.tag}"})
    expect(block.get_by_test_id("parameter-untyped")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, mod)["parameters"]
    assert (parameter["data_type"], parameter["array_of"]) == ("array", "object")
    assert parameter["object_type_id"] == mod.type_id
