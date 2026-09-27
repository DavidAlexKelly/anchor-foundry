"""A parameter's default taken from an object (§588; db 0122; `action-types`
p.27, p.29, p.69-70).

> "Parameters can be set to default values to display either a fixed value or
>  a property of the selected object." (p.27)
> "Only object reference parameters that are placed above the parameter in the
>  input list are available to be used as a default value." (p.29)
> "Each struct parameter field is mapped to fields of a specified object
>  type's struct property. A default value must be defined for all fields in
>  the struct parameter." (p.69-70)

p.29's own example: Change Airplane Details, whose parameters start at the
chosen plane's current values.
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
from src.services import action_defaults  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

PLANES = (
    b"key,model,hours,spec\n"
    b'P1,A320,1200,"{""seats"": 180, ""range_km"": 6100}"\n'
    b'P2,A380,800,"{""seats"": 520, ""range_km"": 15000}"\n'
)
SPEC = [{"api_name": "seats", "data_type": "integer"},
        {"api_name": "range_km", "data_type": "integer"}]


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("object-defaults")))
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
def planes(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Planes {tag}"},
        files={"file": ("planes.csv", io.BytesIO(PLANES), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"plane_{tag}", "display_name": f"Plane {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "model", "data_type": "string"},
                  {"api_name": "hours", "data_type": "integer"},
                  {"api_name": "spec", "data_type": "struct", "struct_fields": SPEC},
              ],
              "title_property": "key"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "model": "model", "hours": "hours",
                                  "spec": "spec"}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub))
    assert synced.status_code == 200, synced.text
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {"type_id": type_id, **{i["primary_key"]: i["id"] for i in items}}


def make_action(client, fx, planes) -> str:
    made = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": planes["type_id"],
              "api_name": f"details_{uuid.uuid4().hex[:6]}",
              "display_name": "Change airplane details", "editable_properties": ["model"]},
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def define(client, fx, action_id: str, parameters: list[dict], rules: list[dict]):
    return client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": parameters, "rules": rules, "criteria": []},
    )


def plane_param(planes) -> dict:
    return {"api_name": "plane", "display_name": "Plane", "data_type": "object",
            "object_type_id": planes["type_id"]}


def writes(prop: str, parameter: str) -> dict:
    return {"kind": "modify_object", "config": {"property": prop, "parameter": parameter}}


def details(client, fx, planes) -> str:
    """p.29's action: the model, the hours and the spec start at the chosen
    plane's."""
    action = make_action(client, fx, planes)
    saved = define(client, fx, action, [
        plane_param(planes),
        {"api_name": "model", "display_name": "Model", "data_type": "string",
         "default_from": {"parameter": "plane", "property": "model"}},
        {"api_name": "hours", "display_name": "Hours", "data_type": "integer",
         "default_from": {"parameter": "plane", "property": "hours"}},
        {"api_name": "spec", "display_name": "Spec", "data_type": "struct",
         "default_from": {"parameter": "plane", "property": "spec"}},
    ], [writes("model", "model"), writes("hours", "hours"), writes("spec", "spec")])
    assert saved.status_code == 200, saved.text
    return action


def effective(client, fx, action: str, values: dict) -> dict[str, dict]:
    r = client.post(f"{wbase(fx)}/action-types/{action}/effective-parameters",
                    headers=hdr(fx.viewer_sub), json={"values": values})
    assert r.status_code == 200, r.text
    return {p["api_name"]: p for p in r.json()}


# ---- the form ---------------------------------------------------------------------
def test_the_form_starts_at_the_chosen_objects_values(client, fx, planes) -> None:
    action = details(client, fx, planes)
    got = effective(client, fx, action, {"plane": planes["P2"]})
    assert got["model"]["default_value"] == "A380"
    assert got["hours"]["default_value"] == 800
    # p.69-70: each struct field from the same struct property.
    assert got["spec"]["default_value"] == {"seats": 520, "range_km": 15000}
    assert got["model"]["default_from"] == {"parameter": "plane", "property": "model"}


def test_nothing_chosen_is_no_default(client, fx, planes) -> None:
    got = effective(client, fx, details(client, fx, planes), {})
    assert got["model"]["default_value"] is None


# ---- the submission ---------------------------------------------------------------
def test_an_untouched_parameter_is_submitted_as_the_objects_value(client, fx, planes) -> None:
    """p.29: "users could choose to modify just one property and keep the rest
    the same. This same default logic will be present anywhere the action is
    submitted." Applied to P1 with P2 chosen, only the hours typed."""
    action = details(client, fx, planes)
    done = client.post(f"{abase(fx)}/{action}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": planes["P1"],
                             "values": {"plane": planes["P2"], "hours": 5}})
    assert done.status_code == 200, done.text
    held = done.json()["instance"]["properties"]
    assert (held["model"], held["hours"]) == ("A380", 5)
    assert held["spec"] == {"seats": 520, "range_km": 15000}


def test_check_reads_the_same_defaults(client, fx, planes) -> None:
    """A required parameter answered by its object default is answered."""
    action = make_action(client, fx, planes)
    assert define(client, fx, action, [
        plane_param(planes),
        {"api_name": "model", "display_name": "Model", "data_type": "string",
         "required": True, "default_from": {"parameter": "plane", "property": "model"}},
    ], [writes("model", "model")]).status_code == 200
    r = client.post(f"{abase(fx)}/{action}/check", headers=hdr(fx.editor_sub),
                    json={"values": {"plane": planes["P1"]}})
    assert r.json() == {"ok": True, "error": None}
    r = client.post(f"{abase(fx)}/{action}/check", headers=hdr(fx.editor_sub),
                    json={"values": {}})
    assert r.json()["ok"] is False and "'model' is required" in r.json()["error"]


