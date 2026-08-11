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


def test_a_rule_kind_this_build_cannot_apply_is_refused_not_ignored(
    client: TestClient, fx: Fixture, ticket_type_id: str, instance_id: str
) -> None:
    """The schema admits five rule kinds and the executor implements one.

    A skipped rule would report success for an action that did half of what it
    says - the failure mode worth refusing loudly, since the day `create_object`
    lands is the day somebody saves one against this executor.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    _add_rule(action["id"], "create_object", '{"object_type": "whatever"}')
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": {"status": "closed"}},
    )
    assert r.status_code == 422
    assert "create_object" in r.text


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
