"""Action parameters and rules (decision 0007; Foundry `action-types` p.25, p.75).

Migration 0044 split one list of property names into **parameters** - what the
caller supplies - and **rules** - what the action does with them. The checks
here are the ones `docs/decisions/0007-action-parameters-and-rules.md` names
under "How you would know it worked", less the two that belong to slices not
built yet (submission criteria, and the form).

The load-bearing one is the first: **the conversion changes nothing.** Every
existing action type became parameters named after the properties it wrote, so
`{property: value}` and `{parameter: value}` are the same wire shape and every
saved Workshop `run_action` effect keeps working. If that is not true, an
upgrade breaks every module that calls an action - which is why the test asserts
the shape of the conversion *and* executes through it.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

TICKETS = b"ticket_id,status,priority,site\n1,open,low,\"51.5,-0.12\"\n2,open,high,\"52.2,0.14\"\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("params-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def abase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/actions"


@pytest.fixture(scope="module")
def ticket_type_id(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"ParamTicket{fx.tag}",
            "display_name": f"ParamTicket {fx.tag}",
            "properties": [
                {"api_name": "status", "data_type": "string"},
                {"api_name": "priority", "data_type": "string"},
                # A non-string property, so "the parameter takes the property's
                # own type" is a claim with something to be wrong about.
                {"api_name": "site", "data_type": "geopoint"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def instance_id(client: TestClient, fx: Fixture, ticket_type_id: str) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"ParamTickets {fx.tag}"},
        files={"file": ("tickets.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": ticket_type_id,
            "dataset_id": dataset_id,
            "primary_key_column": "ticket_id",
            "column_mappings": {"status": "status", "site": "site"},
        },
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    assert client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources/{source_id}/sync",
        headers=hdr(fx.editor_sub),
    ).status_code == 200
    r = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances", headers=hdr(fx.viewer_sub)
    )
    return r.json()["items"][0]["id"]


def make_action(client: TestClient, fx: Fixture, type_id: str, properties: list[str]) -> dict:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id,
            "api_name": f"act_{uuid.uuid4().hex[:8]}",
            "display_name": "Retype ticket",
            "editable_properties": properties,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- the conversion -----------------------------------------------------------
def test_each_editable_property_becomes_a_parameter_and_a_rule(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The shape of the conversion, which is what makes the migration safe.

    One parameter per property, **named after it** and carrying *its* type,
    plus one `modify_object` rule wiring that parameter into that property.
    Mutation: name the parameter anything else, or point the rule at another
    property, and this goes red - along with every saved Workshop effect.
    """
    action = make_action(client, fx, ticket_type_id, ["status", "site"])

    parameters = {p["api_name"]: p for p in action["parameters"]}
    assert set(parameters) == {"status", "site"}
    assert parameters["status"]["data_type"] == "string"
    assert parameters["site"]["data_type"] == "geopoint"
    # Not required, deliberately: submitting a subset has always been legal,
    # and a conversion that changed that would refuse calls that work today.
    assert [p["required"] for p in action["parameters"]] == [False, False]
    assert [p["hidden"] for p in action["parameters"]] == [False, False]

    rules = sorted(action["rules"], key=lambda r: r["sort_order"])
    assert [r["kind"] for r in rules] == ["modify_object", "modify_object"]
    assert [r["config"] for r in rules] == [
        {"property": "status", "parameter": "status"},
        {"property": "site", "parameter": "site"},
    ]
    # The derived list the object-type screens still read.
    assert action["editable_properties"] == ["status", "site"]


def test_a_converted_action_still_writes_what_it_used_to(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """The same payload, the same values landing. The decision's first
    acceptance test: "execute it with the same payload, and assert the same
    property values land"."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": "closed"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["instance"]["properties"]["status"] == "closed"


def test_a_value_for_something_that_is_not_a_parameter_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"priority": "high"}},
    )
    assert r.status_code == 422
    assert "not a parameter" in r.text


# ---- what parameters buy that property names could not ------------------------
def _add_parameter(action_id: str, **columns: object) -> None:
    """Insert a parameter directly.

    There is no editor yet - decision 0007's slice 1 is the model, and the API
    still takes `editable_properties`. Going through the database is what lets
    these checks exist *now* rather than waiting for a form, and it is the same
    thing the editor will write when it lands.
    """
    keys = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            f"INSERT INTO action_parameters (action_type_id, {keys}) "
            f"VALUES (%s, {placeholders})",
            (action_id, *columns.values()),
        )


def _add_rule(action_id: str, kind: str, config: str, sort_order: int = 90) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO action_rules (action_type_id, kind, config, sort_order) "
            "VALUES (%s, %s, %s::jsonb, %s)",
            (action_id, kind, config, sort_order),
        )


def test_a_missing_required_parameter_is_refused_by_name(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """p.25's parameters are inputs, so "you did not give me one" is a thing an
    action can now say. `editable_properties` could not: every property was
    optional because the list was also the output."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    _add_parameter(
        action["id"], api_name="reason", display_name="Reason",
        data_type="string", required=True, sort_order=5,
    )
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": "closed"}},
    )
    assert r.status_code == 422
    assert "'reason' is required" in r.text


def test_a_default_is_used_when_the_caller_supplies_nothing(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """p.27's default values, and the reason they need a parameter to live on:
    a *property* already has a value, so there was nowhere to put one."""
    action = make_action(client, fx, ticket_type_id, ["status", "site"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE action_parameters SET default_value = %s::jsonb "
            "WHERE action_type_id = %s AND api_name = 'status'",
            ('"triaged"', action["id"]),
        )
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"site": "51.9,-0.4"}},
    )
    assert r.status_code == 200, r.text
    properties = r.json()["instance"]["properties"]
    assert properties["status"] == "triaged"      # nobody typed this
    assert properties["site"] == {"lat": 51.9, "lon": -0.4}


