"""What values a parameter accepts (§584; db 0119; `action-types` p.8, p.45,
p.71).

> "Select the Priority parameter to limit the values it can take on. Change
>  the constraints from User input to Multiple choice… Add P0, P1 and P2 as
>  options." (p.8)
> "…a string length constraint can be defined… to only allow string value
>  that are between 10 and 500 characters long." (p.71)
> "An override can change the configuration of the parameter's constraints,
>  visibility, requiredness, and default values." (p.45)
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
from src.services import action_constraints  # noqa: E402
from src.services import actions as actions_service  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

TICKETS = b"key,title,priority,points\nT1,First,P1,3\n"

PRIORITIES = {"kind": "enum", "values": ["P0", "P1", "P2"]}
SUMMARY = {"kind": "range", "minimum": 10, "maximum": 500}


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("parameter-constraints")))
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
def ticket(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Tickets {tag}"},
        files={"file": ("tickets.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"ticket_{tag}", "display_name": f"Ticket {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "title", "data_type": "string"},
                  {"api_name": "priority", "data_type": "string"},
                  {"api_name": "points", "data_type": "integer"},
              ],
              "title_property": "title"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "title": "title",
                                  "priority": "priority", "points": "points"}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub))
    assert synced.status_code == 200, synced.text
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {"type_id": type_id, "instance_id": items[0]["id"]}


def make_action(client, fx, ticket) -> str:
    made = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket["type_id"],
              "api_name": f"act_{uuid.uuid4().hex[:6]}", "display_name": "Act",
              "editable_properties": ["title"]},
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def define(client, fx, action_id: str, parameters: list[dict], rules: list[dict] | None = None):
    return client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": parameters, "rules": rules or [], "criteria": []},
    )


def param(name: str, data_type: str = "string", **extra) -> dict:
    return {"api_name": name, "display_name": name.capitalize(), "data_type": data_type,
            **extra}


def writes(prop: str, parameter: str) -> dict:
    return {"kind": "modify_object", "config": {"property": prop, "parameter": parameter}}


def execute(client, fx, action: str, instance_id: str, values: dict):
    return client.post(f"{abase(fx)}/{action}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": instance_id, "values": values})


# ---- the pure rule ----------------------------------------------------------------
def test_p8s_multiple_choice_takes_only_its_options() -> None:
    p = param("priority", value_constraint=PRIORITIES)
    assert action_constraints.violation(p, "P1") is None
    assert action_constraints.violation(p, "P7") == "'P7' is not one of P0, P1, P2"


def test_p71s_string_length() -> None:
    p = param("summary", value_constraint=SUMMARY)
    assert action_constraints.violation(p, "x" * 10) is None
    assert action_constraints.violation(p, "x" * 500) is None
    assert "below the minimum of 10" in action_constraints.violation(p, "x" * 9)
    assert "above the maximum of 500" in action_constraints.violation(p, "x" * 501)


def test_a_value_is_read_as_its_type_before_it_is_checked() -> None:
    """"5" for an integer is the 5 the rule will write."""
    p = param("points", "integer", value_constraint={"kind": "range", "maximum": 5})
    assert action_constraints.violation(p, "5") is None
    assert "above the maximum of 5" in action_constraints.violation(p, "6")
    assert "integer" in action_constraints.violation(p, "many")


def test_an_array_is_checked_item_by_item() -> None:
    p = param("priorities", "array", array_of="string", value_constraint=PRIORITIES)
    assert action_constraints.violation(p, ["P0", "P2"]) is None
    assert action_constraints.violation(p, ["P0", "P9"]) == "'P9' is not one of P0, P1, P2"


def test_a_list_for_one_value_is_not_read_item_by_item() -> None:
    """Only an array parameter's value is its items: a list sent for a
    single priority is not a priority, however allowed its items are."""
    p = param("priority", value_constraint=PRIORITIES)
    assert "expected a string" in action_constraints.violation(p, ["P0"])


def test_nothing_is_not_a_violation() -> None:
    """p.116's `required` answers "is there a value"; a constraint answers
    "is this value allowed", and an optional parameter left empty is fine."""
    p = param("priority", value_constraint=PRIORITIES)
    assert action_constraints.violation(p, None) is None
    assert action_constraints.violation(param("free"), "anything") is None


def test_bind_refuses_a_value_outside_the_constraint_by_name() -> None:
    parameters = [param("priority", value_constraint=PRIORITIES)]
    with pytest.raises(ValueError, match="'priority': 'P7' is not one of"):
        actions_service.bind_parameters({"priority": "P7"}, parameters=parameters)
    assert actions_service.bind_parameters(
        {"priority": "P0"}, parameters=parameters) == {"priority": "P0"}


def test_an_overrides_constraint_is_the_one_that_applies() -> None:
    """p.45: the first block that holds puts its constraint in place of the
    parameter's own."""
    urgent = {"left": {"kind": "parameter", "parameter": "urgent"}, "operator": "is",
              "right": {"kind": "value", "value": "yes"}}
    parameters = [
        param("urgent"),
        param("priority", value_constraint=PRIORITIES, overrides=[
            {"conditions": [urgent], "set_hidden": None, "set_required": None,
             "set_default": None, "set_constraint": {"kind": "enum", "values": ["P0"]}},
        ]),
    ]
    order = ["urgent", "priority"]
    assert actions_service.bind_parameters(
        {"urgent": "no", "priority": "P2"}, parameters=parameters, form_order=order)
    with pytest.raises(ValueError, match="'P2' is not one of P0"):
        actions_service.bind_parameters(
            {"urgent": "yes", "priority": "P2"}, parameters=parameters, form_order=order)


