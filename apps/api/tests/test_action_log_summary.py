"""The action log's optional Summary and object reference properties (§586;
db 0121; `action-types` p.167-168).

    "[Optional] Summary: A customizable string to describe the action
     [Optional] Property values of object reference parameters (this is not
     supported for object reference parameters if allow multiple values is
     enabled)" (p.168)

    "...the action log supports capturing context beyond specific object
     edits, such as ... the state of the world (as represented by the
     Ontology) at the time of action submission." (p.167)

p.168's Close Alerts example, with the alert's Priority kept beside the
decision: the summary and the properties are the objects *as they were* when
the action was submitted, which the test shows by keeping a property the same
action then changes.
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
from src.services import action_log  # noqa: E402

ALERTS = b"alert_id,status,priority\nA1,open,high\nA2,open,low\nA3,open,high\nA4,open,low\n"
SUMMARY = "Closed a {{{also.priority}}} alert that was {{{also.status}}}, as {{{status}}}"


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
def alerts(client: TestClient, fx: Fixture) -> dict:
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"Summary alerts {fx.tag}"},
                    files={"file": ("alerts.csv", io.BytesIO(ALERTS), "text/csv")})
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"salert_{fx.tag}", "display_name": f"Summary alert {fx.tag}",
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
    return {"type_id": type_id}


def close_alert(client, fx, alerts) -> str:
    """p.168's Close Alerts: a status for this alert and, through `also`, for
    another, plus a list of related alerts that p.168 says cannot be kept."""
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": alerts["type_id"], "api_name": f"close_{uuid.uuid4().hex[:6]}",
        "display_name": "Close alert", "editable_properties": ["status"]})
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{action_id}/definition",
                   headers=hdr(fx.editor_sub), json={
                       "parameters": [
                           {"api_name": "status", "display_name": "Status",
                            "data_type": "string"},
                           {"api_name": "also", "display_name": "Also", "data_type": "object",
                            "object_type_id": alerts["type_id"]},
                           {"api_name": "related", "display_name": "Related",
                            "data_type": "array", "array_of": "object",
                            "object_type_id": alerts["type_id"]}],
                       "rules": [
                           {"kind": "modify_object", "config": {
                               "property": "status", "parameter": "status"}},
                           {"kind": "modify_object", "config": {
                               "object_type": alerts["type_id"], "object": "also",
                               "property": "status", "parameter": "status"}}],
                       "criteria": []})
    assert r.status_code == 200, r.text
    return action_id


def enable(client, fx, action_id: str, **body):
    return client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub),
                       json=body or None)


def objects(client, fx, type_id: str) -> dict[str, dict]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances?limit=100",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {i["primary_key"]: i for i in r.json()["items"]}


def apply(client, fx, alerts, action_id: str, key: str, values: dict) -> dict:
    held = objects(client, fx, alerts["type_id"])
    values = {k: held[v]["id"] if k == "also" else v for k, v in values.items()}
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": held[key]["id"], "values": values})
    assert r.status_code == 200, r.text
    return r.json()


def entry(client, fx, log_type: str, run: dict) -> dict:
    return objects(client, fx, log_type)[run["run_id"]]["properties"]


@pytest.fixture(scope="module")
def logged(client, fx, alerts) -> dict:
    action_id = close_alert(client, fx, alerts)
    r = enable(client, fx, action_id, summary=SUMMARY,
               reference_properties={"also": ["priority", "status"]})
    assert r.status_code == 201, r.text
    return {"action_id": action_id, **r.json()}


# ---- turning it on --------------------------------------------------------------
def test_the_log_keeps_its_summary_and_reference_properties(client, fx, logged) -> None:
    assert logged["log_summary"] == SUMMARY
    assert logged["log_reference_properties"] == {"also": ["priority", "status"]}
    got = client.get(f"{wbase(fx)}/action-types/{logged['action_id']}",
                     headers=hdr(fx.viewer_sub)).json()
    assert (got["log_summary"], got["log_reference_properties"]) == (
        SUMMARY, {"also": ["priority", "status"]})
    log_type = client.get(f"{wbase(fx)}/object-types/{logged['log_object_type_id']}",
                          headers=hdr(fx.viewer_sub)).json()
    names = {p["api_name"] for p in log_type["properties"]}
    assert {"summary", "ref_also__priority", "ref_also__status"} <= names


@pytest.mark.parametrize("body, said", [
    ({"summary": "Closed {{{nobody}}}"},
     "the summary references 'nobody', which is neither a parameter"),
    ({"summary": "Closed {{{also.colour}}}"}, "'also' has no 'colour' property"),
    ({"reference_properties": {"status": ["priority"]}},
     "'status' is not a single object reference"),
    # p.168: "not supported for object reference parameters if allow multiple
    # values is enabled".
    ({"reference_properties": {"related": ["priority"]}},
     "'related' is not a single object reference"),
    ({"reference_properties": {"also": ["colour"]}}, "'also' has no 'colour' property"),
    ({"reference_properties": {"also": []}}, "name at least one property of 'also'"),
    ({"reference_properties": {"gone": ["priority"]}}, "'gone' is not a parameter"),
])
def test_what_could_not_be_kept_is_refused_before_anything_is_made(
    client, fx, alerts, body, said
) -> None:
    action_id = close_alert(client, fx, alerts)
    r = enable(client, fx, action_id, **body)
    assert r.status_code == 422, r.text
    assert said in r.text
    got = client.get(f"{wbase(fx)}/action-types/{action_id}", headers=hdr(fx.viewer_sub)).json()
    assert got["log_object_type_id"] is None


def test_a_log_turned_on_with_neither_is_554s(client, fx, alerts) -> None:
    action_id = close_alert(client, fx, alerts)
    r = client.post(f"{pbase(fx)}/actions/{action_id}/log", headers=hdr(fx.editor_sub))
    assert r.status_code == 201, r.text
    assert (r.json()["log_summary"], r.json()["log_reference_properties"]) == (None, {})
    run = apply(client, fx, alerts, action_id, "A4", {"status": "closed", "also": "A4"})
    got = entry(client, fx, r.json()["log_object_type_id"], run)
    assert got.get("summary") is None


# ---- each submission --------------------------------------------------------------
def test_an_entry_has_the_summary_and_the_state_before_the_edit(client, fx, alerts, logged):
    """The action closes `also`, and its entry says it *was* open: p.167's
    state of the world at the time of submission, not after it."""
    run = apply(client, fx, alerts, logged["action_id"], "A1",
                {"status": "closed", "also": "A2"})
    got = entry(client, fx, logged["log_object_type_id"], run)
    assert got["summary"] == "Closed a low alert that was open, as closed"
    assert (got["ref_also__priority"], got["ref_also__status"]) == ("low", "open")
    assert objects(client, fx, alerts["type_id"])["A2"]["properties"]["status"] == "closed"


def test_the_summary_can_be_changed_and_old_entries_keep_theirs(client, fx, alerts, logged):
    first = apply(client, fx, alerts, logged["action_id"], "A1", {"status": "shut", "also": "A3"})
    r = client.put(f"{wbase(fx)}/action-types/{logged['action_id']}/log/summary",
                   headers=hdr(fx.editor_sub), json={"summary": "Set to {{{status}}}"})
    assert r.status_code == 200, r.text
    second = apply(client, fx, alerts, logged["action_id"], "A1",
                   {"status": "reopened", "also": "A3"})
    log_type = logged["log_object_type_id"]
    assert entry(client, fx, log_type, second)["summary"] == "Set to reopened"
    assert entry(client, fx, log_type, first)["summary"].endswith("as shut")
    refused = client.put(f"{wbase(fx)}/action-types/{logged['action_id']}/log/summary",
                         headers=hdr(fx.editor_sub), json={"summary": "{{{nope}}}"})
    assert refused.status_code == 422, refused.text
    cleared = client.put(f"{wbase(fx)}/action-types/{logged['action_id']}/log/summary",
                         headers=hdr(fx.editor_sub), json={"summary": "  "})
    assert cleared.json() == {"summary": None}
    third = apply(client, fx, alerts, logged["action_id"], "A1", {"status": "shut", "also": "A3"})
    assert entry(client, fx, log_type, third).get("summary") is None


def test_a_summary_needs_a_log(client, fx, alerts) -> None:
    action_id = close_alert(client, fx, alerts)
    r = client.put(f"{wbase(fx)}/action-types/{action_id}/log/summary",
                   headers=hdr(fx.editor_sub), json={"summary": "x"})
    assert r.status_code == 422, r.text
    assert "has no action log" in r.text


# ---- the pure parts -------------------------------------------------------------
def test_a_long_summary_is_shortened_and_says_so() -> None:
    out = action_log.extra_columns(
        summary="{{{note}}}", references={}, values={"note": "x" * 2000}, objects={},
        actor=None)
    assert len(out["summary"]) == action_log.MAX_SUMMARY
    assert out["summary"].endswith("...")


def test_an_unset_reference_is_a_gap() -> None:
    """An object parameter left empty has no object to read: its properties
    are empty, and its references in the summary render as gaps (p.92)."""
    out = action_log.extra_columns(
        summary="a {{{also.priority}}} alert", references={"also": ["priority"]},
        values={}, objects={}, actor=None)
    assert out == {"summary": "a  alert", "ref_also__priority": None}


def test_current_user_is_the_submitter() -> None:
    out = action_log.extra_columns(
        summary="by {{{current_user}}}", references={}, values={}, objects={},
        actor={"display_name": "Ana"})
    assert out["summary"] == "by Ana"


def test_a_property_is_kept_once() -> None:
    kept = action_log.check_references(
        {"also": ["priority", "priority"]},
        parameters=[{"api_name": "also", "data_type": "object"}],
        object_types={"also": "t"}, properties_by_type={"t": {"priority": "string"}})
    assert kept == {"also": ["priority"]}


def test_a_log_keeps_at_most_twenty_properties() -> None:
    props = [f"p{n}" for n in range(action_log.MAX_REFERENCES + 1)]
    declared = {p: "string" for p in props}
    with pytest.raises(ValueError, match="at most 20 reference properties"):
        action_log.check_references(
            {"also": props}, parameters=[{"api_name": "also", "data_type": "object"}],
            object_types={"also": "t"}, properties_by_type={"t": declared})
    kept = action_log.check_references(
        {"also": props[:-1]}, parameters=[{"api_name": "also", "data_type": "object"}],
        object_types={"also": "t"}, properties_by_type={"t": declared})
    assert len(kept["also"]) == action_log.MAX_REFERENCES


def test_current_user_needs_no_parameter() -> None:
    assert action_log.check_summary(
        "by {{{current_user}}}", parameters=[], object_types={},
        properties_by_type={}) == "by {{{current_user}}}"


def test_an_object_parameter_with_no_type_has_nothing_to_keep() -> None:
    with pytest.raises(ValueError, match="does not say which object type it holds"):
        action_log.check_references(
            {"also": ["priority"]}, parameters=[{"api_name": "also", "data_type": "object"}],
            object_types={}, properties_by_type={"t": {"priority": "string"}})


def test_a_kept_property_is_text_as_its_column_is() -> None:
    out = action_log.extra_columns(
        summary=None, references={"also": ["points", "done"]}, values={},
        objects={"also": {"points": 3, "done": True}}, actor=None)
    assert (out["ref_also__points"], out["ref_also__done"]) == ("3", "true")


def test_a_log_made_before_586_is_not_given_a_summary() -> None:
    """Its dataset has no summary column, and a value for a column that is not
    there would be written nowhere."""
    from datetime import datetime

    row = action_log.log_row(
        run_id=uuid.uuid4(), action_type={"id": uuid.uuid4()}, user_id=uuid.uuid4(),
        at=datetime(2026, 9, 27), edited=[], bound={}, columns={"action_rid"},
        extra={"summary": "x", "ref_also__points": "3"})
    assert "summary" not in row and "ref_also__points" not in row
