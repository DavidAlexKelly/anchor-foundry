"""A time series formula over several inputs (§561; `workshop` p.586).

    "The formula transform computes a domain-specific language (DSL) formula
     on a set of input time series. Using the Add input button, users can add
     new input time series - either time series properties or the outputs
     from other transforms - to the transform, and then build formulas using
     variable references to these inputs." (p.586)

The arithmetic runs against a real DuckDB, with each input in a table of its
own as the read loads them; then the variables that name the inputs, and the
endpoint that resolves them under the reader's access.
"""
from __future__ import annotations

import io
import json
import os
import sys
import uuid
from datetime import datetime

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_time_series import (  # noqa: E402,F401
    _fresh_identity_cache, client, declare, fx, instance, ontology, pbase, points, wbase,
)
from src.services import time_series as ts  # noqa: E402
from src.services import workshop_variables as wv  # noqa: E402

#: S1 reads hourly-ish; W1, in another table, reads at 03:00 and on the 2nd.
S1 = [("S1", "2026-01-01 00:00:00", 10.0), ("S1", "2026-01-01 06:00:00", 20.0),
      ("S1", "2026-01-02 00:00:00", 30.0), ("S2", "2026-01-01 00:00:00", 99.0)]
W1 = [("W1", "2026-01-01 03:00:00", 1.0), ("W1", "2026-01-02 00:00:00", 2.0)]
IDS = {"object_type_id": str(uuid.UUID(int=1)), "instance_id": str(uuid.UUID(int=2))}


def spec(series_id: str, table: str, **kw) -> dict:
    return {**IDS, "property": "readings", "interval": kw.get("interval", "none"),
            "aggregate": "avg", "transforms": kw.get("transforms", []), "table": table,
            "key_column": "sensor", "timestamp_column": "taken", "value_column": "reading",
            "series_id": series_id}


