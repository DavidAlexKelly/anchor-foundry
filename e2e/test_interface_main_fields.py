"""An interface property implemented through a struct main field (§675;
`object-link-types` p.169-170).

> "Use struct main fields when … You need to implement interfaces using only
> a single field or subset of fields from a struct." (p.169)

A place's address struct, whose street is its one main field, can answer an
interface's `street` string; its contact struct, with none, cannot. Read
through the interface, the address answers a street rather than a struct.
What each implementation presents is `test_interface_presentation.py`.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from ontology_page import pick_type
from test_interfaces import declare

ADDRESS = [{"api_name": "street", "display_name": "Street", "data_type": "string", "main": True},
           {"api_name": "postal_code", "display_name": "Postal code", "data_type": "string"}]
CONTACT = [{"api_name": "name", "display_name": "Name", "data_type": "string"},
           {"api_name": "phone", "display_name": "Phone", "data_type": "string"}]


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Interface main fields")
    mod.object_type_id = mod.object_type(
        columns=["id", "address", "contact"],
        rows=[{"id": "P1", "address": json.dumps({"street": "12 Main St", "postal_code": "N1 9GU"}),
               "contact": json.dumps({"name": "Ada", "phone": "1"})}],
        key="id", title="id", types={"address": "struct", "contact": "struct"},
        struct_fields={"address": ADDRESS, "contact": CONTACT})
    return mod


def test_a_struct_with_one_main_field_answers_a_string(page, module) -> None:
    api_name = declare(page, module, name=f"Addressed {uuid.uuid4().hex[:4]}",
                       properties=[("Street", "string", True)])
    page.get_by_role("button", name=f"Implement {api_name}").click()
    pick_type(page, "impl-type", {"id": module.object_type_id, "api_name": f"seed_{module.tag}"})
    answered = page.get_by_role("combobox", name="Answered by for street")
    expect(answered.locator("option", has_text="address")).to_have_count(1, timeout=15000)
    expect(answered.locator("option", has_text="contact")).to_have_count(0)
    answered.select_option("address")
    page.get_by_test_id("impl-save").click()
    expect(page.get_by_test_id(f"iface-impls-{api_name}")).to_contain_text("1 object type", timeout=15000)

    page.get_by_role("button", name=f"Objects of {api_name}").click()
    rows = page.get_by_test_id("objects-rows")
    expect(rows.locator("tbody tr")).to_have_count(1, timeout=20000)
    expect(rows).to_contain_text("12 Main St")
    expect(rows).not_to_contain_text("N1 9GU")
