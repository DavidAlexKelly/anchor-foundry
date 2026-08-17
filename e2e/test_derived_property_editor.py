"""Building a derived property in the Ontology Manager (parity `ontology.md`
§1.2; Foundry `object-link-types` p.144-147).

§161 declared one and §162 answered it, both through the API. This is the last
piece: somebody drawing one. The claim under test is the whole chain - pick a
link, pick an aggregation, save, and open an object to find the answer
calculated.

The walk itself (which links are offered from where, whether a hop reaches
many) is unit-tested in `apps/web/src/lib/derived-property.test.ts`, because
that is where the direction of a `one_to_many` hop can actually be pinned. What
needs a browser is that the controls are wired to it and that a saved chain
reaches an object view.
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
# Lopsided on purpose, for §162's reason: C1 has three orders and C2 none, so
# "count" and "count the first one" and "empty" are three different answers.
ORDERS = [
    {"id": "O1", "customer_id": "C1", "total": "10"},
    {"id": "O2", "customer_id": "C1", "total": "20"},
    {"id": "O3", "customer_id": "C1", "total": "30"},
]


@pytest.fixture(scope="module")
def module(api):
    customers = Module(api, "Derived editor")
    customer_type = customers.object_type(
        columns=["id", "name"], rows=CUSTOMERS, key="id", title="name",
    )
    orders = Module(api, "Derived editor orders", beside=customers)
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
            # A side name names the end you arrive at, so from a customer the
            # hop reads "Orders".
            "from_side_name": "Orders",
            "to_side_name": "Placed by",
        },
    )
    customers.order_type_id = order_type
    customers.order_tag = orders.tag
    return customers


def open_type_editor(page, module):
    """This fixture's own type - the objects page lists every type in the
    workspace, so the row is found by api_name."""
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()


def open_customer(page, module, name: str) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(CUSTOMERS),
               what="this type's customers, and only this type's")
    rows.filter(has_text=name).first.get_by_role("button", name="Explore").click()
    expect(page.get_by_role("heading", name=name)).to_be_visible()


def add_property(page, name: str) -> int:
    """Append a property row and return its 1-based index."""
    page.get_by_role("button", name="Add property").click()
    boxes = page.get_by_role("textbox", name="Property")
    index = boxes.count()
    page.get_by_role("textbox", name=f"Property {index} name").fill(name)
    return index


def test_a_derived_property_can_be_drawn_and_it_answers(page, module) -> None:
    """The whole chain. p.145's dropdown offers the link from this type, the
    aggregation is demanded because a customer reaches many orders, and the
    saved property is calculated when the object is opened."""
    open_type_editor(page, module)
    index = add_property(page, "order_count")
    page.get_by_role("button", name=f"Property {index} derive").click()

    # p.145: "the dropdown menu shows all available link types from your
    # current object type", named for the end being travelled to.
    page.get_by_test_id("derive-add-hop").select_option(label="Orders → Seed " + module.order_tag)

    # p.145: a customer reaches many orders, so an aggregation is compulsory -
    # and the editor says so before Apply rather than letting the save refuse.
    expect(page.get_by_test_id("derive-problem")).to_contain_text("more than one object")
    expect(page.get_by_test_id("derive-save")).to_be_disabled()

    page.get_by_test_id("derive-aggregate").select_option("count")
    expect(page.get_by_test_id("derive-save")).to_be_enabled()
    page.get_by_test_id("derive-save").click()
    page.get_by_role("button", name="Save", exact=True).click()

    open_customer(page, module, "North Ltd")
    expect(page.locator("[data-property='order_count']")).to_contain_text("3")

    # And the customer with no orders gets 0 rather than a blank - the count
    # of an empty chain is a number.
    open_customer(page, module, "South Ltd")
    expect(page.locator("[data-property='order_count']")).to_contain_text("0")


def test_the_aggregations_this_platform_cannot_answer_are_not_offered(page, module) -> None:
    """p.145 lists nine. Four are refused by the server - sum, average, minimum
    and maximum on the untyped-property blocker, and approximate cardinality
    because the two stores would disagree about how approximate it is. Offering
    them would be offering a save that fails, so the list says what it can do
    and a hint says why the rest is missing."""
    open_type_editor(page, module)
    index = add_property(page, "unused_probe")
    page.get_by_role("button", name=f"Property {index} derive").click()
    page.get_by_test_id("derive-add-hop").select_option(
        label="Orders → Seed " + module.order_tag
    )

    options = page.get_by_test_id("derive-aggregate").locator("option")
    # Presence before absence: wait for the list to be there before asserting
    # what is not in it (§157's lesson).
    expect(options).to_have_count(5)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Count" in labels, labels
    for absent in ("Sum", "Average", "Minimum", "Maximum", "Approximate"):
        assert not any(absent in label for label in labels), labels
    expect(page.get_by_text("stored untyped", exact=False)).to_be_visible()


def test_a_chain_stops_at_three_links(page, module) -> None:
    """p.147: "up to 3 levels total". The fourth is not offered rather than
    refused on save - the picker disappearing is the rule being visible."""
    open_type_editor(page, module)
    index = add_property(page, "deep_probe")
    page.get_by_role("button", name=f"Property {index} derive").click()
    hop = "Orders → Seed " + module.order_tag
    back = "Placed by → Seed " + module.tag
    for label in (hop, back, hop):
        page.get_by_test_id("derive-add-hop").select_option(label=label)
    expect(page.get_by_test_id("derive-hop-3")).to_be_visible()
    expect(page.get_by_test_id("derive-add-hop")).to_have_count(0)


def test_an_unrelated_edit_does_not_clear_the_derivation(page, module) -> None:
    """**The third time this repo has recorded this failure** (§157, §160, and
    here). The edit dialog rebuilds every property from the type, so any
    setting it forgets to carry is silently reset by somebody changing a
    description - a loss with no error and no trace.

    Runs after the drawing test, so there is a derivation to lose.
    """
    open_type_editor(page, module)
    page.get_by_role("textbox", name="Description", exact=False).fill("Edited")
    page.get_by_role("button", name="Save", exact=True).click()

    open_customer(page, module, "North Ltd")
    expect(page.locator("[data-property='order_count']")).to_contain_text("3")
