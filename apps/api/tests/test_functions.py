"""Functions: versioned SQL over the ontology (decision 0018 option B; §768;
db 0153; Foundry `functions` p.49-50, p.79-81).

The registry, the save-time check, the call and the sandbox. Each consumer
(an Object Table column, a chart layer, a variable, an action) has its own
unit and tests.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import function_engine as engine  # noqa: E402
from src.services import functions as functions_service  # noqa: E402
from test_api import hdr  # noqa: E402
from test_interface_actions import _sync, client, fx, pbase, wbase  # noqa: E402,F401

SITES = (b"code,region,capacity,opened\n"
         b"S1,north,10,2024-01-05\nS2,north,30,2024-03-01\nS3,south,25,2023-11-20\n")


@pytest.fixture(scope="module")
def sites(client, fx) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"site_{tag}", "display_name": f"Site {tag}",
        "properties": [{"api_name": "code", "data_type": "string"},
                       {"api_name": "region", "data_type": "string"},
                       {"api_name": "capacity", "data_type": "integer"},
                       {"api_name": "opened", "data_type": "date"}],
        "title_property": "code"})
    assert r.status_code == 201, r.text
    kind = r.json()
    first = _sync(client, fx, kind["id"], SITES, "code",
                  {"code": "code", "region": "region", "capacity": "capacity",
                   "opened": "opened"}, f"Sites {tag}")
    return {"type": kind, "table": kind["api_name"], "first": first}


def create(client, fx, sites, *, sql: str, output: dict, parameters=None, version="1.0.0",
           api_name: str | None = None, inputs=None):
    return client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": api_name or f"fn_{uuid.uuid4().hex[:6]}",
        "display_name": "A function",
        "version": {"version": version, "parameters": parameters or [],
                    "inputs": [sites["type"]["id"]] if inputs is None else inputs,
                    "output": output, "sql": sql}})


def call(client, fx, function_id: str, values=None, version=None, who=None):
    return client.post(f"{wbase(fx)}/functions/{function_id}/execute",
                       headers=hdr(who or fx.viewer_sub),
                       json={"values": values or {}, "version": version})


# ---- the call ------------------------------------------------------------------

def test_a_value_function_reads_the_objects_with_its_parameters(client, fx, sites) -> None:
    r = create(client, fx, sites,
               sql=f"SELECT sum(capacity) FROM {sites['table']} WHERE region = $region",
               output={"kind": "value", "data_type": "integer"},
               parameters=[{"api_name": "region", "data_type": "string"}])
    assert r.status_code == 201, r.text
    fn = r.json()
    assert (fn["latest_version"], len(fn["versions"])) == ("1.0.0", 1)
    r = call(client, fx, fn["id"], {"region": "north"})
    assert r.status_code == 200, r.text
    assert r.json() == {**r.json(), "kind": "value", "value": 40, "version": "1.0.0"}
    assert call(client, fx, fn["id"], {"region": "west"}).json()["value"] is None


def test_each_output_kind(client, fx, sites) -> None:
    table = sites["table"]
    arr = create(client, fx, sites, sql=f"SELECT opened FROM {table} ORDER BY opened",
                 output={"kind": "array", "data_type": "date"}).json()
    assert call(client, fx, arr["id"]).json()["values"] == [
        "2023-11-20", "2024-01-05", "2024-03-01"]
    objs = create(client, fx, sites,
                  sql=f"SELECT __primary_key FROM {table} WHERE capacity > 20 ORDER BY 1",
                  output={"kind": "object_set", "object_type_id": sites["type"]["id"]}).json()
    assert call(client, fx, objs["id"]).json()["values"] == ["S2", "S3"]
    tab = create(client, fx, sites,
                 sql=f"SELECT region, count(*) AS n FROM {table} GROUP BY 1 ORDER BY 1",
                 output={"kind": "table"}).json()
    got = call(client, fx, tab["id"]).json()
    assert [c["name"] for c in got["columns"]] == ["region", "n"]
    assert got["rows"] == [["north", 2], ["south", 1]]


def test_an_object_parameter_is_read_by_its_primary_key(client, fx, sites) -> None:
    fn = create(client, fx, sites,
                sql=f"SELECT capacity FROM {sites['table']} WHERE __primary_key = $site",
                output={"kind": "value", "data_type": "integer"},
                parameters=[{"api_name": "site", "data_type": "object",
                             "object_type_id": sites["type"]["id"]}]).json()
    first = client.get(f"{wbase(fx)}/object-types/{sites['type']['id']}/instances/"
                       f"{sites['first']}", headers=hdr(fx.viewer_sub)).json()
    r = call(client, fx, fn["id"], {"site": sites["first"]})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == first["properties"]["capacity"]
    r = call(client, fx, fn["id"], {"site": str(uuid.uuid4())})
    assert r.status_code == 422, r.text
    assert "site: no such object" in r.text


@pytest.mark.parametrize("values,said", [
    ({}, "region needs a value"),
    ({"region": "north", "other": 1}, "takes no parameter other"),
    ({"region": "north", "minimum": "ten"}, "minimum: 'ten' is not a integer"),
    ({"region": "north", "minimum": 2.5}, "minimum: 2.5 is not a integer"),
    ({"region": "north", "minimum": True}, "minimum: True is not a integer"),
])
def test_values_are_checked_against_the_parameters(client, fx, sites, values, said) -> None:
    fn = create(client, fx, sites,
                sql=f"SELECT count(*) FROM {sites['table']} "
                    "WHERE region = $region AND capacity >= coalesce($minimum, 0)",
                output={"kind": "value", "data_type": "integer"},
                parameters=[{"api_name": "region", "data_type": "string"},
                            {"api_name": "minimum", "data_type": "integer",
                             "required": False}]).json()
    assert call(client, fx, fn["id"], {"region": "north"}).json()["value"] == 2
    assert call(client, fx, fn["id"], {"region": "north", "minimum": 20}).json()["value"] == 1
    r = call(client, fx, fn["id"], values)
    assert r.status_code == 422, r.text
    assert said in r.text


def test_typed_parameters_bind_as_their_types(client, fx, sites) -> None:
    fn = create(client, fx, sites,
                sql=f"SELECT count(*) FROM {sites['table']} WHERE opened >= $since "
                    "AND (capacity > $cap) = $flag AND $ratio >= 0",
                output={"kind": "value", "data_type": "integer"},
                parameters=[{"api_name": "since", "data_type": "date"},
                            {"api_name": "cap", "data_type": "integer"},
                            {"api_name": "flag", "data_type": "boolean"},
                            {"api_name": "ratio", "data_type": "float"}]).json()
    r = call(client, fx, fn["id"], {"since": "2024-01-01", "cap": 20, "flag": True,
                                    "ratio": 0.5})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 1
    r = call(client, fx, fn["id"], {"since": "soon", "cap": 1, "flag": True, "ratio": 1})
    assert "since: 'soon' is not a date" in r.text
    r = call(client, fx, fn["id"], {"since": "2024-01-01", "cap": 1, "flag": "yes", "ratio": 1})
    assert "flag: 'yes' is not a boolean" in r.text
    r = call(client, fx, fn["id"], {"since": "2024-01-01", "cap": 1, "flag": True, "ratio": False})
    assert "ratio: False is not a float" in r.text


def test_a_result_that_is_not_its_output_is_refused(client, fx, sites) -> None:
    many = create(client, fx, sites, sql=f"SELECT capacity FROM {sites['table']}",
                  output={"kind": "value", "data_type": "integer"}).json()
    r = call(client, fx, many["id"])
    assert r.status_code == 422, r.text
    assert "more than one row" in r.text
    wrong = create(client, fx, sites, sql=f"SELECT region FROM {sites['table']} LIMIT 1",
                   output={"kind": "value", "data_type": "integer"}).json()
    r = call(client, fx, wrong["id"])
    assert r.status_code == 422, r.text
    assert "returned 'region', which is not a integer" in r.text


# ---- the registry --------------------------------------------------------------

def test_a_version_is_immutable_and_a_change_is_a_greater_one(client, fx, sites) -> None:
    """p.49: "chosen by their publishers and are immutable after creation"."""
    fn = create(client, fx, sites, sql=f"SELECT count(*) FROM {sites['table']}",
                output={"kind": "value", "data_type": "integer"}).json()
    body = {"version": "1.1.0", "inputs": [sites["type"]["id"]],
            "output": {"kind": "value", "data_type": "integer"},
            "sql": f"SELECT count(*) * 10 FROM {sites['table']}"}
    for stale in ("1.0.0", "0.9.0", "1.0.0-rc1"):
        r = client.post(f"{wbase(fx)}/functions/{fn['id']}/versions",
                        headers=hdr(fx.editor_sub), json={**body, "version": stale})
        assert r.status_code == 422, r.text
        assert "is not after 1.0.0" in r.text
    r = client.post(f"{wbase(fx)}/functions/{fn['id']}/versions",
                    headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    assert [v["version"] for v in r.json()["versions"]] == ["1.1.0", "1.0.0"]
    assert r.json()["latest_version"] == "1.1.0"
    # The newest by default, and the one named when one is.
    assert call(client, fx, fn["id"]).json() == {**call(client, fx, fn["id"]).json(),
                                                 "value": 30, "version": "1.1.0"}
    assert call(client, fx, fn["id"], version="1.0.0").json()["value"] == 3
    r = call(client, fx, fn["id"], version="9.9.9")
    assert r.status_code == 404, r.text


def test_semantic_versions_order_as_p50_says() -> None:
    order = ["0.1.0", "1.0.0-rc1", "1.0.0-rc2", "1.0.0", "1.0.1", "1.2.0", "1.10.0", "2.0.0"]
    assert sorted(reversed(order), key=functions_service.version_key) == order
    for bad in ("1", "1.0", "v1.0.0", "01.0.0", "1.0.0-", "1.0.0+build"):
        with pytest.raises(engine.FunctionError):
            functions_service.version_key(bad)


@pytest.mark.parametrize("sql,said", [
    ("SELECT nope FROM {t}", "nope"),
    ("SELECT 1 FROM missing_table", "missing_table"),
    ("SELECT 1; SELECT 2", "has 2 statements"),
    ("DELETE FROM {t}", "must be a SELECT"),
    ("SELECT count(*) FROM {t} WHERE region = $region", "$region, which no parameter declares"),
    ("SELECT count(*) FROM {t}", "$unused is declared and the SQL never uses it"),
    ("SELEC 1", "syntax error"),
])
def test_a_version_is_checked_by_running_it(client, fx, sites, sql, said) -> None:
    params = [{"api_name": "unused", "data_type": "string"}] if "never uses" in said else []
    r = create(client, fx, sites, sql=sql.format(t=sites["table"]),
               output={"kind": "value", "data_type": "integer"}, parameters=params)
    assert r.status_code == 422, r.text
    assert said in r.text


@pytest.mark.parametrize("change,said", [
    ({"parameters": [{"api_name": "Bad", "data_type": "string"}]}, "invalid parameter name"),
    ({"parameters": [{"api_name": "a", "data_type": "string"},
                     {"api_name": "a", "data_type": "string"}]}, "two parameters are called a"),
    ({"parameters": [{"api_name": "a", "data_type": "geopoint"}]}, "is not a parameter type"),
    ({"parameters": [{"api_name": "a", "data_type": "object"}]}, "names its object type"),
    ({"output": {"kind": "chart"}}, "is not an output"),
    ({"output": {"kind": "value"}}, "a value output is one of"),
    ({"output": {"kind": "object_set"}}, "an object set output names its object type"),
    ({"inputs": [str(uuid.uuid4())]}, "no object type"),
    ({"version": "one"}, "is not a semantic version"),
])
def test_a_definition_that_cannot_hold_is_refused_by_name(client, fx, sites, change, said) -> None:
    version = {"version": "1.0.0", "parameters": [], "inputs": [sites["type"]["id"]],
               "output": {"kind": "value", "data_type": "integer"},
               "sql": f"SELECT count(*) FROM {sites['table']}", **change}
    r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": version})
    assert r.status_code == 422, r.text
    assert said in r.text


def test_names_are_unique_and_well_formed(client, fx, sites) -> None:
    name = f"fn_{uuid.uuid4().hex[:6]}"
    output = {"kind": "value", "data_type": "integer"}
    sql = f"SELECT count(*) FROM {sites['table']}"
    assert create(client, fx, sites, sql=sql, output=output, api_name=name).status_code == 201
    r = create(client, fx, sites, sql=sql, output=output, api_name=name)
    assert r.status_code == 409, r.text
    r = create(client, fx, sites, sql=sql, output=output, api_name="Bad Name")
    assert r.status_code == 422, r.text


def test_who_may_publish_rename_delete_and_call(client, fx, sites) -> None:
    fn = create(client, fx, sites, sql=f"SELECT count(*) FROM {sites['table']}",
                output={"kind": "value", "data_type": "integer"}).json()
    r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.viewer_sub), json={
        "api_name": "nope", "display_name": "N", "version": {}})
    assert r.status_code in (403, 422), r.text
    assert client.patch(f"{wbase(fx)}/functions/{fn['id']}", headers=hdr(fx.viewer_sub),
                        json={"display_name": "X"}).status_code == 403
    r = client.patch(f"{wbase(fx)}/functions/{fn['id']}", headers=hdr(fx.editor_sub),
                     json={"display_name": "Counted", "description": "How many"})
    assert (r.json()["display_name"], r.json()["description"]) == ("Counted", "How many")
    listed = client.get(f"{wbase(fx)}/functions", headers=hdr(fx.viewer_sub)).json()
    assert next(f for f in listed if f["id"] == fn["id"])["latest_version"] == "1.0.0"
    assert call(client, fx, fn["id"], who=fx.viewer_sub).status_code == 200
    assert client.delete(f"{wbase(fx)}/functions/{fn['id']}",
                         headers=hdr(fx.viewer_sub)).status_code == 403
    assert client.delete(f"{wbase(fx)}/functions/{fn['id']}",
                         headers=hdr(fx.editor_sub)).status_code == 204
    assert client.get(f"{wbase(fx)}/functions/{fn['id']}",
                      headers=hdr(fx.viewer_sub)).status_code == 404


# ---- the sandbox ----------------------------------------------------------------

def test_the_sql_cannot_reach_the_filesystem() -> None:
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([], "SELECT * FROM read_csv('/etc/passwd')", {},
                   {"kind": "table"})
    assert "disabled" in str(caught.value).lower() or "permission" in str(caught.value).lower()


def test_a_call_that_runs_too_long_is_stopped() -> None:
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([], "SELECT count(*) FROM range(100000000000) a", {},
                   {"kind": "value", "data_type": "integer"}, timeout=0.3)
    assert "ran for more than 0.3 seconds" in str(caught.value)


def test_a_stored_value_its_column_cannot_hold_is_named() -> None:
    table = engine.InputTable(name="t", columns=[("n", "BIGINT")],
                              rows=[("1", "k", "not a number")])
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([table], "SELECT * FROM t", {}, {"kind": "table"})
    assert str(caught.value).startswith("t: ")


def test_a_table_output_is_capped() -> None:
    got = engine.run([], f"SELECT * FROM range({engine.MAX_TABLE_ROWS + 5})", {},
                     {"kind": "table"})
    assert (len(got["rows"]), got["truncated"]) == (engine.MAX_TABLE_ROWS, True)
    got = engine.run([], "SELECT * FROM range(3)", {}, {"kind": "table"})
    assert (len(got["rows"]), got["truncated"]) == (3, False)


def test_an_object_set_leaves_out_a_missing_key() -> None:
    got = engine.run([], "SELECT * FROM (VALUES ('a'), (NULL), ('b')) t(k)", {},
                     {"kind": "object_set", "object_type_id": "t"})
    assert got["values"] == ["a", "b"]


def test_a_type_with_more_objects_than_a_call_reads_is_refused(
    client, fx, sites, monkeypatch
) -> None:
    fn = create(client, fx, sites, sql=f"SELECT count(*) FROM {sites['table']}",
                output={"kind": "value", "data_type": "integer"}).json()
    monkeypatch.setattr(functions_service, "MAX_INPUT_OBJECTS", 2)
    r = call(client, fx, fn["id"])
    assert r.status_code == 422, r.text
    assert "has more than 2 objects" in r.text


def test_a_function_reads_at_most_so_many_types(client, fx, sites, monkeypatch) -> None:
    monkeypatch.setattr(functions_service, "MAX_INPUTS", 0)
    r = create(client, fx, sites, sql=f"SELECT count(*) FROM {sites['table']}",
               output={"kind": "value", "data_type": "integer"})
    assert r.status_code == 422, r.text
    assert "reads at most 0 object types" in r.text


def test_sql_of_nothing_but_space_is_no_sql(client, fx, sites) -> None:
    r = create(client, fx, sites, sql="   ", output={"kind": "value", "data_type": "integer"})
    assert r.status_code == 422, r.text
    assert "a function needs its SQL" in r.text


def test_a_property_that_is_not_a_scalar_is_its_json_text() -> None:
    """Read with DuckDB's JSON functions (`duck_type`'s note)."""
    assert functions_service._cell([1, 2], "array") == "[1, 2]"
    assert functions_service._cell({"a": 1}, "struct") == '{"a": 1}'
    assert functions_service._cell("x", "string") == "x"
    assert functions_service._cell(None, "array") is None


# ---- §770: the Object Table's shape -----------------------------------------------

def urgency(client, fx, sites, sql: str | None = None):
    return create(
        client, fx, sites,
        sql=sql or (f"SELECT __primary_key, CASE WHEN capacity > 20 THEN 'High' ELSE 'Low' END "
                    f"AS urgency, capacity * 2 AS doubled FROM {sites['table']} "
                    "WHERE list_contains($shown, __primary_key)"),
        output={"kind": "map", "object_type_id": sites["type"]["id"]},
        parameters=[{"api_name": "shown", "data_type": "object_set",
                     "object_type_id": sites["type"]["id"]}])


def test_a_map_answers_for_the_objects_it_is_given(client, fx, sites) -> None:
    """p.221's function-backed column: an object set in, a map from each of
    those objects to its fields out."""
    r = urgency(client, fx, sites)
    assert r.status_code == 201, r.text
    got = call(client, fx, r.json()["id"], {"shown": ["S1", "S3"]}).json()
    assert got["kind"] == "map"
    assert [c["name"] for c in got["columns"]] == ["urgency", "doubled"]
    assert got["entries"] == {"S1": {"urgency": "Low", "doubled": 20},
                              "S3": {"urgency": "High", "doubled": 50}}
    assert call(client, fx, r.json()["id"], {"shown": []}).json()["entries"] == {}


def test_an_object_set_parameter_is_a_list_of_keys(client, fx, sites) -> None:
    fn = urgency(client, fx, sites).json()
    r = call(client, fx, fn["id"], {"shown": "S1"})
    assert r.status_code == 422, r.text
    assert "shown: 'S1' is not a object_set" in r.text
    r = create(client, fx, sites, sql=f"SELECT count(*) FROM {sites['table']} "
               "WHERE list_contains($shown, __primary_key)",
               output={"kind": "value", "data_type": "integer"},
               parameters=[{"api_name": "shown", "data_type": "object_set"}])
    assert r.status_code == 422, r.text
    assert "names its object type" in r.text


def test_a_map_is_a_key_and_at_least_one_field(client, fx, sites) -> None:
    # Refused at publish: the save-time run shapes the result too.
    r = create(client, fx, sites, sql=f"SELECT __primary_key FROM {sites['table']}",
               output={"kind": "map", "object_type_id": sites["type"]["id"]})
    assert r.status_code == 422, r.text
    assert "at least one value" in r.text


def test_a_map_has_one_answer_per_object(client, fx, sites) -> None:
    fn = urgency(client, fx, sites, sql=f"SELECT 'S1' AS k, 1 AS v FROM {sites['table']} "
                 "WHERE list_contains($shown, __primary_key)").json()
    r = call(client, fx, fn["id"], {"shown": ["S1", "S2"]})
    assert r.status_code == 422, r.text
    assert "gave 'S1' two values" in r.text


def test_a_map_output_names_its_object_type(client, fx, sites) -> None:
    r = create(client, fx, sites, sql=f"SELECT __primary_key, 1 FROM {sites['table']}",
               output={"kind": "map"})
    assert r.status_code == 422, r.text
    assert "an object map output names its object type" in r.text


def test_a_map_leaves_out_a_row_with_no_key() -> None:
    got = engine.run([], "SELECT * FROM (VALUES ('a', 1), (NULL, 2)) t(k, v)", {},
                     {"kind": "map", "object_type_id": "t"})
    assert got["entries"] == {"a": {"v": 1}}


# ---- §771: Chart XY's shape ---------------------------------------------------------

def test_two_and_three_dimensional_aggregations(client, fx, sites) -> None:
    """Workshop p.284: "a function that returns either a
    TwoDimensionalAggregation or ThreeDimensionalAggregation"."""
    table = sites["table"]
    two = create(client, fx, sites,
                 sql=f"SELECT region, sum(capacity) FROM {table} GROUP BY 1 ORDER BY 1",
                 output={"kind": "aggregation"}).json()
    got = call(client, fx, two["id"]).json()
    assert (got["kind"], got["dimensions"]) == ("aggregation", 2)
    assert got["buckets"] == [{"key": "north", "value": 40.0}, {"key": "south", "value": 25.0}]
    three = create(client, fx, sites,
                   sql=f"SELECT region, capacity > 20 AS big, count(*) FROM {table} "
                       "GROUP BY 1, 2 ORDER BY 1, 2",
                   output={"kind": "aggregation"}).json()
    got = call(client, fx, three["id"]).json()
    assert got["dimensions"] == 3
    assert got["buckets"] == [
        {"key": "north", "segment": "false", "value": 1.0},
        {"key": "north", "segment": "true", "value": 1.0},
        {"key": "south", "segment": "true", "value": 1.0}]


