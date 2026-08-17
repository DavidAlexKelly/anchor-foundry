"""Shared properties in the Ontology Manager (parity `docs/parity/ontology.md`
§1.2; Foundry `object-link-types` p.178-191).

§164 built the definition and the attachment through the API. This is somebody
using them: creating one on p.180's page, attaching a property to it on p.187's
dropdown, and finding the two things p.188 promises - the globe, and the
inherited fields disabled.

The claim that needs a browser rather than an API test is the last one. "Direct
edits to inherited metadata will be disabled" is a *form* statement; the API's
refusal is what makes it true rather than polite, and a form that lets somebody
type into a field the save will reject is a worse experience than one that
never offered it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

PEOPLE = [
    {"id": "P1", "name": "Ada", "began": "2020-01-05"},
    {"id": "P2", "name": "Grace", "began": "2021-06-30"},
]


@pytest.fixture(scope="module")
def module(api):
    people = Module(api, "Shared props")
    # `began` is a real date, because p.181's base-type rule is one of the
    # things under test - a string column could not tell a matching shared
    # property from a non-matching one.
    people.object_type(
        columns=["id", "name", "began"], rows=PEOPLE, key="id", title="name",
        types={"began": "date"},
    )
    return people


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_role("heading", name="Shared properties")).to_be_visible(
        timeout=30000
    )


def open_type_editor(page, module) -> None:
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()


def create_shared(page, module, name: str, base_type: str = "date") -> str:
    """Create one through p.181's modal and return its api_name."""
    open_objects(page, module)
    page.get_by_test_id("new-shared-property").click()
    page.get_by_test_id("shared-name").fill(name)
    page.get_by_test_id("shared-type").select_option(base_type)
    page.get_by_test_id("shared-description").fill("The day they began working")
    api_name = name.lower().replace(" ", "_")
    # p.181's own flow: the API name is derived and shown before saving.
    expect(page.get_by_test_id("shared-api-name")).to_contain_text(api_name)
    page.get_by_test_id("shared-save").click()
    expect(page.get_by_test_id("shared-table")).to_contain_text(api_name)
    return api_name


def property_index(page, api_name: str) -> int:
    """The 1-based row index of a property in the edit dialog, since every
    control is labelled by position.

    Waits for the row to be there before reading, rather than counting an
    empty list the instant the dialog opens - the torn-read failure `STATUS.md`
    records, which shows up as "no property row" rather than as a timeout.
    """
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible(
        timeout=15000
    )
    boxes = page.get_by_role("textbox", name="Property")
    for i in range(boxes.count()):
        if boxes.nth(i).input_value() == api_name:
            return i + 1
    raise AssertionError(f"no property row for {api_name!r}")


def test_a_shared_property_can_be_created_and_attached(page, module) -> None:
    """The whole path: p.180's page, p.181's modal, p.187's dropdown, and
    p.178's globe on the property afterwards."""
    name = f"Start date {uuid.uuid4().hex[:4]}"
    api_name = create_shared(page, module, name)

    open_objects(page, module)
    open_type_editor(page, module)
    index = property_index(page, "began")
    page.get_by_role("button", name=f"Property {index} shared").click()

    # p.187: "Use the dropdown menu to select an existing shared property".
    page.get_by_test_id("shared-choice").select_option(label=f"{name} ({api_name})")
    page.get_by_test_id("shared-apply").click()

    # p.178: "Shared properties on objects are denoted with a globe icon next
    # to their name."
    expect(page.get_by_label(f"Property {index} is shared")).to_be_visible()
    page.get_by_role("button", name="Save", exact=True).click()

    # And it is still attached after a reload, which is the half a form-only
    # implementation would fail.
    open_objects(page, module)
    open_type_editor(page, module)
    expect(page.get_by_label(f"Property {property_index(page, 'began')} is shared")).to_be_visible()