def test_a_hidden_parameter_is_marked_hidden_and_still_applied(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """Both halves in one test, on purpose: a hidden parameter that silently
    did nothing would pass a check that only looked at the form (p.25 - "each
    parameter can be individually configured as to whether they are exposed in
    the form or not")."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "UPDATE action_parameters SET hidden = true "
            "WHERE action_type_id = %s AND api_name = 'status'",
            (action["id"],),
        )
    r = client.get(f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.viewer_sub))
    assert [p["hidden"] for p in r.json()["parameters"]] == [True]

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": "escalated"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["instance"]["properties"]["status"] == "escalated"


def test_a_rule_the_executor_cannot_place_is_refused_not_ignored(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """**All five rule kinds execute now (§138), so the thing that can still be
    unplaceable is a target rather than a kind**: a `create_object` naming an
    object type with no dataset mapped in this project has nowhere to put the
    row.

    A skipped rule would report success for an action that did half of what it
    says, which is the failure mode this refusal exists for - and the reason
    this test outlived the restriction it was written against.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    _add_rule(action["id"], "create_object",
              '{"object_type": "whatever", "primary_key": "status"}')
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": "closed"}},
    )
    assert r.status_code == 422
    assert "no dataset mapped in this project" in r.text


def test_a_rule_writing_an_unmapped_property_is_still_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """`priority` is a real property with no dataset column behind it, so there
    is no write-back target. The check moved from the submitted values to the
    rules and has to still be there."""
    action = make_action(client, fx, ticket_type_id, ["priority"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"priority": "high"}},
    )
    assert r.status_code == 422
    assert "no dataset column mapped" in r.text


# ---- the drift guard ----------------------------------------------------------
def test_every_property_type_can_be_an_action_parameter() -> None:
    """`action_parameter_type` is a second enum overlapping `property_data_type`,
    and the two can drift.

    A property type this table cannot express is a property no action could
    ever write - which would show up as a create failing on one object type and
    working on every other. The same drift guard the mirrored connector
    registries carry, and cheap for the same reason.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        labels = {
            name: {
                row[0]
                for row in conn.execute(
                    "SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
                    "WHERE t.typname = %s",
                    (name,),
                ).fetchall()
            }
            for name in ("property_data_type", "action_parameter_type")
        }
    missing = labels["property_data_type"] - labels["action_parameter_type"]
    assert not missing, f"property types no action parameter can hold: {sorted(missing)}"
    # And the one word p.25 needs that the ontology has no use for.
    assert "object" in labels["action_parameter_type"]


# ---- editing the definition ---------------------------------------------------
def definition(client: TestClient, fx: Fixture, action_id: str, body: dict) -> object:
    return client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition",
        headers=hdr(fx.editor_sub),
        json=body,
    )


def test_the_definition_can_be_replaced_as_one_document(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The three lists constrain each other, so they are saved together. This
    is what makes `hidden` and `default_value` reachable by anything other than
    a `psql` prompt."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = definition(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "New status", "data_type": "string",
             "default_value": "triaged"},
            {"api_name": "reason", "display_name": "Reason", "data_type": "string",
             "required": True, "hidden": True},
        ],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "status", "parameter": "status"}}],
        "criteria": [{"message": "A reason is required.",
                      "config": {"left": {"kind": "parameter", "parameter": "reason"},
                                 "operator": "is_not", "right": {"kind": "none"}}}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["api_name"] for p in body["parameters"]] == ["status", "reason"]
    assert body["parameters"][0]["default_value"] == "triaged"
    assert body["parameters"][1]["hidden"] is True
    assert [c["message"] for c in body["criteria"]] == ["A reason is required."]
    # Replaced, not merged: the old converted parameter list is gone, and the
    # only way to tell the two apart is a save that removes something.
    assert len(body["rules"]) == 1


def test_a_rule_naming_something_that_is_not_a_parameter_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The executor would refuse this at click time, in front of somebody who
    did not write it. §1.2a made the same argument for Workshop variables."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = definition(client, fx, action["id"], {
        "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "status", "parameter": "typo"}}],
        "criteria": [],
    })
    assert r.status_code == 422
    assert "not a parameter" in r.text


def test_a_rule_writing_something_that_is_not_a_property_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = definition(client, fx, action["id"], {
        "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "invented", "parameter": "status"}}],
        "criteria": [],
    })
    assert r.status_code == 422
    assert "not a property" in r.text


def test_a_criterion_with_no_message_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """p.56's failure message is what a blocked user is told. A criterion
    without one refuses in silence, which is the problem the message exists to
    solve."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = definition(client, fx, action["id"], {
        "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
        "rules": [],
        "criteria": [{"message": "   ",
                      "config": {"left": {"kind": "parameter", "parameter": "status"},
                                 "operator": "is", "right": {"kind": "value", "value": "open"}}}],
    })
    assert r.status_code == 422