def run(transforms: list[dict], **kw) -> list[tuple[datetime, float | None]]:
    con = duckdb.connect()
    try:
        for table, rows in (("dataset", S1), ("input_1", W1)):
            con.execute(f"CREATE TABLE {table} (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
            con.executemany(f"INSERT INTO {table} VALUES (?, ?, ?)", rows)
        sql = ts.points_sql(key_column="sensor", timestamp_column="taken", value_column="reading",
                            series_id="S1", interval=kw.pop("interval", "none"),
                            aggregate="avg", transforms=transforms, **kw)
        return [(r[0], None if r[1] is None else float(r[1])) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def values(transforms: list[dict], **kw) -> list[float | None]:
    return [v for _, v in run(transforms, **kw)]


def formula(expression: str, **inputs) -> dict:
    return {"kind": "formula", "expression": expression, "inputs": inputs}


# ---- the arithmetic --------------------------------------------------------------
def test_each_input_is_read_as_of_each_point() -> None:
    """The formula's points are the series' own. W1 has no reading at
    midnight on the 1st, so that point is a gap; at 06:00 W1's latest is its
    03:00 reading, and on the 2nd its reading then."""
    assert values([formula("x - y", y=spec("W1", "input_1"))]) == [None, 19.0, 28.0]


def test_an_input_in_the_same_dataset_is_another_series_of_it() -> None:
    assert values([formula("x + y", y=spec("S2", "dataset"))]) == [109.0, 119.0, 129.0]


def test_several_inputs_and_the_functions() -> None:
    got = values([formula("abs(y - z) + x", y=spec("W1", "input_1"), z=spec("S2", "dataset"))])
    assert got == [None, 98.0 + 20, 97.0 + 30]


def test_an_input_is_bucketed_as_its_own_variable_says() -> None:
    """W1 by day stands at midnight on the 1st with its 03:00 reading, so the
    first of S1's points has a value to read now."""
    assert values([formula("x - y", y=spec("W1", "input_1", interval="day"))]) == [9.0, 19.0, 28.0]


def test_where_a_formula_over_inputs_has_no_answer_is_a_gap() -> None:
    """At 06:00 W1 reads 1, so x / (y - 1) divides by zero there."""
    assert values([formula("x / (y - 1)", y=spec("W1", "input_1"))]) == [None, None, 30.0]


def test_an_input_is_read_through_its_own_transforms_in_full() -> None:
    """An input's chain is its own, over all its points: W1's running sum is
    1 then 3, which a read capped before the sum would get wrong."""
    running = spec("W1", "input_1", transforms=[{"kind": "cumulative", "aggregate": "sum"}])
    assert values([formula("y", y=running)]) == [None, 1.0, 3.0]


def test_an_input_may_have_a_formula_with_inputs_of_its_own() -> None:
    inner = spec("W1", "input_1", transforms=[formula("x * 10 + z", z=spec("S2", "dataset"))])
    assert values([formula("x + y", y=inner)]) == [None, 20.0 + 109.0, 30.0 + 119.0]


def test_the_formula_chains_after_and_before_other_transforms() -> None:
    chain = [{"kind": "cumulative", "aggregate": "sum"}, formula("x - y", y=spec("W1", "input_1")),
             {"kind": "shift", "by": 1, "unit": "day"}]
    got = run(chain)
    assert [v for _, v in got] == [None, 29.0, 58.0]
    assert got[0][0] == datetime(2026, 1, 2)


def test_a_bucketed_series_joins_its_buckets() -> None:
    """Bucketed by day, S1 is 15 on the 1st and 30 on the 2nd, and each day's
    bucket stands at midnight - before W1's 03:00 reading."""
    assert values([formula("x - y", y=spec("W1", "input_1"))], interval="day") == [None, 28.0]


def test_each_inputs_dataset_is_loaded_and_held_to_the_size_limit(tmp_path, monkeypatch) -> None:
    from src.services import dataset_engine as engine

    small, big = str(tmp_path / "small.parquet"), str(tmp_path / "big.parquet")
    con = duckdb.connect()
    con.execute(f"COPY (SELECT 1 AS a) TO '{small}' (FORMAT parquet)")
    con.execute(f"COPY (SELECT range AS a, md5(CAST(range AS VARCHAR)) AS b FROM range(5000)) "
                f"TO '{big}' (FORMAT parquet)")
    con.close()
    assert engine.query(small, "SELECT count(*) FROM input_1", tables={"input_1": big}).rows == [[5000]]
    monkeypatch.setattr(engine, "MAX_INTERACTIVE_BYTES", os.path.getsize(small) + 1)
    with pytest.raises(engine.DatasetEngineError, match="too large"):
        engine.query(small, "SELECT 1", tables={"input_1": big})


# ---- what may be written where ---------------------------------------------------
def parsed(raw, mode="references"):
    return ts.parse_transforms(raw, inputs=mode)


def ref(**kw) -> dict:
    return {**IDS, "property": "readings", **kw}


def test_a_read_carries_each_input_as_a_reference() -> None:
    got = parsed([formula("x + y", y=ref(transforms=[{"kind": "cumulative", "aggregate": "sum"}]))])
    assert got == [{"kind": "formula", "expression": "x + y", "inputs": {"y": {
        **IDS, "property": "readings", "interval": "day", "aggregate": "avg",
        "transforms": [{"kind": "cumulative", "aggregate": "sum"}]}}}]
    # No inputs is the one-series formula it always was, and so is an emptied
    # map of them - even where no inputs may be named.
    assert parsed([formula("x * 2")]) == [{"kind": "formula", "expression": "x * 2"}]
    assert parsed([formula("x * 2")], "none") == [{"kind": "formula", "expression": "x * 2"}]


@pytest.mark.parametrize("raw, mode, said", [
    ([formula("x + y", y=ref())], "none",
     "transform 1: a formula here has only its own series - other inputs are a time series "
     "set variable's (p.586)"),
    ([{"kind": "formula", "expression": "x", "inputs": ["y"]}], "references",
     "transform 1: a formula's inputs must be an object of name -> input"),
    ([formula("x", a=ref(), b=ref(), c=ref(), d=ref(), e=ref())], "references",
     "transform 1: a formula takes at most 4 other inputs"),
    ([formula("x + q", y=ref())], "references",
     "transform 1: a formula knows only x, y, not 'q'"),
    ([formula("x", sqrt=ref())], "references",
     "transform 1: 'sqrt' cannot name an input: a lower-case word of at most 16 letters, "
     "digits and underscores, other than x and the functions"),
    ([formula("x", x=ref())], "references", None),
    ([formula("x", Y=ref())], "references", None),
    ([formula("x", y=ref(property=""))], "references", "transform 1: input y needs its property"),
    ([formula("x", y=ref(instance_id="i"))], "references", "transform 1: input y: 'i' is not an id"),
    ([formula("x", y=ref(interval="year"))], "references",
     "transform 1: input y: the interval must be one of none, hour, day, week, month"),
    ([formula("x", y=ref(transforms=[{"kind": "smooth"}]))], "references", None),
    ([formula("x", y=7)], "references", "transform 1: input y must name an object's time series"),
    ([formula("x", y="")], "variables",
     "transform 1: input y must name a time series set variable"),
])
def test_an_input_that_could_not_be_read_is_refused(raw, mode, said) -> None:
    with pytest.raises(ValueError) as caught:
        parsed(raw, mode)
    if said is not None:
        assert str(caught.value) == said
    else:
        assert str(caught.value).startswith("transform 1: ")


def test_inputs_nest_three_deep_and_no_deeper() -> None:
    def nested(depth: int) -> dict:
        inner = ref()
        for _ in range(depth - 1):
            inner = ref(transforms=[formula("x + y", y=inner)])
        return formula("x + y", y=inner)

    assert parsed([nested(3)])
    with pytest.raises(ValueError) as caught:
        parsed([nested(4)])
    assert "nest at most 3 deep" in str(caught.value)


# ---- the variables -----------------------------------------------------------------
def variables(inputs: list[str], transforms: list[dict], **extra) -> dict:
    return {
        "v_a": {"id": "v_a", "kind": "single_object", "label": "Picked"},
        "v_b": {"id": "v_b", "kind": "single_object", "label": "Other"},
        "v_other": {"id": "v_other", "kind": "time_series_set", "label": "Other readings",
                    "derivation": {"transform": "object_series", "inputs": ["v_b"],
                                   "config": {"property": "temps"}}},
        "v_series": {"id": "v_series", "kind": "time_series_set", "label": "Readings",
                     "derivation": {"transform": "object_series", "inputs": inputs,
                                    "config": {"property": "readings", "transforms": transforms}}},
        **extra,
    }


def test_a_series_variable_reads_the_series_its_formula_names() -> None:
    parsedv = wv.parse(variables(["v_a", "v_other"], [formula("x - y", y="v_other")]))
    got = wv.evaluate(parsedv, {"v_a": {"object_type_id": "t", "id": "i"},
                                "v_b": {"object_type_id": "u", "id": "j"}})
    assert got["v_series"]["transforms"] == [{"kind": "formula", "expression": "x - y", "inputs": {
        "y": {"object_type_id": "u", "instance_id": "j", "property": "temps",
              "interval": "day", "aggregate": "avg", "transforms": []}}}]


def test_a_formula_over_a_series_not_picked_yet_has_no_answer() -> None:
    parsedv = wv.parse(variables(["v_a", "v_other"], [formula("x - y", y="v_other")]))
    got = wv.evaluate(parsedv, {"v_a": {"object_type_id": "t", "id": "i"}})
    assert got["v_other"] is None
    assert got["v_series"] is None


@pytest.mark.parametrize("inputs, transforms", [
    (["v_a"], [formula("x - y", y="v_other")]),
    (["v_a", "v_other"], [formula("x * 2")]),
    (["v_a", "v_other", "v_other"], [formula("x - y", y="v_other")]),
])
def test_the_derivation_reads_exactly_the_series_its_formulas_name(inputs, transforms) -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse(variables(inputs, transforms))
    assert str(caught.value) == (
        "variable 'v_series': object_series reads the object and then each series its "
        "formulas name, in order and once each")


def test_a_formula_input_is_a_time_series_set() -> None:
    with pytest.raises(wv.VariableError) as caught:
        wv.parse(variables(["v_a", "v_b"], [formula("x - y", y="v_b")]))
    assert str(caught.value) == ("variable 'Readings': a formula's input 'Other' is not a "
                                 "time series set")


def test_two_series_cannot_read_each_other() -> None:
    raw = variables(["v_a", "v_other"], [formula("x - y", y="v_other")])
    raw["v_other"]["derivation"] = {"transform": "object_series", "inputs": ["v_b", "v_series"],
                                    "config": {"property": "temps",
                                               "transforms": [formula("x + y", y="v_series")]}}
    with pytest.raises(wv.VariableError) as caught:
        wv.parse(raw)
    assert str(caught.value) == ("these variables depend on each other in a loop: "
                                 "Other readings, Readings")


def test_the_first_named_order_is_the_derivations() -> None:
    chain = ts.parse_transforms([formula("x + y + z", y="v_2", z="v_1"), formula("x + y", y="v_1")],
                                inputs="variables")
    assert wv.series_inputs(chain) == ["v_2", "v_1"]


# ---- the endpoint ---------------------------------------------------------------------
@pytest.fixture(scope="module")
def weather(client, fx) -> dict:
    """Another type, in datasets of its own: W1 reads 1 at 03:00 on the 1st
    and 2 at midnight on the 2nd."""
    tag = uuid.uuid4().hex[:8]

    def upload(name: str, body: bytes) -> str:
        r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                        data={"name": f"{name} {tag}"},
                        files={"file": ("f.csv", io.BytesIO(body), "text/csv")})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    # W2 holds no series id. The readings keyed "None" are what reading it as
    # Python's str(None) would find.
    stations = upload("Stations", b"station_id,label,series\nW1,roof,W1\nW2,yard,\n")
    temps = upload("Temps", b"station_id,at,temp\nW1,2026-01-01T03:00:00,1\n"
                            b"W1,2026-01-02T00:00:00,2\nNone,2026-01-01T00:00:00,5\n")
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"station_{tag}", "display_name": f"Station {tag}",
        "properties": [{"api_name": "label", "data_type": "string"},
                       {"api_name": "temps", "data_type": "time_series"},
                       {"api_name": "other", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub), json={
        "object_type_id": type_id, "dataset_id": stations, "primary_key_column": "station_id",
        "column_mappings": {"label": "label", "series": "temps"}})
    assert r.status_code == 201, r.text
    source = r.json()["id"]
    r = client.put(f"{pbase(fx)}/object-type-sources/{source}/series", headers=hdr(fx.editor_sub),
                   json={"property_api_name": "temps", "dataset_id": temps,
                         "key_column": "station_id", "timestamp_column": "at",
                         "value_column": "temp"})
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources/{source}/sync",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub))
    ids = {i["primary_key"]: i["id"] for i in r.json()["items"]}
    return {"type_id": type_id, "W1": ids["W1"], "W2": ids["W2"]}


def read(client, fx, ontology, instance, transforms, **params):
    return client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}/series/readings/points",
        headers=hdr(fx.viewer_sub), params={"transforms": json.dumps(transforms), **params})


