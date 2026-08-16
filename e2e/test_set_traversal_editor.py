"""Building a link traversal in the Variables panel (§155's builder half;
parity `workshop.md` §3.1).

The server side is tested in `apps/api`: a set can be the far side of a link,
in either direction. What needs a browser is that somebody can **draw** one —
the row was ◑ for exactly that reason, because a traversal had to be written
into the document by hand.

The claim under test is the whole chain: pick a base set, pick a link, save,
and the table bound to the derived set shows the linked objects rather than
all of them.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, eventually, open_module, settled

CUSTOMERS = [
    {"id": "C1", "name": "North Ltd", "region": "north"},
    {"id": "C2", "name": "South Ltd", "region": "south"},
]
# Two of C1's, one of C2's — so a traversal that ignored its base set would
# show three rows, and one that followed the wrong end would show customers.
ORDERS = [
    {"id": "O1", "customer_id": "C1", "total": "10"},
    {"id": "O2", "customer_id": "C1", "total": "20"},
    {"id": "O3", "customer_id": "C2", "total": "30"},
]


@pytest.fixture(scope="module")
def module(api):
    customers = Module(api, "Traversal")
    customer_type = customers.object_type(
        columns=["id", "name", "region"], rows=CUSTOMERS, key="id", title="name",
    )
    orders_mod = Module(api, "Traversal orders", beside=customers)
    order_type = orders_mod.object_type(
        columns=["id", "customer_id", "total"], rows=ORDERS, key="id", title="id",
    )
    api.call(
        "POST", f"/workspaces/{customers.workspace_id}/link-types",
        {
            "api_name": f"placed_by_{customers.tag}",
            "display_name": "Placed by",
            "from_type_id": order_type,
            "to_type_id": customer_type,
            "cardinality": "one_to_many",
            "from_property": "customer_id",
            "to_property": "$primary_key",
            # A side name names the end you *arrive at* (p.192, and
            # `ontology.links_for_type`): from an order you land on the
            # customer that placed it, and from a customer on their orders.
            "from_side_name": "Orders",
            "to_side_name": "Placed by",
        },
    )
    customers.order_type_id = order_type
    # What the picker will call the far end: a hop reads "<side> → <type>",
    # and a seeded type's display name is its module's tag.
    customers.orders_hop = f"Orders → Seed {orders_mod.tag}"
    customers.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_linked",
                          "columns": "id,total", "pageSize": 25},
            },
        }),
        "variables": {
            "v_customers": {
                "id": "v_customers", "kind": "object_set", "label": "Northern customers",
                "object_set": object_set(customer_type, [
                    {"property": "region", "op": "eq", "value": "north"},
                ]),
            },
            # Declared but not yet a traversal - the panel is what turns it
            # into one, which is the thing being tested.
            "v_linked": {
                "id": "v_linked", "kind": "object_set", "label": "Their orders",
                "object_set": object_set(order_type),
            },
        },
        "events": {},
    })
    return customers


def rows(page) -> int:
    return page.locator(".canvas-block table tbody tr").count()


def open_variable(page, module, label: str) -> None:
    page.goto(f"{WEB_BASE}{module.url}")
    expect(page.get_by_role("button", name="Preview", exact=True)).to_be_visible(
        timeout=30000
    )
    page.get_by_role("button", name="Variables", exact=False).first.click()
    # By text rather than by role: a variable row is a heading-and-detail
    # block, not a button, and the panel's own selects carry their options'
    # text into any accessible name computed from the surrounding label -
    # which is why the controls below are reached by test id.
    page.get_by_text(label, exact=True).first.click()


def test_a_traversal_can_be_drawn_and_it_narrows_the_table(page, module):
    """The chain: choose a base set, choose a link, save — and the table shows
    the northern customer's orders rather than every order."""
    open_module(page, module)
    eventually(lambda: rows(page), lambda n: n == len(ORDERS),
               what="every order, before the traversal is drawn")

    open_variable(page, module, "Their orders")
    page.get_by_test_id("set-source").select_option("followed")
    page.get_by_test_id("traversal-base").select_option(label="Northern customers")

    # The link picker is empty until a base set is chosen, because which links
    # apply depends on its type.
    link = page.get_by_test_id("traversal-link")
    expect(link).to_be_enabled()
    link.select_option(label=module.orders_hop)

    page.get_by_role("button", name="Save", exact=True).click()
    settled(page)

    open_module(page, module)
    eventually(lambda: rows(page), lambda n: n == 2,
               what="only the northern customer's orders")


def test_the_link_picker_waits_for_a_base_set(page, module):
    """Which links apply depends on the base set's type, so offering them
    before one is chosen would be offering hops that cannot exist."""
    open_variable(page, module, "Northern customers")
    page.get_by_test_id("set-source").select_option("followed")
    expect(page.get_by_test_id("traversal-link")).to_be_disabled()
    expect(page.locator(".vars-derivation")).to_contain_text(
        "which links apply depends on it"
    )


def test_both_ends_of_a_link_are_offered_and_they_land_apart(page, module):
    """A link between two types can be followed either way, and the two land
    somewhere different - so it appears once per end, named for that end."""
    open_variable(page, module, "Their orders")
    page.get_by_test_id("set-source").select_option("followed")
    page.get_by_test_id("traversal-base").select_option(label="Northern customers")
    options = page.get_by_test_id("traversal-link").locator("option")
    # Waited for rather than read straight off: the link types arrive from a
    # request, so counting options the moment the base is chosen counts an
    # empty picker and calls it a rule. One hop plus the placeholder - this
    # type is fresh, so the workspace's other links do not touch it.
    expect(options).to_have_count(2)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    # From a *customer* only one end applies: the orders. The other end is
    # offered when the base set is orders, which is the direction that lands
    # on the primary key.
    assert module.orders_hop in labels, labels
    assert not any("Placed by" in label for label in labels), labels