def test_a_criterion_reading_a_user_attribute_we_cannot_answer_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """Refused at save time as well as at execute time. The executor fails the
    condition (§128, fail-closed); saving it would mean an action that always
    refuses and never says why until somebody reads the code."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = definition(client, fx, action["id"], {
        "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
        "rules": [],
        "criteria": [{"message": "Only acme.",
                      "config": {"left": {"kind": "current_user", "attribute": "organisation"},
                                 "operator": "is", "right": {"kind": "value", "value": "acme"}}}],
    })
    assert r.status_code == 422
    assert "cannot answer" in r.text


def test_removing_a_parameter_a_workshop_module_calls_is_refused_by_name(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """**Decision 0007's last named acceptance test.**

    A saved `run_action` effect names parameters in its `values`. Renaming one
    is, to that module, a parameter that vanished - and the failure would
    arrive at click time in front of somebody who never touched the action. The
    refusal names the module, because the person who has to fix it is usually
    not the person who typed the rename.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    app = client.post(
        f"{wbase(fx)}/projects/{fx.project}/canvas-apps",
        headers=hdr(fx.editor_sub), json={"name": f"Closer {uuid.uuid4().hex[:6]}"},
    ).json()
    saved = client.put(
        f"{wbase(fx)}/projects/{fx.project}/canvas-apps/{app['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={"definition": {
            "format": 2,
            "layout": {"ROOT": {"type": {"resolvedName": "CanvasContainer"}, "isCanvas": True,
                                "props": {}, "nodes": ["btn"], "linkedNodes": {}},
                       "btn": {"type": {"resolvedName": "CanvasButton"},
                               "props": {"label": "Close"}, "parent": "ROOT",
                               "nodes": [], "linkedNodes": {}}},
            "variables": {"v_ticket": {"id": "v_ticket", "kind": "single_object",
                                       "label": "Ticket"}},
            "events": {"e1": {"id": "e1", "trigger": {"node": "btn", "on": "click"},
                              "effects": [{"type": "run_action",
                                           "config": {"action": action["id"],
                                                      "subject": "v_ticket",
                                                      "values": {"status": "closed"}}}]}},
        }},
    )
    assert saved.status_code in (200, 201), saved.text

    r = definition(client, fx, action["id"], {
        "parameters": [{"api_name": "new_status", "display_name": "Status",
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "status", "parameter": "new_status"}}],
        "criteria": [],
    })
    assert r.status_code == 409, r.text
    assert "'status'" in r.text
    assert "Closer" in r.text

    # And the action is untouched - a refusal that half-applied would be worse
    # than the rename it refused.
    after = client.get(
        f"{wbase(fx)}/action-types/{action['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert [p["api_name"] for p in after["parameters"]] == ["status"]


def test_renaming_a_parameter_nobody_calls_is_allowed(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The other half. Without it, a refusal that fired on *every* rename would
    pass the test above."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = definition(client, fx, action["id"], {
        "parameters": [{"api_name": "new_status", "display_name": "Status",
                        "data_type": "string"}],
        "rules": [{"kind": "modify_object",
                   "config": {"property": "status", "parameter": "new_status"}}],
        "criteria": [],
    })
    assert r.status_code == 200, r.text
    assert [p["api_name"] for p in r.json()["parameters"]] == ["new_status"]


def test_a_viewer_cannot_edit_a_definition(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.viewer_sub),
        json={"parameters": [], "rules": [], "criteria": []},
    )
    assert r.status_code == 403


# ---- create_object (decision 0008's first second-write) ------------------------
def _versions(client: TestClient, fx: Fixture, dataset_id: str) -> int:
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/{dataset_id}",
        headers=hdr(fx.viewer_sub),
    )
    return int(r.json()["current_version"])


@pytest.fixture(scope="module")
def dataset_of(client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str) -> str:
    """The dataset behind the ticket type, so a version count can be read."""
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.viewer_sub),
    )
    source = next(s for s in r.json() if s["object_type_id"] == ticket_type_id)
    return source["dataset_id"]


def with_create(client: TestClient, fx: Fixture, type_id: str) -> dict:
    """An action that modifies the ticket it runs on *and* creates another."""
    action = make_action(client, fx, type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "new_key", "display_name": "New ticket id", "data_type": "string"},
                {"api_name": "new_status", "display_name": "New status", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "create_object",
                 "config": {"primary_key": "new_key",
                            "properties": {"status": "new_status"}}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    return action


def test_a_modify_and_a_create_produce_one_dataset_version(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str, dataset_of: str
) -> None:
    """**Decision 0008's second acceptance test**, and the first time this
    codebase writes two rows in one action. One version, not two: three
    versions carrying the same `produced_by_id` would be a history that has to
    be interpreted rather than read."""
    action = with_create(client, fx, ticket_type_id)
    before = _versions(client, fx, dataset_of)
    key = str(uuid.uuid4().int % 9_000_000 + 1000)  # the column is an INTEGER

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "triaged", "new_key": key, "new_status": "open"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert _versions(client, fx, dataset_of) == before + 1

    # Both writes landed: the edited ticket and the new one.
    rows = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/{dataset_of}/query",
        headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT ticket_id, status FROM dataset ORDER BY ticket_id"},
    ).json()["rows"]
    by_key = {str(row[0]): row[1] for row in rows}
    assert by_key[key] == "open", by_key
    assert by_key["1"] == "triaged", by_key


def test_a_failed_create_leaves_the_modify_unapplied(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str, dataset_of: str
) -> None:
    """**`ontology.md` §8's requirement**, and decision 0008's first acceptance
    test: an action whose second write fails leaves the first unapplied.

    The create names a primary key that already exists, which the engine
    refuses. Nothing may reach the dataset - not the modify, not a version.
    """
    action = with_create(client, fx, ticket_type_id)
    before = _versions(client, fx, dataset_of)
    status_before = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["status"]

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              # "1" is the ticket the fixture already has.
              "values": {"status": "should-not-land", "new_key": "1", "new_status": "open"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "already exists" in r.json()["error"]

    assert _versions(client, fx, dataset_of) == before, "a refused action versioned the dataset"
    after = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["status"]
    assert after == status_before, "the modify survived a failed create"


def test_the_created_object_is_findable_immediately(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """The dataset is the record and the index is a projection (decision 0008),
    but a projection nobody updates is a created object that does not exist
    until the next sync."""
    action = with_create(client, fx, ticket_type_id)
    key = str(uuid.uuid4().int % 9_000_000 + 1000)  # the column is an INTEGER
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "open", "new_key": key, "new_status": "queued"}},
    )
    assert r.status_code == 200, r.text

    items = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances", headers=hdr(fx.viewer_sub)
    ).json()["items"]
    created = [i for i in items if i["primary_key"] == key]
    assert len(created) == 1, [i["primary_key"] for i in items]
    assert created[0]["properties"]["status"] == "queued"


