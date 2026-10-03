"""The action log: every submission of an action type, as an object (§554;
db 0116; `action-types` p.167-168).

    "Action log object types map one-to-one with action types. Submitting an
     action generates a single new object of the corresponding action log
     object type. This newly-created object is automatically linked to all
     edited objects." (p.167)

The log is an ordinary object type over an ordinary dataset, so the claims are
about objects: one per submission, carrying p.168's schema, linked to what the
submission edited - and, the dataset being the record (decision 0008), still
there after a re-sync.
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
ALERTS = b"alert_id,status,priority\nA1,open,high\nA2,open,low\nA3,open,high\n"


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


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """p.168's own example: a Close Alerts action over Alerts."""
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"Alerts {fx.tag}"},
                    files={"file": ("alerts.csv", io.BytesIO(ALERTS), "text/csv")})
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"alert_{fx.tag}", "display_name": f"Alert {fx.tag}",
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
        "object_type_id": type_id, "api_name": f"close_alert_{fx.tag}",
        "display_name": "Close alert", "editable_properties": ["status"]})
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{action_id}/definition",
                   headers=hdr(fx.editor_sub), json={
                       "parameters": [
                           {"api_name": "status", "display_name": "Status",
                            "data_type": "string"},
                           {"api_name": "also", "display_name": "Also", "data_type": "object",
                            "object_type_id": type_id, "required": False}],
                       "rules": [
                           {"kind": "modify_object", "config": {
                               "property": "status", "parameter": "status"}},
                           {"kind": "modify_object", "config": {
                               "object_type": type_id, "object": "also",
                               "property": "status", "parameter": "status"}}],
                       "criteria": []})
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub))
    assert r.status_code == 201, r.text
    return {"type_id": type_id, "action_id": action_id, **r.json()}


def objects(client, fx, type_id: str) -> dict[str, dict]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances?limit=100",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {i["primary_key"]: i for i in r.json()["items"]}


def apply(client, fx, world, key: str, values: dict) -> dict:
    alerts = objects(client, fx, world["type_id"])
    values = {k: alerts[v]["id"] if k == "also" else v for k, v in values.items()}
    r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/execute",
                    headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts[key]["id"], "values": values})
    assert r.status_code == 200, r.text
    return r.json()


def log_of(client, fx, world, run: dict) -> dict:
    return objects(client, fx, world["log_object_type_id"])[run["run_id"]]["properties"]


def action_type(client, fx, world) -> dict:
    r = client.get(f"{wbase(fx)}/action-types/{world['action_id']}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


# ---- turning it on -----------------------------------------------------------

def test_the_log_is_a_log_object_type_named_for_its_action(client, fx, world) -> None:
    """p.167: "all action log object types are prefaced with [LOG]"."""
    at = action_type(client, fx, world)
    assert (at["log_object_type_id"], at["log_link_type_id"]) == (
        world["log_object_type_id"], world["log_link_type_id"])
    r = client.get(f"{wbase(fx)}/object-types/{world['log_object_type_id']}",
                   headers=hdr(fx.viewer_sub))
    assert r.json()["display_name"] == "[LOG] Close alert", r.json()
    # p.168's schema, and the one parameter whose value it can hold: `also`
    # is an object reference, whose property values are kept only when asked
    # for (§586). The summary column is always made, so a template can be
    # written later.
    assert sorted(p["api_name"] for p in r.json()["properties"]) == sorted([
        "action_type_rid", "action_type_version", "timestamp", "user_id",
        "edited_objects", "param_status", "summary"])


def test_a_second_log_is_refused(client, fx, world) -> None:
    r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/log", headers=hdr(fx.editor_sub))
    assert r.status_code == 409 and "already has an action log" in r.json()["detail"], r.text


def test_a_log_needs_a_workspace_editor(client, fx, world) -> None:
    """A project editor who only views the workspace cannot add an object
    type by hand, so cannot add one by turning a log on."""
    tag = uuid.uuid4().hex[:6]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        custom = db.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode) "
            "VALUES (%s, %s, %s, %s, 'custom') RETURNING id",
            (fx.workspace, f"Custom {tag}", f"custom-{tag}", fx.owner),
        ).fetchone()[0]
        db.execute("INSERT INTO project_members (project_id, user_id, role) "
                   "VALUES (%s, %s, 'editor')", (custom, fx.viewer))
    r = client.post(f"{wbase(fx)}/projects/{custom}/actions/{world['action_id']}/log",
                    headers=hdr(fx.viewer_sub))
    assert r.status_code == 403 and "workspace editor" in r.json()["detail"], r.text


