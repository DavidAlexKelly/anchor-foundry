"""Function-backed actions, set up in the action editor (§773; decision 0018
option B; `action-types` p.22, p.78-82).

> "In the Rules section, add a single rule of type Function. Search for the
> function you published … and pick the latest version. Configure the inputs
> to match up to the action parameters" (p.78)

The executor is `apps/api/tests/test_function_actions.py`'s and the form's
rules `function-rules.test.ts`'. What needs a browser: the rule chosen in the
dialog, p.79's parameters created for its inputs, p.81's auto upgrade, and the
saved action applying the function's edits.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from test_action_definition_editor import definition, open_editor


def build(api, name: str) -> Module:
    mod = Module(api, name)
    slug = f"fticket_{mod.tag}"
    mod.type_id = mod.object_type(
        columns=["ticket_id", "status"], rows=[{"ticket_id": "1", "status": "open"}],
        key="ticket_id", title="ticket_id", slug=slug)
    mod.action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"close_{uuid.uuid4().hex[:8]}",
        "display_name": "Close ticket", "editable_properties": ["status"]})
    body = {"inputs": [mod.type_id],
            "parameters": [{"api_name": "ticket", "data_type": "object",
                            "object_type_id": mod.type_id},
                           {"api_name": "reason", "data_type": "string"}],
            "output": {"kind": "edits", "object_type_id": mod.type_id}}
    sql = (f"SELECT __primary_key, '{{}}: ' || $reason AS status FROM {slug} "
           "WHERE __primary_key = $ticket")
    mod.fn = api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
        "api_name": f"wrapup_{mod.tag}", "display_name": "Wrap up",
        "version": {**body, "version": "1.0.0", "sql": sql.format("closed")}})
    api.call("POST", f"/workspaces/{mod.workspace_id}/functions/{mod.fn['id']}/versions",
             {**body, "version": "1.1.0", "sql": sql.format("shut")})
    return mod


def test_a_function_rule_set_up_in_the_dialog_saves_and_runs(page, api):
    mod = build(api, "Function action")
    open_editor(page, mod)
    page.get_by_label("Rule 1 kind").select_option("function")
    expect(page.get_by_test_id("rule-1-problem")).to_have_text(
        "Choose the function this action calls.")
    page.get_by_label("Rule 1 function").select_option(mod.fn["id"])
    expect(page.get_by_test_id("rule-1-problem")).to_have_text(
        "Choose the version this action calls.", timeout=15000)
    page.get_by_label("Rule 1 version").select_option("1.0.0")
    # p.79: the inputs are set up and the parameter the reason reads made.
    expect(page.get_by_test_id("rule-1-problem")).to_have_count(0)
    expect(page.get_by_label("Rule 1 ticket from")).to_have_value("$subject")
    expect(page.get_by_label("Rule 1 reason from")).to_have_value("param:reason")
    expect(page.get_by_label("Parameter 2 name")).to_have_value("reason")
    # p.81: the range runs the newest compatible release, and says so.
    page.get_by_label("Rule 1 auto upgrade").check()
    expect(page.get_by_test_id("rule-1-runs")).to_have_text("— runs 1.1.0")
    page.get_by_label("Rule 1 auto upgrade").uncheck()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = definition(api, mod)
    assert [(r["kind"], r["config"]) for r in stored["rules"]] == [("function", {
        "function_id": mod.fn["id"], "version": "1.0.0", "auto_upgrade": False,
        "batched": False,
        "inputs": {"ticket": {"subject": True}, "reason": {"parameter": "reason"}}})]
    assert [p["api_name"] for p in stored["parameters"]] == ["status", "reason"]

    instance = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances",
    )["items"][0]
    done = api.call("POST", f"{mod.base}/actions/{mod.action['id']}/execute",
                    {"instance_id": instance["id"], "values": {"reason": "fixed"}})
    assert done["instance"]["properties"]["status"] == "closed: fixed"


def test_a_value_and_another_source_for_an_input(page, api):
    mod = build(api, "Function action value")
    open_editor(page, mod)
    page.get_by_label("Rule 1 kind").select_option("function")
    page.get_by_label("Rule 1 function").select_option(mod.fn["id"])
    page.get_by_label("Rule 1 version").select_option("1.1.0", timeout=15000)
    # Another of the action's parameters may feed it.
    page.get_by_label("Rule 1 reason from").select_option("param:status")
    expect(page.get_by_test_id("rule-1-problem")).to_have_count(0)
    page.get_by_label("Rule 1 reason from").select_option("$value")
    page.get_by_label("Rule 1 reason value").fill("dup")
    # The one object input of the action's own type may be this object; a
    # string may not.
    expect(page.get_by_label("Rule 1 reason from").locator(
        "option", has_text="This object")).to_have_count(0)
    page.get_by_label("Rule 1 ticket from").select_option("")
    expect(page.get_by_test_id("rule-1-problem")).to_have_text(
        "ticket needs a parameter, a value or this object.")
    page.get_by_label("Rule 1 ticket from").select_option("$subject")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    rule = definition(api, mod)["rules"][0]
    assert rule["config"]["inputs"] == {"ticket": {"subject": True},
                                        "reason": {"value": "dup"}}
    instance = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances",
    )["items"][0]
    # p.79's parameter was made when the version was picked, and stays the
    # action's to keep or remove: given, and not what the function reads.
    done = api.call("POST", f"{mod.base}/actions/{mod.action['id']}/execute",
                    {"instance_id": instance["id"], "values": {"reason": "ignored"}})
    assert done["instance"]["properties"]["status"] == "shut: dup"


def test_a_batched_function_is_run_batched(page, api):
    """p.85: "You can then enable batched execution for this function when
    configuring the action type" (§779) - set when the version picked takes a
    batch, its fields fed as parameters would be."""
    mod = build(api, "Function action batched")
    slug = f"fticket_{mod.tag}"
    fn = api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
        "api_name": f"wrapall_{mod.tag}", "display_name": "Wrap all", "version": {
            "version": "1.0.0", "inputs": [mod.type_id],
            "parameters": [{"api_name": "batch", "data_type": "batch", "fields": [
                {"api_name": "ticket", "data_type": "object", "object_type_id": mod.type_id},
                {"api_name": "reason", "data_type": "string"}]}],
            "output": {"kind": "edits", "object_type_id": mod.type_id},
            "sql": "SELECT b.ticket AS k, 'closed: ' || b.reason AS status "
                   "FROM (SELECT unnest($batch) AS b)"}})
    open_editor(page, mod)
    page.get_by_label("Rule 1 kind").select_option("function")
    page.get_by_label("Rule 1 function").select_option(fn["id"])
    page.get_by_label("Rule 1 version").select_option("1.0.0", timeout=15000)
    expect(page.get_by_test_id("rule-1-batched")).to_be_visible()
    expect(page.get_by_label("Rule 1 ticket from")).to_have_value("$subject")
    expect(page.get_by_test_id("rule-1-problem")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    config = definition(api, mod)["rules"][0]["config"]
    assert (config["batched"], config["inputs"]) == (
        True, {"ticket": {"subject": True}, "reason": {"parameter": "reason"}})
    instance = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances",
    )["items"][0]
    done = api.call("POST", f"{mod.base}/actions/{mod.action['id']}/execute",
                    {"instance_id": instance["id"], "values": {"reason": "batched"}})
    assert done["instance"]["properties"]["status"] == "closed: batched"
