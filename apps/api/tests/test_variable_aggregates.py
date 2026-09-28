"""p.73's Object set aggregation, resolved through the store (§617).

> "Object set aggregation: For variables derived from an aggregation of an
> object set" (`workshop` p.73)

What `evaluate` asks for and how it keys it is `test_workshop_variables.py`.
This is the half only a database can answer: that the route reads each
aggregation from the store, that a number read that way feeds everything
downstream of it - including a set narrowed by it, whose own aggregation is
only askable once the first is answered - and that a question the store
refuses reaches the reader as a refusal rather than as a blank.
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
from src.services.storage import LocalStorageGateway  # noqa: E402

# Four sites, one with no capacity: the average is of the three that have one
# (20), and a sum over nothing measurable is left to its own test.
SITES = (b"site_id,region,capacity\n"
         b"S1,north,10\nS2,south,30\nS3,north,20\nS4,east,\n")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("aggregate-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"{wbase(fx)}/projects/{fx.project}"


@pytest.fixture(scope="module")
def type_id(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Sites{fx.tag}"},
        files={"file": ("sites.csv", io.BytesIO(SITES), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"site_{fx.tag}", "display_name": "Site",
              "properties": [{"api_name": "region", "data_type": "string"},
                             {"api_name": "capacity", "data_type": "integer"}]},
    )
    assert r.status_code == 201, r.text
    made = r.json()["id"]
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": made, "dataset_id": dataset, "primary_key_column": "site_id",
              "column_mappings": {"region": "region", "capacity": "capacity"}},
    )
    assert r.status_code == 201, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
                    headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text
    return made


def aggregate(vid: str, source: str, aggregation: str, prop: str | None = None) -> dict:
    return {"id": vid, "kind": "number", "label": vid, "derivation": {
        "transform": "object_set_aggregation", "inputs": [source],
        "config": {"aggregation": aggregation, **({"property": prop} if prop else {})}}}


def module(client: TestClient, fx: Fixture, variables: dict) -> str:
    r = client.post(f"{pbase(fx)}/canvas-apps", headers=hdr(fx.editor_sub),
                    json={"name": f"Aggregates {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(f"{pbase(fx)}/canvas-apps/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": {"format": 2, "layout": {}, "events": {},
                                        "variables": variables}})
    assert r.status_code == 200, r.text
    return app_id


def resolve(client: TestClient, fx: Fixture, app_id: str, sub: str | None = None):
    return client.post(f"{pbase(fx)}/canvas-apps/{app_id}/variables/evaluate",
                       headers=hdr(sub or fx.viewer_sub), json={"values": {}})


def everything(type_id: str) -> dict:
    return {
        "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                  "object_set": {"object_type_id": type_id, "filters": []}},
        "v_count": aggregate("v_count", "v_all", "count"),
        "v_sum": aggregate("v_sum", "v_all", "sum", "capacity"),
        "v_avg": aggregate("v_avg", "v_all", "avg", "capacity"),
        "v_regions": aggregate("v_regions", "v_all", "count_distinct", "region"),
        "v_max": aggregate("v_max", "v_all", "max", "capacity"),
        # The sites at the largest capacity: a set narrowed by an aggregation,
        # so its own count is a question the first pass cannot ask.
        "v_big": {"id": "v_big", "kind": "object_set", "label": "The largest",
                  "derivation": {"transform": "filter_set", "inputs": ["v_all", "v_max"],
                                 "config": {"property": "capacity", "op": "eq"}}},
        "v_big_count": aggregate("v_big_count", "v_big", "count"),
        "v_two": {"id": "v_two", "kind": "number", "label": "Two", "default": 2},
        "v_twice": {"id": "v_twice", "kind": "number", "label": "Twice", "derivation": {
            "transform": "multiply", "inputs": ["v_sum", "v_two"]}},
    }


def test_each_aggregation_is_read_from_the_store(
    client: TestClient, fx: Fixture, type_id: str,
) -> None:
    r = resolve(client, fx, module(client, fx, everything(type_id)))
    assert r.status_code == 200, r.text
    got = r.json()["values"]
    assert (got["v_count"], got["v_sum"], got["v_avg"], got["v_regions"]) == (4, 60, 20.0, 3)
    # An integer property's sum is a whole number, as the Metric Card's is.
    assert isinstance(got["v_sum"], int)
    # And a number read that way is a number to everything downstream.
    assert got["v_twice"] == 120


def test_a_set_narrowed_by_an_aggregation_is_aggregated_in_turn(
    client: TestClient, fx: Fixture, type_id: str,
) -> None:
    """Only S2 holds the largest capacity, 30. Its count needs the maximum
    first, so it is the second pass's question - the loop in
    `variable_aggregates.evaluate`, and why it is a loop."""
    got = resolve(client, fx, module(client, fx, everything(type_id))).json()["values"]
    assert got["v_max"] == 30
    assert got["v_big"]["filters"] == [{"property": "capacity", "op": "eq", "value": 30}]
    assert got["v_big_count"] == 1


def test_a_question_the_store_refuses_is_a_refusal_not_a_blank(
    client: TestClient, fx: Fixture, type_id: str,
) -> None:
    """A derived set's type is only known when it resolves, so a sum over its
    text property is refused then - with the store's sentence."""
    variables = everything(type_id)
    variables["v_bad"] = aggregate("v_bad", "v_big", "sum", "region")
    r = resolve(client, fx, module(client, fx, variables))
    assert r.status_code == 422, r.text
    assert "an object set aggregation cannot be answered" in r.text


def test_a_set_the_document_defines_is_checked_when_it_is_saved(
    client: TestClient, fx: Fixture, type_id: str,
) -> None:
    variables = everything(type_id)
    variables["v_bad"] = aggregate("v_bad", "v_all", "avg", "region")
    r = client.post(f"{pbase(fx)}/canvas-apps", headers=hdr(fx.editor_sub),
                    json={"name": f"Aggregates {uuid.uuid4().hex[:8]}"})
    r = client.put(f"{pbase(fx)}/canvas-apps/{r.json()['id']}/definition",
                   headers=hdr(fx.editor_sub),
                   json={"definition": {"format": 2, "layout": {}, "events": {},
                                        "variables": variables}})
    assert r.status_code == 422, r.text
    assert "v_bad" in r.text


def test_a_set_of_a_type_nobody_here_has_is_not_counted(
    client: TestClient, fx: Fixture, type_id: str,
) -> None:
    """The ontology is read first, so a type this workspace does not have is
    not found - rather than counted as an empty store's zero, which would be a
    number about data that does not exist."""
    variables = {
        "v_far": {"id": "v_far", "kind": "object_set", "label": "Elsewhere",
                  "object_set": {"object_type_id": str(uuid.uuid4()), "filters": []}},
        "v_n": aggregate("v_n", "v_far", "count"),
    }
    r = resolve(client, fx, module(client, fx, variables))
    assert r.status_code == 404, r.text
