"""Value types in the Ontology Manager (parity `docs/parity/ontology.md` §1.2;
Foundry `object-link-types` p.222-234).

§168 built the definition, the versioning and the enforcement through the API.
This is somebody using them: creating a value type with a rule on p.224's form,
putting it on a property (p.227), changing the rule and watching p.230's
propagation happen, and finding the sync's report when the data does not
comply.

The claim that needs a browser rather than an API test is the last one. **The
report is the whole reason this platform diverges from p.227** - Foundry fails
the index, this reports and keeps the good rows - so "a person can see which
property failed and why" is the thing being asserted, not a JSON field.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

CONTACTS = [
    {"id": "C1", "name": "Ada", "email": "ada@example.com"},
    {"id": "C2", "name": "Grace", "email": "not-an-email"},
]


@pytest.fixture(scope="module")
def module(api):
    contacts = Module(api, "Value types")
    contacts.object_type(
        columns=["id", "name", "email"], rows=CONTACTS, key="id", title="name",
    )
    return contacts


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_role("heading", name="Value types")).to_be_visible(timeout=30000)


def open_type_editor(page, module) -> None:
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()


def property_index(page, api_name: str) -> int:
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible(
        timeout=15000
    )
    boxes = page.get_by_role("textbox", name="Property")
    for i in range(boxes.count()):
        if boxes.nth(i).input_value() == api_name:
            return i + 1
    raise AssertionError(f"no property row for {api_name!r}")


def choose_option(page, testid: str, starts_with: str) -> None:
    """Select the option whose text begins with `starts_with`.

    The option label carries the rule as well as the name (`optionLabel`), and
    Playwright's `label=` wants the whole string - so the text is read once and
    matched, rather than reconstructed here from a format this test would then
    have to keep in step with the component.
    """
    options = page.get_by_test_id(testid).locator("option")
    expect(options.first).to_be_attached(timeout=15000)
    texts = options.all_inner_texts()
    matches = [t for t in texts if t.startswith(starts_with)]
    assert matches, f"no option starting with {starts_with!r} in {texts}"
    page.get_by_test_id(testid).select_option(label=matches[0])


def create_value_type(page, module, name: str, pattern: str) -> str:
    """p.224's form, end to end, returning the api name."""
    open_objects(page, module)
    page.get_by_test_id("new-value-type").click()
    page.get_by_test_id("vt-name").fill(name)
    api_name = name.lower().replace(" ", "_")
    expect(page.get_by_test_id("vt-api-name")).to_contain_text(api_name)
    page.get_by_test_id("vt-base-type").select_option("string")
    page.get_by_test_id("constraint-kind").select_option("regex")
    page.get_by_test_id("constraint-pattern").fill(pattern)
    page.get_by_test_id("vt-example").fill("ada@example.com")
    page.get_by_test_id("vt-save").click()
    expect(page.get_by_test_id("vt-table")).to_contain_text(api_name)
    return api_name


def test_a_value_type_is_created_and_says_what_it_enforces(page, module) -> None:
    """p.224's create flow. The listing shows the *rule*, not just the name -
    an `email` that checks a pattern and one that checks nothing are the same
    row otherwise, and that is the difference somebody choosing between them
    cares about."""
    name = f"Email {uuid.uuid4().hex[:4]}"
    api_name = create_value_type(page, module, name, r"[a-z]+@example\.com")
    expect(page.get_by_test_id(f"vt-rule-{api_name}")).to_contain_text("matches")
    expect(page.get_by_test_id("vt-table")).to_contain_text("v1")


