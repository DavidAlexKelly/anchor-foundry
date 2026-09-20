"""**Answering** a derived property (Foundry `object-link-types` p.143-148).

`test_derived_properties.py` covers the question - which declarations are
refused, and why - and it is pure. This covers the answer, which had no API
test at all: §161 declared, §162 answered, and the only thing exercising §162
was `e2e/test_derived_property_editor.py`, one browser test drawing one chain.

**Written because §406 shipped a broken read behind 46 passing tests.** The new
arithmetic branch asked `ontology.get_type` for the far type's properties;
that returns the type's own row and nothing else, so every `avg` refused
itself on the read. Every one of those 46 tests is validation, so none of them
could have noticed. A full-file browser run did, two tests later, because the
broken derivation stayed on a shared fixture's type.

p.143's own three examples are the shapes: an aggregate over many, a single
value across a one-to-one hop, and a collection.
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

CUSTOMERS = b"customer_id,name\nC1,North Ltd\nC2,South Ltd\n"
# **Lopsided, and not round.** C1 has three orders averaging 20 - a number none
# of the three carries, which is what separates an average from a first-value
# read - and C2 has none, which is the empty answer.
ORDERS = (
    b"order_id,customer_id,total\n"
    b"O1,C1,10\n"
    b"O2,C1,20\n"
    b"O3,C1,30\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("derived-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def dbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def sbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources"


def _upload(client, fx, name: str, body: bytes) -> str:
    r = client.post(
        f"{dbase(fx)}/upload",
        headers=hdr(fx.editor_sub),
        data={"name": name},
        files={"file": (f"{name}.csv", io.BytesIO(body), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _declare(client, fx, api_name: str, properties: list[dict]) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": api_name, "display_name": api_name, "properties": properties},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _map_and_sync(client, fx, type_id: str, dataset_id: str, key: str,
                  mappings: dict) -> None:
    r = client.post(
        sbase(fx),
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset_id,
              "primary_key_column": key, "column_mappings": mappings},
    )
    assert r.status_code == 201, r.text
    source = r.json()["id"]
    r = client.post(f"{sbase(fx)}/{source}/sync", headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """Customers, orders, and the link between them.

    `total` is declared **integer**, which is the whole point of §406: the
    arithmetic aggregations run on the declaration rather than on what the
    values happen to look like.
    """
    customers_ds = _upload(client, fx, f"DerivedCustomers{fx.tag}", CUSTOMERS)
    orders_ds = _upload(client, fx, f"DerivedOrders{fx.tag}", ORDERS)

    customer = _declare(client, fx, f"DerivedCustomer{fx.tag}", [
        {"api_name": "name", "data_type": "string"},
    ])
    order = _declare(client, fx, f"DerivedOrder{fx.tag}", [
        {"api_name": "customer_id", "data_type": "string"},
        {"api_name": "total", "data_type": "integer"},
    ])
    _map_and_sync(client, fx, customer, customers_ds, "customer_id", {"name": "name"})
    _map_and_sync(client, fx, order, orders_ds, "order_id",
                  {"customer_id": "customer_id", "total": "total"})

    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"placed_by{fx.tag}", "display_name": "Placed by",
              "from_type_id": order, "to_type_id": customer,
              "cardinality": "one_to_many",
              "from_property": "customer_id", "to_property": "$primary_key",
              "from_side_name": "Orders", "to_side_name": "Placed by"},
    )
    assert r.status_code == 201, r.text
    return {"customer": customer, "order": order, "link": r.json()["id"]}


def _derive(client, fx, world: dict, api_name: str, derivation: dict,
            data_type: str = "float") -> None:
    """Put one derived property on the customer type, replacing any before it."""
    r = client.get(f"{wbase(fx)}/object-types/{world['customer']}",
                   headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    detail = r.json()
    keep = [dict(p) for p in detail["properties"] if p["derivation"] is None]
    r = client.patch(
        f"{wbase(fx)}/object-types/{world['customer']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": detail["display_name"],
              "properties": keep + [{"api_name": api_name, "display_name": api_name,
                                     "data_type": data_type,
                                     "derivation": derivation}],
              "title_property": detail.get("title_property")},
    )
    assert r.status_code == 200, r.text


def _read(client, fx, world: dict, name: str) -> object:
    r = client.get(f"{wbase(fx)}/object-types/{world['customer']}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    rows = r.json()["items"]
    row = next(i for i in rows if i["properties"]["name"] == name)
    r = client.get(
        f"{wbase(fx)}/object-types/{world['customer']}/instances/{row['id']}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return r.json()["properties"]


@pytest.mark.parametrize(
    "aggregate,expected",
    [("avg", 20), ("sum", 60), ("min", 10), ("max", 30)],
)
def test_p145s_four_arithmetic_aggregations_answer(
    client: TestClient, fx: Fixture, world: dict, aggregate: str, expected: float
) -> None:
    """**The read §406 added, and the one nothing was testing.**

    `avg` is p.143's own opening example - "a Department object type could have
    a derived property for 'Average employee salary'" - and 20 is a number none
    of C1's three orders carries, so a first-value read cannot pass it.
    """
    _derive(client, fx, world, "figure", {
        "links": [{"link_type_id": world["link"]}],
        "aggregate": aggregate, "property": "total",
    })
    assert _read(client, fx, world, "North Ltd")["figure"] == expected


def test_a_customer_with_no_orders_gets_nothing_rather_than_zero(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """C2 placed none. **A sum over nothing is not zero** - the §226 rule at the
    other end of a link chain - because a figure of 0 is a claim about orders
    that were never placed."""
    _derive(client, fx, world, "figure", {
        "links": [{"link_type_id": world["link"]}],
        "aggregate": "sum", "property": "total",
    })
    assert _read(client, fx, world, "South Ltd")["figure"] is None
    # A count over nothing *is* zero, because "how many" always has an answer.
    _derive(client, fx, world, "figure", {
        "links": [{"link_type_id": world["link"]}], "aggregate": "count",
    }, data_type="integer")
    assert _read(client, fx, world, "South Ltd")["figure"] == 0


def test_the_aggregations_that_need_no_declared_type_still_answer(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """§406 added a branch above these; this is the assertion that it did not
    swallow them. `count` and `exact_cardinality` take the older path, and a
    new branch placed one line too early would take both."""
    _derive(client, fx, world, "figure", {
        "links": [{"link_type_id": world["link"]}], "aggregate": "count",
    }, data_type="integer")
    assert _read(client, fx, world, "North Ltd")["figure"] == 3

    _derive(client, fx, world, "figure", {
        "links": [{"link_type_id": world["link"]}],
        "aggregate": "exact_cardinality", "property": "total",
    }, data_type="integer")
    assert _read(client, fx, world, "North Ltd")["figure"] == 3


def test_a_collection_still_answers(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.143's third shape, on the same branch boundary as above."""
    _derive(client, fx, world, "figure", {
        "links": [{"link_type_id": world["link"]}],
        "aggregate": "collect_set", "property": "total",
    }, data_type="string")
    got = _read(client, fx, world, "North Ltd")["figure"]
    assert sorted(str(v) for v in got) == ["10", "20", "30"], got