# ---- the declaration ------------------------------------------------------------
@pytest.mark.parametrize("parameter, said", [
    (param("where", "geopoint", value_constraint=PRIORITIES), "takes no constraint"),
    (param("done", "boolean", value_constraint=SUMMARY),
     "a range constraint does not apply to a boolean"),
    (param("points", "integer", value_constraint={"kind": "regex", "pattern": "x"}),
     "a regex constraint does not apply to a integer"),
    (param("priority", value_constraint={"kind": "enum", "values": []}),
     "an enum constraint needs at least one value"),
    (param("priority", value_constraint={"kind": "wish"}), "constraint kind must be one of"),
    # An empty constraint is not "User input", which is null: it is a
    # constraint with no kind, and saying so beats guessing.
    (param("priority", value_constraint={}), "constraint kind must be one of"),
    (param("priority", value_constraint=PRIORITIES, default_value="P9"),
     "its default 'P9' is not one of P0, P1, P2"),
    (param("priority", value_constraint=PRIORITIES,
           options_from={"object_type_id": str(uuid.uuid4()), "property": "priority"}),
     "two answers to which values it may take"),
])
def test_a_constraint_that_could_not_hold_is_refused(client, fx, ticket, parameter, said):
    action = make_action(client, fx, ticket)
    refused = define(client, fx, action, [parameter])
    assert refused.status_code == 422, refused.text
    assert said in refused.text


def test_an_overrides_constraint_is_refused_on_the_same_terms(client, fx, ticket):
    action = make_action(client, fx, ticket)
    block = {"conditions": [{"left": {"kind": "parameter", "parameter": "urgent"},
                             "operator": "is", "right": {"kind": "value", "value": "yes"}}],
             "set_constraint": {"kind": "regex", "pattern": "("}}
    refused = define(client, fx, action, [param("urgent"),
                                         param("priority", overrides=[block])])
    assert refused.status_code == 422, refused.text
    assert "'priority' (override 1): that regex does not compile" in refused.text


