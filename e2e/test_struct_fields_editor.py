"""Declaring a struct property's fields in the Ontology Manager (parity
`ontology.md` §1.1; Foundry `object-link-types` p.152–158; db 0064).

§245 built the `struct` type and deliberately kept it *off* the property-type
dropdown, on §214's rule: choosing it there would have produced a property the
server refuses, because the dropdown is not the whole declaration. This file is
the other half arriving — the type joins the list in the same commit as the
dialog that completes it.

Three things are worth a browser here, and the first is the one that decides
whether the rest matters:

* **the round trip** — a struct declared entirely through the dialog is stored
  as the server holds it, which is the only way to know the dialog and the API
  agree about a shape neither of them typechecks against the other;
* **the refusal, before the save** — p.149's "at least 1 field" answered where
  it can still be fixed rather than as a 422 with the dialog already closed;
* **p.158's rename warning**, which is the one piece of this dialog that is
  about consequences rather than about the form.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

ADDRESS = json.dumps({"street": "12 Main St", "postal_code": "N1 9GU", "floors": "3"})
CONTACT = json.dumps({"name": "A. Nother", "phone": "020 7946 0000"})

ADDRESS_FIELDS = [
    {"api_name": "street", "display_name": "Street", "data_type": "string"},
    {"api_name": "postal_code", "display_name": "Postal code", "data_type": "string"},
    {"api_name": "floors", "display_name": "Floors", "data_type": "integer"},
]


@pytest.fixture(scope="module")
def module(api):
    """Two struct-shaped columns in two different states, on purpose.

    `address` **is already declared** a struct, so the two tests that inspect
    the dialog have something to inspect; `contact` is still a string, so the
    test that walks p.152's flow has something real to convert.

    **They are separate columns because a test that only passes after another
    one is not a test.** The first version of this file had all three working
    on `address`, which meant the refusal and the rename both depended on the
    conversion above them having happened — and running either alone found a
    plain string property with no Fields button at all.
    """
    mod = Module(api, "Struct fields editor")
    mod.object_type(
        columns=["code", "address", "contact"],
        rows=[{"code": "A1", "address": ADDRESS, "contact": CONTACT}],
        key="code",
        title="code",
        types={"address": "struct"},
        struct_fields={"address": ADDRESS_FIELDS},
    )
    return mod


def properties(api, module) -> dict[str, dict]:
    detail = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )
    return {p["api_name"]: p for p in detail["properties"]}


def open_type_editor(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible()


def save_type(page) -> None:
    """Save the object type, acknowledging the impact when there is one.

    **Converting a property to a struct is a breaking change and the platform
    says so**, which is worth stating rather than working around: a retype is a
    delete plus an insert (0028), so every consumer of the old string property
    is a consumer of a property that no longer exists. The dialog turns Save
    into *Save anyway* behind an explicit tick, and this helper does what a
    person would.
    """
    acknowledge = page.get_by_role("checkbox", name="I understand, save it anyway")
    if acknowledge.count():
        acknowledge.check()
        page.get_by_role("button", name="Save anyway").click()
    else:
        page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)


def property_row(page, api_name: str) -> int:
    """Which numbered property row holds this property — the dialog labels its
    controls by position, and the fixture's column order is not this file's to
    assume."""
    names = page.get_by_role("textbox", name="Property")
    for index in range(names.count()):
        box = page.get_by_role("textbox", name=f"Property {index + 1} name")
        if box.input_value() == api_name:
            return index + 1
    raise AssertionError(f"no property row named {api_name!r}")


def test_a_struct_is_declared_entirely_through_the_dialog(page, api, module) -> None:
    """p.152's flow end to end: pick Struct from the Base type dropdown, name
    the fields, save the type, and find the declaration the server holds.

    **Read back from the API rather than from the dialog.** A dialog that
    showed the fields while having sent something else would look right and be
    the bug this test exists to exclude — the same reason §245's carry test
    asserts on what got stored.
    """
    open_type_editor(page, module)
    index = property_row(page, "contact")
    # A plain string property has no Fields button, because a property that
    # cannot have fields must not get a button that opens an empty dialog.
    expect(page.get_by_role("button", name=f"Property {index} fields")).to_have_count(0)

    page.get_by_role("combobox", name=f"Property {index} type").select_option("struct")
    page.get_by_role("button", name=f"Property {index} fields").click()
    expect(page.get_by_test_id("struct-field-rows")).to_be_visible()

    page.get_by_role("textbox", name="Field 1 name").fill("Name")
    # **By test id, like every other control in this dialog.** `get_by_role`
    # with a name is how the property rows above are reached, and it does not
    # resolve this button once a second dialog is open over the first — the
    # role query walks an accessibility tree that a nested dialog rearranges.
    # The dialog already identifies Apply and its problem line this way.
    page.get_by_test_id("struct-add-field").click()
    page.get_by_role("textbox", name="Field 2 name").fill("phone number")
    page.get_by_role("textbox", name="Field 2 label").fill("Phone")
    page.get_by_test_id("struct-add-field").click()
    page.get_by_role("textbox", name="Field 3 name").fill("floors")
    page.get_by_role("combobox", name="Field 3 type").select_option("integer")
    page.get_by_test_id("struct-save").click()

    # The count on the button is how somebody sees a struct is declared without
    # opening anything, and it is not decoration: a struct with no number is a
    # property the server will refuse.
    expect(page.get_by_role("button", name=f"Property {index} fields")).to_have_text(
        "Fields (3)"
    )
    save_type(page)

    eventually(
        lambda: properties(api, module)["contact"].get("struct_fields"),
        lambda f: f is not None and len(f) == 3,
        what="the declaration the server stored",
    )
    stored = properties(api, module)["contact"]["struct_fields"]
    # **Typed as it would be typed, not as it has to be stored.** "Name" and
    # "phone number" both go in the way somebody types them and come back as
    # field names, which is the normalisation the property row above already
    # applies one level up.
    assert [f["api_name"] for f in stored] == ["name", "phone_number", "floors"]
    assert [f["data_type"] for f in stored] == ["string", "string", "integer"]
    assert stored[1]["display_name"] == "Phone"


def test_a_struct_with_no_fields_is_refused_before_the_save(page, api, module) -> None:
    """p.149's "Structs must have at least 1 field", answered where it can
    still be fixed.

    The server refuses this too, and that refusal is the one that counts — but
    it arrives as a 422 after the dialog has closed and the form is gone. This
    is the same rule asked one layer earlier, which is the split
    `lib/struct-fields.ts` exists to make.
    """
    open_type_editor(page, module)
    index = property_row(page, "address")
    page.get_by_role("button", name=f"Property {index} fields").click()
    expect(page.get_by_test_id("struct-field-rows")).to_be_visible()

    # **Counted rather than assumed.** The removal loop used to run a fixed
    # three times against whatever the previous test had left behind, which is
    # how the order-dependence in this file's first version stayed hidden: the
    # count is the fixture's statement, and emptying the list is the state
    # p.149 refuses.
    #
    # Emptying it is also what found the layout hazard the dialog now guards
    # against: without the empty-state row, removing the last field collapsed
    # the table and slid *Add field* up into the ✕'s position, so the same
    # click landed on it — three clicks producing three removals *and* one add.
    rows = page.get_by_test_id("struct-field-rows").locator("tr[data-struct-field]")
    started = rows.count()
    assert started == len(ADDRESS_FIELDS)
    for remaining in range(started, 0, -1):
        expect(rows).to_have_count(remaining)
        # **`dispatch_event`, not `click`, and the reason is the finding.** A
        # real click carries a *position*, and removing a row moves whatever is
        # below it up into that position — so a repeated click at one point
        # walks down the page as the list shrinks. The dialog now keeps *Add
        # field* above the table so nothing it could land on adds anything
        # back, but a test that removes N rows by pointing at one place is
        # asserting about the layout rather than about p.149. This asks the
        # button directly; the position hazard is recorded where it belongs,
        # beside the button that used to sit underneath.
        rows.first.get_by_role("button").dispatch_event("click")
    expect(rows).to_have_count(0)
    expect(page.get_by_test_id("struct-no-fields")).to_be_visible()

    expect(page.get_by_test_id("struct-problem")).to_contain_text("at least one field")
    expect(page.get_by_test_id("struct-save")).to_be_disabled()


def test_renaming_a_field_says_what_it_will_cost(page, api, module) -> None:
    """p.158: *"changing a struct field's API name will result in a new struct
    field RID being generated … Any applications that reference the updated
    struct field will need to be updated as well."*

    This platform has no RID, and the consequence lands somewhere else: a
    stored value is a mapping keyed by field name, so after a rename every
    existing object still holds the old key and the field reads as empty until
    the next sync. **The warning names the fix**, which is the difference
    between a warning and a scolding.

    It also has to *not* appear the rest of the time, which is the half that
    makes it worth reading — so the dialog is opened and inspected before
    anything is typed.
    """
    open_type_editor(page, module)
    index = property_row(page, "address")
    page.get_by_role("button", name=f"Property {index} fields").click()
    expect(page.get_by_test_id("struct-field-rows")).to_be_visible()
    expect(page.get_by_test_id("struct-rename-warning")).to_have_count(0)

    page.get_by_role("textbox", name="Field 1 name").fill("road")

    warning = page.get_by_test_id("struct-rename-warning")
    expect(warning).to_contain_text("street")
    expect(warning).to_contain_text("synced again")