def test_a_chain_that_lands_back_on_the_type_being_saved(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The overlay, and the mutation sweep is how it got a test.**

    `ontology._update` reads every type's declared properties out of the
    database so `parse` can check an arithmetic aggregation against the far
    type. A chain can land back on the type being *saved* - here Orders and
    then Placed by, two hops home - and the rows in the database for that type
    are the ones this save is about to replace. So the map is overlaid with the
    properties in hand.

    Without the overlay the check reads the definition being replaced, and a
    numeric property added in the *same* request is invisible to a derivation
    added beside it: the save fails saying the type has no such property, about
    a property the request plainly contains. Removing the overlay passed all
    seven of this file's other tests, because none of them looked homeward.
    """
    r = client.get(f"{wbase(fx)}/object-types/{world['customer']}",
                   headers=hdr(fx.editor_sub))
    detail = r.json()
    keep = [dict(p) for p in detail["properties"] if p["derivation"] is None]
    # Both in one request: a brand-new number, and a derivation that aggregates
    # it after walking out to Orders and back.
    r = client.patch(
        f"{wbase(fx)}/object-types/{world['customer']}",
        headers=hdr(fx.editor_sub),
        json={
            "display_name": detail["display_name"],
            "properties": keep + [
                {"api_name": "score", "display_name": "Score",
                 "data_type": "integer"},
                {"api_name": "peer_score", "display_name": "Peer score",
                 "data_type": "float",
                 "derivation": {
                     "links": [{"link_type_id": world["link"]},
                               {"link_type_id": world["link"]}],
                     "aggregate": "avg", "property": "score",
                 }},
            ],
            "title_property": detail.get("title_property"),
        },
    )
    assert r.status_code == 200, r.text
    saved = next(p for p in r.json()["properties"] if p["api_name"] == "peer_score")
    assert saved["derivation"]["aggregate"] == "avg"
    assert saved["derivation"]["far_type_id"] == world["customer"]
