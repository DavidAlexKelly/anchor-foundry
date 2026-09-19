"""A module's usage metrics (§396; `workshop` p.185-188).

    "Action metrics show how many times each action in the module has been
     successfully submitted… Select an action to view which widgets in the
     module use that action." (p.185)

**The reading this file pins down.** "Each action in the module" is two
readings - submissions *of the actions this module uses*, or submissions *made
from this module* - and p.186 settles it: "available by default for all modules
and do not require any additional configuration." A per-module attribution
needs a column and a writer on every submit path, and could never answer for a
module older than the column. So the module scopes which actions are *listed*.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import workshop_metrics as wm  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


# ---- which actions a module uses --------------------------------------------
def test_a_widget_that_names_an_action_is_found() -> None:
    document = {
        "format": 2,
        "layout": {"btn": {"type": {"resolvedName": "CanvasActionForm"},
                           "props": {"actionTypeId": "a1"}}},
        "events": {},
    }
    assert wm.module_actions(document) == {"a1": [{"node": "btn", "via": "widget"}]}


def test_an_event_that_runs_an_action_is_found_too() -> None:
    """**Two places name an action and both count.** A module whose only submit
    is an event would otherwise report no actions at all, which reads as
    "nobody uses this" rather than "we looked in one place"."""
    document = {
        "format": 2,
        "layout": {},
        "events": {"e1": {"id": "e1", "trigger": {"node": "go", "on": "click"},
                          "effects": [{"type": "run_action",
                                       "config": {"action": "a2", "values": {}}}]}},
    }
    assert wm.module_actions(document) == {"a2": [{"node": "go", "via": "event"}]}


def test_one_action_used_twice_reports_both_places() -> None:
    """p.185's "which widgets in the module use that action" is a list, so an
    action used by a form and by a button is two rows rather than one."""
    document = {
        "format": 2,
        "layout": {"f": {"type": {"resolvedName": "CanvasActionForm"},
                         "props": {"actionTypeId": "a1"}}},
        "events": {"e1": {"id": "e1", "trigger": {"node": "b", "on": "click"},
                          "effects": [{"type": "run_action",
                                       "config": {"action": "a1", "values": {}}}]}},
    }
    used = wm.module_actions(document)
    assert sorted(u["via"] for u in used["a1"]) == ["event", "widget"]


def test_a_module_that_runs_nothing_has_no_actions() -> None:
    assert wm.module_actions({"format": 2, "layout": {}, "events": {}}) == {}


def test_a_document_that_is_not_one_is_not_a_crash() -> None:
    """Read at view time rather than at save time, so it must survive whatever
    is stored - including a v1 document, which has no `events` at all."""
    assert wm.module_actions(None) == {}
    assert wm.module_actions({"layout": "nope", "events": 7}) == {}


# ---- the counts -------------------------------------------------------------
def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/canvas-apps"


@pytest.fixture()
def module_with_action(client: TestClient, fx: Fixture):
    """An action type, a module whose button runs it, and submissions placed on
    either side of the period boundary."""
    tag = uuid.uuid4().hex[:8]
    otype = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"order_{tag}", "display_name": f"Order {tag}",
              "properties": [{"api_name": "state", "display_name": "State",
                              "data_type": "string"}]},
    ).json()
    action = client.post(
        f"/api/workspaces/{fx.workspace}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": otype["id"], "api_name": f"ship_{tag}",
              "display_name": f"Ship {tag}", "editable_properties": ["state"]},
    ).json()

    made = client.post(base(fx), headers=hdr(fx.editor_sub),
                       json={"name": f"Metrics {tag}"})
    assert made.status_code == 201, made.text
    app_id = made.json()["id"]
    saved = client.put(
        f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
        json={"definition": {
            "format": 2,
            "layout": {"ROOT": {"type": {"resolvedName": "CanvasContainer"},
                                "nodes": ["form"]},
                       "form": {"type": {"resolvedName": "CanvasActionForm"},
                                "props": {"actionTypeId": action["id"]},
                                "parent": "ROOT"}},
            "variables": {}, "events": {},
        }},
    )
    assert saved.status_code == 200, saved.text
    return {"app_id": app_id, "action_id": action["id"], "name": action["display_name"]}


def submit(action_id: str, *, days_ago: float, status: str = "succeeded") -> None:
    """A run, placed in time. Written directly: what is under test is the
    counting, and driving the real submit path would put every run at `now`."""
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO action_runs (action_type_id, status, started_at, finished_at)
               VALUES (%s, %s, %s, %s)""",
            (action_id, status, when, when),
        )


