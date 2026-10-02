"""p.450's union of object sets, end to end (§686): saved in a module, resolved
by the evaluate route, narrowed part by part, and each part read from the store.
The pure rules are `test_union_sets.py`'s."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import hdr  # noqa: E402
from test_canvas import _module, _new_app, base as app_base  # noqa: E402
from test_object_set_traversal import (  # noqa: E402,F401
    _fresh_identity_cache, client, evaluate, fx, linked,
)


def union_module(linked: dict) -> dict:
    def a_set(vid: str, type_id: str) -> dict:
        return {"id": vid, "kind": "object_set", "label": vid,
                "object_set": {"object_type_id": type_id, "filters": []}}

    return _module({
        "v_customers": a_set("v_customers", linked["customer_type"]),
        "v_orders": a_set("v_orders", linked["order_type"]),
        "v_all": {"id": "v_all", "kind": "object_set", "label": "Everything",
                  "derivation": {"transform": "union_set",
                                 "inputs": ["v_customers", "v_orders"]}},
        "v_filter": {"id": "v_filter", "kind": "object_set_filter", "label": "Filter"},
        "v_narrowed": {"id": "v_narrowed", "kind": "object_set", "label": "Narrowed",
                       "derivation": {"transform": "narrow_set",
                                      "inputs": ["v_all", "v_filter"]}},
    })


def resolved(client, fx, linked, clauses: list) -> dict:
    app_id = _new_app(client, fx)
    saved = client.put(f"{app_base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                       json={"definition": union_module(linked)})
    assert saved.status_code == 200, saved.text
    r = client.post(f"{app_base(fx)}/{app_id}/variables/evaluate",
                    headers=hdr(fx.viewer_sub), json={"values": {"v_filter": clauses}})
    assert r.status_code == 200, r.text
    return r.json()["values"]


def keys(client, fx, part: dict) -> list[str]:
    answer = evaluate(client, fx, part)
    assert answer["status"] == 200, answer
    return sorted(i["primary_key"] for i in answer["body"]["instances"])


def test_a_filter_narrows_every_type_in_the_union(client, fx, linked) -> None:
    """p.450: "all object types instances will be filtered". The key belongs to
    every type, so one clause on it reaches both parts."""
    values = resolved(client, fx, linked,
                      [{"property": "$primary_key", "op": "in", "value": ["C1", "O2"]}])
    customers, orders = values["v_narrowed"]["union"]
    assert customers["object_type_id"] == linked["customer_type"]
    assert keys(client, fx, customers) == ["C1"]
    assert keys(client, fx, orders) == ["O2"]
    # Unnarrowed, the union is each set whole.
    everyone, every_order = values["v_all"]["union"]
    assert keys(client, fx, everyone) == ["C1", "C2", "C3"]
    assert keys(client, fx, every_order) == ["O1", "O2", "O3"]


def test_a_property_one_type_lacks_leaves_that_type_nothing(client, fx, linked) -> None:
    """p.450's Single property. The route supplies the ontology, so a region
    clause is known to be the customers' alone - and an ordered clause on the
    orders' date is not refused against customers, who have none."""
    values = resolved(client, fx, linked,
                      [{"property": "region", "op": "eq", "value": "south"}])
    customers, orders = values["v_narrowed"]["union"]
    assert keys(client, fx, customers) == ["C2"]
    assert keys(client, fx, orders) == []
    values = resolved(client, fx, linked,
                      [{"property": "placed", "op": "gte", "value": "2024-02-01"}])
    customers, orders = values["v_narrowed"]["union"]
    assert keys(client, fx, customers) == []
    assert keys(client, fx, orders) == ["O2", "O3"]


def test_a_read_over_one_type_refuses_a_union_in_a_sentence(client, fx, linked) -> None:
    r = client.post(f"/api/workspaces/{fx.workspace}/object-sets/aggregate",
                    headers=hdr(fx.editor_sub), json={"definition": {"union": [
                        {"object_type_id": linked["customer_type"], "filters": []},
                        {"object_type_id": linked["order_type"], "filters": []},
                    ]}, "aggregation": "count"})
    assert r.status_code == 422, r.text
    assert "union of several object types" in r.json()["detail"]
