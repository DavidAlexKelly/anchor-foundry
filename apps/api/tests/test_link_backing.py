"""Object-backed link types (§666; `object-link-types` p.197, p.199; db 0132).

    "With an object-backed link, you can have the Flight Manifest object type
     that links the Aircraft and Flight objects … this Flight Manifest object
     can contain additional properties such as Pilot and First Mate to provide
     additional metadata on the link." (p.199)

p.199's own example: aircraft, flights, and a flight manifest naming one of
each. Aircraft 1 flew F1 and F2, aircraft 2 flew F2 and F3, and F4 has no
manifest. The two many-to-one links run from the manifest to each end, and
the backed link between aircraft and flights is followed through them.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_link_join_tables import (  # noqa: E402
    instance, key_is, keys_of, links_of, object_type, wbase,
)
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import object_sets  # noqa: E402


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


MANIFESTS = (b"id,aircraft,flight,pilot\n"
             b"M1,1,F1,Ada\nM2,1,F2,Grace\nM3,2,F2,Alan\nM4,2,F3,Ada\n")


def link(client, fx, **body):
    return client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json=body)


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    aircraft = object_type(client, fx, f"aircraft_{tag}", b"id,tail\n1,G-AAAA\n2,G-BBBB\n3,G-CCCC\n", ["tail"])
    flights = object_type(client, fx, f"flight_{tag}",
                          b"id,route\nF1,LHR-JFK\nF2,JFK-SFO\nF3,SFO-LHR\nF4,LHR-CDG\n", ["route"])
    manifests = object_type(client, fx, f"manifest_{tag}", MANIFESTS, ["aircraft", "flight", "pilot"])
    # p.199's prerequisites: a many-to-one link from the manifest to each end.
    to_aircraft = link(client, fx, api_name=f"manifest_aircraft_{tag}", display_name="Manifest aircraft",
                       from_type_id=manifests, to_type_id=aircraft, cardinality="one_to_many",
                       from_property="aircraft", to_property="$primary_key").json()["id"]
    # The other one the other way round: the flight is its `from` end.
    to_flight = link(client, fx, api_name=f"manifest_flight_{tag}", display_name="Manifest flight",
                     from_type_id=flights, to_type_id=manifests, cardinality="one_to_many",
                     from_property="$primary_key", to_property="flight").json()["id"]
    backed = link(client, fx, api_name=f"flew_{tag}", display_name="Flew",
                  from_type_id=aircraft, to_type_id=flights, cardinality="many_to_many",
                  from_side_name="Aircraft", to_side_name="Flights",
                  backing_type_id=manifests, backing_from_link_id=to_aircraft,
                  backing_to_link_id=to_flight)
    assert backed.status_code == 201, backed.text
    return {"aircraft": aircraft, "flights": flights, "manifests": manifests,
            "to_aircraft": to_aircraft, "to_flight": to_flight, "link": backed.json()["id"], "tag": tag}


# ---- defining one ------------------------------------------------------------

def test_the_link_type_names_its_backing(client, fx, world) -> None:
    r = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    got = next(t for t in r.json() if t["id"] == world["link"])
    assert (got["backing_type_id"], got["backing_from_link_id"], got["backing_to_link_id"]) == (
        world["manifests"], world["to_aircraft"], world["to_flight"])
    assert got["backing_display_name"] == f"manifest_{world['tag']}"
    assert (got["from_property"], got["join_dataset_id"]) == (None, None)


def refused(client, fx, world, **changes) -> str:
    body = {"api_name": f"x_{uuid.uuid4().hex[:6]}", "display_name": "X",
            "from_type_id": world["aircraft"], "to_type_id": world["flights"],
            "cardinality": "many_to_many", "backing_type_id": world["manifests"],
            "backing_from_link_id": world["to_aircraft"], "backing_to_link_id": world["to_flight"]}
    r = link(client, fx, **{**body, **changes})
    assert r.status_code == 422, r.text
    return r.json()["detail"]


@pytest.mark.parametrize("changes, says", [
    ({"backing_to_link_id": None}, "needs its backing object type and the link from it to each end"),
    ({"from_property": "tail", "to_property": "route"}, "one of them"),
    ({"backing_type_id": "aircraft"}, "a third type"),
    ({"backing_to_link_id": "to_aircraft"}, "each end needs its own link"),
    # The aircraft link does not reach flights.
    ({"backing_from_link_id": "to_flight", "backing_to_link_id": "to_aircraft"},
     "the from end's backing link must join the backing object type to that end"),
])
def test_what_does_not_back_a_link_is_refused(client, fx, world, changes, says) -> None:
    resolved = {k: world[v] if isinstance(v, str) and v in world else v for k, v in changes.items()}
    assert says in refused(client, fx, world, **resolved)


def test_a_backing_link_joined_on_a_join_table_does_not_back(client, fx, world) -> None:
    tag = uuid.uuid4().hex[:6]
    loose = link(client, fx, api_name=f"loose_{tag}", display_name="Loose",
                 from_type_id=world["manifests"], to_type_id=world["aircraft"],
                 cardinality="one_to_many").json()["id"]
    assert "backing link must join" in refused(client, fx, world, backing_from_link_id=loose)


# ---- following it ------------------------------------------------------------

def test_the_type_lists_it_from_both_ends(client, fx, world) -> None:
    for type_id, direction, far in ((world["aircraft"], "outbound", world["flights"]),
                                    (world["flights"], "inbound", world["aircraft"])):
        r = client.get(f"{wbase(fx)}/object-types/{type_id}/links", headers=hdr(fx.viewer_sub))
        got = next(t for t in r.json() if t["link_type_id"] == world["link"])
        assert (got["direction"], got["far_type_id"], got["backed"], got["join_table"]) == (
            direction, far, True, False)
        # Both ends are joined on their primary keys, as their backing links say.
        assert (got["near_property"], got["far_property"]) == ("$primary_key", "$primary_key")


def test_an_object_shows_what_its_backing_objects_link_it_to(client, fx, world) -> None:
    group = links_of(client, fx, world["aircraft"], "1")[world["link"]]
    assert sorted(i["primary_key"] for i in group["items"]) == ["F1", "F2"]
    assert (group["total"], group["backed"], group["problem"]) == (2, True, None)
    back = links_of(client, fx, world["flights"], "F2")[world["link"]]
    assert sorted(i["primary_key"] for i in back["items"]) == ["1", "2"]
    assert links_of(client, fx, world["flights"], "F4")[world["link"]]["total"] == 0


def test_a_hop_through_the_backing_objects(client, fx, world) -> None:
    hop = {"object_type_id": world["flights"],
           "via": {"link_type_id": world["link"], "base": key_is(world["aircraft"], "2")}}
    assert keys_of(client, fx, hop) == ["F2", "F3"]
    back = {"object_type_id": world["aircraft"],
            "via": {"link_type_id": world["link"], "base": key_is(world["flights"], "F2", "F4")}}
    assert keys_of(client, fx, back) == ["1", "2"]


def test_filters_on_linked_objects_go_through_them_backwards(client, fx, world) -> None:
    def linked(type_id: str, filters: list) -> dict:
        return {"object_type_id": type_id, "filters": [
            {"property": world["link"], "op": "has_link", "value": {"filters": filters}}]}
    assert keys_of(client, fx, linked(world["aircraft"], [])) == ["1", "2"]
    assert keys_of(client, fx, linked(world["flights"], [])) == ["F1", "F2", "F3"]
    assert keys_of(client, fx, linked(world["aircraft"], [
        {"property": "route", "op": "eq", "value": "SFO-LHR"}])) == ["2"]


def test_a_derived_property_counts_through_them(client, fx, world) -> None:
    r = client.get(f"{wbase(fx)}/object-types/{world['aircraft']}", headers=hdr(fx.editor_sub))
    detail = r.json()
    keep = [dict(p) for p in detail["properties"] if p["derivation"] is None]
    r = client.patch(f"{wbase(fx)}/object-types/{world['aircraft']}", headers=hdr(fx.editor_sub),
                     json={"display_name": detail["display_name"], "title_property": detail.get("title_property"),
                           "properties": keep + [{
                               "api_name": "flights_flown", "display_name": "Flights flown",
                               "data_type": "integer",
                               "derivation": {"links": [world["link"]], "aggregate": "count"}}]})
    assert r.status_code == 200, r.text
    for key, flown in (("1", 2), ("2", 2), ("3", 0)):
        got = instance(client, fx, world["aircraft"], key)
        r = client.get(f"{wbase(fx)}/object-types/{world['aircraft']}/instances/{got['id']}",
                       headers=hdr(fx.viewer_sub))
        assert r.json()["properties"]["flights_flown"] == flown, (key, r.json())
    # And a page of them at once, as a table asks (§604): every row's links in
    # one read of the backing objects.
    r = client.post(f"{wbase(fx)}/object-types/{world['aircraft']}/derived-values",
                    headers=hdr(fx.viewer_sub), json={"keys": ["1", "2", "3"], "properties": ["flights_flown"]})
    assert r.status_code == 200, r.text
    assert r.json()["errors"] == {}
    assert {row["primary_key"]: row["values"]["flights_flown"] for row in r.json()["rows"]} == {
        "1": 2, "2": 2, "3": 0}


def test_too_many_backing_objects_are_refused_with_the_number(client, fx, world, monkeypatch) -> None:
    monkeypatch.setattr(object_sets, "MAX_JOIN_VALUES", 1)
    hop = {"object_type_id": world["flights"],
           "via": {"link_type_id": world["link"], "base": key_is(world["aircraft"], "1")}}
    r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=hdr(fx.editor_sub),
                    json={"definition": hop, "limit": 50, "offset": 0})
    assert r.status_code == 422, r.text
    assert "linked by more than 1 backing objects" in r.json()["detail"]


# ---- converting one, and losing its backing ----------------------------------

def test_an_existing_link_is_converted_and_unmapped_when_its_backing_goes(client, fx, world) -> None:
    tag = uuid.uuid4().hex[:6]
    plain = link(client, fx, api_name=f"plain_{tag}", display_name="Plain",
                 from_type_id=world["aircraft"], to_type_id=world["flights"],
                 cardinality="many_to_many").json()["id"]
    helper = link(client, fx, api_name=f"helper_{tag}", display_name="Helper",
                  from_type_id=world["manifests"], to_type_id=world["aircraft"], cardinality="one_to_many",
                  from_property="aircraft", to_property="$primary_key").json()["id"]
    # p.199: "update the join method and select Object type".
    r = client.patch(f"{wbase(fx)}/link-types/{plain}", headers=hdr(fx.editor_sub), json={
        "backing_type_id": world["manifests"], "backing_from_link_id": helper,
        "backing_to_link_id": world["to_flight"]})
    assert r.status_code == 200, r.text
    assert r.json()["backing_type_id"] == world["manifests"]
    assert sorted(i["primary_key"] for i in links_of(client, fx, world["aircraft"], "2")[plain]["items"]) \
        == ["F2", "F3"]
    # Its backing link deleted, the link stays, unmapped: no longer followed.
    assert client.delete(f"{wbase(fx)}/link-types/{helper}", headers=hdr(fx.editor_sub)).status_code == 204
    r = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub))
    after = next(t for t in r.json() if t["id"] == plain)
    assert (after["backing_type_id"], after["backing_from_link_id"]) == (world["manifests"], None)
    assert plain not in links_of(client, fx, world["aircraft"], "2")
