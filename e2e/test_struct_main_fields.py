"""p.169's struct main fields (§674; `object-link-types` p.169-170).

> "Struct main fields enable you to designate a struct's core value and
> supplementary metadata … Applications that support struct main fields
> display only the main fields in compact views, like the Object Table and
> Object List widgets in Workshop, while providing access to the full struct
> through an expanded view or upon hover." (p.169)

An address whose street and postal code are its main fields, and whose
collection date is metadata. The table and the cards show the two alone with
the whole address on hover; the Property List, a detailed view, shows it all.
Which fields are main and what a compact view draws is `struct-fields.test.ts`;
the stored flag is `test_struct_properties.py`.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module
from ontology_page import save_type
from test_struct_fields_editor import open_type_editor, properties, property_row

FIELDS = [
    {"api_name": "street", "display_name": "Street", "data_type": "string", "main": True},
    {"api_name": "collected", "display_name": "Collected", "data_type": "string"},
    {"api_name": "postal_code", "display_name": "Postal code", "data_type": "string", "main": True},
]
ADDRESS = json.dumps({"street": "12 Main St", "collected": "2024-01-01", "postal_code": "N1 9GU"})


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Struct main fields")
    mod.object_type(columns=["code", "address"], rows=[{"code": "A1", "address": ADDRESS}],
                    key="code", title="code", types={"address": "struct"},
                    struct_fields={"address": FIELDS})
    return mod


def build(api, module, name: str) -> Module:
    mod = Module(api, name, beside=module)
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_set", "columns": "address", "pageSize": 10, "autoSelect": False}},
            "cards": {"resolvedName": "CanvasObjectCards", "props": {
                "objectSetVariable": "v_set", "fields": "address", "pageSize": 10}},
            "pl": {"resolvedName": "CanvasPropertyList", "props": {
                "objectSetVariable": "v_set", "layout": "adjacent", "properties": "address",
                "columns": 1, "hideNull": False}},
        }),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Places",
                                "object_set": object_set(module.object_type_id)}},
        "events": {},
    })
    return mod


def test_compact_views_show_the_main_fields_and_the_rest_on_hover(page, api, module) -> None:
    open_module(page, build(api, module, "Struct main fields views"))
    cell = page.locator(".data-grid tbody [data-testid='struct-value']")
    expect(cell).to_have_count(1, timeout=20000)
    expect(cell).to_have_attribute("data-main", "true")
    expect(cell).to_contain_text("12 Main St")
    expect(cell).to_contain_text("N1 9GU")
    expect(cell).not_to_contain_text("2024-01-01")
    expect(cell).to_have_attribute("title", "Street: 12 Main St\nCollected: 2024-01-01\nPostal code: N1 9GU")

    card = page.locator(".canvas-cards [data-testid='struct-value']")
    expect(card).to_have_attribute("data-main", "true")
    expect(card).not_to_contain_text("2024-01-01")

    # A detailed view: the whole struct.
    listed = page.get_by_test_id("property-list").locator("[data-testid='struct-value']")
    expect(listed).to_contain_text("2024-01-01")
    expect(listed).not_to_have_attribute("data-main", "true")


def test_the_fields_dialog_designates_a_main_field(page, api, module) -> None:
    open_type_editor(page, module)
    index = property_row(page, "address")
    page.get_by_role("button", name=f"Property {index} fields").click()
    expect(page.get_by_test_id("struct-field-rows")).to_be_visible()
    expect(page.get_by_role("checkbox", name="Field 1 main field")).to_be_checked()
    page.get_by_role("checkbox", name="Field 1 main field").uncheck()
    page.get_by_role("checkbox", name="Field 2 main field").check()
    page.get_by_test_id("struct-save").click()
    save_type(page)
    eventually(lambda: [f.get("main", False) for f in properties(api, module)["address"]["struct_fields"]],
               lambda got: got == [False, True, True], what="the main fields saved")


def test_the_fields_are_reordered_without_a_rename_warning(page, api, module) -> None:
    """p.169: "reorder them for clarity by clicking and dragging a field's
    panel" (§676) - here a button each way. A moved field keeps its name, so
    p.158's rename warning stays away."""
    open_type_editor(page, module)
    index = property_row(page, "address")
    page.get_by_role("button", name=f"Property {index} fields").click()
    expect(page.get_by_test_id("struct-field-rows")).to_be_visible()
    before = [f["api_name"] for f in properties(api, module)["address"]["struct_fields"]]
    expect(page.get_by_role("button", name="Move field 1 up", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name=f"Move field {len(before)} down", exact=True)).to_be_disabled()
    page.get_by_role("button", name=f"Move field {len(before)} up", exact=True).click()
    expect(page.get_by_test_id("struct-rename-warning")).to_have_count(0)
    page.get_by_test_id("struct-save").click()
    save_type(page)
    expected = before[:-2] + [before[-1], before[-2]]
    eventually(lambda: [f["api_name"] for f in properties(api, module)["address"]["struct_fields"]],
               lambda got: got == expected, what="the new order saved")