def test_a_create_rule_naming_an_object_type_the_workspace_lacks_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """Creating *another* type's object is allowed (§139); creating a type
    nobody has is not, and the two are told apart at save time."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
            ],
            "rules": [{"kind": "create_object",
                       "config": {"object_type": str(uuid.uuid4()), "primary_key": "status",
                                  "properties": {"status": "status"}}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "does not have" in r.text


def test_a_create_rule_is_checked_against_the_type_it_creates(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """`status` is a Ticket property and not a Team one. A validator that
    checked against the action's own type would accept this and produce a row
    with a column the Team dataset has never heard of."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
            ],
            "rules": [{"kind": "create_object",
                       "config": {"object_type": linked["team_type_id"],
                                  "primary_key": "status",
                                  "properties": {"status": "status"}}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "the object type it creates" in r.text


def test_a_create_rule_setting_something_that_is_not_a_property_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
            "rules": [{"kind": "create_object",
                       "config": {"primary_key": "status",
                                  "properties": {"invented": "status"}}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "not a property" in r.text


def test_a_new_key_of_the_wrong_type_says_why(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """`ticket_id` is an INTEGER column, and DuckDB's own message for a value
    that will not convert is "Attempting to execute an unsuccessful or closed
    pending query result" - a sentence with nothing in it for the person who
    typed the value. The reason is on the *second* line, and this is the one
    place that reads further."""
    action = with_create(client, fx, ticket_type_id)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "open", "new_key": "not-a-number", "new_status": "open"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "could not add a row" in r.json()["error"]
    assert "not-a-number" in r.json()["error"]


def test_a_create_rule_with_no_primary_key_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """A row with no identity is not a created object - nothing can address it,
    and the next sync would treat it as a stranger. Refused at save, where the
    rule is still in front of the person who wrote it."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "status", "display_name": "Status", "data_type": "string"}],
            "rules": [{"kind": "create_object", "config": {"properties": {"status": "status"}}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "primary_key" in r.text


# ---- link rules (p.75's "create and delete links") ----------------------------
@pytest.fixture(scope="module")
def linked(client: TestClient, fx: Fixture, ticket_type_id: str) -> dict:
    """A Team type, and a link from Ticket to Team joined on `owner`.

    A link here is **derived** from a property value (migration 0027): "which
    instances of the far type have `to_property` equal to this instance's
    `from_property`". So the Ticket side holds the foreign key, and creating a
    link is writing it.
    """
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"ParamTeam{fx.tag}",
            "display_name": f"ParamTeam {fx.tag}",
            "properties": [{"api_name": "code", "data_type": "string"}],
        },
    )
    assert r.status_code == 201, r.text
    team_type_id = r.json()["id"]
    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"owned_by_{uuid.uuid4().hex[:6]}",
            "display_name": "Owned by",
            "from_type_id": ticket_type_id,
            "to_type_id": team_type_id,
            "cardinality": "one_to_many",
            "from_property": "priority",
            "to_property": "code",
        },
    )
    assert r.status_code == 201, r.text
    return {"team_type_id": team_type_id, "link_id": r.json()["id"]}


def test_a_create_link_rule_writes_the_join_property(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str, linked: dict
) -> None:
    """p.75 lists creating links among the simple rules. In this platform the
    link *is* the property value, so the rule writes it - and `priority` is the
    join property, which is why this is not just a modify with another name."""
    action = make_action(client, fx, ticket_type_id, ["priority"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team", "display_name": "Team", "data_type": "string"},
            ],
            "rules": [{"kind": "create_link",
                       "config": {"link_type": linked["link_id"], "target": "team"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    # `priority` is not mapped to a dataset column on this source, so the write
    # is refused for the reason every unmapped write is - which is the same
    # sentence a modify would produce, and proves the rule went down the write
    # path rather than being quietly ignored.
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team": "alpha"}},
    )
    assert r.status_code == 422
    assert "no dataset column mapped" in r.text


def test_a_link_rule_from_the_wrong_side_needs_the_object_it_links(
    client: TestClient, fx: Fixture, linked: dict
) -> None:
    """The foreign key lives on the *from* side, so a rule on the other side
    has no column of its own to write - it can only write some other object's,
    and which one is not a thing a link type knows.

    Until §142 that was the whole refusal. Now the rule is legal *with* the
    parameter that names the object; without one there is still nothing it
    could mean, which is what this asserts.
    """
    action = make_action(client, fx, linked["team_type_id"], ["code"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "code", "display_name": "Code", "data_type": "string"}],
            "rules": [{"kind": "create_link",
                       "config": {"link_type": linked["link_id"], "target": "code"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "needs an `object` naming the parameter" in r.text


def test_a_create_link_rule_without_a_target_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    action = make_action(client, fx, ticket_type_id, ["priority"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "team", "display_name": "Team", "data_type": "string"}],
            "rules": [{"kind": "create_link", "config": {"link_type": linked["link_id"]}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "target" in r.text


def test_a_link_rule_naming_an_unknown_link_type_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "team", "display_name": "Team", "data_type": "string"}],
            "rules": [{"kind": "create_link",
                       "config": {"link_type": str(uuid.uuid4()), "target": "team"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "does not have" in r.text


@pytest.fixture(scope="module")
def mapped_link(client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict) -> str:
    """A second link, joined on `status` - which *is* mapped to a dataset
    column, so the write can actually land and be read back."""
    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"status_of_{uuid.uuid4().hex[:6]}",
            "display_name": "Status team",
            "from_type_id": ticket_type_id,
            "to_type_id": linked["team_type_id"],
            "cardinality": "one_to_many",
            "from_property": "status",
            "to_property": "code",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def link_action(client: TestClient, fx: Fixture, type_id: str, kind: str, link_id: str) -> dict:
    action = make_action(client, fx, type_id, ["status"])
    config = {"link_type": link_id}
    if kind == "create_link":
        config["target"] = "team"
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "team", "display_name": "Team", "data_type": "string"}],
            "rules": [{"kind": kind, "config": config}],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    return action


def test_creating_a_link_lands_as_the_join_propertys_value(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str, mapped_link: str
) -> None:
    """The happy path, and the one that shows a link *is* the property value in
    this platform (migration 0027) rather than a row somewhere else."""
    action = link_action(client, fx, ticket_type_id, "create_link", mapped_link)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team": "alpha"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["instance"]["properties"]["status"] == "alpha"


def test_deleting_a_link_clears_it(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str, mapped_link: str
) -> None:
    """`delete_link` needs no target: there is one join property and clearing it
    is the whole operation. It takes a value first so the clearing is visible -
    a test that asserted "empty" against an already-empty property would pass
    against a rule that did nothing."""
    create = link_action(client, fx, ticket_type_id, "create_link", mapped_link)
    client.post(
        f"{abase(fx)}/{create['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team": "beta"}},
    )
    assert client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["status"] == "beta"

    remove = link_action(client, fx, ticket_type_id, "delete_link", mapped_link)
    r = client.post(
        f"{abase(fx)}/{remove['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert not r.json()["instance"]["properties"].get("status")


# ---- delete_object (the last rule kind) ---------------------------------------
def delete_action(client: TestClient, fx: Fixture, type_id: str) -> dict:
    action = make_action(client, fx, type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "status", "display_name": "Status",
                            "data_type": "string"}],
            "rules": [{"kind": "delete_object", "config": {}}],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    return action


def test_deleting_an_object_removes_the_row_and_the_instance(
    client: TestClient, fx: Fixture, ticket_type_id: str, dataset_of: str
) -> None:
    """The last of p.75's simple rules, and the only one that removes rather
    than writes - so it is also the only one where the *index* has to be told
    something the dataset already knows."""
    # Its own row, created through an action, so nothing else in this file
    # loses the instance it was using.
    creator = with_create(client, fx, ticket_type_id)
    key = str(uuid.uuid4().int % 9_000_000 + 1000)
    victim = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances", headers=hdr(fx.viewer_sub)
    ).json()["items"][0]["id"]
    client.post(
        f"{abase(fx)}/{creator['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": victim, "values": {"status": "open", "new_key": key,
                                                "new_status": "doomed"}},
    )
    created = next(
        i for i in client.get(
            f"{wbase(fx)}/object-types/{ticket_type_id}/instances", headers=hdr(fx.viewer_sub)
        ).json()["items"] if i["primary_key"] == key
    )

    before = _versions(client, fx, dataset_of)
    action = delete_action(client, fx, ticket_type_id)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": created["id"], "values": {}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert _versions(client, fx, dataset_of) == before + 1

    # Gone from the dataset...
    rows = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/{dataset_of}/query",
        headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT ticket_id FROM dataset"},
    ).json()["rows"]
    assert key not in {str(row[0]) for row in rows}
    # ...and from the index, which is the half the dataset cannot do for itself.
    keys = {
        i["primary_key"] for i in client.get(
            f"{wbase(fx)}/object-types/{ticket_type_id}/instances", headers=hdr(fx.viewer_sub)
        ).json()["items"]
    }
    assert key not in keys


def test_an_action_cannot_both_change_and_delete_the_same_object(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """Not two things in some order - a contradiction. The order they happen to
    run in is not a specification, so it is refused where both rules are still
    on screen."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "status", "display_name": "Status",
                            "data_type": "string"}],
            "rules": [
                {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}},
                {"kind": "delete_object", "config": {}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "both change and delete" in r.text


def test_a_delete_rule_reading_something_that_is_not_a_parameter_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """Deleting a *named* object is allowed (§140); naming it with something
    that is not a parameter is not."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "status", "display_name": "Status",
                            "data_type": "string"}],
            "rules": [{"kind": "delete_object", "config": {"object": "nonexistent"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "not a parameter" in r.text


def test_a_delete_rule_naming_a_type_but_no_object_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """An object type with no object names a *set*, and deleting a set is not
    something p.75's simple rules express."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "status", "display_name": "Status",
                            "data_type": "string"}],
            "rules": [{"kind": "delete_object",
                       "config": {"object_type": linked["team_type_id"]}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "which object" in r.text


# ---- creating another type's object (§139) ------------------------------------
@pytest.fixture(scope="module")
def team_dataset(client: TestClient, fx: Fixture, linked: dict) -> str:
    """A dataset behind the Team type, so a Ticket action can create Teams.

    This is the lookup §135 and §136 kept refusing for: a type with a source in
    *this project* is a type an action can write into.
    """
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"ParamTeams {fx.tag}"},
        files={"file": ("teams.csv", io.BytesIO(b"team_id,code\nT1,alpha\n"), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": linked["team_type_id"],
            "dataset_id": dataset_id,
            "primary_key_column": "team_id",
            "column_mappings": {"code": "code"},
        },
    )
    assert r.status_code == 201, r.text
    client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources/{r.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    return dataset_id


def test_an_action_can_create_another_types_object(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str, dataset_of: str,
) -> None:
    """**Two datasets in one action**, which is what decision 0008's
    `commit_versions` was built for and nothing had exercised: the Ticket is
    modified and a Team is created, each in its own dataset, both committed
    together."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team_id", "display_name": "Team id", "data_type": "string"},
                {"api_name": "team_code", "display_name": "Team code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "create_object",
                 "config": {"object_type": linked["team_type_id"], "primary_key": "team_id",
                            "properties": {"code": "team_code"}}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    tickets_before = _versions(client, fx, dataset_of)
    teams_before = _versions(client, fx, team_dataset)
    team_id = f"T{uuid.uuid4().hex[:6]}"

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "assigned", "team_id": team_id, "team_code": "gamma"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]

    # One new version of each dataset - not two of one and none of the other.
    assert _versions(client, fx, dataset_of) == tickets_before + 1
    assert _versions(client, fx, team_dataset) == teams_before + 1

    # And the Team exists as an object, in its own type.
    teams = client.get(
        f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    ).json()["items"]
    created = [t for t in teams if t["primary_key"] == team_id]
    assert len(created) == 1, [t["primary_key"] for t in teams]
    assert created[0]["properties"]["code"] == "gamma"


def test_a_failure_in_the_second_dataset_leaves_the_first_alone(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str, dataset_of: str,
) -> None:
    """**Decision 0008's acceptance test, across two datasets** - the case
    `commit_versions` exists for and that nothing could reach until an action
    could write twice.

    The Team key already exists, so the second write refuses. The Ticket's
    dataset must be untouched: not one version applied and an error returned.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team_id", "display_name": "Team id", "data_type": "string"},
                {"api_name": "team_code", "display_name": "Team code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "create_object",
                 "config": {"object_type": linked["team_type_id"], "primary_key": "team_id",
                            "properties": {"code": "team_code"}}},
            ],
            "criteria": [],
        },
    )
    tickets_before = _versions(client, fx, dataset_of)
    teams_before = _versions(client, fx, team_dataset)
    status_before = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["status"]

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              # T1 is the row the Team dataset was seeded with.
              "values": {"status": "should-not-land", "team_id": "T1", "team_code": "x"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False
    assert "already exists" in r.json()["error"]

    assert _versions(client, fx, dataset_of) == tickets_before
    assert _versions(client, fx, team_dataset) == teams_before
    after = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["status"]
    assert after == status_before


# ---- deleting an object a parameter names (§140) -------------------------------
def test_an_action_can_delete_an_object_a_parameter_names(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str, dataset_of: str,
) -> None:
    """**p.25's `object` parameter type, finally resolving to something.**

    The action modifies the Ticket it was run against and deletes a *Team* a
    parameter names - two objects, two datasets, one transaction. Changing one
    object and deleting another is an ordinary two-object action rather than
    the contradiction §138 refuses, and this is the test that says so.
    """
    creator = make_action(client, fx, ticket_type_id, ["status"])
    client.put(
        f"{wbase(fx)}/action-types/{creator['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team_id", "display_name": "Team id", "data_type": "string"},
                {"api_name": "team_code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [{"kind": "create_object",
                       "config": {"object_type": linked["team_type_id"],
                                  "primary_key": "team_id",
                                  "properties": {"code": "team_code"}}}],
            "criteria": [],
        },
    )
    team_key = f"T{uuid.uuid4().hex[:6]}"
    assert client.post(
        f"{abase(fx)}/{creator['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"team_id": team_key, "team_code": "doomed"}},
    ).status_code == 200
    team = next(
        t for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"] if t["primary_key"] == team_key
    )

    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "delete_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    tickets_before = _versions(client, fx, dataset_of)
    teams_before = _versions(client, fx, team_dataset)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "reassigned", "team": team["id"]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]

    assert _versions(client, fx, dataset_of) == tickets_before + 1
    assert _versions(client, fx, team_dataset) == teams_before + 1
    assert r.json()["instance"]["properties"]["status"] == "reassigned"
    keys = {
        t["primary_key"] for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"]
    }
    assert team_key not in keys


