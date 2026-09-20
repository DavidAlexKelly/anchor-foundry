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
from ontology_page import find_type_row

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
        # **Declared**, because §406's arithmetic aggregations run on the
        # declaration rather than on what the values look like. An untyped
        # `total` is the state this platform was in before §220, and it is what
        # the refusal §406 removed used to be about.
        types={"total": "integer"},
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
    row = find_type_row(page, f"seed_{module.tag}")
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


def test_eight_of_p145s_nine_aggregations_are_offered(page, module) -> None:
    """p.145 lists nine and this platform offers eight.

    **This test asserted four more absences until §406.** It read "sum,
    average, minimum and maximum on the untyped-property blocker" and checked
    for a hint saying "stored untyped" - a sentence that was true when it was
    written and untrue from §220, which typed the properties, and §226, which
    answered those four over an object set. The test was a faithful record of
    a refusal nobody had re-read.

    `approx_cardinality` is still absent, and its reason has not moved:
    OpenSearch approximates where Postgres is exact, so it is a difference
    between the two stores rather than a gap here.
    """
    open_type_editor(page, module)
    index = add_property(page, "unused_probe")
    page.get_by_role("button", name=f"Property {index} derive").click()
    page.get_by_test_id("derive-add-hop").select_option(
        label="Orders → Seed " + module.order_tag
    )

    options = page.get_by_test_id("derive-aggregate").locator("option")
    # Presence before absence: wait for the list to be there before asserting
    # what is not in it (§157's lesson, §318's rule).
    expect(options).to_have_count(9)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    for present in ("Count", "Sum", "Average", "Minimum", "Maximum"):
        assert any(present in label for label in labels), labels
    assert not any("Approximate" in label for label in labels), labels
    # And the hint now names the one thing that is missing, rather than a
    # blocker that no longer exists.
    expect(page.get_by_text("Approximate cardinality is not available",
                            exact=False)).to_be_visible()
    expect(page.get_by_text("stored untyped", exact=False)).to_have_count(0)


def test_the_property_picker_narrows_for_arithmetic(page, module) -> None:
    """p.169's rule and §226's, in the control that has to enforce both.

    `sum` runs on a declared `integer` or `float`; `customer_id` is a string
    and `id` is the key, so offering them to a sum would be offering a save
    that fails. **Two lists, and this is the assertion that they are two** -
    the same check `test_metric_card.py` makes of the Metric Card's picker,
    because it is the same rule in a second place.
    """
    open_type_editor(page, module)
    index = add_property(page, "unused_probe2")
    page.get_by_role("button", name=f"Property {index} derive").click()
    page.get_by_test_id("derive-add-hop").select_option(
        label="Orders → Seed " + module.order_tag
    )

    picker = page.get_by_test_id("derive-property").locator("option")
    # A collection takes anything, which is the wide list.
    page.get_by_test_id("derive-aggregate").select_option("collect_list")
    eventually(lambda: picker.count(), lambda n: n > 2,
               what="every property of the linked type")
    # Lower-cased on the way in: the options carry *display* names, which the
    # seeder title-cases ("Total", "Customer_Id"), so matching the api name
    # verbatim finds nothing - which is how this first failed.
    wide = {picker.nth(i).inner_text().lower() for i in range(picker.count())}
    assert any("total" in label for label in wide), wide
    assert any("customer_id" in label for label in wide), wide

    page.get_by_test_id("derive-aggregate").select_option("sum")
    eventually(
        lambda: {picker.nth(i).inner_text().lower() for i in range(picker.count())},
        lambda got: not any("customer_id" in label for label in got),
        what="the string property to drop out of the list",
    )
    narrow = {picker.nth(i).inner_text().lower() for i in range(picker.count())}
    assert any("total" in label for label in narrow), narrow
    assert narrow < wide, (narrow, wide)


def test_p143s_own_first_example_can_be_built_and_answers(page, module) -> None:
    """"A Department object type could have a derived property for 'Average
    employee salary'" - the shape p.143 leads with, and the one this platform
    refused until §406.

    Here it is a customer's average order total: C1 has orders of 10, 20 and
    30, so the answer is 20 - **a number none of the three orders carries**,
    which is what separates an average from a first-value read.
    """
    open_type_editor(page, module)
    index = add_property(page, "avg_order")
    page.get_by_role("button", name=f"Property {index} derive").click()
    page.get_by_test_id("derive-add-hop").select_option(
        label="Orders → Seed " + module.order_tag
    )
    page.get_by_test_id("derive-aggregate").select_option("avg")
    page.get_by_test_id("derive-property").select_option("total")
    page.get_by_test_id("derive-save").click()
    page.get_by_role("button", name="Save").first.click()
    expect(page.get_by_text("Saved", exact=False).first).to_be_visible()

    open_customer(page, module, "North Ltd")
    eventually(lambda: page.get_by_text("avg_order", exact=False).count(),
               lambda n: n >= 1, what="the derived property on the object view")
    expect(page.get_by_text("20", exact=True).first).to_be_visible()


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
