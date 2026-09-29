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