def test_a_constraint_is_kept_and_described(client, fx, ticket):
    action = make_action(client, fx, ticket)
    saved = define(client, fx, action, [param("priority", value_constraint=PRIORITIES)],
                   [writes("priority", "priority")])
    assert saved.status_code == 200, saved.text
    got = client.get(f"{wbase(fx)}/action-types/{action}",
                     headers=hdr(fx.viewer_sub)).json()
    [p] = got["parameters"]
    assert p["value_constraint"] == {"kind": "enum", "values": ["P0", "P1", "P2"],
                                     "case_sensitive": True}
    assert p["constraint_summary"] == "one of P0, P1, P2"
    unconstrained = client.get(f"{wbase(fx)}/action-types/{make_action(client, fx, ticket)}",
                               headers=hdr(fx.viewer_sub)).json()["parameters"][0]
    assert (unconstrained["value_constraint"], unconstrained["constraint_summary"]) == (None, "")


# ---- the submission -------------------------------------------------------------
def test_p8s_action_writes_only_its_options(client, fx, ticket):
    action = make_action(client, fx, ticket)
    assert define(client, fx, action, [param("priority", value_constraint=PRIORITIES)],
                  [writes("priority", "priority")]).status_code == 200
    refused = execute(client, fx, action, ticket["instance_id"], {"priority": "P7"})
    assert refused.status_code == 422, refused.text
    assert "'priority': 'P7' is not one of P0, P1, P2" in refused.text
    done = execute(client, fx, action, ticket["instance_id"], {"priority": "P0"})
    assert done.status_code == 200, done.text
    assert done.json()["instance"]["properties"]["priority"] == "P0"


def test_check_says_so_before_submitting(client, fx, ticket):
    """Workshop p.513's check runs `bind_parameters`, so it answers too."""
    action = make_action(client, fx, ticket)
    assert define(client, fx, action, [param("title", value_constraint=SUMMARY)],
                  [writes("title", "title")]).status_code == 200
    checked = client.post(f"{abase(fx)}/{action}/check", headers=hdr(fx.editor_sub),
                          json={"values": {"title": "too short"}})
    assert checked.status_code == 200, checked.text
    assert checked.json()["ok"] is False
    assert "9 characters is below the minimum of 10" in checked.json()["error"]


def test_the_form_is_given_the_overrides_constraint(client, fx, ticket):
    """p.45's constraint reaches the form through the same resolution."""
    action = make_action(client, fx, ticket)
    block = {"conditions": [{"left": {"kind": "parameter", "parameter": "urgent"},
                             "operator": "is", "right": {"kind": "value", "value": "yes"}}],
             "set_constraint": {"kind": "enum", "values": ["P0"]}}
    assert define(client, fx, action, [
        param("urgent"),
        param("priority", value_constraint=PRIORITIES, overrides=[block]),
    ], [writes("priority", "priority")]).status_code == 200
    got = client.get(f"{wbase(fx)}/action-types/{action}",
                     headers=hdr(fx.viewer_sub)).json()
    stored = got["parameters"][1]["overrides"][0]
    assert stored["set_constraint"] == {"kind": "enum", "values": ["P0"],
                                        "case_sensitive": True}
    resolved = client.post(f"{wbase(fx)}/action-types/{action}/effective-parameters",
                           headers=hdr(fx.viewer_sub), json={"values": {"urgent": "yes"}})
    assert resolved.status_code == 200, resolved.text
    priority = resolved.json()[1]
    assert (priority["value_constraint"]["values"], priority["constraint_summary"]) == (
        ["P0"], "one of P0")


def test_an_ontology_export_carries_both(client, fx, ticket):
    """p.65's file: a constraint is values and bounds, no ids, so it travels
    as written, and p.45's block carries its own."""
    action = make_action(client, fx, ticket)
    block = {"conditions": [{"left": {"kind": "parameter", "parameter": "urgent"},
                             "operator": "is", "right": {"kind": "value", "value": "yes"}}],
             "set_constraint": {"kind": "enum", "values": ["P0"]}}
    assert define(client, fx, action, [
        param("urgent"),
        param("priority", value_constraint=PRIORITIES, overrides=[block]),
    ], [writes("priority", "priority")]).status_code == 200
    name = client.get(f"{wbase(fx)}/action-types/{action}",
                      headers=hdr(fx.viewer_sub)).json()["api_name"]
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [a for a in document["action_types"] if a["api_name"] == name]
    urgent, priority = exported["parameters"]
    assert "value_constraint" not in urgent
    assert priority["value_constraint"]["values"] == ["P0", "P1", "P2"]
    assert priority["overrides"][0]["set_constraint"]["values"] == ["P0"]


