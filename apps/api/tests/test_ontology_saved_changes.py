"""The Ontology's saved changes, across the workspace (§683; `ontology-manager`
p.8).

> "Select the History tab in the homepage sidebar to view a list of all saved
> Ontology changes with details on when the changes were made and the user who
> applied them." (p.8)

The history is the audit log, read: so the first thing tested is that every
ontology write *writes* to it. A route that saved a change and recorded nothing
would be a change the history never shows, with nothing to say one is missing.
"""
from __future__ import annotations

import inspect
import os
import re
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_value_types import client, fx, make_type, wbase  # noqa: E402,F401

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]

#: Ontology routes that write and are **not** a change to its definition, each
#: for a reason: they compute an answer (and POST only to carry a body), or
#: they change something beside the definition.
NOT_CHANGES = {
    "object_type_impact": "reads what a change would do",
    "plan_ontology_import": "reads what a file would do",
    "evaluate_interface_set": "reads objects",
    "execute_function": "a call reads, as a query does (§768)",
    "derived_values_for_page": "reads values",
    "object_type_freshness": "reads freshness",
    "action_parameter_choices": "reads choices",
    "effective_action_parameters": "reads a form",
    "visible_action_sections": "reads a form",
    "save_ontology_cleanup_settings": "the cleanup queue's settings, not the ontology",
    "snooze_object_type": "the cleanup queue's state, not the type",
    "wake_object_type": "the cleanup queue's state, not the type",
    "post_object_comment": "a comment on an object, not on its type",
}
PREFIXES = ("/object-types", "/link-types", "/action-types", "/interfaces",
            "/shared-properties", "/value-types", "/object-type-groups", "/ontology",
            "/promotion-requests", "/functions")


