"""A page of derived values in one read per hop (§604; `object-link-types`
p.143-147, `workshop` p.169).

`test_derived_property_reads.py` is the single-object answer. This is the
page's, and **the standard it is held to is that answer**: every test below
reads the same rows both ways and requires them to agree, then says what the
agreed value is - agreement alone would pass a batch and a single read that
were wrong together.

The world is chosen for where a batch could go wrong and a single read could
not: a product reached twice from one customer (a chain is a *set*), a
customer with no orders (each aggregation's own empty), a customer whose only
order has no total (arithmetic over nothing that parses), duplicate totals
(distinct is distinct), and a join table in the middle of a two-hop chain
(each row must get back its own pairs, not the page's).
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
from src.services import derived_values  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

CUSTOMERS = b"customer_id,name\nC1,North\nC2,South\nC3,East\nC4,West\n"
ORDERS = (
    b"order_id,customer_id,total\n"
    # Not in key order, so the smallest is not the first and the largest is
    # not the last.
    b"O1,C1,20\nO2,C1,31\nO3,C1,10\n"
    # East's third order has no total: an average is over the totals there are.
    b"O4,C3,5\nO5,C3,5\nO8,C3,\n"
    b"O6,C4,\n"
    # A customer nobody has: this order's chain reaches nothing.
    b"O7,C9,1\n"
)
PRODUCTS = b"product_id,name,price\nP1,Anvil,7\nP2,Bolt,2\nP3,Cog,3\n"
# O1 and O2 both carry the Bolt, so North reaches it twice; North's three
# orders make four pairs, which is what tells the join table's bound from the
# orders' own; O1 carries the later products and O2 the earlier, so North's
# products arrive out of key order unless something puts them back; and one
# pair is in the table twice, which is still one pair.
LINES = (
    b"order,product\nO1,P3\nO1,P2\nO2,P1\nO2,P2\nO2,P1\nO4,P3\nO5,P3\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("derived-values-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def _upload(client, fx, name: str, body: bytes) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": name},
        files={"file": (f"{name}.csv", io.BytesIO(body), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _declare(client, fx, api_name: str, properties: list[dict]) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": api_name, "display_name": api_name, "properties": properties},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _map_and_sync(client, fx, type_id: str, dataset_id: str, key: str, mappings: dict) -> None:
    sbase = f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources"
    r = client.post(
        sbase, headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset_id,
              "primary_key_column": key, "column_mappings": mappings},
    )
    assert r.status_code == 201, r.text
    r = client.post(f"{sbase}/{r.json()['id']}/sync", headers=hdr(fx.editor_sub), json={})
    assert r.status_code == 200, r.text


def _link(client, fx, body: dict) -> str:
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    customer = _declare(client, fx, f"DvCustomer{fx.tag}", [
        {"api_name": "name", "data_type": "string"}])
    order = _declare(client, fx, f"DvOrder{fx.tag}", [
        {"api_name": "customer_id", "data_type": "string"},
        {"api_name": "total", "data_type": "integer"}])
    product = _declare(client, fx, f"DvProduct{fx.tag}", [
        {"api_name": "name", "data_type": "string"},
        {"api_name": "price", "data_type": "integer"}])
    _map_and_sync(client, fx, customer, _upload(client, fx, f"DvC{fx.tag}", CUSTOMERS),
                  "customer_id", {"name": "name"})
    _map_and_sync(client, fx, order, _upload(client, fx, f"DvO{fx.tag}", ORDERS),
                  "order_id", {"customer_id": "customer_id", "total": "total"})
    _map_and_sync(client, fx, product, _upload(client, fx, f"DvP{fx.tag}", PRODUCTS),
                  "product_id", {"name": "name", "price": "price"})
    placed = _link(client, fx, {
        "api_name": f"dv_placed{fx.tag}", "display_name": "Placed by",
        "from_type_id": order, "to_type_id": customer, "cardinality": "one_to_many",
        "from_property": "customer_id", "to_property": "$primary_key"})
    carries = _link(client, fx, {
        "api_name": f"dv_carries{fx.tag}", "display_name": "Carries",
        "from_type_id": order, "to_type_id": product, "cardinality": "many_to_many",
        "join_dataset_id": _upload(client, fx, f"DvL{fx.tag}", LINES),
        "join_from_column": "order", "join_to_column": "product"})
    return {"customer": customer, "order": order, "product": product,
            "placed": placed, "carries": carries}


def _derive(client, fx, type_id: str, derived: dict[str, tuple[dict, str]]) -> None:
    """Replace a type's derived properties with these, all in one save."""
    r = client.get(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub))
    detail = r.json()
    keep = [dict(p) for p in detail["properties"] if p["derivation"] is None]
    r = client.patch(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
        json={"display_name": detail["display_name"],
              "properties": keep + [
                  {"api_name": name, "display_name": name, "data_type": data_type,
                   "derivation": derivation}
                  for name, (derivation, data_type) in derived.items()],
              "title_property": detail.get("title_property")},
    )
    assert r.status_code == 200, r.text