# ---- p.71-72's struct fields (§585) -----------------------------------------------
RESOLUTION = [{"api_name": "summary", "data_type": "string"},
              {"api_name": "hours", "data_type": "integer"}]


@pytest.fixture(scope="module")
def resolved(client: TestClient, fx: Fixture) -> dict:
    """A type with a struct property, which is what p.66's parameter writes."""
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Resolved {tag}"},
        files={"file": ("resolved.csv", io.BytesIO(
            b'key,title,resolution\nR1,First,"{""summary"": ""seeded summary"", ""hours"": 1}"\n'),
            "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"resolved_{tag}", "display_name": f"Resolved {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "title", "data_type": "string"},
                  {"api_name": "resolution", "data_type": "struct",
                   "struct_fields": RESOLUTION},
              ],
              "title_property": "title"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "title": "title",
                                  "resolution": "resolution"}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub))
    assert synced.status_code == 200, synced.text
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {"type_id": type_id, "instance_id": items[0]["id"]}


def struct_action(client, fx, resolved, **extra) -> tuple[str, object]:
    made = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": resolved["type_id"],
              "api_name": f"res_{uuid.uuid4().hex[:6]}", "display_name": "Resolve",
              "editable_properties": ["title"]},
    )
    assert made.status_code == 201, made.text
    action = made.json()["id"]
    saved = define(client, fx, action,
                   [param("resolution", "struct", **extra)],
                   [writes("resolution", "resolution")])
    return action, saved


SUMMARY_LENGTH = {"summary": SUMMARY}


def test_p71s_field_constraint_is_kept_and_described(client, fx, resolved):
    action, saved = struct_action(client, fx, resolved, field_constraints=SUMMARY_LENGTH)
    assert saved.status_code == 200, saved.text
    [p] = client.get(f"{wbase(fx)}/action-types/{action}",
                     headers=hdr(fx.viewer_sub)).json()["parameters"]
    assert p["field_constraints"] == {"summary": {"kind": "range", "minimum": 10,
                                                  "maximum": 500}}
    assert p["field_constraint_summaries"] == {"summary": "between 10 and 500"}


def test_p72_a_struct_is_valid_only_when_every_field_is(client, fx, resolved):
    action, saved = struct_action(client, fx, resolved, field_constraints={
        **SUMMARY_LENGTH, "hours": {"kind": "range", "maximum": 40}})
    assert saved.status_code == 200, saved.text
    short = execute(client, fx, action, resolved["instance_id"],
                    {"resolution": {"summary": "too short", "hours": 2}})
    assert short.status_code == 422, short.text
    assert "'resolution': field 'summary': 9 characters is below the minimum of 10" in short.text
    # The field is read as its type first, as a parameter is.
    long_hours = execute(client, fx, action, resolved["instance_id"],
                         {"resolution": {"summary": "a proper summary", "hours": "41"}})
    assert long_hours.status_code == 422, long_hours.text
    assert "field 'hours': 41 is above the maximum of 40" in long_hours.text
    done = execute(client, fx, action, resolved["instance_id"],
                   {"resolution": {"summary": "a proper summary", "hours": 3}})
    assert done.status_code == 200, done.text
    assert done.json()["instance"]["properties"]["resolution"] == {
        "summary": "a proper summary", "hours": 3}


def test_an_empty_field_meets_its_constraint(client, fx, resolved):
    """p.116's `required` answers "is there a value"; a field left empty is
    not one the constraint judges."""
    action, _ = struct_action(client, fx, resolved, field_constraints=SUMMARY_LENGTH)
    done = execute(client, fx, action, resolved["instance_id"],
                   {"resolution": {"hours": 1}})
    assert done.status_code == 200, done.text