def test_every_ontology_write_is_recorded(client: TestClient) -> None:
    from route_table import api_routes

    missing, seen = [], 0
    for template, methods, route in api_routes(client.app):
        if not methods & {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        tail = re.sub(r"^/api/workspaces/\{workspace_id\}(/projects/\{project_id\})?", "",
                      template)
        if not tail.startswith(PREFIXES) or route.endpoint.__name__ in NOT_CHANGES:
            continue
        seen += 1
        if "audit.record" not in inspect.getsource(route.endpoint):
            missing.append(f"{sorted(methods)[0]} {tail}")
    assert missing == [], missing
    # **Not vacuous** (§837): FastAPI 0.142's route table left this walking
    # nothing and passing. The ontology has 45 writes as of §837; a floor a
    # little under that fails a walk that finds none without failing a route
    # retired on purpose.
    assert seen >= 40, seen


def history(client: TestClient, fx: Fixture, **params) -> list[dict]:
    r = client.get(f"{wbase(fx)}/ontology-history", headers=hdr(fx.viewer_sub), params=params)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def changes(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    kind = make_type(client, fx, [{"api_name": "id", "data_type": "string"},
                                  {"api_name": "street", "data_type": "string"}])
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Placed{tag}", "display_name": f"Placed {tag}",
        "properties": [{"api_name": "street", "display_name": "Street", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    face = r.json()
    r = client.put(f"{wbase(fx)}/interfaces/{face['id']}", headers=hdr(fx.editor_sub), json={
        "display_name": f"Located {tag}", "description": "",
        "properties": [{"api_name": "street", "display_name": "Street", "data_type": "string"}]})
    assert r.status_code == 200, r.text
    r = client.put(f"{wbase(fx)}/object-types/{kind['id']}/interfaces", headers=hdr(fx.editor_sub),
                   json=[{"interface_id": face["id"], "property_mapping": {"street": "street"}}])
    assert r.status_code == 200, r.text
    r = client.put(f"{wbase(fx)}/object-types/{kind['id']}/interfaces", headers=hdr(fx.editor_sub),
                   json=[])
    assert r.status_code == 200, r.text
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Gone{tag}", "display_name": f"Gone {tag}", "properties": []})
    gone = r.json()
    r = client.delete(f"{wbase(fx)}/interfaces/{gone['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text
    # Somebody *using* an action type, recorded against it: not an edit.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO audit_log (organisation_id, user_id, action, resource_type, resource_id,"
            " workspace_id) VALUES (%s, %s, 'action.execute', 'object_type', %s, %s)",
            (fx.org, fx.editor, kind["id"], fx.workspace))
    return {"type": kind, "interface": face, "gone": gone, "tag": tag}


def test_the_history_names_each_change_its_author_and_what_it_was_made_to(
    client: TestClient, fx: Fixture, changes: dict,
) -> None:
    entries = history(client, fx, limit=6)
    assert [e["action"] for e in entries] == [
        "interface.delete", "interface.create", "object_type.set_interfaces",
        "object_type.set_interfaces", "interface.update", "interface.create"]
    # Newest first, each saying who.
    assert all(e["user_id"] == str(fx.editor) for e in entries)
    assert all(e["user_name"] for e in entries)
    assert [e["id"] for e in entries] == sorted((e["id"] for e in entries), reverse=True)
    face = changes["interface"]
    # Named as it is now, though it was created under another name…
    assert entries[5]["resource_id"] == face["id"]
    assert entries[5]["resource_name"] == f"Located {changes['tag']}"
    # …and a deleted one by what the record called it.
    assert entries[0]["resource_name"] == f"Gone{changes['tag']}"
    assert entries[2]["metadata"] == {"interfaces": 0}
    assert entries[3]["metadata"] == {"interfaces": 1}
    assert entries[4]["metadata"] == {"api_name": f"Placed{changes['tag']}", "properties": 1}


def test_running_an_action_is_not_a_change_to_the_ontology(
    client: TestClient, fx: Fixture, changes: dict,
) -> None:
    kind = changes["type"]["id"]
    assert all(e["action"] != "action.execute" for e in history(client, fx, limit=200))
    # One resource's history (p.8's tab on its own page) is its changes only.
    own = history(client, fx, resource_id=kind)
    assert [e["action"] for e in own] == [
        "object_type.set_interfaces", "object_type.set_interfaces", "object_type.create"]
    assert own[-1]["resource_name"] == changes["type"]["display_name"]


def test_the_next_page_starts_where_the_last_ended(
    client: TestClient, fx: Fixture, changes: dict,
) -> None:
    first = history(client, fx, limit=2)
    second = history(client, fx, limit=2, before=first[-1]["id"])
    assert len(second) == 2
    assert second[0]["id"] < first[-1]["id"]
    assert [e["id"] for e in history(client, fx, limit=4)] == [e["id"] for e in first + second]


def test_only_this_workspace_s_readers_see_it(client: TestClient, fx: Fixture, changes) -> None:
    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.get(f"{wbase(fx)}/ontology-history", headers=hdr(sub))
        assert r.status_code in (403, 404), r.text


def test_the_other_saves_are_recorded_too(client: TestClient, fx: Fixture) -> None:
    """The four other writes that recorded nothing before §683, each read back
    through the history."""
    r = client.post(f"{wbase(fx)}/value-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"code_{uuid.uuid4().hex[:6]}", "display_name": "Code", "base_type": "string"})
    vt = r.json()
    r = client.patch(f"{wbase(fx)}/value-types/{vt['id']}", headers=hdr(fx.editor_sub),
                     json={"display_name": "Postal code", "description": "", "example_value": ""})
    assert r.status_code == 200, r.text
    top = history(client, fx, resource_id=vt["id"])
    assert [e["action"] for e in top] == ["value_type.update", "value_type.create"]
    assert top[0]["resource_name"] == "Postal code"


def test_a_record_with_no_resource_is_still_read(client: TestClient, fx: Fixture, changes) -> None:
    """The history reads what is stored, and a stored row need not name its
    resource - one written by a build before it did, say. It is shown unnamed
    rather than taking the page down."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO audit_log (organisation_id, user_id, action, resource_type, workspace_id)"
            " VALUES (%s, %s, 'object_type.update', 'object_type', %s)",
            (fx.org, fx.editor, fx.workspace))
    newest = history(client, fx, limit=1)[0]
    assert (newest["action"], newest["resource_id"], newest["resource_name"]) == (
        "object_type.update", None, None)