def _single(client, fx, type_id: str) -> dict[str, dict]:
    """Every object of a type, each read on its own - the reference answer."""
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                   headers=hdr(fx.viewer_sub))
    out = {}
    for item in r.json()["items"]:
        r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances/{item['id']}",
                       headers=hdr(fx.viewer_sub))
        assert r.status_code == 200, r.text
        out[item["primary_key"]] = r.json()["properties"]
    return out


def _page(client, fx, type_id: str, keys: list[str], names: list[str]) -> dict:
    r = client.post(
        f"{wbase(fx)}/object-types/{type_id}/derived-values", headers=hdr(fx.viewer_sub),
        json={"keys": keys, "properties": names},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _agreed(client, fx, type_id: str, names: list[str]) -> dict[str, dict]:
    """The page's answer, after requiring it to be the single reads' answer."""
    single = _single(client, fx, type_id)
    body = _page(client, fx, type_id, sorted(single), names)
    assert body["errors"] == {}
    page = {row["primary_key"]: row["values"] for row in body["rows"]}
    assert set(page) == set(single)
    for key, values in page.items():
        for name in names:
            assert values[name] == single[key][name], (key, name, values[name], single[key][name])
    return page


def one_hop(world: dict, **rest) -> dict:
    return {"links": [{"link_type_id": world["placed"]}], **rest}


def two_hops(world: dict, **rest) -> dict:
    return {"links": [{"link_type_id": world["placed"]},
                      {"link_type_id": world["carries"]}], **rest}


def test_the_arithmetic_agrees_with_the_single_read(client, fx, world) -> None:
    _derive(client, fx, world["customer"], {
        "total_sum": (one_hop(world, aggregate="sum", property="total"), "integer"),
        "total_avg": (one_hop(world, aggregate="avg", property="total"), "float"),
        "total_min": (one_hop(world, aggregate="min", property="total"), "integer"),
        "total_max": (one_hop(world, aggregate="max", property="total"), "integer"),
    })
    page = _agreed(client, fx, world["customer"],
                   ["total_sum", "total_avg", "total_min", "total_max"])
    assert page["C1"] == {"total_sum": 61, "total_avg": pytest.approx(61 / 3),
                          "total_min": 10, "total_max": 31}
    # Integers stay whole where the store keeps them whole, and an average is
    # a float whatever it averages.
    assert isinstance(page["C1"]["total_sum"], int)
    assert isinstance(page["C3"]["total_avg"], float) and page["C3"]["total_avg"] == 5.0
    # No orders, and an order with no total: nothing to add up is not zero.
    for key in ("C2", "C4"):
        assert set(page[key].values()) == {None}, page[key]


def test_counting_agrees_and_counts_a_set(client, fx, world) -> None:
    _derive(client, fx, world["customer"], {
        "orders": (one_hop(world, aggregate="count"), "integer"),
        "totals": (one_hop(world, aggregate="exact_cardinality", property="total"), "integer"),
        "products": (two_hops(world, aggregate="count"), "integer"),
    })
    page = _agreed(client, fx, world["customer"], ["orders", "totals", "products"])
    assert {k: v["orders"] for k, v in page.items()} == {"C1": 3, "C2": 0, "C3": 3, "C4": 1}
    # East's orders total 5, 5 and nothing; West's one total is empty.
    assert {k: v["totals"] for k, v in page.items()} == {"C1": 3, "C2": 0, "C3": 1, "C4": 0}
    # North reaches the Bolt through two orders and counts it once; East
    # reaches the Cog twice; West's order carries nothing.
    assert {k: v["products"] for k, v in page.items()} == {"C1": 3, "C2": 0, "C3": 1, "C4": 0}


def test_collections_agree_in_key_order_within_their_limit(client, fx, world) -> None:
    _derive(client, fx, world["customer"], {
        "names": (two_hops(world, aggregate="collect_set", property="name", limit=10),
                  "string"),
        "first_two": (one_hop(world, aggregate="collect_list", property="$primary_key",
                              limit=2), "string"),
        "prices": (two_hops(world, aggregate="sum", property="price"), "integer"),
        "first_products": (two_hops(world, aggregate="collect_list",
                                    property="$primary_key", limit=2), "string"),
        "totals": (one_hop(world, aggregate="collect_set", property="total", limit=10),
                   "string"),
    })
    page = _agreed(client, fx, world["customer"],
                   ["names", "first_two", "prices", "first_products", "totals"])
    # A set: East's two fives are one five, and the order is the values' own
    # rather than the orders' keys (20, 31, 10).
    assert page["C3"]["totals"] == [5]
    assert page["C1"]["totals"] == [10, 20, 31]
    assert page["C1"]["names"] == ["Anvil", "Bolt", "Cog"]
    assert page["C1"]["first_two"] == ["O1", "O2"]
    # Key order across two hops, as the single read's one sorted read gives it.
    assert page["C1"]["first_products"] == ["P1", "P2"]
    # A set: the Bolt's price once, not once per order that carries it.
    assert page["C1"]["prices"] == 12
    assert page["C2"] == {"names": [], "first_two": [], "prices": None,
                          "first_products": [], "totals": []}


def test_a_single_value_across_a_one_to_one_hop(client, fx, world) -> None:
    """p.143's second shape - no aggregation - from the other end."""
    _derive(client, fx, world["order"], {
        "customer_name": ({"links": [{"link_type_id": world["placed"]}],
                           "property": "name"}, "string"),
    })
    page = _agreed(client, fx, world["order"], ["customer_name"])
    assert {k: v["customer_name"] for k, v in page.items()} == {
        "O1": "North", "O2": "North", "O3": "North", "O4": "East", "O5": "East",
        "O6": "West", "O7": None, "O8": "East",
    }


def test_only_the_keys_asked_for_and_only_ones_that_exist(client, fx, world) -> None:
    _derive(client, fx, world["customer"], {
        "orders": (one_hop(world, aggregate="count"), "integer"),
    })
    body = _page(client, fx, world["customer"], ["C3", "C1", "C3", "nobody"], ["orders"])
    assert sorted((r["primary_key"], r["values"]["orders"]) for r in body["rows"]) == [
        ("C1", 3), ("C3", 3)]
    assert _page(client, fx, world["customer"], [], ["orders"]) == {"rows": [], "errors": {}}


def test_a_property_that_is_not_derived_is_refused(client, fx, world) -> None:
    for name in ("name", "nothing_here"):
        r = client.post(
            f"{wbase(fx)}/object-types/{world['customer']}/derived-values",
            headers=hdr(fx.viewer_sub), json={"keys": ["C1"], "properties": [name]},
        )
        assert r.status_code == 422, r.text
        assert "not a derived property" in r.json()["detail"]


def test_a_page_that_reaches_too_far_says_so_for_that_column_only(
    client, fx, world, monkeypatch
) -> None:
    """One column's chain reaching past the bound does not blank the others,
    and the column that did gets a sentence rather than some rows' values.

    North's three orders are inside a bound of three; the four join-table
    pairs they make are not - so this is the pairs' bound, counted before a
    single product is read."""
    _derive(client, fx, world["customer"], {
        "orders": (one_hop(world, aggregate="count"), "integer"),
        "products": (two_hops(world, aggregate="count"), "integer"),
    })
    monkeypatch.setattr(derived_values, "MAX_REACHED", 3)
    body = _page(client, fx, world["customer"], ["C1"], ["orders", "products"])
    assert list(body["errors"]) == ["products"]
    assert "more than 3 objects" in body["errors"]["products"]
    assert body["rows"] == [{"primary_key": "C1", "values": {"orders": 3}}]


def test_a_pair_in_the_join_table_twice_is_one_pair(client, fx, world, monkeypatch) -> None:
    """O2 and the Anvil appear twice in the join table; North's pairs are four,
    not five, so a bound of four answers."""
    _derive(client, fx, world["customer"], {
        "products": (two_hops(world, aggregate="count"), "integer"),
    })
    monkeypatch.setattr(derived_values, "MAX_REACHED", 4)
    body = _page(client, fx, world["customer"], ["C1"], ["products"])
    assert body == {"rows": [{"primary_key": "C1", "values": {"products": 3}}], "errors": {}}


def test_the_far_objects_are_bounded_too(client, fx, world, monkeypatch) -> None:
    _derive(client, fx, world["customer"], {
        "orders": (one_hop(world, aggregate="count"), "integer"),
    })
    monkeypatch.setattr(derived_values, "MAX_REACHED", 2)
    body = _page(client, fx, world["customer"], ["C1"], ["orders"])
    assert "more than 2 objects" in body["errors"]["orders"]


def test_a_link_deleted_under_a_derivation_is_a_sentence(client, fx, world) -> None:
    """Deleting a link type does not refuse over a derivation that follows it
    (only an action parameter holds one), so a saved chain can dangle - and the
    page says so for that column rather than failing."""
    spare = _link(client, fx, {
        "api_name": f"dv_spare{fx.tag}", "display_name": "Spare",
        "from_type_id": world["order"], "to_type_id": world["customer"],
        "cardinality": "one_to_many",
        "from_property": "customer_id", "to_property": "$primary_key"})
    _derive(client, fx, world["customer"], {
        "orders": (one_hop(world, aggregate="count"), "integer"),
        "spare_orders": ({"links": [{"link_type_id": spare}], "aggregate": "count"},
                         "integer"),
    })
    r = client.delete(f"{wbase(fx)}/link-types/{spare}", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text
    body = _page(client, fx, world["customer"], ["C1"], ["orders", "spare_orders"])
    assert "does not connect" in body["errors"]["spare_orders"]
    assert body["rows"] == [{"primary_key": "C1", "values": {"orders": 3}}]


def test_a_page_is_one_read_in_the_types_usage(client, fx, world) -> None:
    """p.32-33: counted once for the page, whatever its size, under the
    application that asked."""
    _derive(client, fx, world["customer"], {
        "orders": (one_hop(world, aggregate="count"), "integer"),
    })

    def reads() -> int:
        r = client.get(f"{wbase(fx)}/object-types/{world['customer']}/usage/by-application",
                       headers=hdr(fx.viewer_sub))
        return next((a["reads"] for a in r.json() if a["application"] == "workshop"), 0)

    before = reads()
    r = client.post(
        f"{wbase(fx)}/object-types/{world['customer']}/derived-values?application=workshop",
        headers=hdr(fx.viewer_sub),
        json={"keys": ["C1", "C2", "C3", "C4"], "properties": ["orders"]},
    )
    assert r.status_code == 200, r.text
    assert reads() == before + 1


def test_a_viewer_of_another_workspace_gets_nothing(client, fx, world) -> None:
    r = client.post(
        f"{wbase(fx)}/object-types/{world['customer']}/derived-values",
        headers=hdr(fx.outsider_sub), json={"keys": ["C1"], "properties": ["products"]},
    )
    assert r.status_code in (403, 404), r.text
