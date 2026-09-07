"""Notifications, from an action's rule to somebody's inbox (§257).

Foundry `action-types` p.89-101. The pure half - what a rule means, what its
content renders to, who p.96 lets it reach - is `test_notifications.py` and
needs no database. This is the half that needs one, and every test here is
about something that can only be wrong once a row exists:

* the rule reaches the database at all, as a sixth `action_rule_kind` (db 0066);
* the content is rendered against the world **before** the action's edits
  (p.92), which is a claim about ordering that no unit test can make;
* p.96's strict mode refuses the whole action, leaving the object unchanged -
  "no data will be edited and no notifications will be sent";
* and the inbox is yours, which is RLS rather than a handler.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ALERTS = b"alert_id,priority,case_manager\nA1,low,\nA2,high,\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("notify-storage")))
    )
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def abase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/actions"


@pytest.fixture(scope="module")
def alert_type(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Alert{fx.tag}", "display_name": f"Alert {fx.tag}",
            "properties": [
                {"api_name": "priority", "data_type": "string"},
                # p.96: a recipient property "stores the Foundry user or group
                # ID as a string".
                {"api_name": "case_manager", "data_type": "string"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def alert(client: TestClient, fx: Fixture, alert_type: str) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Alerts {fx.tag}"},
        files={"file": ("alerts.csv", io.BytesIO(ALERTS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": alert_type, "dataset_id": r.json()["id"],
            "primary_key_column": "alert_id",
            "column_mappings": {"priority": "priority",
                                "case_manager": "case_manager"},
        },
    )
    assert r.status_code == 201, r.text
    assert client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{r.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    ).status_code == 200
    listed = client.get(
        f"{wbase(fx)}/object-types/{alert_type}/instances", headers=hdr(fx.viewer_sub)
    ).json()["items"]
    return sorted(listed, key=lambda i: i["primary_key"])[0]["id"]


def make_action(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id,
            "api_name": f"notify_{uuid.uuid4().hex[:8]}",
            "display_name": "Retriage",
            "editable_properties": ["priority"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def define(client: TestClient, fx: Fixture, action: dict, notify: dict):
    """The action's own rule, plus one notify rule."""
    return client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "priority", "display_name": "Priority",
                 "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "priority", "parameter": "priority"}},
                {"kind": "notify", "config": notify},
            ],
            "criteria": [],
        },
    )


def inbox(client: TestClient, sub: str) -> dict:
    r = client.get("/api/notifications", headers=hdr(sub))
    assert r.status_code == 200, r.text
    return r.json()


# ---- the rule reaches the database ----------------------------------------------
def test_a_notify_rule_is_saved_like_any_other_rule(
    client: TestClient, fx: Fixture, alert_type: str
) -> None:
    """p.89 puts notifications in the same *Add new rule* dropdown as the other
    five, so `notify` is a sixth `action_rule_kind` rather than a resource of
    its own. This is that enum value surviving a round trip."""
    action = make_action(client, fx, alert_type)
    r = define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.viewer)]},
        "subject": "Retriaged",
        "body": "Now {{{priority}}}.",
    })
    assert r.status_code == 200, r.text
    kinds = [rule["kind"] for rule in r.json()["rules"]]
    assert "notify" in kinds


def test_a_notify_rule_that_names_nothing_is_refused_at_save_time(
    client: TestClient, fx: Fixture, alert_type: str
) -> None:
    """Every rule kind is checked where it is typed rather than where it runs:
    the executor would refuse it later, in front of somebody who did not write
    it."""
    action = make_action(client, fx, alert_type)
    r = define(client, fx, action, {
        "recipients": {"kind": "parameter", "parameter": "nobody"},
        "subject": "x",
    })
    assert r.status_code == 422, r.text
    assert "not a parameter" in r.text


# ---- delivery -------------------------------------------------------------------
def test_running_the_action_puts_a_notification_in_the_inbox(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.viewer)]},
        "subject": "Alert retriaged",
        "body": "It is now {{{priority}}}, said {{{current_user}}}.",
    }).status_code == 200

    before = inbox(client, fx.viewer_sub)["total"]
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "urgent"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.text

    page = inbox(client, fx.viewer_sub)
    assert page["total"] == before + 1
    newest = page["items"][0]
    assert newest["subject"] == "Alert retriaged"
    # The submitted value, and p.101's `Current User`.
    assert "urgent" in newest["body"]
    assert newest["actor_name"], newest
    assert newest["read_at"] is None
    assert page["unread"] >= 1