@pytest.mark.parametrize("sql,said", [
    ("SELECT region FROM {t}", "this one gives 1 columns"),
    ("SELECT region, code, capacity, opened FROM {t}", "this one gives 4 columns"),
])
def test_an_aggregation_is_two_or_three_columns(client, fx, sites, sql, said) -> None:
    r = create(client, fx, sites, sql=sql.format(t=sites["table"]),
               output={"kind": "aggregation"})
    assert r.status_code == 422, r.text
    assert said in r.text


def test_an_aggregations_value_is_a_number(client, fx, sites) -> None:
    fn = create(client, fx, sites, sql=f"SELECT code, region FROM {sites['table']}",
                output={"kind": "aggregation"}).json()
    r = call(client, fx, fn["id"])
    assert r.status_code == 422, r.text
    assert "'region' is not a number" in r.text


def test_an_aggregation_is_capped(monkeypatch) -> None:
    monkeypatch.setattr(engine, "MAX_ARRAY_ITEMS", 2)
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([], "SELECT range, 1 FROM range(3)", {}, {"kind": "aggregation"})
    assert "more than 2 buckets" in str(caught.value)


# ---- §773: an action's edit function ----------------------------------------------

def test_an_edit_function_names_objects_and_the_properties_to_set(client, fx, sites) -> None:
    """`action-types` p.75's Ontology edit function, as SQL: each row an object
    by its primary key, and the properties to set on it."""
    table = sites["table"]
    fn = create(client, fx, sites,
                sql=f"SELECT __primary_key, capacity + $more AS capacity, 'x' AS region "
                    f"FROM {table} WHERE region = 'north' ORDER BY 1",
                parameters=[{"api_name": "more", "data_type": "integer"}],
                output={"kind": "edits", "object_type_id": sites["type"]["id"]})
    assert fn.status_code == 201, fn.text
    got = call(client, fx, fn.json()["id"], {"more": 5}).json()
    assert got["kind"] == "edits"
    assert [c["name"] for c in got["columns"]] == ["capacity", "region"]
    # Each with the type it edits, as a typed edit's is (§783).
    t = sites["type"]["id"]
    assert got["edits"] == [
        {"primary_key": "S1", "properties": {"capacity": 15, "region": "x"}, "object_type_id": t},
        {"primary_key": "S2", "properties": {"capacity": 35, "region": "x"}, "object_type_id": t}]