def test_an_interface_action_has_no_one_type_to_link_its_log_to() -> None:
    import anyio
    from src.services import action_log
    with pytest.raises(ValueError, match="no one object type"):
        anyio.run(lambda: action_log.enable(
            None, None, workspace_id=uuid.uuid4(), project_id=uuid.uuid4(),
            action_type={"id": uuid.uuid4(), "object_type_id": None}, by=uuid.uuid4()))


# ---- a submission ------------------------------------------------------------

def test_a_submission_is_one_log_object_with_p168s_schema(client, fx, world) -> None:
    # `also` naming the subject itself: one object edited, listed once.
    run = apply(client, fx, world, "A1", {"status": "closed", "also": "A1"})
    got = log_of(client, fx, world, run)
    at = action_type(client, fx, world)
    assert got["action_type_rid"] == world["action_id"]
    assert got["action_type_version"] == at["version"]
    assert got["user_id"] == str(fx.editor)
    assert json.loads(got["edited_objects"]) == ["A1"]
    assert got["param_status"] == "closed"
    assert got["timestamp"]


def test_the_log_object_is_linked_to_every_object_it_edited(client, fx, world) -> None:
    """p.167's ten alerts closed at once, as two: one log object linked to both
    - and each alert linked back to it."""
    run = apply(client, fx, world, "A2", {"status": "closed", "also": "A3"})
    assert json.loads(log_of(client, fx, world, run)["edited_objects"]) == ["A2", "A3"]
    log = objects(client, fx, world["log_object_type_id"])[run["run_id"]]
    r = client.get(f"{wbase(fx)}/object-types/{world['log_object_type_id']}/instances/"
                   f"{log['id']}/links", headers=hdr(fx.viewer_sub))
    group = next(g for g in r.json() if g["link_type_id"] == world["log_link_type_id"])
    assert sorted(i["primary_key"] for i in group["items"]) == ["A2", "A3"]
    a3 = objects(client, fx, world["type_id"])["A3"]
    r = client.get(f"{wbase(fx)}/object-types/{world['type_id']}/instances/{a3['id']}/links",
                   headers=hdr(fx.viewer_sub))
    back = next(g for g in r.json() if g["link_type_id"] == world["log_link_type_id"])
    assert run["run_id"] in [i["primary_key"] for i in back["items"]]


def test_the_version_is_the_action_types_at_submission(client, fx, world) -> None:
    """p.168: "Version number that auto-increments each time an action type is
    updated"."""
    before = action_type(client, fx, world)
    r = client.put(f"{wbase(fx)}/action-types/{world['action_id']}/definition",
                   headers=hdr(fx.editor_sub), json={
                       "parameters": [dict(p) for p in before["parameters"]],
                       "rules": [{"kind": r["kind"], "config": r["config"]}
                                 for r in before["rules"]],
                       "criteria": []})
    assert r.status_code == 200, r.text
    assert r.json()["version"] == before["version"] + 1
    run = apply(client, fx, world, "A1", {"status": "reopened", "also": "A1"})
    assert log_of(client, fx, world, run)["action_type_version"] == before["version"] + 1


def test_the_log_survives_a_re_sync_of_its_dataset(client, fx, world) -> None:
    """The dataset is the record (decision 0008): the index's log object is a
    projection of a row, not the only copy."""
    run = apply(client, fx, world, "A3", {"status": "triaged", "also": "A3"})
    r = client.get(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub))
    source = next(s for s in r.json() if s["object_type_id"] == world["log_object_type_id"])
    r = client.post(f"{pbase(fx)}/object-type-sources/{source['id']}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert log_of(client, fx, world, run)["param_status"] == "triaged"


def test_a_run_that_writes_nothing_logs_nothing(client, fx, world) -> None:
    """A failed submission changed nothing, so there is no decision to record."""
    before = len(objects(client, fx, world["log_object_type_id"]))
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        # A value the action type's own check lets through and the dataset's
        # column cannot hold is the one failure an apply reports as `ok: false`.
        db.execute("UPDATE object_type_sources SET primary_key_column = 'gone' "
                   "WHERE object_type_id = %s", (world["type_id"],))
        try:
            alerts = objects(client, fx, world["type_id"])
            r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/execute",
                            headers=hdr(fx.editor_sub),
                            json={"instance_id": alerts["A1"]["id"],
                                  "values": {"status": "x", "also": alerts["A1"]["id"]}})
        finally:
            db.execute("UPDATE object_type_sources SET primary_key_column = 'alert_id' "
                       "WHERE object_type_id = %s", (world["type_id"],))
    assert r.status_code == 200 and r.json()["ok"] is False, r.text
    assert len(objects(client, fx, world["log_object_type_id"])) == before


