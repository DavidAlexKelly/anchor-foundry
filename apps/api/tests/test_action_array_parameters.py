"""Array parameters on actions (§580; db 0118; `object-link-types` p.86, p.116;
`action-types` p.127).

> "Array properties cannot contain null elements." (p.86)
> "Array properties cannot be empty: Setting an array property to required
>  ensures the presence of at least one item." (p.116)

db 0087 made `array` storable on a parameter and refused it at save, because a
parameter could not say *of what* and the form had nothing that collects
several values. db 0118 is the first half and the form's list control the
second. With both, an action can write an array property - which, until this
unit, no action could: the write path coerced an array without its element
type, and that coercion refuses (every such write was refused).
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
from src.services import actions as actions_service  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

TAGGED = (
    b"key,name,tags,counts,spot\n"
    b'T1,First,"[""alpha""]","[""1""]","{""floors"": 1}"\n'
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("array-actions")))
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
def tagged(client: TestClient, fx: Fixture) -> dict:
    """A synced type with two array properties, one of strings and one of
    integers - an integer element because `string` is what an unread element
    type falls back to, so strings alone could not tell the difference."""
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Tagged {tag}"},
        files={"file": ("tagged.csv", io.BytesIO(TAGGED), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"tagged_{tag}", "display_name": f"Tagged {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "name", "data_type": "string"},
                  {"api_name": "tags", "data_type": "array", "array_of": "string"},
                  {"api_name": "counts", "data_type": "array", "array_of": "integer"},
                  {"api_name": "spot", "data_type": "struct",
                   "struct_fields": [{"api_name": "floors", "data_type": "integer"}]},
              ],
              "title_property": "name"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "name": "name", "tags": "tags",
                                  "counts": "counts", "spot": "spot"}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub))
    assert synced.status_code == 200, synced.text
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {"type_id": type_id, "instance_id": items[0]["id"], "tag": tag}


def make_action(client, fx, tagged, **extra) -> str:
    made = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": tagged["type_id"],
              "api_name": f"act_{uuid.uuid4().hex[:6]}", "display_name": "Act",
              "editable_properties": ["name"], **extra},
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


def define(client, fx, action_id: str, parameters: list[dict], rules: list[dict]):
    return client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": parameters, "rules": rules, "criteria": []},
    )


def array(name: str, of: str | None, **extra) -> dict:
    return {"api_name": name, "display_name": name.capitalize(), "data_type": "array",
            **({"array_of": of} if of is not None else {}), **extra}


def writes(prop: str, parameter: str) -> dict:
    return {"kind": "modify_object", "config": {"property": prop, "parameter": parameter}}


# ---- the declaration --------------------------------------------------------------
@pytest.mark.parametrize("parameter, said", [
    (array("tags", None), "is an array and does not say what of"),
    (array("tags", "  "), "is an array and does not say what of"),
    (array("tags", "array"), "cannot be an array of 'array'"),
    (array("tags", "time_series"), "cannot be an array of 'time_series'"),
    ({"api_name": "tags", "display_name": "Tags", "data_type": "string",
      "array_of": "string"}, "is a string, so it cannot say what it is an array of"),
    (array("tags", "string", options_from={"object_type_id": str(uuid.uuid4()),
                                           "property": "name"}),
     # `action_options`' own refusal, which already covered it (§580 wrote a
     # second one and the test showed it could never be reached).
     "cannot be offered as a list of values"),
])
def test_an_array_parameter_says_what_of_or_is_refused(client, fx, tagged, parameter, said):
    action = make_action(client, fx, tagged)
    refused = define(client, fx, action, [parameter], [])
    assert refused.status_code == 422, refused.text
    assert said in refused.text


def test_an_array_parameter_is_kept_with_its_element_type(client, fx, tagged):
    action = make_action(client, fx, tagged)
    saved = define(client, fx, action, [array("tags", "string")], [writes("tags", "tags")])
    assert saved.status_code == 200, saved.text
    got = client.get(f"{wbase(fx)}/action-types/{action}", headers=hdr(fx.viewer_sub)).json()
    [parameter] = got["parameters"]
    assert (parameter["data_type"], parameter["array_of"]) == ("array", "string")
    scalar = next(p for p in client.get(
        f"{wbase(fx)}/action-types/{make_action(client, fx, tagged)}",
        headers=hdr(fx.viewer_sub)).json()["parameters"])
    assert scalar["array_of"] is None


def test_an_array_property_made_editable_becomes_an_array_parameter(client, fx, tagged):
    """p.30's create screen writes one parameter per editable property, and an
    array property's is an array of what the property holds."""
    action = make_action(client, fx, tagged, editable_properties=["counts", "tags"])
    got = client.get(f"{wbase(fx)}/action-types/{action}", headers=hdr(fx.viewer_sub)).json()
    held = {p["api_name"]: p["array_of"] for p in got["parameters"]}
    assert held == {"counts": "integer", "tags": "string"}