@pytest.mark.parametrize("sql,output,said", [
    ("SELECT __primary_key, 1 AS nonsense FROM {t}", None,
     "the query sets 'nonsense', which is not a property of"),
    ("SELECT __primary_key FROM {t}", None, "then at least one property to set"),
    ("SELECT __primary_key, 1 AS capacity FROM {t}", {"kind": "edits"},
     "an edit output names its object type"),
])
def test_an_edit_function_that_cannot_hold_is_refused_at_publish(
    client, fx, sites, sql, output, said
) -> None:
    r = create(client, fx, sites, sql=sql.format(t=sites["table"]),
               output=output or {"kind": "edits", "object_type_id": sites["type"]["id"]})
    assert r.status_code == 422, r.text
    assert said in r.text


def test_an_edit_function_edits_an_object_once() -> None:
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([], "SELECT * FROM (VALUES ('a', 1), ('a', 2)) t(k, v)", {},
                   {"kind": "edits", "object_type_id": "t"})
    assert "edits 'a' twice" in str(caught.value)


def test_an_edit_row_with_no_key_is_no_edit() -> None:
    got = engine.run([], "SELECT * FROM (VALUES ('a', 1), (NULL, 2)) t(k, v)", {},
                     {"kind": "edits", "object_type_id": "t"})
    assert got["edits"] == [{"primary_key": "a", "properties": {"v": 1}}]


