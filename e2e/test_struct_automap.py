"""Struct columns read as structs, and p.160's Automap all (§735;
`object-link-types` p.149, p.160).

> "Struct properties are created from struct type dataset columns." (p.149)

> "If the object has already been created, users can automap all columns by
> using the Automap all feature." (p.160)

A JSON Lines upload whose `address` is an object arrives as a STRUCT column.
The suggestion offers it as a struct with its members as fields, and the type
created from that suggestion holds them. A type that declared the struct by
hand with one field gets the rest from the dialog's Automap all, and keeps
what was written by hand.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import find_type_row, save_type

ROWS = [
    {"code": "A1", "address": {"street": "1 Main St", "number": 1, "First Name": "x"},
     "tags": ["north", "big"], "contact": {"phone": "0101"}},
    {"code": "B2", "address": {"street": "9 Side Rd", "number": 9, "First Name": "y"},
     "tags": ["south"], "contact": {"phone": "0202"}},
]


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Struct automap")
    body = "\n".join(json.dumps(r) for r in ROWS).encode()
    mod.dataset = api.upload_csv(f"{mod.base}/datasets/upload", f"sites_{mod.tag}", body,
                                 filename="sites.jsonl")
    return mod


def properties(api, module, type_id: str) -> dict[str, dict]:
    detail = api.call("GET", f"/workspaces/{module.workspace_id}/object-types/{type_id}")
    return {p["api_name"]: p for p in detail["properties"]}


def test_the_suggestion_offers_a_struct_column_as_a_struct(page, api, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    page.get_by_role("button", name="Suggest from dataset").first.click()
    dialog = page.locator("dialog.dialog").filter(
        has=page.get_by_role("heading", name="Suggest an object type from a dataset")).last
    dialog.locator("select").first.select_option(module.dataset["id"])
    address = dialog.locator("[data-testid='suggested-property'][data-column='address']")
    expect(address.get_by_test_id("suggested-type")).to_have_text("struct")
    expect(address.get_by_test_id("suggested-fields")).to_have_text("fields: street, number")
    expect(address.get_by_test_id("suggested-skipped")).to_have_text("not mapped: First Name")
    tags = dialog.locator("[data-testid='suggested-property'][data-column='tags']")
    expect(tags.get_by_test_id("suggested-type")).to_have_text("array of string")
    name = f"Automapped {module.tag}"
    dialog.get_by_role("textbox").first.fill(name)
    dialog.get_by_role("button", name="Create type & map dataset").click()
    expect(dialog).to_have_count(0)

    types = api.call("GET", f"/workspaces/{module.workspace_id}/object-types")
    [created] = [t for t in (types["items"] if isinstance(types, dict) else types)
                 if t["display_name"] == name]
    stored = properties(api, module, created["id"])
    assert [f["api_name"] for f in stored["address"]["struct_fields"]] == ["street", "number"]
    assert [f["data_type"] for f in stored["address"]["struct_fields"]] == ["string", "integer"]
    assert (stored["tags"]["data_type"], stored["tags"]["array_of"]) == ("array", "string")


@pytest.fixture
def hand_declared(api, module) -> str:
    """The struct declared by hand with one field, and mapped from the column."""
    type_id = api.call("POST", f"/workspaces/{module.workspace_id}/object-types", {
        "api_name": f"HandSite{module.tag}", "display_name": f"Hand site {module.tag}",
        "properties": [
            {"api_name": "code", "data_type": "string"},
            # A second struct column, mapped to another property: its
            # automap is that property's, not this one's.
            {"api_name": "contact", "data_type": "json"},
            {"api_name": "address", "data_type": "struct", "struct_fields": [
                {"api_name": "street", "display_name": "Street", "data_type": "string",
                 "description": "written by hand"}]},
        ]})["id"]
    api.call("POST", f"{module.base}/object-type-sources", {
        "object_type_id": type_id, "dataset_id": module.dataset["id"],
        "primary_key_column": "code", "column_mappings": {"code": "code", "contact": "contact", "address": "address"}})
    return type_id


def test_automap_all_adds_the_columns_members(page, api, module, hand_declared) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    find_type_row(page, f"HandSite{module.tag}").get_by_role("button", name="Edit").click()
    names = page.get_by_role("textbox", name="Property 3 name")
    expect(names).to_have_value("address")
    page.get_by_role("button", name="Property 3 fields").click()
    automap = page.get_by_test_id("struct-automap")
    expect(automap).to_have_text(f"Automap all from sites_{module.tag} · address")
    expect(page.get_by_test_id("struct-automap-skipped")).to_contain_text("Not mapped: First Name")
    automap.click()
    rows = page.get_by_test_id("struct-field-rows").locator("tr[data-struct-field]")
    expect(rows).to_have_count(2)
    # Twice is once: nothing is added a second time.
    automap.click()
    expect(rows).to_have_count(2)
    expect(page.get_by_role("combobox", name="Field 2 type")).to_have_value("integer")
    page.get_by_test_id("struct-save").click()
    save_type(page)
    eventually(lambda: properties(api, module, hand_declared)["address"]["struct_fields"],
               lambda f: [x["api_name"] for x in f] == ["street", "number"],
               what="the automapped field stored")
    stored = properties(api, module, hand_declared)["address"]["struct_fields"]
    assert stored[0]["description"] == "written by hand"