# ---- the declaration --------------------------------------------------------------
def model(**over) -> dict:
    return {"api_name": "model", "display_name": "Model", "data_type": "string",
            "default_from": {"parameter": "plane", "property": "model"}, **over}


@pytest.mark.parametrize("parameters, said", [
    # p.29: "placed above the parameter in the input list".
    (lambda p: [model(), plane_param(p)], "which is not above it in the form"),
    (lambda p: [plane_param(p), model(default_from={"parameter": "model2", "property": "x"})],
     "'model2', which is not a parameter"),
    (lambda p: [{"api_name": "other", "display_name": "O", "data_type": "string"},
                model(default_from={"parameter": "other", "property": "model"})],
     "'other', which is not a single object reference"),
    (lambda p: [plane_param(p), model(default_from={"parameter": "plane", "property": "wings"})],
     "the object in 'plane' has no 'wings' property"),
    (lambda p: [plane_param(p), model(default_from={"parameter": "plane", "property": "hours"})],
     "'model' is a string and 'hours' on the object in 'plane' is a integer"),
    (lambda p: [plane_param(p), model(default_value="A320")],
     "a fixed default and one from an object"),
    (lambda p: [plane_param(p), model(default_from={"parameter": "plane", "property": "model",
                                                    "fields": {"a": "b"}})],
     "is not a struct, so it has no fields to map"),
    (lambda p: [plane_param(p), model(default_from={"parameter": "plane", "property": "model",
                                                    "when": "always"})],
     "unknown default option when"),
])
def test_a_default_that_could_not_be_read_is_refused(client, fx, planes, parameters, said):
    action = make_action(client, fx, planes)
    refused = define(client, fx, action, parameters(planes), [writes("model", "model")])
    assert refused.status_code == 422, refused.text
    assert said in refused.json()["detail"]


def test_a_struct_default_maps_every_field(client, fx, planes) -> None:
    """p.70: "A default value must be defined for all fields in the struct
    parameter" - a field with no counterpart is refused, and `fields` maps
    one whose name differs."""
    action = make_action(client, fx, planes)
    spec = {"api_name": "spec", "display_name": "Spec", "data_type": "struct",
            "default_from": {"parameter": "plane", "property": "spec",
                             "fields": {"seats": "range_km"}}}
    saved = define(client, fx, action, [plane_param(planes), spec], [writes("spec", "spec")])
    assert saved.status_code == 200, saved.text
    got = effective(client, fx, action, {"plane": planes["P2"]})
    assert got["spec"]["default_value"] == {"seats": 15000, "range_km": 15000}
    spec["default_from"]["fields"] = {"seats": "wingspan"}
    refused = define(client, fx, action, [plane_param(planes), spec], [writes("spec", "spec")])
    assert refused.status_code == 422, refused.text
    assert "field 'seats' has no field to take its default from" in refused.text


def test_an_ontology_export_carries_it(client, fx, planes) -> None:
    action = details(client, fx, planes)
    name = client.get(f"{wbase(fx)}/action-types/{action}",
                      headers=hdr(fx.viewer_sub)).json()["api_name"]
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [a for a in document["action_types"] if a["api_name"] == name]
    by_name = {p["api_name"]: p for p in exported["parameters"]}
    assert by_name["model"]["default_from"] == {"parameter": "plane", "property": "model"}
    assert "default_from" not in by_name["plane"]


# ---- the pure part ----------------------------------------------------------------
def test_an_object_that_holds_nothing_there_gives_no_default() -> None:
    p = {"api_name": "model", "default_from": {"parameter": "plane", "property": "model"}}
    assert action_defaults.resolve([p], {"plane": {}}) == [p]
    assert action_defaults.resolve([p], {}) == [p]
    assert action_defaults.resolve([p], {"plane": {"model": "A320"}})[0]["default_value"] == "A320"


def check(parameters, **over):
    options = dict(
        order=[p["api_name"] for p in parameters],
        object_types={"plane": "t"},
        properties_by_type={"t": {"model": "string", "spec": "struct"}},
        struct_fields_by_type={"t": {"spec": [{"api_name": "seats", "data_type": "string"}]}},
        parameter_fields={"spec": [{"api_name": "seats", "data_type": "integer"}]},
    )
    options.update(over)
    action_defaults.check(parameters, **options)


def test_an_object_parameter_that_says_no_type_has_nothing_to_read() -> None:
    parameters = [{"api_name": "plane", "data_type": "object"},
                  {"api_name": "model", "data_type": "string",
                   "default_from": {"parameter": "plane", "property": "model"}}]
    with pytest.raises(ValueError, match="'plane' does not say which object type it holds"):
        check(parameters, object_types={})


def test_a_struct_field_takes_a_default_only_of_its_own_type() -> None:
    parameters = [{"api_name": "plane", "data_type": "object"},
                  {"api_name": "spec", "data_type": "struct",
                   "default_from": {"parameter": "plane", "property": "spec"}}]
    with pytest.raises(ValueError, match="field 'seats' is a integer and 'seats' is a string"):
        check(parameters)