def test_edits_are_capped_at_p130_s_limit(monkeypatch) -> None:
    assert engine.MAX_EDITS == 10_000
    monkeypatch.setattr(engine, "MAX_EDITS", 2)
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([], "SELECT range, 1 AS v FROM range(3)", {},
                   {"kind": "edits", "object_type_id": "t"})
    assert "more than 2 edits" in str(caught.value)
    assert len(engine.run([], "SELECT range, 1 AS v FROM range(2)", {},
                          {"kind": "edits", "object_type_id": "t"})["edits"]) == 2


def test_the_querys_own_error_is_said_as_written() -> None:
    """p.166's "error intended to be displayed to the user": DuckDB's
    `error()`, told apart from a built-in's bad input by the query calling it."""
    with pytest.raises(engine.UserFacingError) as caught:
        engine.run([], "SELECT error('Closed tickets stay closed')", {},
                   {"kind": "value", "data_type": "string"})
    assert str(caught.value) == "Closed tickets stay closed"
    with pytest.raises(engine.FunctionError) as caught:
        engine.run([], "SELECT strptime('x', '%Y')", {},
                   {"kind": "value", "data_type": "string"})
    assert not isinstance(caught.value, engine.UserFacingError)
    assert caught.value.args[0].startswith("Invalid Input Error")