def test_the_content_is_the_world_before_the_edits(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """**p.92, and it is the sharpest rule in this feature.**

    > "Any Ontology data used for generating notification content will reflect
    > the state of the Ontology before edits of the current Action are
    > applied."

    The action sets `priority`, and the body names *the object's* priority. If
    the content were rendered after the write, both would read the new value
    and nothing on screen would show the difference — which is exactly why this
    test asserts the old one.
    """
    action = make_action(client, fx, alert_type)
    # Put the object at a known priority first, through the same action, so
    # "before" is a value this test chose rather than one the fixture left.
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.viewer)]},
        "subject": "s", "body": "b",
    }).status_code == 200
    assert client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "before-value"}},
    ).status_code == 200

    # The object has to be *named* to be referenced: `{{{alert.priority}}}`
    # reads an object parameter, so the action declares one and is handed the
    # same instance it is running against.
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "priority", "display_name": "Priority",
                 "data_type": "string"},
                {"api_name": "alert", "display_name": "Alert",
                 "data_type": "object"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "priority", "parameter": "priority"}},
                {"kind": "notify", "config": {
                    "recipients": {"kind": "static",
                                   "user_ids": [str(fx.viewer)]},
                    "subject": "Priority moved",
                    "body": "from {{{alert.priority}}} to {{{priority}}}",
                }},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert,
              "values": {"priority": "after-value", "alert": alert}},
    )
    assert r.status_code == 200, r.text

    newest = inbox(client, fx.viewer_sub)["items"][0]
    assert newest["body"] == "from before-value to after-value", newest


def test_a_recipient_read_off_the_objects_own_property(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """p.100's tutorial case: "use the option Recipient(s) from property of
    object parameter … then select the Case managers property"."""
    action = make_action(client, fx, alert_type)
    # Put a user id in the property the rule will read.
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.editor)]},
        "subject": "s", "body": "b",
    }).status_code == 200

    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "case_manager", "display_name": "Case manager",
                 "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "case_manager",
                            "parameter": "case_manager"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    assert client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"case_manager": str(fx.viewer)}},
    ).status_code == 200

    # Now an action that notifies whoever that property names.
    notifier = make_action(client, fx, alert_type)
    r = client.put(
        f"{wbase(fx)}/action-types/{notifier['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "priority", "display_name": "Priority",
                 "data_type": "string"},
                {"api_name": "alert", "display_name": "Alert",
                 "data_type": "object"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "priority", "parameter": "priority"}},
                {"kind": "notify", "config": {
                    "recipients": {
                        "kind": "object_property", "parameter": "alert",
                        "object_type": alert_type, "property": "case_manager",
                    },
                    "subject": "Your alert changed",
                    "body": "Now {{{priority}}}.",
                }},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    before = inbox(client, fx.viewer_sub)["total"]
    r = client.post(
        f"{abase(fx)}/{notifier['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert,
              "values": {"priority": "critical", "alert": alert}},
    )
    assert r.status_code == 200, r.text
    assert inbox(client, fx.viewer_sub)["total"] == before + 1


# ---- p.96's refusal, and what it leaves behind -----------------------------------
def test_a_recipient_who_cannot_see_the_data_stops_the_whole_action(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """p.96's default mode: "If any recipients do not have the required access,
    an error will be shown … **no data will be edited and no notifications will
    be sent**."

    The second half is the one worth a database: an action that refused after
    writing would leave the object changed and say it had not.
    """
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        # `outsider` is in the organisation and not in this workspace.
        "recipients": {"kind": "static",
                       "user_ids": [str(fx.viewer), str(fx.outsider)]},
        "subject": "Retriaged", "body": "b",
    }).status_code == 200

    before = client.get(
        f"{wbase(fx)}/object-types/{alert_type}/instances/{alert}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"].get("priority")
    inbox_before = inbox(client, fx.viewer_sub)["total"]

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "should-not-land"}},
    )
    assert r.status_code == 422, r.text
    assert "nothing has been changed" in r.text

    after = client.get(
        f"{wbase(fx)}/object-types/{alert_type}/instances/{alert}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"].get("priority")
    assert after == before, "the refused action wrote to the object anyway"
    assert inbox(client, fx.viewer_sub)["total"] == inbox_before


