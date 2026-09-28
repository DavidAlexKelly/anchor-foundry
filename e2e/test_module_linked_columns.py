"""p.169's Linked property/aggregation, declared by a module (§605; parity
`workshop.md` §9; Foundry workshop p.168-172).

> "Linked property: allows users to derive a single property from a linked
> object type… Linked aggregation: allows users to aggregate linked
> properties" (p.169)

The chain is the one an ontology derived property holds, answered by §604's
read - `apps/api/tests/test_derived_values.py` holds a module's chain to the
same answer as the type's. What needs a browser is the seam: a chain on the
module document becoming a column, **column math over it** (p.170: "aggregation
type derived properties may be used and referenced"), and one drawn in the
Settings panel with the ontology's own chain editor.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

CUSTOMERS = [{"id": "C1", "name": "North"}, {"id": "C2", "name": "South"}]
ORDERS = [
    {"id": "O1", "customer_id": "C1", "total": "10"},
    {"id": "O2", "customer_id": "C1", "total": "20"},
    {"id": "O3", "customer_id": "C1", "total": "30"},
]


@pytest.fixture(scope="module")
def world(api):
    customers = Module(api, "Linked columns")
    customer_type = customers.object_type(
        columns=["id", "name"], rows=CUSTOMERS, key="id", title="name")
    orders = Module(api, "Linked columns orders", beside=customers)
    order_type = orders.object_type(
        columns=["id", "customer_id", "total"], rows=ORDERS, key="id", title="id",
        types={"total": "integer"})
    link = api.call("POST", f"/workspaces/{customers.workspace_id}/link-types", {
        "api_name": f"lc_placed_{customers.tag}", "display_name": "Placed by",
        "from_type_id": order_type, "to_type_id": customer_type,
        "cardinality": "one_to_many",
        "from_property": "customer_id", "to_property": "$primary_key",
        "from_side_name": "Orders", "to_side_name": "Placed by"})
    return {"api": api, "customers": customers, "customer_type": customer_type,
            "order_type": order_type, "link": link["id"], "order_tag": orders.tag}


def module(world, name: str, columns: str, declared: list | None):
    mod = Module(world["api"], name, beside=world["customers"])
    definition = {
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": columns,
                              "pageSize": 25, "activeVariable": None,
                              "autoSelect": False}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Customers",
                      "object_set": object_set(world["customer_type"])},
        },
        "events": {},
    }
    if declared is not None:
        definition["derived_properties"] = {world["customer_type"]: declared}
    mod.define(definition)
    return mod


def chain(world, **rest) -> dict:
    return {"links": [{"link_type_id": world["link"]}], **rest}


def test_linked_columns_and_column_math_over_them(page, world):
    mod = module(world, "Linked columns read", "name,m_avg,per_order", [
        {"api_name": "m_orders", "kind": "linked",
         "derivation": chain(world, aggregate="count")},
        {"api_name": "m_avg", "kind": "linked",
         "derivation": chain(world, aggregate="avg", property="total")},
        {"api_name": "per_order", "kind": "column_math",
         "expression": "m_avg * m_orders"},
    ])
    reads = []
    page.on("request", lambda r: reads.append(r) if "/derived-values" in r.url else None)
    open_module(page, mod)

    expect(page.get_by_test_id("derived-C1-m_avg")).to_have_text("20", timeout=15000)
    # **m_orders is not a column here**, and per_order still has it: the table
    # asks for what a shown expression references, not only what is shown.
    row = page.locator("tbody tr").filter(has_text="North").first
    expect(row.locator('[data-derived="per_order"]')).to_have_text("60")
    # South placed nothing: no average, so no product either - not 0.
    south = page.locator("tbody tr").filter(has_text="South").first
    expect(page.get_by_test_id("derived-C2-m_avg")).to_have_attribute("data-state", "value")
    assert south.locator('[data-derived="per_order"]').inner_text().strip() != "0"

    assert len(reads) == 1, [r.url for r in reads]
    body = json.loads(reads[0].post_data or "{}")
    assert sorted(body["derivations"]) == ["m_avg", "m_orders"]
    assert body["properties"] == []


def test_a_linked_column_drawn_in_the_panel(page, world):
    """p.168's order - the type, then the column - and p.169's chain built with
    the ontology's own editor, saved, and answered for a reader."""
    mod = module(world, "Linked columns panel", "name,m_built", None)
    open_builder(page, mod)
    settled(page)
    picker = page.get_by_test_id("derived-type")
    eventually(lambda: picker.locator("option").count(), lambda n: n >= 2,
               what="the object types this module reads")
    picker.select_option(index=1)
    page.get_by_test_id("derived-add-linked").click()
    page.get_by_test_id("derived-name-1").fill("m_built")
    # Named and not built: said, rather than a column that silently draws
    # nothing.
    expect(page.get_by_test_id("derived-problem-1")).to_contain_text("Build the chain")
    expect(page.get_by_test_id("derived-chain-1")).to_have_text("not built yet")

    page.get_by_test_id("derived-chain-1").click()
    page.get_by_test_id("derive-add-hop").select_option(
        label=f"Orders → Seed {world['order_tag']}")
    page.get_by_test_id("derive-aggregate").select_option("count")
    page.get_by_test_id("derive-save").click()
    expect(page.get_by_test_id("derived-chain-1")).to_have_text("count over 1 link")
    expect(page.get_by_test_id("derived-problem-1")).to_have_count(0)
    save(page)

    open_module(page, mod)
    expect(page.get_by_test_id("derived-C1-m_built")).to_have_text("3", timeout=15000)
    expect(page.get_by_test_id("derived-C2-m_built")).to_have_text("0")
