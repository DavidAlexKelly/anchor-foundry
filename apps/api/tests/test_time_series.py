"""Time series properties (decision 0009 part 1; db 0047; parity
`docs/parity/ontology.md` §1.1 and §4.1).

Two halves, and they fail in different ways. **Declaring** a series is a set of
refusals - a chart that could never draw should be refused where somebody can
still fix it. **Reading** one is SQL, and the shape of that SQL is where a
wrong bucket, an unfiltered key or a missing cap would live, so it is tested
without a Parquet file as well as with one.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import time_series as ts  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


# ---- the SQL, without a dataset ----------------------------------------------
def test_the_query_filters_by_the_series_and_orders_by_time() -> None:
    """A chart drawn from rows in whatever order the file held them is not a
    chart, and DuckDB promises nothing without an ORDER BY."""
    sql = ts.points_sql(
        key_column="sensor", timestamp_column="at", value_column="reading",
        series_id="S1", interval="none", aggregate="avg",
    )
    assert "CAST(\"sensor\" AS VARCHAR) = 'S1'" in sql
    assert "ORDER BY at" in sql
    assert "LIMIT" in sql


def test_raw_points_are_still_capped() -> None:
    """"No bucketing" is not "no limit": a decade of readings would otherwise
    decide how much memory the API uses."""
    sql = ts.points_sql(
        key_column="sensor", timestamp_column="at", value_column="reading",
        series_id="S1", interval="none", aggregate="avg", limit=10 ** 9,
    )
    assert f"LIMIT {ts.MAX_POINTS}" in sql


def test_an_interval_buckets_and_aggregates() -> None:
    sql = ts.points_sql(
        key_column="sensor", timestamp_column="at", value_column="reading",
        series_id="S1", interval="day", aggregate="max",
    )
    assert "date_trunc('day', \"at\")" in sql
    assert "max(\"reading\")" in sql
    assert "GROUP BY at" in sql


def test_last_is_the_value_at_the_greatest_timestamp() -> None:
    """A series of readings is often a *level* rather than a rate, and
    averaging a level across a day answers a question nobody asked."""
    sql = ts.points_sql(
        key_column="sensor", timestamp_column="at", value_column="reading",
        series_id="S1", interval="day", aggregate="last",
    )
    assert "arg_max(\"reading\", \"at\")" in sql


def test_a_window_narrows_the_query() -> None:
    sql = ts.points_sql(
        key_column="sensor", timestamp_column="at", value_column="reading",
        series_id="S1", interval="none", aggregate="avg",
        start=datetime(2026, 1, 1), end=datetime(2026, 2, 1),
    )
    assert "\"at\" >= TIMESTAMP '2026-01-01T00:00:00'" in sql
    assert "\"at\" <= TIMESTAMP '2026-02-01T00:00:00'" in sql


def test_a_series_id_with_a_quote_cannot_escape_the_literal() -> None:
    """The series id is an instance's property value, which a write-back can
    set - so it is customer input inside a query, and quoted as such."""
    sql = ts.points_sql(
        key_column="sensor", timestamp_column="at", value_column="reading",
        series_id="it's", interval="none", aggregate="avg",
    )
    assert "'it''s'" in sql


def test_an_unknown_interval_or_aggregate_is_refused() -> None:
    for kwargs in ({"interval": "fortnight", "aggregate": "avg"},
                   {"interval": "none", "aggregate": "median"}):
        with pytest.raises(ValueError):
            ts.points_sql(
                key_column="s", timestamp_column="t", value_column="v",
                series_id="S1", **kwargs,
            )


# ---- declaring a series -------------------------------------------------------
@pytest.fixture(scope="module")
def ontology(client: TestClient, fx: Fixture) -> dict:
    """A type with a `time_series` property, its own dataset, and a readings
    dataset holding the points."""
    tag = uuid.uuid4().hex[:8]
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Sensors {tag}"},
        files={"file": ("sensors.csv", io.BytesIO(b"sensor_id,site\nS1,north\nS2,south\n"),
                        "text/csv")},
    )
    assert r.status_code == 201, r.text
    sensors = r.json()["id"]

    readings = (
        b"sensor_id,taken_at,reading\n"
        b"S1,2026-01-01T00:00:00,10\n"
        b"S1,2026-01-01T06:00:00,20\n"
        b"S1,2026-01-02T00:00:00,30\n"
        b"S2,2026-01-01T00:00:00,99\n"
    )
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Readings {tag}"},
        files={"file": ("readings.csv", io.BytesIO(readings), "text/csv")},
    )
    assert r.status_code == 201, r.text
    points = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"sensor_{tag}",
            "display_name": f"Sensor {tag}",
            "properties": [
                {"api_name": "site", "data_type": "string"},
                {"api_name": "readings", "data_type": "time_series",
                 "visibility": "prominent"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id,
            "dataset_id": sensors,
            "primary_key_column": "sensor_id",
            "column_mappings": {"site": "site", "sensor_id": "readings"},
        },
    )
    assert r.status_code == 201, r.text
    return {"type_id": type_id, "source_id": r.json()["id"], "points": points, "tag": tag}


def declare(client: TestClient, fx: Fixture, ontology: dict, **overrides) -> object:
    body = {
        "property_api_name": "readings",
        "dataset_id": ontology["points"],
        "key_column": "sensor_id",
        "timestamp_column": "taken_at",
        "value_column": "reading",
        **overrides,
    }
    return client.put(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series",
        headers=hdr(fx.editor_sub), json=body,
    )


def test_time_series_is_a_property_type_now(client: TestClient, fx: Fixture, ontology: dict) -> None:
    """The declaration half of decision 0009: the instance holds a series *id*,
    which is an ordinary scalar - the type is what says it means points."""
    r = client.get(f"{wbase(fx)}/object-types/{ontology['type_id']}", headers=hdr(fx.viewer_sub))
    types = {p["api_name"]: p["data_type"] for p in r.json()["properties"]}
    assert types["readings"] == "time_series"


def test_a_series_can_be_declared_read_back_and_cleared(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    r = declare(client, fx, ontology)
    assert r.status_code == 200, r.text
    assert r.json()["property_api_name"] == "readings"
    assert r.json()["dataset_id"] == ontology["points"]

    r = client.get(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series",
        headers=hdr(fx.viewer_sub),
    )
    assert [s["property_api_name"] for s in r.json()] == ["readings"]

    assert client.delete(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series/readings",
        headers=hdr(fx.editor_sub),
    ).status_code == 204
    r = client.get(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series",
        headers=hdr(fx.viewer_sub),
    )
    assert r.json() == []


def test_a_property_that_is_not_a_time_series_is_refused(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """Points behind a string property are points nothing would ever draw."""
    r = declare(client, fx, ontology, property_api_name="site")
    assert r.status_code == 422
    assert "only a time_series property" in r.text


def test_a_property_the_type_does_not_have_is_refused(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    r = declare(client, fx, ontology, property_api_name="nonesuch")
    assert r.status_code == 422
    assert "not a property of this object type" in r.text


def test_a_column_the_points_dataset_does_not_have_is_refused(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """**Checked against the dataset's own schema.** A check against anything
    else would let a chart be configured that could never draw, and the person
    who finds out is whoever opens it."""
    r = declare(client, fx, ontology, value_column="temperature")
    assert r.status_code == 422
    assert "value column 'temperature'" in r.text


def test_the_three_columns_must_be_different(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """A series whose timestamp and value are the same column is a straight
    line, and saying so now beats discovering it from a graph."""
    r = declare(client, fx, ontology, value_column="taken_at")
    assert r.status_code == 422
    assert "three different columns" in r.text


def test_declaring_a_series_needs_editor(client: TestClient, fx: Fixture, ontology: dict) -> None:
    r = client.put(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series",
        headers=hdr(fx.viewer_sub),
        json={"property_api_name": "readings", "dataset_id": ontology["points"],
              "key_column": "sensor_id", "timestamp_column": "taken_at",
              "value_column": "reading"},
    )
    assert r.status_code == 403


# ---- reading points -----------------------------------------------------------
def points(client: TestClient, fx: Fixture, ontology: dict, **params) -> object:
    return client.get(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series/readings/points",
        headers=hdr(fx.viewer_sub),
        params={"series_id": "S1", **params},
    )


def test_reading_points_returns_this_series_only(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """**The acceptance test for the whole decision**: the points were never
    copied anywhere, and they come back out of the dataset they arrived in."""
    assert declare(client, fx, ontology).status_code == 200
    r = points(client, fx, ontology)
    assert r.status_code == 200, r.text
    body = r.json()
    assert [p["value"] for p in body["points"]] == [10, 20, 30]
    # S2's reading of 99 belongs to a different sensor and is not here.
    assert 99 not in [p["value"] for p in body["points"]]


def test_bucketing_by_day_aggregates_within_the_bucket(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    assert declare(client, fx, ontology).status_code == 200
    r = points(client, fx, ontology, interval="day", aggregate="avg")
    assert [p["value"] for p in r.json()["points"]] == [15, 30]
    r = points(client, fx, ontology, interval="day", aggregate="max")
    assert [p["value"] for p in r.json()["points"]] == [20, 30]
    r = points(client, fx, ontology, interval="day", aggregate="count")
    assert [p["value"] for p in r.json()["points"]] == [2, 1]


def test_a_window_narrows_what_comes_back(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    assert declare(client, fx, ontology).status_code == 200
    r = points(client, fx, ontology, start="2026-01-01T12:00:00")
    assert [p["value"] for p in r.json()["points"]] == [30]


def test_a_series_nobody_declared_is_a_404(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    client.delete(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/series/readings",
        headers=hdr(fx.editor_sub),
    )
    r = points(client, fx, ontology)
    assert r.status_code == 404
    assert declare(client, fx, ontology).status_code == 200  # restore for later tests


def test_an_unknown_interval_is_refused_by_the_endpoint(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    assert declare(client, fx, ontology).status_code == 200
    assert points(client, fx, ontology, interval="fortnight").status_code == 422


def test_a_series_id_nothing_matches_is_an_empty_list_not_an_error(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """An instance whose series has no readings yet is ordinary, not broken."""
    assert declare(client, fx, ontology).status_code == 200
    r = points(client, fx, ontology, series_id="NOPE")
    assert r.status_code == 200
    assert r.json()["points"] == []


# ---- reading one object's points, workspace-scoped -----------------------------
@pytest.fixture(scope="module")
def instance(client: TestClient, fx: Fixture, ontology: dict) -> str:
    """A synced sensor whose `readings` value is its own key.

    The source maps `sensor_id` to *both* the primary key and the series
    property, which is decision 0009's ordinary case: the series id is the
    instance's own key.
    """
    assert declare(client, fx, ontology).status_code == 200
    r = client.post(
        f"{pbase(fx)}/object-type-sources/{ontology['source_id']}/sync",
        headers=hdr(fx.editor_sub), json={},
    )
    assert r.status_code == 200, r.text
    r = client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    )
    return next(i["id"] for i in r.json()["items"] if i["primary_key"] == "S1")


def instance_points(client: TestClient, fx: Fixture, ontology: dict, iid: str, **params) -> object:
    return client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{iid}"
        f"/series/readings/points",
        headers=hdr(fx.viewer_sub), params=params,
    )


def test_an_objects_points_are_readable_at_the_workspace_floor(
    client: TestClient, fx: Fixture, ontology: dict, instance: str
) -> None:
    """**The same floor every other read of an instance sits at.** The ontology
    is shared across a workspace and instance properties are already visible
    here; a time series property's points are the value of one of those
    properties, so putting them behind project membership would make one
    property readable and another not, on the same screen."""
    r = instance_points(client, fx, ontology, instance)
    assert r.status_code == 200, r.text
    assert [p["value"] for p in r.json()["points"]] == [10, 20, 30]
    assert r.json()["series_id"] == "S1"


def test_the_series_id_comes_from_the_instance_not_the_caller(
    client: TestClient, fx: Fixture, ontology: dict, instance: str
) -> None:
    """A caller supplying one could ask for somebody else's series through an
    instance they can see. The question this endpoint answers is "this object's
    readings", so a `series_id` parameter is ignored rather than honoured."""
    r = instance_points(client, fx, ontology, instance, series_id="S2")
    assert r.json()["series_id"] == "S1"
    assert 99 not in [p["value"] for p in r.json()["points"]]


def test_each_object_gets_its_own_readings(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """The other half of "the series id comes from the instance": S2's chart is
    S2's, drawn from the same dataset and the same mapping.

    Written this way after a first version claimed to cover the *no series id*
    case and could not - every synced instance here has one, so the assertion
    was true for the wrong reason. What is checked is what the fixture can
    actually distinguish.
    """
    r = client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    )
    iid = next(i["id"] for i in r.json()["items"] if i["primary_key"] == "S2")
    body = instance_points(client, fx, ontology, iid).json()
    assert body["series_id"] == "S2"
    assert [p["value"] for p in body["points"]] == [99]


def test_an_outsider_cannot_read_an_objects_points(
    client: TestClient, fx: Fixture, ontology: dict, instance: str
) -> None:
    r = client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}"
        f"/series/readings/points",
        headers=hdr(fx.outsider_sub),
    )
    assert r.status_code in (403, 404)


def test_a_property_with_no_series_mapped_is_a_404(
    client: TestClient, fx: Fixture, ontology: dict, instance: str
) -> None:
    r = client.get(
        f"{wbase(fx)}/object-types/{ontology['type_id']}/instances/{instance}"
        f"/series/site/points",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 404