def test_the_lenient_mode_sends_to_whoever_can_see_it(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """p.96's other half: "If at least one user can see the object, the Action
    will succeed. Only users with permissions will receive notifications"."""
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static",
                       "user_ids": [str(fx.viewer), str(fx.outsider)]},
        "subject": "Retriaged anyway", "body": "b",
        "permissions": "any",
    }).status_code == 200

    before = inbox(client, fx.viewer_sub)["total"]
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "landed"}},
    )
    assert r.status_code == 200, r.text
    assert inbox(client, fx.viewer_sub)["total"] == before + 1
    # And the outsider got nothing, which is the "only users with permissions"
    # half — without it this passes against a mode that notified everybody.
    assert inbox(client, fx.outsider_sub)["total"] == 0


def test_an_organisation_admin_is_a_recipient_without_being_a_member(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """**The rule is `effective_workspace_role`, not `workspace_members`.**

    db 0005 gives workspace access three ways: direct membership, membership
    through a group, and being an owner or admin of the organisation. An
    organisation admin is a member of nothing and can see everything — so a
    notification naming them failed p.96's check and took the whole action down
    with it.

    Every account in this fixture except the admin and the owner is an ordinary
    org member, which is why the first version of this suite could not see the
    difference; a browser test found it, because the account that suite signs
    in as is exactly this person.
    """
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.admin)]},
        "subject": "For the admin", "body": "b",
    }).status_code == 200

    before = inbox(client, fx.admin_sub)["total"]
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "admin-visible"}},
    )
    assert r.status_code == 200, r.text
    assert inbox(client, fx.admin_sub)["total"] == before + 1


# ---- the inbox ------------------------------------------------------------------
def test_an_inbox_is_yours(client: TestClient, fx: Fixture) -> None:
    """db 0066's policy is `user_id = rls_current_user_id()`, so this is RLS
    rather than a handler — and a workspace admin reading other people's
    messages is not a feature anybody asked for."""
    mine = inbox(client, fx.viewer_sub)
    assert mine["total"] > 0, "the delivery tests above should have filled this"
    assert inbox(client, fx.foreign_sub)["total"] == 0


