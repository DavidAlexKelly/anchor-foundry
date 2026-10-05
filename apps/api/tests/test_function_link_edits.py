"""A function's link edits on a join table (§784; decision 0018 option B;
`action-types` p.75, `functions` "Ontology edit").

> "Create several different types of objects and set up links between
> them." (action-types p.75)

A typed edit (§783) whose `__edit` is `link` or `unlink` adds or removes a
join table's pairs. Its `__properties` name each link type and the object, or
objects, at its other end: `json_object('flown_by', '3')` beside a flight
links it to aircraft 3, as `flight.flownBy.add(aircraft)` would.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_link_join_tables import (  # noqa: E402
    PAIRS, instance, links_of, object_type, pbase, upload, wbase,
)
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture
def world(client, fx) -> dict:
    """Fresh per test, because each one writes the join table."""
    tag = uuid.uuid4().hex[:6]
    aircraft = object_type(client, fx, f"aircraft_{tag}",
                           b"id,tail\n1,G-AAAA\n2,G-BBBB\n3,G-CCCC\n", ["tail"])
    flights = object_type(client, fx, f"flight_{tag}",
                          b"id,route\nF1,LHR-JFK\nF2,JFK-SFO\nF3,SFO-LHR\nF4,LHR-CDG\n",
                          ["route"])
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"flown_by_{tag}", "display_name": "Flown by",
        "from_type_id": flights, "to_type_id": aircraft, "cardinality": "many_to_many",
        "join_dataset_id": upload(client, fx, f"flown_{tag}", PAIRS),
        "join_from_column": "flight", "join_to_column": "aircraft"})
    assert r.status_code == 201, r.text
    return {"aircraft": aircraft, "flights": flights, "link": r.json()["id"],
            "link_name": f"flown_by_{tag}", "flight": f"flight_{tag}",
            "plane": f"aircraft_{tag}"}


def backed(client, fx, world, sql: str, types=("flights", "aircraft")) -> str:
    """An action on a flight whose one rule is a function returning `sql`'s
    edits, fed the flight it runs on."""
    made = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [],
            "parameters": [{"api_name": "flight", "data_type": "object",
                            "object_type_id": world["flights"]}],
            "output": {"kind": "edits", "object_type_ids": [world[t] for t in types]},
            "sql": sql}})
    assert made.status_code == 201, made.text
    act = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["flights"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": "Act", "editable_properties": ["route"]})
    assert act.status_code == 201, act.text
    r = client.put(f"{wbase(fx)}/action-types/{act.json()['id']}/definition",
                   headers=hdr(fx.editor_sub), json={
                       "parameters": [], "criteria": [], "rules": [{"kind": "function", "config": {
                           "function_id": made.json()["id"], "version": "1.0.0",
                           "auto_upgrade": False, "inputs": {"flight": {"subject": True}}}}]})
    assert r.status_code == 200, r.text
    return act.json()["id"]


def run(client, fx, world, act: str, key: str):
    return client.post(f"{pbase(fx)}/actions/{act}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": instance(client, fx, world["flights"], key)["id"],
                             "values": {}})


def linked(client, fx, world, key: str) -> list[str]:
    group = links_of(client, fx, world["flights"], key).get(world["link"])
    return sorted(i["primary_key"] for i in (group or {"items": []})["items"])


def row(world, key: str, verb: str, props: str, of: str = "flight") -> str:
    return (f"SELECT '{world[of]}' AS __object_type, {key} AS __primary_key, "
            f"'{verb}' AS __edit, {props} AS __properties")


def test_a_function_links_the_flight_it_runs_on(client, fx, world) -> None:
    act = backed(client, fx, world,
                 row(world, "$flight", "link", f"json_object('{world['link_name']}', '3')"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F4") == ["3"]
    # The pairs already there stay.
    assert linked(client, fx, world, "F2") == ["1", "2"]


def test_a_function_unlinks_another_flight(client, fx, world) -> None:
    act = backed(client, fx, world,
                 row(world, "'F2'", "unlink", f"json_object('{world['link_name']}', '1')")
                 + " WHERE $flight IS NOT NULL")
    r = run(client, fx, world, act, "F1")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F2") == ["2"]


def test_a_link_from_its_other_end_and_to_several(client, fx, world) -> None:
    """From the aircraft's side, and a list of keys for several pairs."""
    act = backed(client, fx, world,
                 row(world, "'3'", "link", f"json_object('{world['link_name']}', [$flight])",
                     of="plane")
                 + " UNION ALL "
                 + row(world, "$flight", "link",
                       f"json_object('{world['link_name']}', ['1', '2'])"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F4") == ["1", "2", "3"]


def test_a_link_to_an_object_the_function_creates(client, fx, world) -> None:
    act = backed(client, fx, world,
                 row(world, "'9'", "create", "json_object('tail', 'G-NEW')", of="plane")
                 + " UNION ALL "
                 + row(world, "$flight", "link", f"json_object('{world['link_name']}', '9')"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F4") == ["9"]


def test_an_undo_removes_the_pairs_it_added(client, fx, world) -> None:
    act = backed(client, fx, world,
                 row(world, "$flight", "link", f"json_object('{world['link_name']}', '3')"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F4") == ["3"]
    assert r.json()["can_undo"] is True, r.json()
    undone = client.post(f"{pbase(fx)}/actions/{act}/runs/{r.json()['run_id']}/undo",
                         headers=hdr(fx.editor_sub))
    assert undone.status_code == 200, undone.text
    assert linked(client, fx, world, "F4") == []


@pytest.mark.parametrize("make, said", [
    (lambda w: row(w, "$flight", "link", f"json_object('{w['link_name']}', '7')"),
     "the function links F4 to 7, which does not exist"),
    (lambda w: row(w, "'F9'", "link", f"json_object('{w['link_name']}', '1')")
     + " WHERE $flight IS NOT NULL",
     "the function links F9, which does not exist"),
    (lambda w: row(w, "$flight", "link", "json_object('nope', '1')"),
     "the function links through 'nope', which is not a link type of"),
    (lambda w: row(w, "$flight", "link", "json_object()"),
     "the function says nothing to link F4 to"),
    (lambda w: row(w, "$flight", "link", f"json_object('{w['link_name']}', json_object())"),
     "is a key or a list of keys"),
])
def test_a_link_that_cannot_be_made_fails_the_action(client, fx, world, make, said) -> None:
    act = backed(client, fx, world, make(world))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 422, r.text
    assert said in r.json()["detail"], r.text
    assert linked(client, fx, world, "F4") == []


def test_a_link_to_a_type_it_does_not_declare_fails(client, fx, world) -> None:
    """p.83's provenance, for a link: both its ends are types the function
    says it edits."""
    act = backed(client, fx, world,
                 row(world, "$flight", "link", f"json_object('{world['link_name']}', '3')"),
                 types=("flights",))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 422, r.text
    assert "which is not an object type it declares (action-types p.83)" in r.json()["detail"]


def test_a_property_match_link_is_set_by_its_property(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"tailed_{uuid.uuid4().hex[:6]}", "display_name": "Tailed",
        "from_type_id": world["flights"], "to_type_id": world["aircraft"],
        "cardinality": "one_to_many", "from_property": "route", "to_property": "tail"})
    assert r.status_code == 201, r.text
    act = backed(client, fx, world,
                 row(world, "$flight", "link", f"json_object('{r.json()['api_name']}', '1')"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 422, r.text
    assert "matches a property rather than keeping a join table; set route" \
        in r.json()["detail"]


def test_a_key_given_as_a_number_names_the_same_object(client, fx, world) -> None:
    act = backed(client, fx, world,
                 row(world, "$flight", "link", f"json_object('{world['link_name']}', 3)"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F4") == ["3"]


def test_a_link_type_of_another_pair_of_types_is_not_this_ones(client, fx, world) -> None:
    """The link named has to touch the row's own type."""
    notes = object_type(client, fx, f"note_{uuid.uuid4().hex[:6]}", b"id,text\nN1,x\n",
                        ["text"])
    world = {**world, "notes": notes,
             "note": client.get(f"{wbase(fx)}/object-types/{notes}",
                                headers=hdr(fx.viewer_sub)).json()["api_name"]}
    act = backed(client, fx, world,
                 row(world, "'N1'", "link", f"json_object('{world['link_name']}', 'F1')",
                     of="note") + " WHERE $flight IS NOT NULL",
                 types=("flights", "aircraft", "notes"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 422, r.text
    assert f"links through '{world['link_name']}', which is not a link type of " \
        f"{world['note']}" in r.json()["detail"]


def test_an_object_backed_link_is_set_by_its_backing_objects(client, fx, world) -> None:
    """A link kept by objects of a third type (§562) has no pairs to add."""
    tag = uuid.uuid4().hex[:6]
    manifests = object_type(client, fx, f"manifest_{tag}", b"id,aircraft,flight\nM1,1,F1\n",
                            ["aircraft", "flight"])

    def link(**body):
        r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json=body)
        assert r.status_code == 201, r.text
        return r.json()

    to_aircraft = link(api_name=f"m_aircraft_{tag}", display_name="A", from_type_id=manifests,
                       to_type_id=world["aircraft"], cardinality="one_to_many",
                       from_property="aircraft", to_property="$primary_key")["id"]
    to_flight = link(api_name=f"m_flight_{tag}", display_name="F", from_type_id=world["flights"],
                     to_type_id=manifests, cardinality="one_to_many",
                     from_property="$primary_key", to_property="flight")["id"]
    backed_link = link(api_name=f"flew_{tag}", display_name="Flew",
                       from_type_id=world["flights"], to_type_id=world["aircraft"],
                       cardinality="many_to_many", backing_type_id=manifests,
                       backing_from_link_id=to_flight, backing_to_link_id=to_aircraft)
    act = backed(client, fx, world,
                 row(world, "$flight", "link", f"json_object('{backed_link['api_name']}', '3')"))
    r = run(client, fx, world, act, "F4")
    assert r.status_code == 422, r.text
    assert f"flew_{tag} is not kept in a join table, so a function cannot link through it" \
        in r.json()["detail"]