def station(weather, **kw) -> dict:
    return {"object_type_id": weather["type_id"], "instance_id": weather["W1"],
            "property": "temps", "interval": "none", "aggregate": "avg", **kw}


def test_the_endpoint_reads_an_input_from_another_dataset(client, fx, ontology, instance, weather) -> None:
    r = read(client, fx, ontology, instance, [formula("x - y", y=station(weather))])
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["points"]] == [None, 19, 28]


def test_the_endpoint_reads_an_input_from_the_same_dataset(client, fx, ontology, instance) -> None:
    listed = client.get(f"{wbase(fx)}/object-types/{ontology['type_id']}/instances",
                        headers=hdr(fx.viewer_sub)).json()["items"]
    s2 = next(i["id"] for i in listed if i["primary_key"] == "S2")
    y = {"object_type_id": ontology["type_id"], "instance_id": s2, "property": "readings",
         "interval": "none"}
    r = read(client, fx, ontology, instance, [formula("x + y", y=y)])
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["points"]] == [109, 119, 129]


def test_an_input_with_no_series_has_no_readings(client, fx, ontology, instance, weather) -> None:
    r = read(client, fx, ontology, instance,
             [formula("x - y", y=station(weather, instance_id=weather["W2"]))])
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["points"]] == [None, None, None]