def test_the_inherited_controls_are_disabled_while_attached(page, module) -> None:
    """p.188: "While associated with a shared property, direct edits to
    property metadata that is inherited from the shared property will be
    disabled."

    Runs after the attaching test, so there is an attachment to be disabled by.
    The API refuses these edits too (§164) - this is what stops somebody
    meeting that refusal by surprise, after typing.
    """
    open_objects(page, module)
    open_type_editor(page, module)
    index = property_index(page, "began")
    expect(page.get_by_label(f"Property {index} visibility")).to_be_disabled()
    expect(page.get_by_role("button", name=f"Property {index} format")).to_be_disabled()
    # A property that is *not* attached is untouched by any of this.
    other = property_index(page, "name")
    expect(page.get_by_label(f"Property {other} visibility")).to_be_enabled()


def test_editing_the_shared_property_renames_it_on_the_object_type(page, module) -> None:
    """p.178's reason to exist: "update start date metadata in one place
    instead of on each object type"."""
    open_objects(page, module)
    row = page.get_by_test_id("shared-table").locator("tbody tr").first
    api_name = row.locator(".slug").inner_text()
    row.get_by_role("button", name=f"Edit {api_name}").click()
    page.get_by_test_id("shared-name").fill("Renamed once")
    page.get_by_test_id("shared-visibility").select_option("prominent")
    page.get_by_test_id("shared-save").click()

    # **Waiting on the refetch is the assertion, not a delay.** Editing a
    # shared property has to invalidate every object type *detail* in the
    # cache, keyed per type - and the queries are inactive while no dialog is
    # open, so the refetch happens when this one mounts. `staleTime` is 15s
    # (`providers.tsx`), so without the invalidation the dialog is served the
    # metadata from before the edit and no request is made at all: this times
    # out rather than racing.
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "GET"
    ):
        open_type_editor(page, module)
    index = property_index(page, "began")
    expect(page.get_by_label(f"Property {index} visibility")).to_have_value("prominent")


def test_a_base_type_that_does_not_match_is_not_offered(page, module) -> None:
    """p.181 requires the base types to match, so offering a `date` shared
    property for a `string` column would be offering a save that fails - the
    same rule the derived-property editor follows about links."""
    open_objects(page, module)
    open_type_editor(page, module)
    index = property_index(page, "name")  # a string property
    page.get_by_role("button", name=f"Property {index} shared").click()
    options = page.get_by_test_id("shared-choice").locator("option")
    # Presence before absence (§157's lesson): wait for the list to render
    # before asserting what is not in it.
    expect(options.first).to_have_text("Not shared")
    assert options.count() == 1, [
        options.nth(i).inner_text() for i in range(options.count())
    ]
    expect(page.get_by_text("is a string", exact=False)).to_be_visible()


def test_usage_names_the_object_type_and_the_property(page, module) -> None:
    """p.191's Usage. Reached from the count on the row, because the moment
    somebody wants it is the moment before they press Delete."""
    open_objects(page, module)
    row = page.get_by_test_id("shared-table").locator("tbody tr").first
    api_name = row.locator(".slug").inner_text()
    row.get_by_role("button", name=f"Usage of {api_name}").click()
    table = page.get_by_test_id("shared-usage-table")
    expect(table).to_contain_text(f"Seed {module.tag}")
    # p.188 lets the two names differ, so the row says which property it is.
    expect(table).to_contain_text("began")


def test_deleting_a_shared_property_leaves_the_property_behind(page, module) -> None:
    """p.185: "When a shared property is deleted, all object types using this
    shared property will revert to regular properties."

    **Not a cascade**, and this is the test that would catch one: the property
    is still on the object type afterwards, with the name it inherited, and
    editable again.

    Runs last, because it removes what the tests above are about.
    """
    open_objects(page, module)
    row = page.get_by_test_id("shared-table").locator("tbody tr").first
    api_name = row.locator(".slug").inner_text()
    row.get_by_role("button", name=f"Delete {api_name}").click()
    expect(page.get_by_test_id("shared-table")).not_to_contain_text(api_name)

    # Same reason as the rename test: the revert happens in the database, and
    # this refetch is what makes it visible without a reload.
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "GET"
    ):
        open_type_editor(page, module)
    index = property_index(page, "began")
    expect(page.get_by_label(f"Property {index} is shared")).to_have_count(0)
    # p.188's disabling is gone with the association it came from.
    expect(page.get_by_label(f"Property {index} visibility")).to_be_enabled()
