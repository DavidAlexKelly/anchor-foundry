"""p.73's function-backed variables (§772; decision 0018 option B; Foundry
`workshop` p.73, `functions` p.79-80).

> "Function: For function-backed, dynamically computed variables" (p.73)

> "Below is the mapping between Workshop variable types and their equivalents
> … Numeric … Array … Object Set" (`functions` p.80)

Resolved through the module's own resolve, as an aggregation is (§617): the
function is called as the viewer with its inputs as the module holds them,
and its answer feeds what is downstream.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import variable_aggregates  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402
from test_api import hdr  # noqa: E402
from test_variable_aggregates import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, module, pbase, resolve, type_id, wbase,
)


def publish(client, fx, type_id: str, *, sql: str, output: dict, parameters=None) -> dict:
    r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F",
        "version": {"version": "1.0.0", "parameters": parameters or [], "inputs": [type_id],
                    "output": output, "sql": sql}})
    assert r.status_code == 201, r.text
    return r.json()


def table(client, fx, type_id: str) -> str:
    return client.get(f"{wbase(fx)}/object-types/{type_id}",
                      headers=hdr(fx.viewer_sub)).json()["api_name"]


def function_variable(vid: str, kind: str, fn: dict, inputs: dict[str, str],
                      values: dict | None = None, version: str | None = None) -> dict:
    return {"id": vid, "kind": kind, "label": vid, "derivation": {
        "transform": "function", "inputs": list(inputs.values()),
        "config": {"function_id": fn["id"], "version": version,
                   "parameters": list(inputs), "values": values or {}}}}


def test_a_number_from_a_function_of_other_variables(client, fx, type_id) -> None:
    t = table(client, fx, type_id)
    fn = publish(client, fx, type_id,
                 sql=f"SELECT coalesce(sum(capacity), 0) FROM {t} "
                     "WHERE region = $region AND capacity >= $minimum",
                 output={"kind": "value", "data_type": "integer"},
                 parameters=[{"api_name": "region", "data_type": "string"},
                             {"api_name": "minimum", "data_type": "integer"}])
    app = module(client, fx, {
        "v_region": {"id": "v_region", "kind": "string", "label": "Region", "default": "north"},
        "v_total": function_variable("v_total", "number", fn, {"region": "v_region"},
                                     values={"minimum": 15}),
        "v_two": {"id": "v_two", "kind": "number", "label": "Two", "default": 2},
        "v_twice": {"id": "v_twice", "kind": "number", "label": "Twice", "derivation": {
            "transform": "multiply", "inputs": ["v_total", "v_two"]}},
    })
    r = resolve(client, fx, app)
    assert r.status_code == 200, r.text
    got = r.json()["values"]
    # North's 10 and 20, of which only 20 is at least 15; and downstream of it.
    assert (got["v_total"], got["v_twice"]) == (20, 40)


def test_an_object_set_and_an_array_from_a_function(client, fx, type_id) -> None:
    t = table(client, fx, type_id)
    big = publish(client, fx, type_id,
                  sql=f"SELECT __primary_key FROM {t} WHERE list_contains($within, __primary_key) "
                      "AND capacity > 15 ORDER BY 1",
                  output={"kind": "object_set", "object_type_id": type_id},
                  parameters=[{"api_name": "within", "data_type": "object_set",
                               "object_type_id": type_id}])
    regions = publish(client, fx, type_id,
                      sql=f"SELECT DISTINCT region FROM {t} ORDER BY 1",
                      output={"kind": "array", "data_type": "string"})
    app = module(client, fx, {
        "v_north": {"id": "v_north", "kind": "object_set", "label": "North",
                    "object_set": {"object_type_id": type_id, "filters": [
                        {"property": "region", "op": "eq", "value": "north"}]}},
        "v_big": function_variable("v_big", "object_set", big, {"within": "v_north"}),
        "v_regions": function_variable("v_regions", "array", regions, {}),
    })
    got = resolve(client, fx, app).json()["values"]
    # The set variable's members went in by their keys; the answer is a set
    # of the output's type, narrowed to the keys the function gave.
    assert got["v_big"] == {"object_type_id": type_id, "filters": [
        {"property": "$primary_key", "op": "in", "value": ["S3"]}]}
    assert got["v_regions"] == ["east", "north", "south"]
    r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=hdr(fx.viewer_sub),
                    json={"definition": got["v_big"], "limit": 10})
    assert [i["primary_key"] for i in r.json()["instances"]] == ["S3"]


def test_a_picked_object_goes_in_by_its_id(client, fx, type_id) -> None:
    t = table(client, fx, type_id)
    fn = publish(client, fx, type_id,
                 sql=f"SELECT capacity FROM {t} WHERE __primary_key = $site",
                 output={"kind": "value", "data_type": "integer"},
                 parameters=[{"api_name": "site", "data_type": "object",
                              "object_type_id": type_id}])
    instance = next(i for i in client.get(
        f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub)
    ).json()["items"] if i["primary_key"] == "S2")
    app = module(client, fx, {
        "v_site": {"id": "v_site", "kind": "single_object", "label": "Site"},
        "v_capacity": function_variable("v_capacity", "number", fn, {"site": "v_site"}),
    })
    r = client.post(f"{pbase(fx)}/canvas-apps/{app}/variables/evaluate",
                    headers=hdr(fx.viewer_sub), json={"values": {"v_site": {
                        "id": instance["id"], "object_type_id": type_id,
                        "primary_key": "S2", "properties": instance["properties"]}}})
    assert r.status_code == 200, r.text
    assert r.json()["values"]["v_capacity"] == 30
    # Nothing picked: a required input with nothing in it is refused by name.
    r = resolve(client, fx, app)
    assert r.status_code == 422, r.text
    assert "site needs a value" in r.text


@pytest.mark.parametrize("kind,output,said", [
    ("number", {"kind": "array", "data_type": "integer"},
     "returns array, and a number variable takes value"),
    ("array", {"kind": "value", "data_type": "integer"},
     "returns value, and a array variable takes array"),
])
def test_the_output_must_be_what_the_variable_holds(client, fx, type_id, kind, output, said) -> None:
    t = table(client, fx, type_id)
    sql = f"SELECT capacity FROM {t} LIMIT 1"
    fn = publish(client, fx, type_id, sql=sql, output=output)
    app = module(client, fx, {"v": function_variable("v", kind, fn, {})})
    r = resolve(client, fx, app)
    assert r.status_code == 422, r.text
    assert said in r.text


def test_a_named_version_and_a_missing_one(client, fx, type_id) -> None:
    t = table(client, fx, type_id)
    fn = publish(client, fx, type_id, sql=f"SELECT count(*) FROM {t}",
                 output={"kind": "value", "data_type": "integer"})
    r = client.post(f"{wbase(fx)}/functions/{fn['id']}/versions", headers=hdr(fx.editor_sub),
                    json={"version": "1.1.0", "inputs": [type_id],
                          "output": {"kind": "value", "data_type": "integer"},
                          "sql": f"SELECT count(*) * 100 FROM {t}"})
    assert r.status_code == 201, r.text
    app = module(client, fx, {
        "v_pinned": function_variable("v_pinned", "number", fn, {}, version="1.0.0"),
        "v_newest": function_variable("v_newest", "number", fn, {}),
    })
    got = resolve(client, fx, app).json()["values"]
    assert (got["v_pinned"], got["v_newest"]) == (4, 400)
    app = module(client, fx, {"v": function_variable("v", "number", fn, {}, version="9.0.0")})
    r = resolve(client, fx, app)
    assert r.status_code == 422, r.text
    assert "has no version 9.0.0" in r.text
    app = module(client, fx, {"v": function_variable(
        "v", "number", {"id": str(uuid.uuid4())}, {})})
    r = resolve(client, fx, app)
    assert r.status_code == 422, r.text
    assert "is not here" in r.text


def test_a_set_larger_than_a_function_is_given_is_refused(
    client, fx, type_id, monkeypatch
) -> None:
    t = table(client, fx, type_id)
    fn = publish(client, fx, type_id,
                 sql=f"SELECT count(*) FROM {t} WHERE list_contains($within, __primary_key)",
                 output={"kind": "value", "data_type": "integer"},
                 parameters=[{"api_name": "within", "data_type": "object_set",
                              "object_type_id": type_id}])
    monkeypatch.setattr(variable_aggregates, "MAX_SET_INPUT", 3)
    app = module(client, fx, {
        "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                  "object_set": {"object_type_id": type_id, "filters": []}},
        "v": function_variable("v", "number", fn, {"within": "v_all"}),
    })
    r = resolve(client, fx, app)
    assert r.status_code == 422, r.text
    assert "holds 4 objects, more than the 3" in r.text


@pytest.mark.parametrize("config,said", [
    ({"parameters": []}, "names its function"),
    ({"function_id": "f"}, "names the parameter each of its inputs feeds"),
    ({"function_id": "f", "parameters": ["a", "b"]}, "names the parameter each"),
    ({"function_id": "f", "parameters": [3]}, "names the parameter each"),
    ({"function_id": "f", "parameters": ["a"], "values": []}, "values are an object"),
])
def test_a_function_variable_that_cannot_be_called_is_refused_at_save(config, said) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({
            "a": {"id": "a", "kind": "string", "label": "A"},
            "v": {"id": "v", "kind": "number", "label": "V", "derivation": {
                "transform": "function", "inputs": ["a"], "config": config}}})
    assert said in str(caught.value)


def test_the_call_is_asked_for_and_keyed_by_what_it_is_given() -> None:
    """`evaluate` stays pure: it names the call and reads the answer back."""
    variables = wv.parse({
        "a": {"id": "a", "kind": "string", "label": "A", "default": "north"},
        "v": {"id": "v", "kind": "number", "label": "V", "derivation": {
            "transform": "function", "inputs": ["a"],
            "config": {"function_id": "f", "parameters": ["region"], "values": {"n": 1}}}}})
    wanted: dict = {}
    assert wv.evaluate(variables, {}, aggregates={}, wanted=wanted)["v"] is None
    [(key, request)] = wanted.items()
    assert request == {"function": "f", "version": None, "kind": "number",
                       "values": {"n": 1, "region": "north"}}
    assert wv.evaluate(variables, {}, aggregates={key: 7})["v"] == 7


@pytest.mark.parametrize("kind", ["single_object", "struct", "object_set_filter"])
def test_a_kind_a_function_cannot_fill_is_refused_at_save(kind) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse({"v": {"id": "v", "kind": kind, "label": "V", "derivation": {
            "transform": "function", "inputs": [],
            "config": {"function_id": "f", "parameters": []}}}})
    assert f"is a {kind}, which a function cannot fill" in str(caught.value)


@pytest.mark.parametrize("kind", wv.FUNCTION_KINDS)
def test_every_kind_a_function_fills_is_taken(kind) -> None:
    variables = wv.parse({"v": {"id": "v", "kind": kind, "label": "V", "derivation": {
        "transform": "function", "inputs": [],
        "config": {"function_id": "f", "parameters": []}}}})
    assert variables["v"].derivation.transform == "function"


def test_a_function_variable_reads_another(client, fx, type_id) -> None:
    """A chain of calls resolves: each is a question the next pass answers."""
    t = table(client, fx, type_id)
    total = publish(client, fx, type_id, sql=f"SELECT sum(capacity) FROM {t}",
                    output={"kind": "value", "data_type": "integer"})
    above = publish(client, fx, type_id,
                    sql=f"SELECT count(*) FROM {t} WHERE capacity * 4 > $total",
                    output={"kind": "value", "data_type": "integer"},
                    parameters=[{"api_name": "total", "data_type": "integer"}])
    app = module(client, fx, {
        "v_total": function_variable("v_total", "number", total, {}),
        "v_above": function_variable("v_above", "number", above, {"total": "v_total"}),
    })
    r = resolve(client, fx, app)
    assert r.status_code == 200, r.text
    got = r.json()["values"]
    # 10, 30, 20 and none: a quarter of 60 is 15, so two are above it.
    assert (got["v_total"], got["v_above"]) == (60, 2)


def test_a_parameter_fed_by_a_variable_and_a_value_takes_the_variable(client, fx, type_id) -> None:
    t = table(client, fx, type_id)
    fn = publish(client, fx, type_id,
                 sql=f"SELECT count(*) FROM {t} WHERE region = $region",
                 output={"kind": "value", "data_type": "integer"},
                 parameters=[{"api_name": "region", "data_type": "string"}])
    app = module(client, fx, {
        "v_region": {"id": "v_region", "kind": "string", "label": "Region", "default": "south"},
        "v": function_variable("v", "number", fn, {"region": "v_region"},
                               values={"region": "north"}),
    })
    assert resolve(client, fx, app).json()["values"]["v"] == 1


def test_a_set_is_read_whole_a_page_at_a_time(client, fx, type_id, monkeypatch) -> None:
    from src.services import instance_store

    t = table(client, fx, type_id)
    fn = publish(client, fx, type_id,
                 sql=f"SELECT count(*) FROM {t} WHERE list_contains($within, __primary_key)",
                 output={"kind": "value", "data_type": "integer"},
                 parameters=[{"api_name": "within", "data_type": "object_set",
                              "object_type_id": type_id}])
    monkeypatch.setattr(instance_store, "INSTANCE_PAGE_SIZE", 3)
    app = module(client, fx, {
        "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                  "object_set": {"object_type_id": type_id, "filters": []}},
        "v": function_variable("v", "number", fn, {"within": "v_all"}),
    })
    assert resolve(client, fx, app).json()["values"]["v"] == 4
