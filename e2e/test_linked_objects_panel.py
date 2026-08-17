"""The last two capabilities of the Linked objects component (parity
`ontology.md` §4.1; Foundry `object-views` p.11).

p.11 lists four things the component is for. Two were built: viewing linked
objects grouped by link type (§18) and previewing their properties inline
without leaving the view (§145). These are the other two:

    "Open a subset of linked objects in a new tab for further exploration.
     Preview a selected linked object in the side panel of the standard
     Object View."

Where the URL *points* is unit-tested (`apps/web/src/lib/link-subset.test.ts`),
because a browser can only confirm it navigated somewhere. What needs a browser
is that the link is offered at all, that following it lands on the subset
rather than on every object of that type, and that the panel holds one object
beside the view instead of replacing it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

CUSTOMERS = [
    {"id": "C1", "name": "North Ltd"},
    {"id": "C2", "name": "South Ltd"},
]
# Two of C1's and one of C2's, so "the subset" and "every order" are different
# numbers - without that, opening the subset could be opening the lot.
ORDERS = [
    {"id": "O1", "customer_id": "C1", "total": "10"},
    {"id": "O2", "customer_id": "C1", "total": "20"},
    {"id": "O3", "customer_id": "C2", "total": "30"},
]


@pytest.fixture(scope="module")
def module(api):
    customers = Module(api, "Linked panel")
    customer_type = customers.object_type(
        columns=["id", "name"], rows=CUSTOMERS, key="id", title="name",
    )
    orders = Module(api, "Linked panel orders", beside=customers)
    order_type = orders.object_type(
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
            "from_side_name": "Orders",
            "to_side_name": "Placed by",
        },
    )
    customers.order_type_id = order_type
    return customers


def open_customer(page, module, name: str):
    """The Explorer filtered to the customer type, then into one customer."""
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(CUSTOMERS),
               what="this type's customers, and only this type's")
    rows.filter(has_text=name).first.get_by_role("button", name="Explore").click()
    expect(page.get_by_text("Linked objects", exact=True)).to_be_visible()


def test_the_subset_link_is_offered_and_opens_only_the_linked_objects(page, module):
    """p.11's third capability. The count is the claim: this customer has two
    orders and the type has three, so a link that opened "all orders" would be
    indistinguishable from a working one on any fixture where they matched."""
    open_customer(page, module, "North Ltd")
    subset = page.locator("[data-testid^='link-subset-']").first
    expect(subset).to_be_visible()
    # A new tab, because p.11 says so and because the point is *further*
    # exploration - taking the reader off the object they are standing on
    # would make the two exclusive.
    assert subset.get_attribute("target") == "_blank"

    with page.context.expect_page() as opened:
        subset.click()
    tab = opened.value
    rows = tab.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 2,
               what="this customer's two orders, not all three")
    expect(tab.locator("tbody")).to_contain_text("O1")
    expect(tab.locator("tbody")).not_to_contain_text("O3")
    tab.close()


def test_a_linked_object_opens_in_the_side_panel_without_leaving(page, module):
    """p.11's fourth capability. "Without leaving" is the whole distinction
    from traversal, so the evidence is what did *not* change: no breadcrumb
    trail appeared, and the dialog is still titled for the customer."""
    open_customer(page, module, "North Ltd")
    page.get_by_role("button", name="Show O1 in the side panel").click()

    panel = page.get_by_role("complementary", name="Linked object panel")
    expect(panel).to_be_visible()
    expect(panel).to_contain_text("O1")
    # Still on the customer: previewing is not traversing.
    expect(page.get_by_label("Traversal trail")).to_have_count(0)
    expect(page.get_by_text("Linked objects", exact=True)).to_be_visible()


def test_the_panel_holds_one_object_and_closes_again(page, module):
    """One, not a set - which is what makes it a different answer from the
    inline preview beside it, where several open at once on purpose."""
    open_customer(page, module, "North Ltd")
    page.get_by_role("button", name="Show O1 in the side panel").click()
    page.get_by_role("button", name="Show O2 in the side panel").click()

    panel = page.get_by_role("complementary", name="Linked object panel")
    expect(panel).to_have_count(1)
    expect(panel).to_contain_text("O2")
    expect(panel).not_to_contain_text("O1")

    # The same control both ways round.
    page.get_by_role("button", name="Show O2 in the side panel").click()
    expect(page.get_by_role("complementary", name="Linked object panel")).to_have_count(0)


def test_the_panel_does_not_survive_a_hop(page, module):
    """A panel still showing something linked to where you *were* is the
    wrong-context bug the trail exists to prevent, and it would be silent."""
    open_customer(page, module, "North Ltd")
    page.get_by_role("button", name="Show O1 in the side panel").click()
    expect(page.get_by_role("complementary", name="Linked object panel")).to_be_visible()

    # Traverse to that order - a different object, so a different set of links.
    page.get_by_role("button", name="O1", exact=False).first.click()
    expect(page.get_by_label("Traversal trail")).to_be_visible()
    expect(page.get_by_role("complementary", name="Linked object panel")).to_have_count(0)