def test_reading_one_clears_it_and_the_badge(client: TestClient, fx: Fixture) -> None:
    page = inbox(client, fx.viewer_sub)
    unread = [n for n in page["items"] if n["read_at"] is None]
    assert unread, page
    before = page["unread"]

    r = client.post(
        f"/api/notifications/{unread[0]['id']}/read", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    assert r.json()["unread"] == before - 1


def test_reading_it_twice_is_not_an_error(client: TestClient, fx: Fixture) -> None:
    """Two tabs open on the same inbox is an ordinary thing, and the second one
    should not report a failure for agreeing.

    **And the timestamp does not move**, which is the half a mutant walked
    through: "when did you see this" is a fact about the person, and an answer
    that crept forward every time they scrolled past it would be a fact about
    their scrolling.
    """
    page = inbox(client, fx.viewer_sub)
    read = [n for n in page["items"] if n["read_at"] is not None]
    assert read, page
    first = read[0]
    assert client.post(
        f"/api/notifications/{first['id']}/read", headers=hdr(fx.viewer_sub)
    ).status_code == 200

    again = [
        n for n in inbox(client, fx.viewer_sub)["items"] if n["id"] == first["id"]
    ]
    assert again and again[0]["read_at"] == first["read_at"], again


def test_somebody_elses_notification_is_not_found(
    client: TestClient, fx: Fixture
) -> None:
    """The same answer as one that does not exist. Telling them apart would say
    whether somebody else received a notification."""
    mine = inbox(client, fx.viewer_sub)["items"][0]["id"]
    r = client.post(
        f"/api/notifications/{mine}/read", headers=hdr(fx.foreign_sub)
    )
    assert r.status_code == 404, r.text


def test_see_all_clears_the_badge(client: TestClient, fx: Fixture) -> None:
    """p.91's "See All", which is where somebody clears the badge."""
    r = client.post("/api/notifications/read", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert r.json()["unread"] == 0
    assert client.get(
        "/api/notifications/unread", headers=hdr(fx.viewer_sub)
    ).json()["unread"] == 0


def test_a_failed_action_sends_nothing(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """**A notification saying an object changed, sent after the change
    failed, is the one outcome worse than no notification**: the recipient acts
    on it and finds nothing.

    The action is made to fail at the *write*, past the point where the
    notifications were already resolved and permitted — which is the only place
    this can be got wrong, and where a mutant that dropped the `if ok:` walked
    straight through the suite.
    """
    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.viewer)]},
        "subject": "Should never arrive", "body": "b",
    }).status_code == 200

    # **The failure has to land in the write**, past the point where the
    # notifications were already resolved and permitted. A bad instance id is
    # refused earlier than that and would leave `notices` empty, which is a
    # test that passes for the wrong reason — the first version of this did
    # exactly that and a mutant dropping the `if ok:` walked through it.
    #
    # An unreadable source file is the cheapest failure on the far side: the
    # engine refuses the extension, the route catches `DatasetEngineError` and
    # closes the run with `ok=False`.
    import psycopg

    from test_api import ADMIN_DSN

    # A second dataset whose file exists and whose *columns* are wrong: the
    # file opens, and the query referencing `priority` does not. Pointing at a
    # missing path instead would raise before the try block and prove nothing.
    other = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Wrong shape {uuid.uuid4().hex[:6]}"},
        files={"file": ("wrong.csv", io.BytesIO(b"only_column\nx\n"), "text/csv")},
    )
    assert other.status_code == 201, other.text

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        original = conn.execute(
            """SELECT d.id, d.s3_location FROM datasets d
                JOIN object_type_sources s ON s.dataset_id = d.id
               WHERE s.object_type_id = %s LIMIT 1""",
            (alert_type,),
        ).fetchone()
        assert original, "the fixture should have mapped a dataset"
        wrong = conn.execute(
            "SELECT s3_location FROM datasets WHERE id = %s",
            (other.json()["id"],),
        ).fetchone()[0]
        conn.execute(
            "UPDATE datasets SET s3_location = %s WHERE id = %s",
            (wrong, original[0]),
        )

    before = inbox(client, fx.viewer_sub)["total"]
    try:
        r = client.post(
            f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
            json={"instance_id": alert, "values": {"priority": "x"}},
        )
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is False, "the write should have failed"
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
            conn.execute(
                "UPDATE datasets SET s3_location = %s WHERE id = %s",
                (original[1], original[0]),
            )

    assert inbox(client, fx.viewer_sub)["total"] == before
    assert "Should never arrive" not in str(
        inbox(client, fx.viewer_sub)["items"]
    )


def test_a_member_of_another_workspace_still_cannot_be_notified(
    client: TestClient, fx: Fixture, alert_type: str, alert: str
) -> None:
    """p.96 is about *this* workspace's data.

    A mutant that dropped the workspace from the permission query survived the
    strict-mode test above, because that test's outsider is a member of no
    workspace at all — so "everybody who is a member of something" and "the
    members of this workspace" were the same set.

    **And the actor has to be in both**, which is the second half and the one
    that took instrumenting to find. `workspace_members` is itself under RLS,
    so a membership in a workspace the *actor* cannot see is invisible to the
    permission query whether or not it filters on the workspace — the explicit
    filter is only observable when the actor can see both memberships and one
    of them is still the wrong workspace.
    """
    import psycopg

    from test_api import ADMIN_DSN

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        other = conn.execute(
            """INSERT INTO workspaces (organisation_id, name, slug, s3_prefix,
                                       pg_schema, search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (fx.org, f"Other {fx.tag}", f"other-{fx.tag}",
             f"workspaces/other-{fx.tag}/", f"ws_other_{fx.tag}",
             f"ws-other-{fx.tag}-", fx.owner),
        ).fetchone()[0]
        for member in (fx.outsider, fx.editor):
            conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (%s,%s,'editor')",
                (other, member),
            )

    action = make_action(client, fx, alert_type)
    assert define(client, fx, action, {
        "recipients": {"kind": "static", "user_ids": [str(fx.outsider)]},
        "subject": "Wrong workspace", "body": "b",
    }).status_code == 200

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": alert, "values": {"priority": "nope"}},
    )
    assert r.status_code == 422, r.text
    assert inbox(client, fx.outsider_sub)["total"] == 0
