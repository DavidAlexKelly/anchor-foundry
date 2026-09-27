"""The action log for a batch of inline edits (§587; `action-types` p.135,
p.167-168).

    "Inline edits differ in that they are validated and submitted in bulk."
    (p.136)

    "Submitting an action generates a single new object of the corresponding
     action log object type. This newly-created object is automatically linked
     to all edited objects." (p.167)

An Object Table's Submit is several submissions of one action at once, so it
makes one log entry per edit, each linked to the object it edited - written in
the batch's one commit, as a single submission's is in its own. Until §587 a
batch wrote no log at all, so a decision made from a table was the one kind the
log never recorded.
"""
from __future__ import annotations

import io
import json
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)
ALERTS = b"alert_id,status,priority\nB1,open,high\nB2,open,low\nB3,open,high\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"Batch alerts {fx.tag}"},
                    files={"file": ("alerts.csv", io.BytesIO(ALERTS), "text/csv")})
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"balert_{fx.tag}", "display_name": f"Batch alert {fx.tag}",
        "properties": [{"api_name": "status", "data_type": "string"},
                       {"api_name": "priority", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "dataset_id": dataset_id, "primary_key_column": "alert_id",
        "column_mappings": {"status": "status", "priority": "priority"}})
    assert r.status_code == 201, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "api_name": f"set_status_{fx.tag}",
        "display_name": "Set status", "editable_properties": ["status"]})
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    r = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub),
                    json={"summary": "{{{status}}} by {{{current_user}}}"})
    assert r.status_code == 201, r.text
    return {"type_id": type_id, "action_id": action_id, **r.json()}


def objects(client, fx, type_id: str) -> dict[str, dict]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances?limit=100",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {i["primary_key"]: i for i in r.json()["items"]}


def batch(client, fx, world, edits: dict[str, dict]) -> dict:
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/execute-batch",
                    headers=hdr(fx.editor_sub),
                    json={"edits": [{"instance_id": alerts[k]["id"], "values": v}
                                    for k, v in edits.items()]})
    assert r.status_code == 200, r.text
    return r.json()


def runs_of(batch_id: str) -> list[str]:
    with psycopg.connect(ADMIN_DSN) as db:
        return [str(r[0]) for r in db.execute(
            "SELECT id FROM action_runs WHERE batch_id = %s ORDER BY started_at, id",
            (batch_id,)).fetchall()]


def test_each_edit_in_a_batch_is_one_log_entry(client, fx, world) -> None:
    done = batch(client, fx, world, {"B1": {"status": "closed"}, "B2": {"status": "triaged"}})
    assert done["ok"] is True, done
    runs = runs_of(done["batch_id"])
    assert len(runs) == 2
    log = objects(client, fx, world["log_object_type_id"])
    entries = {json.loads(log[run]["properties"]["edited_objects"])[0]: log[run]["properties"]
               for run in runs}
    assert set(entries) == {"B1", "B2"}
    assert entries["B1"]["param_status"] == "closed"
    # The summary names who submitted the batch, as a single submission's does.
    assert entries["B2"]["summary"].startswith("triaged by ")
    assert entries["B2"]["summary"] != "triaged by "
    # One commit for the batch and its record: the edited dataset, the log's
    # and its join table each got the version this batch made.
    assert len(done["dataset_versions"]) == 3


def test_each_entry_is_linked_to_the_object_it_edited(client, fx, world) -> None:
    done = batch(client, fx, world, {"B3": {"status": "closed"}})
    [run] = runs_of(done["batch_id"])
    log = objects(client, fx, world["log_object_type_id"])[run]
    r = client.get(f"{wbase(fx)}/object-types/{world['log_object_type_id']}/instances/"
                   f"{log['id']}/links", headers=hdr(fx.viewer_sub))
    group = next(g for g in r.json() if g["link_type_id"] == world["log_link_type_id"])
    assert [i["primary_key"] for i in group["items"]] == ["B3"]


def test_the_entries_survive_a_re_sync_of_the_log(client, fx, world) -> None:
    """Written to the log's dataset, not only to the index."""
    done = batch(client, fx, world, {"B1": {"status": "reopened"}})
    [run] = runs_of(done["batch_id"])
    r = client.get(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub))
    source = next(s for s in r.json() if s["object_type_id"] == world["log_object_type_id"])
    r = client.post(f"{pbase(fx)}/object-type-sources/{source['id']}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert objects(client, fx, world["log_object_type_id"])[run]["properties"][
        "param_status"] == "reopened"


def test_a_batch_that_fails_logs_nothing(client, fx, world) -> None:
    """p.138's whole-or-nothing: a batch that made no edits made no decision
    to record."""
    before = len(objects(client, fx, world["log_object_type_id"]))
    alerts = objects(client, fx, world["type_id"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("UPDATE object_type_sources SET primary_key_column = 'gone' "
                   "WHERE object_type_id = %s", (world["type_id"],))
        try:
            r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/execute-batch",
                            headers=hdr(fx.editor_sub),
                            json={"edits": [{"instance_id": alerts["B2"]["id"],
                                             "values": {"status": "x"}}]})
        finally:
            db.execute("UPDATE object_type_sources SET primary_key_column = 'alert_id' "
                       "WHERE object_type_id = %s", (world["type_id"],))
    assert r.status_code == 200 and r.json()["ok"] is False, r.text
    assert len(objects(client, fx, world["log_object_type_id"])) == before


def test_a_log_the_editor_cannot_write_refuses_the_batch(client, fx, world) -> None:
    """p.167: "users need the appropriate permissions for the action log
    object type" - refused before anything is written, as a single
    submission is. The log lives in a project this editor is not in."""
    tag = uuid.uuid4().hex[:6]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        hidden = db.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode) "
            "VALUES (%s, %s, %s, %s, 'custom') RETURNING id",
            (fx.workspace, f"Logs {tag}", f"logs-{tag}", fx.owner),
        ).fetchone()[0]
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["type_id"], "api_name": f"hidden_{tag}",
        "display_name": "Hidden", "editable_properties": ["status"]})
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    r = client.post(f"{wbase(fx)}/projects/{hidden}/actions/{action_id}/log",
                    headers=hdr(fx.admin_sub))
    assert r.status_code == 201, r.text
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute-batch",
                    headers=hdr(fx.editor_sub),
                    json={"edits": [{"instance_id": alerts["B1"]["id"],
                                     "values": {"status": "y"}}]})
    assert r.status_code == 403 and "action log you cannot write" in r.json()["detail"], r.text
    assert objects(client, fx, world["type_id"])["B1"]["properties"]["status"] != "y"