def test_an_input_nested_in_an_input_is_resolved_too(client, fx, ontology, instance, weather) -> None:
    inner = station(weather, transforms=[formula("x * 10 + z", z=station(weather))])
    r = read(client, fx, ontology, instance, [formula("y", y=inner)])
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["points"]] == [None, 11, 22]


def test_an_input_the_reader_cannot_find_is_said(client, fx, ontology, instance, weather) -> None:
    r = read(client, fx, ontology, instance,
             [formula("x - y", y=station(weather, instance_id=str(uuid.uuid4())))])
    assert (r.status_code, r.json()["detail"]) == (
        422, "input y: that object does not exist or you cannot see it")
    r = read(client, fx, ontology, instance, [formula("x - y", y=station(weather, property="other"))])
    assert (r.status_code, r.json()["detail"]) == (
        422, "input y: 'other' is not a time series on that object")


def test_a_read_by_series_id_takes_no_inputs(client, fx, ontology, weather) -> None:
    r = points(client, fx, ontology, transforms=json.dumps([formula("x - y", y=station(weather))]))
    assert r.status_code == 422
    assert "other inputs are a time series set variable's" in r.json()["detail"]


# ---- p.393's Combine time series (§650) -------------------------------------------
def combine(aggregate: str | None = None, **inputs) -> dict:
    out = {"kind": "combine", "inputs": inputs}
    return {**out, "aggregate": aggregate} if aggregate else out