# ---- the write --------------------------------------------------------------------
def execute(client, fx, action: str, instance_id: str, values: dict):
    return client.post(f"{abase(fx)}/{action}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": instance_id, "values": values})


def test_an_action_writes_an_array_property_element_by_element(client, fx, tagged):
    action = make_action(client, fx, tagged, editable_properties=["counts", "tags"])
    done = execute(client, fx, action, tagged["instance_id"],
                   {"tags": ["x", "y"], "counts": ["3", 4]})
    assert done.status_code == 200, done.text
    held = done.json()["instance"]["properties"]
    assert held["tags"] == ["x", "y"]
    # **The integers are the assertion**: an element type that never reached
    # the coercer would have refused the write, or left "3" a string.
    assert held["counts"] == [3, 4]


@pytest.mark.parametrize("values, said", [
    ({"counts": ["a"]}, "element 0 (integer)"),
    ({"counts": [1, None]}, "element 1 is null"),
    ({"counts": "3"}, "an array value must be a list"),
])
def test_an_element_the_array_cannot_hold_is_refused(client, fx, tagged, values, said):
    action = make_action(client, fx, tagged, editable_properties=["counts"])
    refused = execute(client, fx, action, tagged["instance_id"], values)
    assert refused.status_code == 422, refused.text
    assert said in refused.text


def test_a_required_array_needs_an_item(client, fx, tagged):
    action = make_action(client, fx, tagged)
    assert define(client, fx, action, [array("tags", "string", required=True)],
                  [writes("tags", "tags")]).status_code == 200
    refused = execute(client, fx, action, tagged["instance_id"], {"tags": []})
    assert refused.status_code == 422, refused.text
    assert "an empty list is not an answer" in refused.text
    done = execute(client, fx, action, tagged["instance_id"], {"tags": ["kept"]})
    assert done.status_code == 200, done.text


def test_an_optional_array_may_be_emptied(client, fx, tagged):
    action = make_action(client, fx, tagged, editable_properties=["tags"])
    done = execute(client, fx, action, tagged["instance_id"], {"tags": []})
    assert done.status_code == 200, done.text
    assert done.json()["instance"]["properties"]["tags"] == []


def test_bind_refuses_only_an_empty_required_array():
    parameters = [{"api_name": "tags", "data_type": "array", "required": True},
                  {"api_name": "note", "data_type": "string", "required": True}]
    with pytest.raises(ValueError, match="an empty list is not an answer"):
        actions_service.bind_parameters({"tags": [], "note": ""}, parameters=parameters)
    # A required string given "" is not this rule's business.
    assert actions_service.bind_parameters({"tags": ["a"], "note": ""},
                                           parameters=parameters) == {"tags": ["a"], "note": ""}