# ---- §779: a batch parameter (`action-types` p.84-85) ----------------------------

def batch_parameter(sites, **over) -> dict:
    return {"api_name": "batch", "data_type": "batch", "fields": [
        {"api_name": "site", "data_type": "object", "object_type_id": sites["type"]["id"]},
        {"api_name": "extra", "data_type": "integer"}], **over}


def test_a_batch_is_a_list_of_structs_the_sql_unnests(client, fx, sites) -> None:
    fn = create(client, fx, sites,
                sql=(f"SELECT b.site AS k, s.capacity + b.extra AS capacity FROM "
                     f"(SELECT unnest($batch) AS b) JOIN {sites['table']} s "
                     "ON s.__primary_key = b.site ORDER BY 1"),
                parameters=[batch_parameter(sites)],
                output={"kind": "edits", "object_type_id": sites["type"]["id"]})
    assert fn.status_code == 201, fn.text
    ids = {i["primary_key"]: i["id"] for i in client.get(
        f"{wbase(fx)}/object-types/{sites['type']['id']}/instances",
        headers=hdr(fx.viewer_sub)).json()["items"]}
    got = call(client, fx, fn.json()["id"], {"batch": [
        {"site": ids["S1"], "extra": 1}, {"site": ids["S3"], "extra": 2}]})
    assert got.status_code == 200, got.text
    t = sites["type"]["id"]
    assert got.json()["edits"] == [
        {"primary_key": "S1", "properties": {"capacity": 11}, "object_type_id": t},
        {"primary_key": "S3", "properties": {"capacity": 27}, "object_type_id": t}]