@pytest.mark.parametrize("aggregate, on_the_2nd", [
    ("avg", 16.0), ("min", 2.0), ("max", 30.0), ("sum", 32.0), (None, 16.0),
])
def test_combining_keeps_every_point_and_merges_where_they_meet(aggregate, on_the_2nd) -> None:
    """p.393: "Merge multiple time series into a single plot, specifying how to
    handle overlapping time points (for example, mean, min, or max)". S1 and W1
    meet only at midnight on the 2nd; elsewhere each point is its own."""
    got = run([ts.parse_transforms([combine(aggregate, y=ref())], inputs="references")[0]
               | {"inputs": {"y": spec("W1", "input_1")}}])
    assert got == [(datetime(2026, 1, 1, 0), 10.0), (datetime(2026, 1, 1, 3), 1.0),
                   (datetime(2026, 1, 1, 6), 20.0), (datetime(2026, 1, 2, 0), on_the_2nd)]


def test_combining_several_with_a_gap_left_out() -> None:
    """A series silent at an instant does not drag its mean: S1's gap on the
    3rd is not a point, so W1's is the only one there."""
    rows_gap = spec("S2", "dataset")
    got = values([{"kind": "combine", "aggregate": "sum",
                   "inputs": {"y": spec("W1", "input_1"), "z": rows_gap}}])
    assert got == [10.0 + 99.0, 1.0, 20.0, 30.0 + 2.0]


def test_an_instant_where_every_series_is_silent_stays_a_gap() -> None:
    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE dataset (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO dataset VALUES (?, ?, ?)",
                        S1 + [("S1", "2026-01-03 00:00:00", None)])
        con.execute("CREATE TABLE input_1 (sensor VARCHAR, taken TIMESTAMP, reading DOUBLE)")
        con.executemany("INSERT INTO input_1 VALUES (?, ?, ?)", W1)
        sql = ts.points_sql(key_column="sensor", timestamp_column="taken", value_column="reading",
                            series_id="S1", interval="none", aggregate="avg", transforms=[
                                {"kind": "combine", "aggregate": "avg",
                                 "inputs": {"y": spec("W1", "input_1")}}])
        got = con.execute(sql).fetchall()
    finally:
        con.close()
    assert got[-1] == (datetime(2026, 1, 3), None)


def test_combining_chains_after_other_transforms() -> None:
    chain = [{"kind": "cumulative", "aggregate": "sum"},
             {"kind": "combine", "aggregate": "max", "inputs": {"y": spec("W1", "input_1")}}]
    assert values(chain) == [10.0, 1.0, 30.0, 60.0]


@pytest.mark.parametrize("raw, mode, said", [
    ({"kind": "combine", "inputs": {}}, "references",
     "transform 1: combining needs at least one other series"),
    ({"kind": "combine", "aggregate": "median", "inputs": {"y": ref()}}, "references",
     "transform 1: overlapping points combine by one of avg, min, max, sum"),
    ({"kind": "combine", "inputs": {"y": ref()}}, "none",
     "transform 1: a formula here has only its own series - other inputs are a time series "
     "set variable's (p.586)"),
])
def test_a_combine_that_could_not_be_read_is_refused(raw, mode, said) -> None:
    with pytest.raises(ValueError) as caught:
        parsed([raw], mode)
    assert str(caught.value) == said


def test_a_combine_names_its_variables_as_a_formula_does() -> None:
    got = parsed([{"kind": "combine", "inputs": {"y": "v_other"}}], "variables")
    assert got == [{"kind": "combine", "aggregate": "avg", "inputs": {"y": "v_other"}}]
    assert wv.series_inputs(got) == ["v_other"]