def test_a_created_object_takes_its_arrays(client, fx, tagged):
    """The create path coerced with the type alone, so a created object's
    array (or struct) property was refused for want of the declaration its
    context already held."""
    action = make_action(client, fx, tagged)
    saved = define(
        client, fx, action,
        [{"api_name": "key", "display_name": "Key", "data_type": "string"},
         {"api_name": "name", "display_name": "Name", "data_type": "string"},
         array("counts", "integer")],
        [{"kind": "create_object", "config": {
            "primary_key": "key",
            "properties": {"key": "key", "name": "name", "counts": "counts"}}}],
    )
    assert saved.status_code == 200, saved.text
    done = client.post(f"{abase(fx)}/{action}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": tagged["instance_id"],
                             "values": {"key": "T9", "name": "Made", "counts": ["5", "6"]}})
    assert done.status_code == 200, done.text
    items = client.get(f"{wbase(fx)}/object-types/{tagged['type_id']}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    made = next(i for i in items if i["properties"]["key"] == "T9")
    assert made["properties"]["counts"] == [5, 6]


def test_the_element_type_travels_with_an_exported_ontology(client, fx, tagged):
    action = make_action(client, fx, tagged, editable_properties=["counts", "name"])
    doc = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    exported = next(a for a in doc["action_types"] if a["api_name"] == client.get(
        f"{wbase(fx)}/action-types/{action}", headers=hdr(fx.viewer_sub)).json()["api_name"])
    held = {p["api_name"]: p.get("array_of") for p in exported["parameters"]}
    assert held == {"counts": "integer", "name": None}


def test_a_created_object_takes_its_structs(client, fx, tagged):
    """The same gap for p.66's struct: a create of the subject's own type
    coerced a struct with no fields to read it against, and was refused."""
    action = make_action(client, fx, tagged)
    saved = define(
        client, fx, action,
        [{"api_name": "key", "display_name": "Key", "data_type": "string"},
         {"api_name": "spot", "display_name": "Spot", "data_type": "struct"}],
        [{"kind": "create_object", "config": {
            "primary_key": "key", "properties": {"key": "key", "spot": "spot"}}}],
    )
    assert saved.status_code == 200, saved.text
    done = client.post(f"{abase(fx)}/{action}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": tagged["instance_id"],
                             "values": {"key": "T8", "spot": {"floors": "3"}}})
    assert done.status_code == 200, done.text
    items = client.get(f"{wbase(fx)}/object-types/{tagged['type_id']}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    made = next(i for i in items if i["properties"]["key"] == "T8")
    assert made["properties"]["spot"] == {"floors": 3}


def test_the_action_editor_offers_every_element_type_the_server_takes() -> None:
    """§191's drift guard for the parameter's element list. The property
    editor's `ELEMENT_TYPES` leaves `attachment` out for want of an upload,
    which that test states; an action form has one, so the parameter list is
    that list **and** attachment - p.127's "Allow multiple values" for an
    attachment parameter - and object, p.36's ObjectReference list (§581),
    which no property holds. Together they must be the server's."""
    import re

    from src.services import actions as actions_service

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    editor = open(os.path.join(root, "web", "src", "components",
                               "action-definition-editor.tsx"), encoding="utf-8").read()
    listed = re.search(r"const PARAMETER_ELEMENTS = \[(.*?)\];", editor, re.S)
    assert listed, "PARAMETER_ELEMENTS not found - has the editor moved?"
    assert listed.group(1).replace(" ", "") == '...ELEMENT_TYPES,"attachment","object"'
    types = re.search(r"const PARAMETER_TYPES = \[(.*?)\];", editor, re.S)
    assert types and '"array"' in types.group(1)
    elements = open(os.path.join(root, "web", "src", "lib", "array-property.ts"),
                    encoding="utf-8").read()
    base = re.search(r"export const ELEMENT_TYPES: PropertyDataType\[\] = \[(.*?)\];",
                     elements, re.S)
    assert base
    offered = set(re.findall(r'"([a-z_]+)"', base.group(1))) | {"attachment", "object"}
    assert offered == set(actions_service._parameter_elements())