def test_deleting_an_object_that_is_not_there_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str,
) -> None:
    """Success for an object nobody could find is indistinguishable from
    success for one that was deleted."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "team", "display_name": "Team", "data_type": "object"}],
            "rules": [{"kind": "delete_object",
                       "config": {"object_type": linked["team_type_id"], "object": "team"}}],
            "criteria": [],
        },
    )
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team": str(uuid.uuid4())}},
    )
    assert r.status_code == 404


# ---- changing an object a parameter names (§141) -------------------------------
def make_team(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, code: str,
) -> dict:
    """A Team row to aim a second action at, made the way an action makes one."""
    creator = make_action(client, fx, ticket_type_id, ["status"])
    assert client.put(
        f"{wbase(fx)}/action-types/{creator['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team_id", "display_name": "Team id", "data_type": "string"},
                {"api_name": "team_code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [{"kind": "create_object",
                       "config": {"object_type": linked["team_type_id"],
                                  "primary_key": "team_id",
                                  "properties": {"code": "team_code"}}}],
            "criteria": [],
        },
    ).status_code == 200
    key = f"T{uuid.uuid4().hex[:6]}"
    assert client.post(
        f"{abase(fx)}/{creator['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team_id": key, "team_code": code}},
    ).status_code == 200
    return next(
        t for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"] if t["primary_key"] == key
    )


def test_an_action_can_change_an_object_a_parameter_names(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str, dataset_of: str,
) -> None:
    """**The last of p.75's three "some other object" shapes.**

    The action changes the Ticket it was run against *and* a Team a parameter
    names - two types, two datasets, one transaction. It is the same rule kind
    as an ordinary modify because it is the same rule; the only new thing in
    the config is which object it means.
    """
    team = make_team(client, fx, ticket_type_id, instance_id, linked, "before")
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "modify_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team",
                            "property": "code", "parameter": "code"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    # The far object's property is not one of *this* action's editable
    # properties: a `run_action` effect citing `code` would be citing a
    # property of a different object.
    assert r.json()["editable_properties"] == ["status"]

    tickets_before = _versions(client, fx, dataset_of)
    teams_before = _versions(client, fx, team_dataset)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "escalated", "team": team["id"], "code": "after"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]

    assert _versions(client, fx, dataset_of) == tickets_before + 1
    assert _versions(client, fx, team_dataset) == teams_before + 1
    assert r.json()["instance"]["properties"]["status"] == "escalated"
    changed = next(
        t for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"] if t["id"] == team["id"]
    )
    assert changed["properties"]["code"] == "after"


def test_changing_an_object_that_is_not_there_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str, dataset_of: str,
) -> None:
    """Refused before anything is staged, and no version left behind - the same
    argument `test_deleting_an_object_that_is_not_there_is_refused` makes, from
    the side where the subject's own write would otherwise have gone through."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    assert client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "modify_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team",
                            "property": "code", "parameter": "code"}},
            ],
            "criteria": [],
        },
    ).status_code == 200

    before = _versions(client, fx, dataset_of)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "escalated", "team": str(uuid.uuid4()), "code": "after"}},
    )
    assert r.status_code == 404
    assert _versions(client, fx, dataset_of) == before


