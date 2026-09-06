"""What an object type edit carries forward, and a struct arriving through a
sync (parity `ontology.md` §1.1; Foundry `object-link-types` p.149; db 0064).

Two claims, and they are here together because the second found the first.

**The editor sends the whole definition on every save.** `object-type-editor`
maps each property into a `PropertyInput` by hand, and the comment beside that
list has said since §157 what the risk is: *"every new property setting has to
be added here, and nothing fails if it is not."* §245 went to add
`struct_fields` to it and found `description` already missing - so opening the
edit dialog and saving, for any reason at all, erased every property
description the type had. Nothing failed, exactly as predicted.

The fix is a type rather than a longer list (`CARRIED` in that file), so the
compiler refuses the next omission. This file is the behaviour behind it: an
edit that touches one thing leaves the others alone.

**A struct is a schema, and the sync applies it.** The CSV cell holds JSON
text - which is the form `column_value` writes back, so it is the round trip
rather than a convenience - and what comes out the other side is the declared
fields, in the declared order, with the undeclared key dropped. That last part
is the assertion that separates a struct from a `json` property: both would
store the value, and only one of them says what it contains.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import find_type_row

FIELDS = [
    {"api_name": "street", "display_name": "Street", "data_type": "string"},
    {"api_name": "postal_code", "display_name": "Postal code", "data_type": "string"},
    {"api_name": "floors", "display_name": "Floors", "data_type": "integer"},
]

# **`county` is not declared**, and that is the test: a dataset may carry more
# than the ontology asks for, the same way a table may have columns no property
# names, so it has to be dropped rather than refused *and* rather than kept.
ADDRESS = json.dumps(
    {"street": "12 Main St", "postal_code": "N1 9GU", "floors": "3",
     "county": "Greater London"}
)

SITES = [{"code": "A1", "address": ADDRESS}]

CODE_DESCRIPTION = "The site's own code, as the depot system spells it."


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Type editor carry")
    mod.object_type(
        columns=["code", "address"],
        rows=SITES,
        key="code",
        title="code",
        types={"address": "struct"},
        struct_fields={"address": FIELDS},
        descriptions={"code": CODE_DESCRIPTION},
    )
    return mod


def properties(api, module) -> dict[str, dict]:
    """This type's properties as the **server** holds them, by api_name."""
    detail = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )
    return {p["api_name"]: p for p in detail["properties"]}


def open_type_editor(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = find_type_row(page, f"seed_{module.tag}")
    row.get_by_role("button", name="Edit").click()
    # **Waited for by content, not by the dialog's own box.** §241 found this
    # helper asserting on a dialog nothing had waited for, in five copies of
    # itself; the first property's name box is the thing that has to be there
    # before anything below can type into it.
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible()


def test_the_type_starts_with_a_description_and_a_struct(api, module) -> None:
    """The baseline, and it is not decoration: the test below asserts that two
    settings *survive* an edit, and without this it would pass just as happily
    against a type that never had them."""
    before = properties(api, module)
    assert before["code"]["description"] == CODE_DESCRIPTION
    assert [f["api_name"] for f in before["address"]["struct_fields"]] == [
        "street", "postal_code", "floors"
    ]


def test_editing_a_type_keeps_the_settings_the_edit_did_not_touch(
    page, api, module
) -> None:
    """The bug this file exists for. Renaming the *type* is about as far from a
    property's description as an edit gets, and it erased every one of them -
    because the dialog rebuilds the whole property list from a hand-kept map
    and `description` was not in it.

    Asserted through the API rather than by reading the dialog back, because
    what was lost is what got *stored*: a dialog that still showed the old
    description while having sent an empty one would look correct and be the
    same bug.
    """
    open_type_editor(page, module)
    name = page.get_by_role("textbox", name="Display name")
    name.fill(f"Seed {module.tag} renamed")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    eventually(
        lambda: properties(api, module)["code"]["description"],
        lambda d: d == CODE_DESCRIPTION,
        what="the property description an unrelated edit must not have touched",
    )
    after = properties(api, module)
    assert [f["api_name"] for f in after["address"]["struct_fields"]] == [
        "street", "postal_code", "floors"
    ], "the struct's schema did not survive an edit to a different property"


def test_a_synced_struct_holds_the_declared_fields_and_nothing_else(
    page, api, module
) -> None:
    """The value side, end to end: a CSV cell of JSON text, through the sync's
    coercion, onto the screen.

    **The undeclared key is the assertion.** `street` appearing proves the
    value arrived; `county` *not* appearing proves the declaration was applied
    rather than the value merely stored, which is the whole difference between
    this type and `json`.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(SITES),
               what="this type's sites, and only this type's")
    rows.first.get_by_role("button", name="Explore").click()
    # **Scoped, and exact.** `get_by_role`'s name match is a substring, and the
    # page carries two headings containing "A1" once the title resolves — the
    # breadcrumb's "Seed <tag> · A1" and the view's own. Unscoped, this passed
    # or failed depending on which had rendered first.
    expect(
        page.get_by_test_id("standard-object-view").get_by_role(
            "heading", name="A1", exact=True
        )
    ).to_be_visible()

    # **Read as its declared fields, not as JSON** (§246): the declaration is
    # what supplies the labels *and* the order, and the order cannot be
    # recovered any other way — `jsonb` reorders an object's keys on the way
    # into storage, so the value itself no longer remembers what p.154's author
    # chose.
    shown = page.get_by_test_id("struct-value").first
    expect(shown).to_be_visible()
    labels = shown.locator(".struct-field-label")
    assert [
        labels.nth(i).text_content() for i in range(labels.count())
    ] == ["Street", "Postal code", "Floors"], "the declared order and labels"

    # **Exact, not `in`.** The whole text is the strongest form of "and nothing
    # else": `county` was in the CSV cell and is absent here because the
    # declaration does not name it, which is the difference between this type
    # and `json`. The labels run into their values because the gap between them
    # is CSS — `text_content` reads the DOM, not the layout (§214).
    assert " ".join((shown.text_content() or "").split()) == (
        "Street12 Main StPostal codeN1 9GUFloors3"
    )
