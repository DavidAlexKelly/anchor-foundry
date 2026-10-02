"""p.91's bulk edit of an object type's properties (§672).

> "You can select multiple properties in the property editor by holding the
> Cmd/Ctrl key while selecting properties. Once multiple properties are
> selected, the following bulk editing actions become available: Changing
> base type. Adding/removing of type classes. Changing render hints.
> Changing visibility. Adding/removing value formatting."
> (`object-link-types` p.91)

What each action does to the rows, and that a shared property keeps what it
inherits, is `property-bulk.test.ts`. What needs a browser is selecting rows,
the bar appearing for two and not one, and the edits reaching a save.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import eventually
from test_object_type_editor_carry import open_type_editor

ROWS = [{"id": "M1", "name": "Pump", "flow": "3", "head": "12"}]


@pytest.fixture(scope="module")
def meters(api):
    mod = Module(api, "Bulk edit")
    mod.object_type_id = mod.object_type(columns=["id", "name", "flow", "head"], rows=ROWS, key="id",
                                         title="name", types={"flow": "integer", "head": "integer"})
    return mod


def by_name(api, mod) -> dict:
    got = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")
    return {p["api_name"]: p for p in got["properties"]}


def select(page, names: list[str], *wanted: str) -> None:
    for name in wanted:
        page.get_by_label(f"Select property {names.index(name) + 1}").check()


def names_of(page) -> list[str]:
    boxes = page.get_by_role("textbox", name=re.compile(r"^Property \d+ name$"))
    return [b.input_value() for b in boxes.all()]


def test_two_selected_properties_are_edited_together(page, api, meters) -> None:
    open_type_editor(page, meters)
    names = names_of(page)
    bar = page.get_by_test_id("property-bulk")
    select(page, names, "flow")
    # One is not "multiple properties".
    expect(bar).to_have_count(0)
    select(page, names, "head")
    expect(bar).to_contain_text("2 properties selected")
    bar.get_by_label("Change visibility").select_option("hidden")
    bar.get_by_label("Type class to add").fill("units:si")
    bar.get_by_role("button", name="Add type class").click()
    expect(bar.get_by_label("Type class to remove").locator("option")).to_have_text(
        ["Remove type class…", "units:si"])
    # Both integers, so one formatter fits both.
    expect(bar.get_by_role("button", name="Add formatting")).to_be_enabled()
    # The name is not selected, and is untouched.
    expect(page.get_by_label(f"Property {names.index('flow') + 1} visibility")).to_have_value("hidden")
    expect(page.get_by_label(f"Property {names.index('name') + 1} visibility")).to_have_value("normal")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    eventually(lambda: by_name(api, meters),
               lambda got: [(got[n]["visibility"], got[n]["type_classes"]) for n in ("flow", "head", "name")]
               == [("hidden", ["units:si"]), ("hidden", ["units:si"]), ("normal", [])],
               what="the bulk edit saved")


def test_properties_of_two_types_take_no_one_formatter(page, api, meters) -> None:
    open_type_editor(page, meters)
    names = names_of(page)
    select(page, names, "name", "flow")
    bar = page.get_by_test_id("property-bulk")
    expect(bar.get_by_role("button", name="Add formatting")).to_be_disabled()
    bar.get_by_label("Change base type").select_option("string")
    expect(page.get_by_label(f"Property {names.index('flow') + 1} type", exact=True)).to_have_value("string")
    # Now one type, a formatter fits them both.
    expect(bar.get_by_role("button", name="Add formatting")).to_be_enabled()
    bar.get_by_role("button", name="Clear selection").click()
    expect(bar).to_have_count(0)