def test_a_modify_rule_naming_an_object_it_cannot_find_a_parameter_for_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "code", "display_name": "Code", "data_type": "string"}],
            "rules": [{"kind": "modify_object",
                       "config": {"object": "team", "property": "code", "parameter": "code"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "which is not a parameter" in r.text


def test_a_modify_rule_naming_a_type_without_an_object_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """A type with no object names every object of that type, and changing all
    of them is not a rule p.75 expresses."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "code", "display_name": "Code", "data_type": "string"}],
            "rules": [{"kind": "modify_object",
                       "config": {"object_type": linked["team_type_id"],
                                  "property": "code", "parameter": "code"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "also needs the parameter that says which object" in r.text


def test_a_modify_rule_is_checked_against_the_type_it_changes(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """`status` is a Ticket property and not a Team one. Checking the rule
    against the action's own type would let this through and write a column
    the Team source has never heard of."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
            ],
            "rules": [{"kind": "modify_object",
                       "config": {"object_type": linked["team_type_id"], "object": "team",
                                  "property": "status", "parameter": "status"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "not a property of the object type it changes" in r.text


def test_an_action_cannot_change_and_delete_the_same_named_object(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """§138's contradiction, arrived at from the far side. Two rules that name
    the same type and read the same parameter mean the same object, which is
    visible in the definition rather than only at click time."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team",
                            "property": "code", "parameter": "code"}},
                {"kind": "delete_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "both change and delete the same object" in r.text


def test_changing_one_object_and_deleting_another_is_not_a_contradiction(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """The other half of the check above: two different parameters name two
    different objects, and refusing that would refuse a definition that is
    fine. Without this the contradiction check could be written as "any modify
    and any delete" and nothing would notice."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "other", "display_name": "Other team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team",
                            "property": "code", "parameter": "code"}},
                {"kind": "delete_object",
                 "config": {"object_type": linked["team_type_id"], "object": "other"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text


# ---- linking two named objects from the far side (§142) ------------------------
@pytest.fixture(scope="module")
def far_link(client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict) -> str:
    """A link whose join property is on the **Team** side.

    `linked` runs Ticket → Team on `priority`, which the ticket source does not
    map - fine for asserting refusals, useless for asserting a write. This one
    runs Team → Ticket on `code`, which the team source does map, so an action
    on a *Ticket* is on the side that holds no foreign key and has to write the
    Team's.
    """
    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"handles_{uuid.uuid4().hex[:6]}",
            "display_name": "Handles",
            "from_type_id": linked["team_type_id"],
            "to_type_id": ticket_type_id,
            "cardinality": "one_to_many",
            "from_property": "code",
            "to_property": "status",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_link_rule_from_the_far_side_writes_the_named_object(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, far_link: str, team_dataset: str, dataset_of: str,
) -> None:
    """**Both ends of a link named, from the end that holds no foreign key.**

    A link here is derived from a property value (migration 0027), so linking
    is writing that value - and when the action's object type is the *to* side
    there is no value of its own to write. The rule names the from-side object
    through a parameter and writes *its* join property with *this* object's
    `to_property`, which is what makes it a link to this object rather than a
    modify with extra steps.
    """
    team = make_team(client, fx, ticket_type_id, instance_id, linked, "unlinked")
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "team", "display_name": "Team", "data_type": "object"}],
            "rules": [{"kind": "create_link",
                       "config": {"link_type": far_link, "object": "team"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    subject = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances/{instance_id}",
        headers=hdr(fx.viewer_sub),
    ).json()
    teams_before = _versions(client, fx, team_dataset)
    tickets_before = _versions(client, fx, dataset_of)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team": team["id"]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]

    # Only the Team's dataset moved: the subject is the end of the link that
    # holds nothing, so nothing on it changed.
    assert _versions(client, fx, team_dataset) == teams_before + 1
    assert _versions(client, fx, dataset_of) == tickets_before
    linked_team = next(
        t for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"] if t["id"] == team["id"]
    )
    assert linked_team["properties"]["code"] == subject["properties"]["status"]


def test_a_far_side_link_uses_the_value_this_action_leaves(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, far_link: str, team_dataset: str,
) -> None:
    """The action changes `status` *and* links on it. Reading the stored value
    would write the one the ticket had before the submit and create a link that
    does not hold the moment the action finishes."""
    team = make_team(client, fx, ticket_type_id, instance_id, linked, "stale")
    action = make_action(client, fx, ticket_type_id, ["status"])
    assert client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "create_link",
                 "config": {"link_type": far_link, "object": "team"}},
            ],
            "criteria": [],
        },
    ).status_code == 200

    fresh = f"handled_{uuid.uuid4().hex[:6]}"
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": fresh, "team": team["id"]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert r.json()["instance"]["properties"]["status"] == fresh
    linked_team = next(
        t for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"] if t["id"] == team["id"]
    )
    assert linked_team["properties"]["code"] == fresh


def test_a_far_side_delete_link_clears_the_named_object(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, far_link: str, team_dataset: str,
) -> None:
    """Deleting a link is clearing the same column creating it wrote - on the
    other object, which is the only thing the far side changes."""
    team = make_team(client, fx, ticket_type_id, instance_id, linked, "attached")
    action = make_action(client, fx, ticket_type_id, ["status"])
    assert client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "team", "display_name": "Team", "data_type": "object"}],
            "rules": [{"kind": "delete_link",
                       "config": {"link_type": far_link, "object": "team"}}],
            "criteria": [],
        },
    ).status_code == 200

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"team": team["id"]}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    linked_team = next(
        t for t in client.get(
            f"{wbase(fx)}/object-types/{linked['team_type_id']}/instances",
            headers=hdr(fx.viewer_sub),
        ).json()["items"] if t["id"] == team["id"]
    )
    assert linked_team["properties"]["code"] is None


