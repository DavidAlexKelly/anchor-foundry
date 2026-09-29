"""Generate join table (§562; db 0117; `object-link-types` p.200-201).

    "It is now possible to automatically generate a join table for new link
     types. The Generate join table option will create a dataset with the
     correct schema based on the primary keys of the two object types you
     have selected. This means that you can get started faster if you have
     user edit-backed data, or if you want to provide production data later
     on." (p.200-201)

The dataset it makes is empty, so the test that it is *the correct schema* is
that it works: a link backed by it follows nothing, then an action writes a
pair into it (§553) and the link follows that.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_link_join_tables import instance, links_of, object_type, pbase, wbase  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import link_join_tables  # noqa: E402


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


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    aircraft = object_type(client, fx, f"aircraft_{tag}", b"id,tail\n1,G-AAAA\n2,G-BBBB\n", ["tail"])
    flights = object_type(client, fx, f"flight_{tag}", b"id,route\nF1,LHR-JFK\nF2,JFK-SFO\n",
                          ["route"])
    return {"aircraft": aircraft, "flights": flights, "tag": tag}


def generate(client, fx, from_type: str, to_type: str, name: str, sub: str | None = None):
    return client.post(f"{pbase(fx)}/datasets/join-table", headers=hdr(sub or fx.editor_sub),
                       json={"from_type_id": from_type, "to_type_id": to_type, "name": name})


def test_it_makes_an_empty_dataset_keyed_by_both_types(client, fx, world) -> None:
    tag = world["tag"]
    r = generate(client, fx, world["flights"], world["aircraft"], "Flown by join table")
    assert r.status_code == 201, r.text
    made = r.json()
    assert (made["from_column"], made["to_column"]) == (f"flight_{tag}_key", f"aircraft_{tag}_key")
    dataset = made["dataset"]
    assert dataset["name"] == "Flown by join table"
    assert dataset["origin"] == "join_table"
    assert [(c["name"], c["data_type"]) for c in dataset["table_schema"]] == [
        (f"flight_{tag}_key", "VARCHAR"), (f"aircraft_{tag}_key", "VARCHAR")]
    assert dataset["row_count"] == 0
    r = client.get(f"{pbase(fx)}/datasets/{dataset['id']}/origin", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "join_table"
    # A second one with the same name is the next free one, not a refusal.
    again = generate(client, fx, world["flights"], world["aircraft"], "Flown by join table")
    assert again.status_code == 201, again.text
    assert again.json()["dataset"]["name"] == "Flown by join table 2"


def test_a_link_backed_by_it_gains_the_pairs_an_action_writes(client, fx, world) -> None:
    made = generate(client, fx, world["flights"], world["aircraft"], "Crewed join table").json()
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"crewed_{uuid.uuid4().hex[:6]}", "display_name": "Crewed",
        "from_type_id": world["flights"], "to_type_id": world["aircraft"],
        "cardinality": "many_to_many", "join_dataset_id": made["dataset"]["id"],
        "join_from_column": made["from_column"], "join_to_column": made["to_column"]})
    assert r.status_code == 201, r.text
    link = r.json()["id"]
    assert links_of(client, fx, world["flights"], "F1")[link]["items"] == []

    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["flights"], "api_name": f"crew_{uuid.uuid4().hex[:6]}",
        "display_name": "Crew", "editable_properties": ["route"]})
    assert r.status_code == 201, r.text
    action = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{action}/definition", headers=hdr(fx.editor_sub), json={
        "parameters": [{"api_name": "craft", "display_name": "Aircraft", "data_type": "object",
                        "object_type_id": world["aircraft"]}],
        "rules": [{"kind": "create_link", "config": {"link_type": link, "object": "craft"}}],
        "criteria": []})
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/actions/{action}/execute", headers=hdr(fx.editor_sub), json={
        "instance_id": instance(client, fx, world["flights"], "F1")["id"],
        "values": {"craft": instance(client, fx, world["aircraft"], "2")["id"]}})
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert [i["primary_key"] for i in links_of(client, fx, world["flights"], "F1")[link]["items"]] == ["2"]
    assert [i["primary_key"] for i in links_of(client, fx, world["aircraft"], "2")[link]["items"]] == ["F1"]


def test_a_link_from_a_type_to_itself_gets_a_column_for_each_end(client, fx, world) -> None:
    r = generate(client, fx, world["flights"], world["flights"], "Connects join table")
    assert r.status_code == 201, r.text
    tag = world["tag"]
    assert (r.json()["from_column"], r.json()["to_column"]) == (
        f"from_flight_{tag}_key", f"to_flight_{tag}_key")


def test_the_columns_are_named_for_the_types() -> None:
    assert link_join_tables.generated_columns({"api_name": "a"}, {"api_name": "b"}) == ("a_key", "b_key")
    assert link_join_tables.generated_columns({"api_name": "a"}, {"api_name": "a"}) == (
        "from_a_key", "to_a_key")


def test_a_type_that_does_not_exist_is_not_found(client, fx, world) -> None:
    r = generate(client, fx, world["flights"], str(uuid.uuid4()), "Nowhere join table")
    assert r.status_code == 404, r.text


def test_making_one_takes_an_editor(client, fx, world) -> None:
    r = generate(client, fx, world["flights"], world["aircraft"], "Viewer join table",
                 sub=fx.viewer_sub)
    assert r.status_code == 403, r.text