def test_check_answers_for_a_field_too(client, fx, resolved):
    action, _ = struct_action(client, fx, resolved, field_constraints=SUMMARY_LENGTH)
    checked = client.post(f"{abase(fx)}/{action}/check", headers=hdr(fx.editor_sub),
                          json={"values": {"resolution": {"summary": "short"}}})
    assert checked.json() == {
        "ok": False,
        "error": "'resolution': field 'summary': 5 characters is below the minimum of 10"}


@pytest.mark.parametrize("extra, said", [
    ({"field_constraints": {"notes": SUMMARY}}, "'resolution' has no field 'notes'"),
    ({"field_constraints": {"hours": {"kind": "regex", "pattern": "x"}}},
     "'resolution' field 'hours': a regex constraint does not apply to a integer"),
    ({"field_constraints": {"summary": {"kind": "enum", "values": []}}},
     "'resolution' field 'summary': an enum constraint needs at least one value"),
])
def test_a_field_constraint_that_could_not_hold_is_refused(client, fx, resolved, extra, said):
    _, saved = struct_action(client, fx, resolved, **extra)
    assert saved.status_code == 422, saved.text
    assert said in saved.text


def test_only_a_struct_has_fields_to_constrain(client, fx, ticket):
    action = make_action(client, fx, ticket)
    refused = define(client, fx, action, [param("title", field_constraints=SUMMARY_LENGTH)],
                     [writes("title", "title")])
    assert refused.status_code == 422, refused.text
    assert "'title' is a string, which has no fields to constrain" in refused.text


def test_a_struct_nothing_writes_has_no_fields(client, fx, resolved):
    """A struct parameter's fields are the property's its rule writes (p.73),
    so one no rule writes has none to constrain."""
    made = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": resolved["type_id"],
              "api_name": f"res_{uuid.uuid4().hex[:6]}", "display_name": "Resolve",
              "editable_properties": ["title"]},
    )
    refused = define(client, fx, made.json()["id"],
                     [param("resolution", "struct", field_constraints=SUMMARY_LENGTH)])
    assert refused.status_code == 422, refused.text
    assert "no rule writes it to a struct property" in refused.text


def test_field_constraints_are_exported(client, fx, resolved):
    action, _ = struct_action(client, fx, resolved, field_constraints=SUMMARY_LENGTH)
    name = client.get(f"{wbase(fx)}/action-types/{action}",
                      headers=hdr(fx.viewer_sub)).json()["api_name"]
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [a for a in document["action_types"] if a["api_name"] == name]
    assert exported["parameters"][0]["field_constraints"] == {
        "summary": {"kind": "range", "minimum": 10, "maximum": 500}}


def test_a_field_constraint_is_stored_normalised_and_null_is_user_input(client, fx, resolved):
    """The stored document is the parsed one (an enum on a string says it is
    case sensitive), and a field set to null is p.8's User input, so it is
    not stored at all."""
    action, saved = struct_action(client, fx, resolved, field_constraints={
        "summary": None, "hours": {"kind": "enum", "values": [1, 2]}})
    assert saved.status_code == 200, saved.text
    [p] = client.get(f"{wbase(fx)}/action-types/{action}",
                     headers=hdr(fx.viewer_sub)).json()["parameters"]
    assert p["field_constraints"] == {"hours": {"kind": "enum", "values": [1, 2]}}
    action, _ = struct_action(client, fx, resolved, field_constraints={
        "summary": {"kind": "enum", "values": ["done"]}})
    [p] = client.get(f"{wbase(fx)}/action-types/{action}",
                     headers=hdr(fx.viewer_sub)).json()["parameters"]
    assert p["field_constraints"]["summary"]["case_sensitive"] is True


def test_a_value_that_is_not_a_struct_is_left_to_the_coercer() -> None:
    """The fields of something that has none are not this check's to read:
    the rule's coercion refuses a struct that is not one, by name."""
    p = param("resolution", "struct", field_constraints=SUMMARY_LENGTH)
    assert action_constraints.field_violation(p, "not a struct", RESOLUTION) is None
    assert action_constraints.field_violation(p, {"summary": "short"}, RESOLUTION) == (
        "field 'summary': 5 characters is below the minimum of 10")
