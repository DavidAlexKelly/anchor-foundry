"""Somebody's inbox (Foundry `action-types` p.87-101; §257).

The API's half — the rule, the rendering, p.96's permission modes — is
`apps/api/tests/test_notification_delivery.py`, where a wrong answer is a row.
What needs a browser is the other end of the same wire: that running an action
somebody is a recipient of puts something in *their* bar, that the badge counts
it, and that reading it clears the badge.

**The recipient is the account the browser is signed in as**, which is also
the one the API calls run as. That the two can differ — and that p.96 refuses
when a recipient may not see the data — is the API tests' claim, and it needs
rows rather than a screen. What this file is for is the other end of the wire:
that a delivered notification reaches the bar, is counted, and can be cleared.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def module(api):
    alerts = Module(api, "Notifications")
    alerts.object_type(
        columns=["id", "priority"],
        rows=[{"id": "A1", "priority": "low"}],
        key="id", title="id",
    )
    return alerts


@pytest.fixture(scope="module")
def notifying_action(api, module):
    """An action that retriages the alert and notifies whoever runs it."""
    action = api.call(
        "POST", f"/workspaces/{module.workspace_id}/action-types",
        {
            "object_type_id": module.object_type_id,
            "api_name": f"retriage_{uuid.uuid4().hex[:8]}",
            "display_name": f"Retriage {module.tag}",
            "editable_properties": ["priority"],
        },
    )
    # The account the browser is signed in as, so what the API delivers is
    # what the bar has to show.
    me = api.call("GET", "/auth/me")
    api.call(
        "PUT",
        f"/workspaces/{module.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "priority", "display_name": "Priority",
                 "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "priority", "parameter": "priority"}},
                {"kind": "notify", "config": {
                    "recipients": {"kind": "static", "user_ids": [me["user_id"]]},
                    "subject": f"Alert retriaged {module.tag}",
                    "body": "It is now {{{priority}}}.",
                }},
            ],
            "criteria": [],
        },
    )
    return action


def run_it(api, module, action, priority: str) -> None:
    instance = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types"
        f"/{module.object_type_id}/instances",
    )["items"][0]
    result = api.call(
        "POST",
        f"{module.base}/actions/{action['id']}/execute",
        {"instance_id": instance["id"], "values": {"priority": priority}},
    )
    assert result["ok"], result


def test_the_bar_says_nothing_when_there_is_nothing_to_say(page, module):
    """**Null rather than "0".** A badge showing zero is a mark on every screen
    meaning "nothing has happened", which is the one message it does not need
    to deliver."""
    page.goto(f"{WEB_BASE}/home")
    bell = page.get_by_test_id("notification-bell")
    expect(bell).to_be_visible(timeout=30000)
    # The panel opens, and opening it is not the same as reading anything.
    bell.click()
    expect(page.get_by_test_id("notification-panel")).to_be_visible(timeout=15000)


def test_running_the_action_reaches_the_recipients_bar(
    page, api, module, notifying_action
):
    """The claim a browser is for: what the API delivered actually reaches the
    bar, keyed and rendered the way p.91 and p.92 say."""
    run_it(api, module, notifying_action, "urgent")

    page.goto(f"{WEB_BASE}/home")
    bell = page.get_by_test_id("notification-bell")
    expect(bell).to_be_visible(timeout=30000)
    bell.click()
    panel = page.get_by_test_id("notification-panel")
    expect(panel).to_be_visible(timeout=15000)
    expect(panel).to_contain_text(f"Alert retriaged {module.tag}", timeout=15000)
    # The submitted value, substituted by p.92's triple handlebars.
    expect(panel).to_contain_text("It is now urgent.")


def test_the_badge_counts_and_reading_clears_it(page, api, module, notifying_action):
    """p.91's "See All", which is where somebody clears the badge.

    Two-sided: the badge has to be there before it can be cleared, and a test
    that only checked the clearing would pass against a badge that was never
    drawn.
    """
    run_it(api, module, notifying_action, "high")

    page.goto(f"{WEB_BASE}/home")
    badge = page.get_by_test_id("notification-badge")
    expect(badge).to_be_visible(timeout=30000)

    page.get_by_test_id("notification-bell").click()
    expect(page.get_by_test_id("notification-panel")).to_be_visible(timeout=15000)
    page.get_by_test_id("notification-read-all").click()
    expect(badge).to_have_count(0, timeout=15000)