def metrics(client: TestClient, fx: Fixture, app_id: str, days: int | None = None):
    url = f"{base(fx)}/{app_id}/metrics" + (f"?days={days}" if days else "")
    return client.get(url, headers=hdr(fx.viewer_sub))


def test_the_module_lists_its_action_with_its_submissions(
    client: TestClient, fx: Fixture, module_with_action
) -> None:
    submit(module_with_action["action_id"], days_ago=1)
    submit(module_with_action["action_id"], days_ago=2)
    r = metrics(client, fx, module_with_action["app_id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["days"] == 30
    (row,) = body["actions"]
    assert row["display_name"] == module_with_action["name"]
    assert row["submissions"] == 2
    assert row["used_by"] == [{"node": "form", "via": "widget"}]


def test_only_successful_submissions_are_counted(
    client: TestClient, fx: Fixture, module_with_action
) -> None:
    """p.185: "how many times each action has been **successfully** submitted".
    Failures belong to the action type's own metrics screen (§323), where
    somebody is debugging the action rather than reading how a module is used.
    """
    submit(module_with_action["action_id"], days_ago=1)
    submit(module_with_action["action_id"], days_ago=1, status="failed")
    r = metrics(client, fx, module_with_action["app_id"])
    (row,) = r.json()["actions"]
    assert row["submissions"] == 1


def test_the_previous_period_is_the_same_length_immediately_before(
    client: TestClient, fx: Fixture, module_with_action
) -> None:
    """p.188: "when viewing the last 30 days, the percentage change compares
    against the 30 days before that"."""
    submit(module_with_action["action_id"], days_ago=1)
    submit(module_with_action["action_id"], days_ago=40)
    submit(module_with_action["action_id"], days_ago=100)  # outside both
    r = metrics(client, fx, module_with_action["app_id"])
    (row,) = r.json()["actions"]
    assert row["submissions"] == 1
    assert row["previous"] == 1


def test_the_period_changes_what_is_counted(
    client: TestClient, fx: Fixture, module_with_action
) -> None:
    """p.188's three windows. A 40-day-old submission is outside 30 days and
    inside 90, which is the only way to tell the picker is doing anything."""
    submit(module_with_action["action_id"], days_ago=40)
    assert metrics(client, fx, module_with_action["app_id"], 30).json()[
        "actions"][0]["submissions"] == 0
    assert metrics(client, fx, module_with_action["app_id"], 90).json()[
        "actions"][0]["submissions"] == 1


def test_a_window_the_pages_do_not_offer_is_refused(
    client: TestClient, fx: Fixture, module_with_action
) -> None:
    """**Refused rather than clamped.** p.188 offers three and no others, and a
    panel that asked for 45 days and was quietly given 30 would label the
    answer with the number it asked for."""
    r = metrics(client, fx, module_with_action["app_id"], 45)
    assert r.status_code == 422, r.text
    assert "30 days" in r.json()["detail"]


def test_an_action_nobody_has_used_is_a_row_of_zeroes(
    client: TestClient, fx: Fixture, module_with_action
) -> None:
    """**The most interesting row on the panel**, and an absent one reads as an
    action the module does not have."""
    r = metrics(client, fx, module_with_action["app_id"])
    (row,) = r.json()["actions"]
    assert row["submissions"] == 0
    assert row["previous"] == 0


def test_a_module_that_runs_nothing_reports_no_actions(
    client: TestClient, fx: Fixture
) -> None:
    made = client.post(base(fx), headers=hdr(fx.editor_sub),
                       json={"name": f"Empty {uuid.uuid4().hex[:8]}"})
    app_id = made.json()["id"]
    r = metrics(client, fx, app_id)
    assert r.status_code == 200, r.text
    assert r.json()["actions"] == []
