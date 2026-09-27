"""The action log, turned on from the Actions table and read as objects
(§554; `action-types` p.167-168).

    "Action log object types map one-to-one with action types. Submitting an
     action generates a single new object of the corresponding action log
     object type." (p.167)

The schema, the links and the re-sync are `apps/api/tests/test_action_log.py`.
What needs a browser is the button that turns a log on, and the log's objects
being where a person looks for objects.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def alerts(api):
    mod = Module(api, "Action log")
    mod.object_type(columns=["id", "status"], rows=[{"id": "A1", "status": "open"}],
                    key="id", title="id")
    mod.action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"close_{uuid.uuid4().hex[:8]}",
        "display_name": f"Close {mod.tag}", "editable_properties": ["status"]})
    return mod


def test_turning_on_a_log_makes_each_submission_an_object(page, api, alerts) -> None:
    page.goto(f"{WEB_BASE}/{alerts.workspace_slug}/{alerts.project_slug}/objects")
    name = alerts.action["api_name"]
    page.get_by_test_id(f"action-log-on-{name}").click()
    # p.168's optional fields are offered first (§586); with neither filled in
    # this is §554's log.
    page.get_by_role("dialog").get_by_role("button", name="Turn on").click()
    log = page.get_by_test_id(f"action-log-{name}")
    expect(log).to_be_visible(timeout=20000)

    action = api.call("GET", f"/workspaces/{alerts.workspace_id}/action-types/"
                             f"{alerts.action['id']}")
    instances = api.call("GET", f"/workspaces/{alerts.workspace_id}/object-types/"
                                f"{alerts.object_type_id}/instances")["items"]
    run = api.call("POST", f"{alerts.base}/actions/{alerts.action['id']}/execute",
                   {"instance_id": instances[0]["id"], "values": {"status": "closed"}})
    assert run["ok"], run

    log.click()
    # p.167: "all action log object types are prefaced with [LOG]".
    expect(page.get_by_text(f"[LOG] Close {alerts.tag}").first).to_be_visible(timeout=20000)
    expect(page.get_by_text(run["run_id"]).first).to_be_visible(timeout=20000)
    assert action["log_object_type_id"] in page.url


@pytest.fixture(scope="module")
def triage(api):
    """p.168's Close Alerts with an `also` alert, whose Priority the log keeps."""
    mod = Module(api, "Action log summary")
    mod.object_type(columns=["id", "status", "priority"],
                    rows=[{"id": "B1", "status": "open", "priority": "high"},
                          {"id": "B2", "status": "open", "priority": "low"}],
                    key="id", title="id")
    mod.action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.object_type_id, "api_name": f"triage_{uuid.uuid4().hex[:8]}",
        "display_name": f"Triage {mod.tag}", "editable_properties": ["status"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition", {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
            {"api_name": "also", "display_name": "Also", "data_type": "object",
             "object_type_id": mod.object_type_id},
        ],
        "rules": [{"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}],
        "criteria": []})
    return mod


def test_p168s_summary_and_properties_from_the_dialog(page, api, triage) -> None:
    page.goto(f"{WEB_BASE}/{triage.workspace_slug}/{triage.project_slug}/objects")
    name = triage.action["api_name"]
    page.get_by_test_id(f"action-log-on-{name}").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_test_id("log-summary").fill("{{{status}}} after a {{{also.priority}}} alert")
    dialog.get_by_label("Keep also priority").check()
    dialog.get_by_role("button", name="Turn on").click()
    expect(page.get_by_test_id(f"action-log-{name}")).to_be_visible(timeout=20000)
    action = api.call("GET", f"/workspaces/{triage.workspace_id}/action-types/{triage.action['id']}")
    assert action["log_reference_properties"] == {"also": ["priority"]}

    instances = {i["primary_key"]: i["id"] for i in api.call(
        "GET", f"/workspaces/{triage.workspace_id}/object-types/"
               f"{triage.object_type_id}/instances")["items"]}
    run = api.call("POST", f"{triage.base}/actions/{triage.action['id']}/execute",
                   {"instance_id": instances["B1"],
                    "values": {"status": "closed", "also": instances["B2"]}})
    assert run["ok"], run
    logged = {i["primary_key"]: i["properties"] for i in api.call(
        "GET", f"/workspaces/{triage.workspace_id}/object-types/"
               f"{action['log_object_type_id']}/instances")["items"]}[run["run_id"]]
    assert (logged["summary"], logged["ref_also__priority"]) == (
        "closed after a low alert", "low")

    # The summary can be changed afterwards; the kept properties are said.
    page.reload()
    page.get_by_test_id(f"action-log-summary-{name}").click()
    dialog = page.get_by_role("dialog")
    expect(dialog.get_by_test_id("log-references")).to_contain_text("Keeps also: priority.")
    expect(dialog.get_by_test_id("log-summary")).to_have_value(
        "{{{status}}} after a {{{also.priority}}} alert")
    dialog.get_by_test_id("log-summary").fill("{{{nobody}}}")
    dialog.get_by_role("button", name="Save").click()
    expect(dialog.get_by_test_id("log-error")).to_contain_text("'nobody'")
    dialog.get_by_test_id("log-summary").fill("Set to {{{status}}}")
    dialog.get_by_role("button", name="Save").click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    action = api.call("GET", f"/workspaces/{triage.workspace_id}/action-types/{triage.action['id']}")
    assert action["log_summary"] == "Set to {{{status}}}"