def test_deleting_the_log_type_turns_the_log_off(client, fx, world) -> None:
    """db 0116: SET NULL, and the action goes on without one."""
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["type_id"], "api_name": f"tag_{uuid.uuid4().hex[:6]}",
        "display_name": "Tag alert", "editable_properties": ["priority"]})
    tag = r.json()["id"]
    made = client.post(f"{pbase(fx)}/actions/{tag}/log", headers=hdr(fx.editor_sub)).json()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("DELETE FROM object_types WHERE id = %s", (made["log_object_type_id"],))
    r = client.get(f"{wbase(fx)}/action-types/{tag}", headers=hdr(fx.viewer_sub))
    assert r.json()["log_object_type_id"] is None, r.json()
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{tag}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts["A2"]["id"], "values": {"priority": "mid"}})
    assert r.status_code == 200 and r.json()["ok"], r.text


def test_the_log_times_its_entries_as_a_re_sync_does(client, fx, world) -> None:
    """The timestamp the index is given is the one a re-sync reads back, so an
    entry does not change its time when its dataset is synced."""
    run = apply(client, fx, world, "A2", {"status": "held", "also": "A2"})
    before = log_of(client, fx, world, run)["timestamp"]
    r = client.get(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub))
    source = next(s for s in r.json() if s["object_type_id"] == world["log_object_type_id"])
    client.post(f"{pbase(fx)}/object-type-sources/{source['id']}/sync",
                headers=hdr(fx.editor_sub))
    assert log_of(client, fx, world, run)["timestamp"] == before


def make_action(client, fx, world, *, parameters: list, rules: list) -> str:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["type_id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": f"Act {uuid.uuid4().hex[:4]}", "editable_properties": ["status"]})
    action_id = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{action_id}/definition",
                   headers=hdr(fx.editor_sub),
                   json={"parameters": parameters, "rules": rules, "criteria": []})
    assert r.status_code == 200, r.text
    return action_id


STATUS = {"api_name": "status", "display_name": "Status", "data_type": "string"}
OTHER = {"api_name": "other", "display_name": "Other", "data_type": "object"}


def test_an_action_that_edits_only_another_object_logs_only_that_one(
    client, fx, world
) -> None:
    action_id = make_action(
        client, fx, world, parameters=[STATUS, {**OTHER, "object_type_id": world["type_id"]}],
        rules=[{"kind": "modify_object", "config": {
            "object_type": world["type_id"], "object": "other", "property": "status",
            "parameter": "status"}}])
    made = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub)).json()
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts["A1"]["id"],
                          "values": {"status": "escalated", "other": alerts["A2"]["id"]}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    got = objects(client, fx, made["log_object_type_id"])[r.json()["run_id"]]["properties"]
    assert json.loads(got["edited_objects"]) == ["A2"]


def test_a_parameter_added_after_the_log_is_logged_too(client, fx, world) -> None:
    """The definition's save gives the log its column (§792; until then a
    parameter added later was left out)."""
    action_id = make_action(client, fx, world, parameters=[STATUS], rules=[
        {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}])
    made = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub)).json()
    r = client.put(f"{wbase(fx)}/action-types/{action_id}/definition", headers=hdr(fx.editor_sub),
                   json={"parameters": [STATUS, {"api_name": "reason",
                                                 "display_name": "Reason",
                                                 "data_type": "string"}],
                         "rules": [{"kind": "modify_object", "config": {
                             "property": "status", "parameter": "status"}}],
                         "criteria": []})
    assert r.status_code == 200, r.text
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts["A3"]["id"],
                          "values": {"status": "muted", "reason": "noise"}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    got = objects(client, fx, made["log_object_type_id"])[r.json()["run_id"]]["properties"]
    assert (got["param_status"], got["param_reason"]) == ("muted", "noise"), got