def test_a_near_side_link_rule_cannot_also_name_an_object(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """On the side that holds the join property the rule already knows whose
    row it writes - its own. A parameter naming another object would be a
    second answer, and the two can disagree."""
    action = make_action(client, fx, ticket_type_id, ["priority"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [{"kind": "create_link",
                       "config": {"link_type": linked["link_id"], "target": "code",
                                  "object": "team"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "cannot also name one" in r.text


def test_a_far_side_link_rule_reading_a_non_parameter_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, far_link: str
) -> None:
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "code", "display_name": "Code", "data_type": "string"}],
            "rules": [{"kind": "create_link",
                       "config": {"link_type": far_link, "object": "team"}}],
            "criteria": [],
        },
    )
    assert r.status_code == 422
    assert "which is not a parameter" in r.text


def test_a_far_side_link_to_an_object_with_no_join_value_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, far_link: str, team_dataset: str,
) -> None:
    """This link joins on `status`; blanking it leaves nothing to point the
    Team at, and writing the blank anyway would be a `delete_link` reporting
    itself as a create."""
    team = make_team(client, fx, ticket_type_id, instance_id, linked, "waiting")
    blanker = make_action(client, fx, ticket_type_id, ["status"])
    assert client.put(
        f"{wbase(fx)}/action-types/{blanker['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "create_link",
                 "config": {"link_type": far_link, "object": "team"}},
            ],
            "criteria": [],
        },
    ).status_code == 200
    r = client.post(
        f"{abase(fx)}/{blanker['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": None, "team": team["id"]}},
    )
    assert r.status_code == 422
    assert "nothing can be linked to it" in r.text