@pytest.mark.parametrize("values,said", [
    ({"batch": "S1"}, "a batch is a list of at most"),
    ({"batch": ["S1"]}, "each entry is an object"),
    ({"batch": [{"colour": 1}]}, "batch has no field colour"),
    ({"batch": [{"extra": "lots"}]}, "batch.extra: 'lots' is not a integer"),
    ({"batch": [{"site": "00000000-0000-0000-0000-000000000000"}]}, "batch.site: no such object"),
])
def test_a_batch_is_bound_field_by_field(client, fx, sites, values, said) -> None:
    fn = create(client, fx, sites,
                sql="SELECT count(*) FROM (SELECT unnest($batch) AS b)",
                parameters=[batch_parameter(sites)],
                output={"kind": "value", "data_type": "integer"}).json()
    r = call(client, fx, fn["id"], values)
    assert r.status_code == 422, r.text
    assert said in r.text


@pytest.mark.parametrize("parameters,said", [
    ([{"api_name": "batch", "data_type": "batch"}], "declares its fields"),
    ([{"api_name": "batch", "data_type": "batch", "fields": []}], "declares its fields"),
    ([{"api_name": "batch", "data_type": "batch", "fields": [
        {"api_name": "x", "data_type": "object",
         "object_type_id": "00000000-0000-0000-0000-000000000000"}]}],
     "in this workspace"),
    ([{"api_name": "batch", "data_type": "batch", "fields": [{"api_name": "x",
                                                              "data_type": "batch"}]}],
     "is not a field type"),
    ([{"api_name": "batch", "data_type": "batch", "fields": [{"api_name": "x",
                                                              "data_type": "object"}]}],
     "an object field names its object type"),
    ([{"api_name": "batch", "data_type": "batch", "fields": [
        {"api_name": "x", "data_type": "string"}, {"api_name": "x", "data_type": "string"}]}],
     "two fields are called x"),
    ([{"api_name": "batch", "data_type": "batch", "fields": [{"api_name": "X Y",
                                                              "data_type": "string"}]}],
     "invalid field name"),
    ([{"api_name": "batch", "data_type": "batch", "fields": ["x"]}], "each field must be"),
    ([{"api_name": "batch", "data_type": "batch",
       "fields": [{"api_name": "x", "data_type": "string"}]},
      {"api_name": "other", "data_type": "string"}], "a single input parameter"),
])
def test_a_batch_parameter_that_cannot_hold_is_refused(client, fx, sites, parameters,
                                                       said) -> None:
    uses = " ".join(f"${p['api_name']}" for p in parameters if isinstance(p, dict))
    r = create(client, fx, sites, sql=f"SELECT 1 WHERE {uses} IS NOT NULL",
               parameters=parameters, output={"kind": "value", "data_type": "integer"})
    assert r.status_code == 422, r.text
    assert said in r.text