def test_a_log_can_be_made_again_after_its_type_is_deleted(client, fx, world) -> None:
    """Its datasets outlive the type, so the second log's are named around them;
    and a type already called `log_<action>` is named around too."""
    action_id = make_action(client, fx, world, parameters=[STATUS], rules=[
        {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}])
    api_name = client.get(f"{wbase(fx)}/action-types/{action_id}",
                          headers=hdr(fx.viewer_sub)).json()["api_name"]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"log_{api_name}", "display_name": f"Somebody's log_{api_name}",
        "properties": [{"api_name": "note", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    first = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub))
    assert first.status_code == 201, first.text
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        db.execute("DELETE FROM object_types WHERE id = %s",
                   (first.json()["log_object_type_id"],))
    again = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub))
    assert again.status_code == 201, again.text


def test_a_log_the_person_applying_cannot_write_refuses_the_action(
    client, fx, world
) -> None:
    """p.167: "users need the appropriate permissions for the action log object
    type". The log lives in a project this editor is not in."""
    tag = uuid.uuid4().hex[:6]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        hidden = db.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode) "
            "VALUES (%s, %s, %s, %s, 'custom') RETURNING id",
            (fx.workspace, f"Logs {tag}", f"logs-{tag}", fx.owner),
        ).fetchone()[0]
    action_id = make_action(client, fx, world, parameters=[STATUS], rules=[
        {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}])
    r = client.post(f"{wbase(fx)}/projects/{hidden}/actions/{action_id}/log",
                    headers=hdr(fx.admin_sub))
    assert r.status_code == 201, r.text
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts["A1"]["id"], "values": {"status": "x"}})
    assert r.status_code == 403 and "action log you cannot write" in r.json()["detail"], r.text


def test_a_parameter_value_is_kept_as_text_the_way_the_dataset_holds_it(
    client, fx, world
) -> None:
    """A number or a flag is text in the log, in the index as after a re-sync -
    and the index holds p.168's fields, not the key as a property besides."""
    action_id = make_action(client, fx, world, parameters=[
        STATUS, {"api_name": "count", "display_name": "Count", "data_type": "integer"},
        {"api_name": "urgent", "display_name": "Urgent", "data_type": "boolean"}], rules=[
        {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}])
    made = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub)).json()
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts["A1"]["id"],
                          "values": {"status": "counted", "count": 5, "urgent": True}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    got = objects(client, fx, made["log_object_type_id"])[r.json()["run_id"]]["properties"]
    assert (got["param_count"], got["param_urgent"]) == ("5", "true"), got
    assert "action_rid" not in got, got


def test_only_edits_of_the_linked_type_are_linked(client, fx, world) -> None:
    """A submission that also creates an object of another type lists its key
    among the edited objects, and links only what the log's link reaches - even
    where the other type's key happens to be an alert's."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"Notes {tag}"},
                    files={"file": ("notes.csv", io.BytesIO(b"note_id,text\nN1,x\n"),
                                    "text/csv")})
    notes_ds = r.json()["id"]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"note_{tag}", "display_name": f"Note {tag}",
        "properties": [{"api_name": "text", "data_type": "string"}]})
    notes = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": notes, "dataset_id": notes_ds, "primary_key_column": "note_id",
        "column_mappings": {"text": "text"}})
    assert r.status_code == 201, r.text
    action_id = make_action(client, fx, world, parameters=[
        STATUS, {"api_name": "key", "display_name": "Key", "data_type": "string"}], rules=[
        {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}},
        {"kind": "create_object", "config": {
            "object_type": notes, "primary_key": "key", "properties": {"text": "status"}}}])
    made = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub)).json()
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": alerts["A1"]["id"],
                          "values": {"status": "noted", "key": "A3"}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    log = objects(client, fx, made["log_object_type_id"])[r.json()["run_id"]]
    assert json.loads(log["properties"]["edited_objects"]) == ["A1", "A3"]
    r = client.get(f"{wbase(fx)}/object-types/{made['log_object_type_id']}/instances/"
                   f"{log['id']}/links", headers=hdr(fx.viewer_sub))
    group = next(g for g in r.json() if g["link_type_id"] == made["log_link_type_id"])
    assert [i["primary_key"] for i in group["items"]] == ["A1"]
