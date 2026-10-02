"""Value types over arrays and structs, on p.224's form (§681; `object-link-types`
p.234).

What each constraint means is `apps/api/tests/test_value_types_composite.py`
and `value-type.test.ts`. What needs a browser is the form: that an array is
offered p.234's three kinds and a struct its one, that "each item" and "each
field" are picked from the workspace's scalar value types, and that the
listing then says what was chosen by name.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from test_value_types import choose_option, open_objects


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Value types")
    mod.object_type(columns=["id", "name"], rows=[{"id": "1", "name": "Ada"}],
                    key="id", title="name")
    return mod


@pytest.fixture(scope="module")
def email(api, module) -> dict:
    return api.call("POST", f"/workspaces/{module.workspace_id}/value-types", {
        "api_name": f"email_{uuid.uuid4().hex[:6]}", "display_name": f"Email {uuid.uuid4().hex[:4]}",
        "base_type": "string",
        "constraint": {"kind": "regex", "pattern": r"[a-z]+@example\.com"}})


def new_value_type(page, module, name: str, base_type: str) -> None:
    open_objects(page, module)
    page.get_by_test_id("new-value-type").click()
    page.get_by_test_id("vt-name").fill(name)
    page.get_by_test_id("vt-base-type").select_option(base_type)


def kinds(page) -> list[str]:
    options = page.get_by_test_id("constraint-kind").locator("option")
    return [options.nth(i).get_attribute("value") for i in range(options.count())]


def test_an_array_is_offered_size_uniqueness_and_items(page, module) -> None:
    new_value_type(page, module, "Tags", "array")
    expect(page.get_by_test_id("constraint-kind").locator("option")).to_have_count(4)
    assert kinds(page) == ["", "range", "unique", "nested"]
    page.get_by_test_id("constraint-kind").select_option("range")
    expect(page.get_by_text("Minimum size")).to_be_visible()
    page.get_by_test_id("constraint-min").fill("-1")
    expect(page.get_by_test_id("constraint-problem")).to_have_text("A size cannot be negative.")
    page.get_by_test_id("vt-base-type").select_option("struct")
    expect(page.get_by_test_id("constraint-kind").locator("option")).to_have_count(2)
    assert kinds(page) == ["", "elements"]


def test_every_item_is_a_chosen_value_type(page, module, email) -> None:
    name = f"Emails {uuid.uuid4().hex[:4]}"
    new_value_type(page, module, name, "array")
    page.get_by_test_id("constraint-kind").select_option("nested")
    expect(page.get_by_test_id("constraint-problem")).to_have_text(
        "Choose the value type every item must be.")
    expect(page.get_by_test_id("vt-save")).to_be_disabled()
    # Only scalar value types are offered - not the array being made, nor
    # any other array or struct.
    options = page.get_by_test_id("constraint-nested").locator("option")
    expect(options.filter(has_text=email["display_name"])).to_have_count(1)
    assert all("(array)" not in t and "(struct)" not in t for t in options.all_inner_texts())
    choose_option(page, "constraint-nested", email["display_name"])
    page.get_by_test_id("vt-save").click()
    api_name = name.lower().replace(" ", "_")
    expect(page.get_by_test_id(f"vt-rule-{api_name}")).to_have_text(
        f"each item is {email['api_name']}")


def test_each_named_field_is_a_chosen_value_type(page, module, email) -> None:
    name = f"Contact {uuid.uuid4().hex[:4]}"
    new_value_type(page, module, name, "struct")
    page.get_by_test_id("constraint-kind").select_option("elements")
    page.get_by_role("textbox", name="Field 1").fill("work")
    expect(page.get_by_test_id("constraint-problem")).to_have_text(
        "Choose the value type for work.")
    page.get_by_role("combobox", name="Value type for field 1").select_option(
        label=f"{email['display_name']} (string)")
    page.get_by_role("button", name="Add field").click()
    page.get_by_role("textbox", name="Field 2").fill("work")
    page.get_by_role("combobox", name="Value type for field 2").select_option(
        label=f"{email['display_name']} (string)")
    expect(page.get_by_test_id("constraint-problem")).to_have_text("That names work twice.")
    # A stray space is not part of a field's name.
    page.get_by_role("textbox", name="Field 2").fill("home ")
    expect(page.get_by_test_id("constraint-problem")).to_have_count(0)
    page.get_by_test_id("vt-save").click()
    api_name = name.lower().replace(" ", "_")
    expect(page.get_by_test_id(f"vt-rule-{api_name}")).to_have_text(
        f"home is {email['api_name']}, work is {email['api_name']}")