def test_a_batch_field_the_query_misspells_is_refused_at_publish(client, fx, sites) -> None:
    """The publish-time run is given one entry of the declared fields, so a
    field the query reads and the batch does not declare is found then."""
    r = create(client, fx, sites, sql="SELECT b.colour FROM (SELECT unnest($batch) AS b)",
               parameters=[batch_parameter(sites)],
               output={"kind": "value", "data_type": "string"})
    assert r.status_code == 422, r.text
    assert "colour" in r.text


def test_a_batch_is_capped_and_an_empty_field_is_nothing(client, fx, sites, monkeypatch) -> None:
    fn = create(client, fx, sites,
                sql="SELECT count(*) FROM (SELECT unnest($batch) AS b) WHERE b.extra IS NULL",
                parameters=[batch_parameter(sites)],
                output={"kind": "value", "data_type": "integer"}).json()
    r = call(client, fx, fn["id"], {"batch": [{"extra": ""}, {"extra": 3}]})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == 1
    monkeypatch.setattr(engine, "MAX_ARRAY_ITEMS", 1)
    r = call(client, fx, fn["id"], {"batch": [{"extra": 1}, {"extra": 2}]})
    assert r.status_code == 422, r.text
    assert "a list of at most 1 entries" in r.text


# ---- §780: a set variable's definition for an object_set parameter -------------

def test_an_object_set_parameter_takes_a_sets_definition(client, fx, sites, monkeypatch) -> None:
    """Workshop p.221's "Use a variable": the set whole, read on the server to
    the keys it holds, so a widget can pass a set variable as it stands."""
    from src.services import function_engine

    fn = urgency(client, fx, sites, sql=(
        f"SELECT __primary_key, capacity AS v FROM {sites['table']} "
        "WHERE list_contains($shown, __primary_key) ORDER BY 1")).json()
    north = {"object_type_id": sites["type"]["id"],
             "filters": [{"property": "region", "op": "eq", "value": "north"}]}
    r = call(client, fx, fn["id"], {"shown": north})
    assert r.status_code == 200, r.text
    assert sorted(r.json()["entries"]) == ["S1", "S2"]
    r = call(client, fx, fn["id"], {"shown": {**north, "object_type_id": str(uuid.uuid4())}})
    assert r.status_code == 422, r.text
    assert "the set is of another object type" in r.text
    monkeypatch.setattr(function_engine, "MAX_ARRAY_ITEMS", 1)
    r = call(client, fx, fn["id"], {"shown": north})
    assert r.status_code == 422, r.text
    assert "holds 2 objects, more than the 1" in r.text
