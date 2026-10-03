"""Groups as notification recipients (§755; `action-types` p.95-96).

> "Static: In the configuration, you may select a set of users or groups who
> will always be notified" (p.95) … "Groups will be resolved to individual
> users in order to check permissions on the data before sending the
> notifications." (p.96)

Until §755 a group id reached `deliver`, which looked it up in `users` and
found nobody, so groups were left out of the picker. Here a group is its
members by the time p.96 asks anything, wherever the id came from: a static
list, a parameter, or an object's property.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_notification_delivery import (  # noqa: E402,F401
    abase, alert, alert_type, client, define, fx, inbox, make_action, wbase,
)


def a_group(client: TestClient, fx: Fixture, name: str, *members, sub: str | None = None) -> str:
    r = client.post("/api/org/groups", headers=hdr(sub or fx.admin_sub),
                    json={"name": f"{name} {fx.tag}"})
    assert r.status_code == 201, r.text
    gid = r.json()["id"]
    for user in members:
        assert client.put(f"/api/org/groups/{gid}/members/{user}",
                          headers=hdr(sub or fx.admin_sub)).status_code == 204
    return gid


@pytest.fixture(scope="module")
def team(client: TestClient, fx: Fixture) -> str:
    """Two people who can both see the workspace."""
    return a_group(client, fx, "Triage", fx.viewer, fx.editor)


@pytest.fixture(scope="module")
def mixed(client: TestClient, fx: Fixture) -> str:
    """One who can see it and one (`outsider`, in the organisation and not the
    workspace) who cannot."""
    return a_group(client, fx, "Mixed", fx.viewer, fx.outsider)


def run(client: TestClient, fx: Fixture, action: dict, alert: str, priority: str):
    return client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": priority}},
    )


def totals(client: TestClient, *subs: str) -> list[int]:
    return [inbox(client, sub)["total"] for sub in subs]


# ---- the picker (p.95) ----------------------------------------------------------
def test_the_picker_offers_groups_beside_people(
    client: TestClient, fx: Fixture, team: str, mixed: str
) -> None:
    r = client.get(f"{wbase(fx)}/notification-recipients", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    groups = {row["id"]: row for row in r.json() if row["kind"] == "group"}
    assert groups[team]["display_name"] == f"Triage {fx.tag}"
    assert groups[team]["email"] is None
    # How many members, and how many of them p.96 would let through.
    assert (groups[team]["members"], groups[team]["reachable"]) == (2, 2)
    assert (groups[mixed]["members"], groups[mixed]["reachable"]) == (2, 1)
    people = [row for row in r.json() if row["kind"] == "user"]
    assert people and all(row["members"] is None for row in people)


def test_an_empty_group_is_offered_as_reaching_nobody(
    client: TestClient, fx: Fixture
) -> None:
    nobody = a_group(client, fx, "Nobody yet")
    r = client.get(f"{wbase(fx)}/notification-recipients", headers=hdr(fx.editor_sub))
    found = next(row for row in r.json() if row["id"] == nobody)
    assert (found["members"], found["reachable"]) == (0, 0)


def test_another_organisations_groups_are_not_offered(
    client: TestClient, fx: Fixture
) -> None:
    theirs = a_group(client, fx, "Theirs", sub=fx.foreign_sub)
    r = client.get(f"{wbase(fx)}/notification-recipients", headers=hdr(fx.editor_sub))
    assert theirs not in {row["id"] for row in r.json()}


# ---- saving -----------------------------------------------------------------------
def test_a_static_list_may_be_groups_alone(
    client: TestClient, fx: Fixture, alert_type: str, team: str
) -> None:
    action = make_action(client, fx, alert_type)
    r = define(client, fx, action, {
        "recipients": {"kind": "static", "group_ids": [team]},
        "subject": "s", "body": "b",
    })
    assert r.status_code == 200, r.text
    rule = next(x for x in r.json()["rules"] if x["kind"] == "notify")
    assert rule["config"]["recipients"]["group_ids"] == [team]


def test_a_static_list_naming_nobody_is_refused(
    client: TestClient, fx: Fixture, alert_type: str
) -> None:
    action = make_action(client, fx, alert_type)
    r = define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [], "group_ids": []},
        "subject": "s", "body": "b",
    })
    assert r.status_code == 422, r.text
    assert "at least one person or group" in r.text


# ---- delivery (p.96) -------------------------------------------------------------
def test_each_member_of_a_group_is_notified_once(
    client: TestClient, fx: Fixture, alert_type: str, alert: str, team: str
) -> None:
    action = make_action(client, fx, alert_type)
    # The viewer is named and in the group: one notification, not two (p.90's
    # "each recipient individually").
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.viewer)], "group_ids": [team]},
        "subject": "For the team", "body": "b",
    }).status_code == 200
    before = totals(client, fx.viewer_sub, fx.editor_sub, fx.admin_sub)
    r = run(client, fx, action, alert, "team")
    assert r.status_code == 200, r.text
    assert totals(client, fx.viewer_sub, fx.editor_sub, fx.admin_sub) == [
        before[0] + 1, before[1] + 1, before[2]]
    newest = inbox(client, fx.editor_sub)["items"][0]
    assert newest["subject"] == "For the team"


def test_a_member_who_cannot_see_the_data_refuses_the_strict_mode(
    client: TestClient, fx: Fixture, alert_type: str, alert: str, mixed: str
) -> None:
    """p.96 checks the people, not the group: the outsider in it is refused
    as they would be by name, and nothing is changed or sent."""
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "group_ids": [mixed]},
        "subject": "s", "body": "b",
    }).status_code == 200
    before = totals(client, fx.viewer_sub)
    r = run(client, fx, action, alert, "should-not-land")
    assert r.status_code == 422, r.text
    assert str(fx.outsider) in r.text
    assert "nothing has been changed" in r.text
    assert totals(client, fx.viewer_sub) == before


def test_the_lenient_mode_sends_to_the_members_who_can_see_it(
    client: TestClient, fx: Fixture, alert_type: str, alert: str, mixed: str
) -> None:
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "group_ids": [mixed]},
        "subject": "s", "body": "b", "permissions": "any",
    }).status_code == 200
    before = totals(client, fx.viewer_sub, fx.outsider_sub)
    r = run(client, fx, action, alert, "mixed")
    assert r.status_code == 200, r.text
    assert totals(client, fx.viewer_sub, fx.outsider_sub) == [before[0] + 1, before[1]]


def test_an_empty_group_is_nobody_and_no_refusal(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    empty = a_group(client, fx, "Empty")
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "group_ids": [empty]},
        "subject": "s", "body": "b",
    }).status_code == 200
    r = run(client, fx, action, alert, "empty")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_another_organisations_group_reaches_nobody(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """Its id is not a group this organisation can see, so it is left as an
    id, which names no user who can see the data, and the strict mode
    refuses it rather than reading its members."""
    theirs = a_group(client, fx, "Foreign", fx.foreign, sub=fx.foreign_sub)
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "group_ids": [theirs]},
        "subject": "s", "body": "b",
    }).status_code == 200
    before = totals(client, fx.foreign_sub)
    r = run(client, fx, action, alert, "foreign")
    assert r.status_code == 422, r.text
    assert theirs in r.text
    assert totals(client, fx.foreign_sub) == before


def test_a_group_id_in_an_objects_property_reaches_its_members(
    client: TestClient, fx: Fixture, alert_type: str, alert: str, team: str
) -> None:
    """p.95's third way: "one of the properties of that object contains a
    Foundry user or group ID"."""
    setter = make_action(client, fx, alert_type)
    r = client.put(
        f"{wbase(fx)}/action-types/{setter['id']}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": [{"api_name": "case_manager", "display_name": "Case manager",
                              "data_type": "string"}],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "case_manager", "parameter": "case_manager"}}],
              "criteria": []})
    assert r.status_code == 200, r.text
    assert client.post(
        f"{abase(fx)}/{setter['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"case_manager": team}},
    ).status_code == 200

    notifier = make_action(client, fx, alert_type)
    r = client.put(
        f"{wbase(fx)}/action-types/{notifier['id']}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": [
                {"api_name": "priority", "display_name": "Priority", "data_type": "string"},
                {"api_name": "alert", "display_name": "Alert", "data_type": "object"}],
              "rules": [
                {"kind": "modify_object",
                 "config": {"property": "priority", "parameter": "priority"}},
                {"kind": "notify", "config": {
                    "recipients": {"kind": "object_property", "parameter": "alert",
                                   "object_type": alert_type, "property": "case_manager"},
                    "subject": "Your team's alert", "body": "b"}}],
              "criteria": []})
    assert r.status_code == 200, r.text
    before = totals(client, fx.viewer_sub, fx.editor_sub)
    r = client.post(
        f"{abase(fx)}/{notifier['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "p", "alert": alert}},
    )
    assert r.status_code == 200, r.text
    assert totals(client, fx.viewer_sub, fx.editor_sub) == [before[0] + 1, before[1] + 1]


def test_a_static_group_list_is_not_carried_by_an_export(
    client: TestClient, fx: Fixture, alert_type: str, team: str
) -> None:
    """A group is this organisation's, as a person is, so p.65's export
    refuses to carry either (`action_rule_transfer`)."""
    from src.services import action_rule_transfer
    rule = {"kind": "notify", "config": {"recipients": {"kind": "static", "group_ids": [team]}}}
    assert action_rule_transfer.outside_ontology(rule) == ["a list of named recipients"]
