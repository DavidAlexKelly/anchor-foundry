"""Declaring an array property in the Ontology Manager (parity `ontology.md`
§1.1; Foundry `object-link-types` p.86, p.140; db 0087).

§346 built the `array` type and deliberately kept it *off* the property-type
dropdown, on §214's rule and §245's precedent: choosing it there would have
produced a property the server refuses, because an array's declaration is not
finished until it says what it is a list of. This file is the other half
arriving — the type joins the list in the same commit as the control that
completes it.

Three things need a browser, and the first decides whether the rest matters:

* **the round trip** — an array declared entirely through the dialog is stored
  as the server holds it, which is the only way to know the dialog and the API
  agree about a pairing neither typechecks against the other;
* **the transition**, which is this unit's real rule: switching a property
  *away* from `array` has to clear the element type, or the row becomes a
  `string` carrying a claim the server refuses — silently, because the row
  still looks right;
* **the value on the screen**, because an array that stored correctly and drew
  as `["a","b"]` is the half §346 could not deliver on its own.

The list of element types and the transition are unit-tested in
`apps/web/src/lib/array-property.test.ts`; the list is guarded against the
server's own in `apps/api/tests/test_array_properties.py`.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import find_type_row, save_type

TAGS = json.dumps(["alpha", "beta"])
#: p.140's "Struct Array": a list whose elements are structs, as the CSV cell
#: holds it. `struct_fields` describes the *element* (db 0064), which is what
#: let the server carry this shape without a second column.
STOPS = json.dumps([
    {"street": "Main", "floors": "2"},
    {"street": "High", "floors": "4"},
])
STOP_FIELDS = [
    {"api_name": "street", "display_name": "Street", "data_type": "string"},
    {"api_name": "floors", "display_name": "Floors", "data_type": "integer"},
]


@pytest.fixture(scope="module")
def module(api):
    """One column already an array and one still a string, on purpose.

    `tags` **is already declared** an array, so the tests that inspect a
    declared one have something to inspect; `labels` is still a string, so the
    test that walks the whole flow has something real to convert.

    Separate columns because a test that only passes after another one is not a
    test — `test_struct_fields_editor` writes down how that bit it there.
    """
    mod = Module(api, "Array property editor")
    mod.object_type(
        columns=["code", "tags", "labels"],
        rows=[{"code": "A1", "tags": TAGS, "labels": "plain"}],
        key="code",
        title="code",
        types={"tags": "array"},
        array_of={"tags": "string"},
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
    row = find_type_row(page, f"seed_{module.tag}")
    row.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible()


def property_row(page, api_name: str) -> int:
    names = page.get_by_role("textbox", name="Property")
    for index in range(names.count()):
        box = page.get_by_role("textbox", name=f"Property {index + 1} name")
        if box.input_value() == api_name:
            return index + 1
    raise AssertionError(f"no property row named {api_name!r}")


def test_an_array_is_declared_entirely_through_the_dialog(page, api, module) -> None:
    """p.86's declaration end to end: pick Array from the type dropdown, say
    what it is a list of, save, and find both halves stored.

    **Read back from the API rather than from the dialog.** A dialog that
    showed the element type while having sent something else would look right
    and be the bug this test exists to exclude.
    """
    open_type_editor(page, module)
    index = property_row(page, "labels")
    # A plain string has no element-type control, because a property that is
    # not a list must not carry a claim about what it is a list of.
    expect(
        page.get_by_role("combobox", name=f"Property {index} element type")
    ).to_have_count(0)

    page.get_by_role("combobox", name=f"Property {index} type").select_option("array")
    element = page.get_by_role("combobox", name=f"Property {index} element type")
    expect(element).to_be_visible()
    # It arrives already answered rather than empty: an empty one is a
    # declaration the server refuses, and the reader would have to notice a
    # second control to fix it.
    expect(element).to_have_value("string")
    element.select_option("integer")
    save_type(page)

    held = properties(api, module)["labels"]
    assert held["data_type"] == "array", held
    assert held["array_of"] == "integer", held


def test_switching_away_from_an_array_clears_what_it_held(page, api, module) -> None:
    """**This unit's real rule, and the one a plain `{...prop, data_type}` gets
    wrong.** db 0087 refuses a `string` carrying an element type, so a dropdown
    that changed only the base type would make every switch away from `array`
    into a save the server rejects — with a message about a field the dialog no
    longer shows.

    Asserted through the API for the round-trip reason above: the dialog
    hiding the control is not the same as the row having dropped the value.
    """
    open_type_editor(page, module)
    index = property_row(page, "tags")
    expect(
        page.get_by_role("combobox", name=f"Property {index} element type")
    ).to_have_value("string")

    page.get_by_role("combobox", name=f"Property {index} type").select_option("string")
    expect(
        page.get_by_role("combobox", name=f"Property {index} element type")
    ).to_have_count(0)
    save_type(page)

    held = properties(api, module)["tags"]
    assert held["data_type"] == "string", held
    assert held["array_of"] is None, held


def test_an_array_of_structs_opens_the_fields_dialog(page, api, module) -> None:
    """p.140's "Struct Array", which needed nothing new anywhere: db 0064's
    column holds the *element's* fields, so the same button opens the same
    dialog about the same declaration.

    The Fields button appearing on an array of structs and **not** on an array
    of strings is the whole claim — a button on every array would open a dialog
    about fields the property has no use for.
    """
    open_type_editor(page, module)
    index = property_row(page, "labels")
    page.get_by_role("combobox", name=f"Property {index} type").select_option("array")
    fields = page.get_by_role("button", name=f"Property {index} fields")
    expect(fields).to_have_count(0)

    page.get_by_role(
        "combobox", name=f"Property {index} element type"
    ).select_option("struct")
    expect(fields).to_be_visible()


def test_an_array_value_is_drawn_as_its_elements(page, api, module) -> None:
    """The half §346 could not deliver: before this an array fell through to
    `JSON.stringify` and a list of tags read as `["alpha","beta"]`.

    Its own module, because the two tests above retype `tags` and this one is
    about a workspace where it is still an array.
    """
    mod = Module(api, "Array property values")
    mod.object_type(
        columns=["code", "tags"],
        rows=[{"code": "B1", "tags": TAGS}],
        key="code", title="code",
        types={"tags": "array"}, array_of={"tags": "string"},
    )
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects/"
        f"{mod.object_type_id}"
    )
    drawn = page.get_by_test_id("array-value").first
    expect(drawn).to_be_visible(timeout=30000)
    expect(drawn).to_contain_text("alpha")
    expect(drawn).to_contain_text("beta")
    # **Not the JSON.** The brackets and quotes are what the fall-through drew,
    # and asserting only on "alpha" would pass over it.
    assert "[" not in drawn.inner_text(), drawn.inner_text()


def test_an_array_of_structs_draws_each_element_against_the_fields(
    page, api, module
) -> None:
    """p.140's "Struct Array", rendered — the case that needed no third
    per-property prop, because `structFields` already means the *element's*
    fields for an array (db 0064).

    The **labels** are the assertion. An element drawn without the declaration
    falls through to the JSON a `json` property gets, which still contains the
    values — so asserting on "Main" alone would pass over exactly the bug this
    test is for.
    """
    mod = Module(api, "Array of structs")
    mod.object_type(
        columns=["code", "stops"],
        rows=[{"code": "C1", "stops": STOPS}],
        key="code", title="code",
        types={"stops": "array"}, array_of={"stops": "struct"},
        struct_fields={"stops": STOP_FIELDS},
    )
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects/"
        f"{mod.object_type_id}"
    )
    drawn = page.get_by_test_id("array-value").first
    expect(drawn).to_be_visible(timeout=30000)
    # Upper-cased by `.struct-field-label`, so the comparison is too — the
    # claim is that the label is *there*, not how it is cased.
    text = drawn.inner_text().upper()
    assert "STREET" in text and "FLOORS" in text, text
    assert "MAIN" in text and "HIGH" in text, text
    # And the declared order, which the value's own keys cannot recover: a
    # struct arrives from jsonb with its keys reordered.
    assert text.index("STREET") < text.index("FLOORS"), text
