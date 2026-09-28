"""Derived properties as Object Table columns (§604; `object-link-types`
p.143, `workshop` p.169).

A derived property is calculated from an object's links, so a list read has
never carried one, and a table showing one drew an empty column. §604 answers a
page of them in one read per hop. What needs a browser is that the table asks
**once for the page** - not once per row, which is the cost that kept the
column empty - and draws each row's own answer, a zero as a zero and nothing as
the table's empty.

That the page's answers are the single read's answers is
`apps/api/tests/test_derived_values.py`, row by row.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, open_module

CUSTOMERS = [
    {"id": "C1", "name": "North"},
    {"id": "C2", "name": "South"},
]
ORDERS = [
    {"id": "O1", "customer_id": "C1", "total": "10"},
    {"id": "O2", "customer_id": "C1", "total": "20"},
    {"id": "O3", "customer_id": "C1", "total": "30"},
]


@pytest.fixture(scope="module")
def world(api):
    customers = Module(api, "Derived columns")
    customer_type = customers.object_type(
        columns=["id", "name"], rows=CUSTOMERS, key="id", title="name")
    orders = Module(api, "Derived columns orders", beside=customers)
    order_type = orders.object_type(
        columns=["id", "customer_id", "total"], rows=ORDERS, key="id", title="id",
        types={"total": "integer"})
    ws = f"/workspaces/{customers.workspace_id}"
    link = api.call("POST", f"{ws}/link-types", {
        "api_name": f"dc_placed_{customers.tag}", "display_name": "Placed by",
        "from_type_id": order_type, "to_type_id": customer_type,
        "cardinality": "one_to_many",
        "from_property": "customer_id", "to_property": "$primary_key"})
    detail = api.call("GET", f"{ws}/object-types/{customer_type}")
    chain = [{"link_type_id": link["id"]}]
    api.call("PATCH", f"{ws}/object-types/{customer_type}", {
        "display_name": detail["display_name"],
        "properties": [dict(p) for p in detail["properties"]] + [
            {"api_name": "order_count", "display_name": "Orders", "data_type": "integer",
             "derivation": {"links": chain, "aggregate": "count"}},
            {"api_name": "average_total", "display_name": "Average total",
             "data_type": "float",
             "derivation": {"links": chain, "aggregate": "avg", "property": "total"}},
        ],
        "title_property": detail.get("title_property")})
    customers.customer_type_id = customer_type
    customers.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_all",
                          "columns": "name,order_count,average_total",
                          "pageSize": 25, "activeVariable": None, "autoSelect": False},
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(customer_type)},
        },
        "events": {},
    })
    return customers


def test_a_derived_column_is_filled_in_by_one_read_for_the_page(page, world):
    reads = []
    page.on("request", lambda r: reads.append(r) if "/derived-values" in r.url else None)
    open_module(page, world)

    expect(page.get_by_test_id("derived-C1-order_count")).to_have_text("3", timeout=15000)
    expect(page.get_by_test_id("derived-C1-average_total")).to_contain_text("20")
    # South placed none: a count of nothing is 0, and an average of nothing is
    # no average - drawn as the table's empty, not as 0.
    expect(page.get_by_test_id("derived-C2-order_count")).to_have_text("0")
    south = page.get_by_test_id("derived-C2-average_total")
    expect(south).to_have_attribute("data-state", "value")
    expect(south).not_to_contain_text("0")

    # Both columns and both rows, in one request - counted as Workshop's
    # read (p.33's "in which Foundry applications").
    assert len(reads) == 1, [r.url for r in reads]
    assert "application=workshop" in reads[0].url
    body = json.loads(reads[0].post_data or "{}")
    assert sorted(body["keys"]) == ["C1", "C2"]
    assert body["properties"] == ["order_count", "average_total"]


def test_a_column_the_page_cannot_answer_says_why_once(page, world):
    """The server's sentence for a chain that reached too far, above the table
    rather than in every cell - and the other column still answered."""
    def too_far(route):
        response = route.fetch()
        answer = response.json()
        answer["errors"] = {"average_total": "this page's rows reach too far"}
        for row in answer["rows"]:
            row["values"].pop("average_total", None)
        route.fulfill(response=response, json=answer)

    page.route("**/derived-values*", too_far)
    open_module(page, world)
    expect(page.get_by_test_id("derived-error-average_total")).to_have_text(
        "Average total: this page's rows reach too far", timeout=15000)
    expect(page.get_by_test_id("derived-C1-average_total")).to_have_attribute(
        "data-state", "error")
    expect(page.get_by_test_id("derived-C1-order_count")).to_have_text("3")


def test_the_types_own_list_fills_them_in_too(page, world):
    """The objects page's list of a type's instances draws every property, so
    it has the same column - read as the Ontology Manager, which p.32 leaves
    out of a type's usage."""
    reads = []
    page.on("request", lambda r: reads.append(r) if "/derived-values" in r.url else None)
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects/"
              f"{world.customer_type_id}")
    expect(page.get_by_test_id("derived-C1-order_count")).to_have_text("3", timeout=30000)
    expect(page.get_by_test_id("derived-C2-order_count")).to_have_text("0")
    expect(page.get_by_test_id("derived-C1-average_total")).to_contain_text("20")
    assert len(reads) == 1 and "application=ontology_manager" in reads[0].url