def test_deleting_the_subject_and_changing_another_object_is_allowed(
    client: TestClient, fx: Fixture, ticket_type_id: str, linked: dict
) -> None:
    """§138's contradiction is about the *subject*: writing a property of a row
    and removing the same row. A rule that names another object writes a
    different row, so the two rules do not disagree - and a check that counted
    every modify would refuse "close this ticket and update the team".
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team",
                            "property": "code", "parameter": "code"}},
                {"kind": "delete_object", "config": {}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text


# ---- p.513's Output object set -------------------------------------------------
def _touched(result: dict) -> dict[str, str]:
    """`primary_key` → `change`, which is what every assertion below asks."""
    return {t["primary_key"]: t["change"] for t in result["touched"]}


def test_an_action_reports_the_object_it_modified(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """Workshop p.513: "Specify the object set that will be created or modified
    when the Action is submitted."

    **Only the executor can answer this.** A browser cannot work out which
    objects an action wrote: a rule can create one whose primary key comes from
    a parameter, and can modify one a *different* parameter names.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": "reported"}},
    )
    assert r.status_code == 200, r.text
    assert _touched(r.json()) == {"1": "modified"}
    assert r.json()["touched"][0]["object_type_id"] == ticket_type_id


def test_a_created_object_is_reported_as_created(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """Both of p.513's verbs in one submission, told apart.

    The action modifies the ticket it runs on and creates another, so a report
    that lost the distinction - or lost one of the two rows - has something to
    be wrong about.
    """
    action = with_create(client, fx, ticket_type_id)
    key = str(uuid.uuid4().int % 9_000_000 + 1000)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "triaged", "new_key": key, "new_status": "open"}},
    )
    assert r.status_code == 200, r.text
    assert _touched(r.json()) == {"1": "modified", key: "created"}


def test_an_action_that_writes_nothing_to_its_subject_does_not_report_it(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """**The distinction the whole feature turns on.** An action whose only
    rule creates an object has not modified the one it ran on, and putting that
    row in the output set would hand a module an object that did not change -
    which is precisely what p.513's set is supposed to tell it apart from.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "new_key", "display_name": "New id", "data_type": "string"},
                {"api_name": "new_status", "display_name": "New status",
                 "data_type": "string"},
            ],
            "rules": [
                {"kind": "create_object",
                 "config": {"primary_key": "new_key",
                            "properties": {"status": "new_status"}}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text
    key = str(uuid.uuid4().int % 9_000_000 + 1000)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"new_key": key, "new_status": "open"}},
    )
    assert r.status_code == 200, r.text
    assert _touched(r.json()) == {key: "created"}


def test_a_refused_write_reports_nothing(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """A set naming rows the action did not manage to write is worse than an
    empty one: the reader acts on objects that never changed.

    The create names a primary key that already exists, which the engine
    refuses - so `ok` is false and nothing was written at all.
    """
    action = with_create(client, fx, ticket_type_id)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "x", "new_key": "1", "new_status": "open"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False, r.json()
    assert r.json()["touched"] == []


def test_an_object_a_parameter_names_is_reported_too(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str,
    linked: dict, team_dataset: str, dataset_of: str,
) -> None:
    """p.75's third shape, in p.513's report.

    **Untested until a mutant said so.** Every other test here modifies the
    subject or creates, so the `modifications` branch - the objects a
    *parameter* names - was reported by code nothing exercised. It is also the
    branch that makes the widget's single-type rule matter: two object types
    come back, and only one belongs in a set narrowed from the ticket's.
    """
    team = make_team(client, fx, ticket_type_id, instance_id, linked, "before")
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "team", "display_name": "Team", "data_type": "object"},
                {"api_name": "code", "display_name": "Code", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "modify_object",
                 "config": {"object_type": linked["team_type_id"], "object": "team",
                            "property": "code", "parameter": "code"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "escalated", "team": team["id"], "code": "after"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]

    touched = r.json()["touched"]
    # Both objects, both as *modifications* - a named object is changed, not
    # created, and reporting it as a creation would have a module treating an
    # existing row as new.
    assert {t["change"] for t in touched} == {"modified"}, touched
    by_type = {t["object_type_id"]: t["primary_key"] for t in touched}
    assert by_type[ticket_type_id] == "1", touched
    assert by_type[linked["team_type_id"]] == str(team["primary_key"]), touched


def test_an_object_written_twice_is_reported_once(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """An action can write the subject *and* name it through a parameter — the
    same object twice, which a set cannot hold twice.

    **The case the dedupe exists for**, and nothing reached it: every other
    fixture writes each object once, so a mutant deleting the check changed no
    result. A clause list naming a key twice is the same set written twice, and
    the count beside it would be wrong.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "status", "display_name": "Status", "data_type": "string"},
                {"api_name": "same", "display_name": "The same ticket",
                 "data_type": "object"},
                {"api_name": "note", "display_name": "Note", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                # The subject again, named the long way round. `status` rather
                # than a second property because it is the one this fixture's
                # source maps - the point here is the *object* being named
                # twice, not which column it writes.
                {"kind": "modify_object",
                 "config": {"object_type": ticket_type_id, "object": "same",
                            "property": "status", "parameter": "note"}},
            ],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id,
              "values": {"status": "twice", "same": instance_id, "note": "high"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert _touched(r.json()) == {"1": "modified"}
    assert len(r.json()["touched"]) == 1, r.json()["touched"]