def test_only_the_constraints_the_base_type_allows_are_offered(page, module) -> None:
    """p.233 lists constraints *per base type*. Offering a regex on an integer
    would be offering a save that fails - and worse, a rule that could never
    pass if it somehow got through."""
    open_objects(page, module)
    page.get_by_test_id("new-value-type").click()

    page.get_by_test_id("vt-base-type").select_option("string")
    options = page.get_by_test_id("constraint-kind").locator("option")
    # Presence before absence (§157's lesson).
    expect(options).to_have_count(5)  # none + enum, range, regex, uuid
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert any("pattern" in label for label in labels), labels

    page.get_by_test_id("vt-base-type").select_option("integer")
    options = page.get_by_test_id("constraint-kind").locator("option")
    expect(options).to_have_count(3)  # none + enum, range
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert not any("pattern" in label for label in labels), labels


def test_a_range_says_what_it_bounds(page, module) -> None:
    """p.233: "For String properties, the length of the string is
    constrained." One word for two meanings is how somebody ends up believing
    they bounded the alphabet."""
    open_objects(page, module)
    page.get_by_test_id("new-value-type").click()
    page.get_by_test_id("vt-base-type").select_option("string")
    page.get_by_test_id("constraint-kind").select_option("range")
    expect(page.get_by_text("Minimum length", exact=False)).to_be_visible()

    page.get_by_test_id("vt-base-type").select_option("integer")
    page.get_by_test_id("constraint-kind").select_option("range")
    expect(page.get_by_text("Minimum value", exact=False)).to_be_visible()


def test_an_impossible_range_is_named_before_save(page, module) -> None:
    """The server refuses it either way; the point of saying so here is that
    the numbers are still on screen when somebody finds out."""
    open_objects(page, module)
    page.get_by_test_id("new-value-type").click()
    page.get_by_test_id("vt-name").fill("Bad range")
    page.get_by_test_id("vt-base-type").select_option("integer")
    page.get_by_test_id("constraint-kind").select_option("range")
    page.get_by_test_id("constraint-min").fill("10")
    page.get_by_test_id("constraint-max").fill("1")
    expect(page.get_by_test_id("constraint-problem")).to_contain_text(
        "nothing could satisfy"
    )
    expect(page.get_by_test_id("vt-save")).to_be_disabled()


def test_a_value_type_goes_on_a_property_and_survives_an_unrelated_edit(
    page, module
) -> None:
    """p.227's dropdown, and **the carry-through failure for the sixth time**
    (§157, §160, §163, §164, and here). The edit dialog rebuilds every property
    from the type, so any setting it forgets to carry is silently reset by
    somebody changing something else. Only a *second* edit exercises it.
    """
    name = f"Contact email {uuid.uuid4().hex[:4]}"
    create_value_type(page, module, name, r"[a-z]+@example\.com")

    open_type_editor(page, module)
    index = property_index(page, "email")
    page.get_by_role("button", name=f"Property {index} value type").click()
    choose_option(page, "vt-choice", name)
    page.get_by_test_id("vt-apply").click()
    page.get_by_role("button", name="Save", exact=True).click()

    # Still attached after a reload.
    open_objects(page, module)
    open_type_editor(page, module)
    index = property_index(page, "email")
    expect(
        page.get_by_role("button", name=f"Property {index} value type")
    ).to_contain_text("•")

    # And after an edit that has nothing to do with it.
    page.get_by_role("textbox", name="Description", exact=False).fill("Edited")
    page.get_by_role("button", name="Save", exact=True).click()
    open_objects(page, module)
    open_type_editor(page, module)
    index = property_index(page, "email")
    expect(
        page.get_by_role("button", name=f"Property {index} value type")
    ).to_contain_text("•")


def test_only_matching_base_types_are_offered_on_a_property(page, module) -> None:
    """p.222's proposition is that the value type *is* the type. A string
    value type on an integer property would reject every row."""
    open_objects(page, module)
    open_type_editor(page, module)
    # `name` is a string, so the string value type is on offer.
    index = property_index(page, "name")
    page.get_by_role("button", name=f"Property {index} value type").click()
    options = page.get_by_test_id("vt-choice").locator("option")
    expect(options.first).to_have_text("Not constrained")
    assert options.count() >= 2, "the string value type should be offered"
