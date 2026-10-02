"""A property's type classes, set in the Ontology Manager, and p.222's
hubble:icon in the Object Table (§671).

> "Type classes: Apply type classes as additional metadata that can be
>  interpreted by applications." (`object-link-types` p.91)
>
> "If your object has a property that stores a URL to an image, you can add
>  the type class hubble:icon to display the image instead of the icon that
>  was selected when setting up the object type." (`workshop` p.222)

The shape and the save, restore and export are `test_type_classes.py`
(API); the box's parsing and which URLs load are `type-classes.test.ts`.
What needs a browser is the editor's box saving what was typed, saying what
it will not save, and the table drawing each object's picture.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module
from test_object_type_editor_carry import open_type_editor

ROWS = [
    {"id": "P1", "name": "Pump", "picture": "https://example.com/pump.png"},
    {"id": "P2", "name": "Valve", "picture": "javascript:alert(1)"},
    {"id": "P3", "name": "Gauge", "picture": ""},
]


@pytest.fixture(scope="module")
def parts(api):
    mod = Module(api, "Type classes")
    mod.object_type_id = mod.object_type(columns=["id", "name", "picture"], rows=ROWS,
                                         key="id", title="name")
    return mod


def detail(api, mod) -> dict:
    return api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")


def classes_of(api, mod) -> dict:
    return {p["api_name"]: p["type_classes"] for p in detail(api, mod)["properties"]}


def with_classes(api, mod, classes: list[str]) -> None:
    got = detail(api, mod)
    title = next(p["api_name"] for p in got["properties"] if p["id"] == got.get("title_property_id"))
    api.call("PATCH", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}", {
        "display_name": got["display_name"], "title_property": title,
        "properties": [{k: p.get(k) for k in ("api_name", "display_name", "data_type")}
                       | ({"type_classes": classes} if p["api_name"] == "picture" else {})
                       for p in got["properties"]]})


def test_the_ontology_manager_sets_a_property_s_type_classes(page, api, parts) -> None:
    open_type_editor(page, parts)
    names = [page.get_by_role("textbox", name=f"Property {i} name").input_value() for i in (1, 2, 3)]
    box = page.get_by_label(f"Property {names.index('picture') + 1} type classes")
    box.fill("hubble:icon, team:photo, icon")
    box.press("Tab")
    # What is not kind:name is said, and left out of the save.
    expect(page.get_by_role("alert").filter(has_text="Not kind:name: icon")).to_be_visible()
    # And the box shows what will be saved.
    expect(box).to_have_value("hubble:icon, team:photo")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    eventually(lambda: classes_of(api, parts)["picture"],
               lambda got: got == ["hubble:icon", "team:photo"], what="the type classes saved")
    # Opened again, the box holds what was saved.
    open_type_editor(page, parts)
    expect(page.get_by_label(f"Property {names.index('picture') + 1} type classes")).to_have_value(
        "hubble:icon, team:photo")


def table(api, parts, name: str) -> Module:
    mod = Module(api, name, beside=parts)
    mod.define({
        "format": 2,
        "layout": layout({"tbl": {"resolvedName": "CanvasObjectTable", "props": {
            "objectSetVariable": "v_parts", "columns": "name", "pageSize": 50, "autoSelect": False}}}),
        "variables": {"v_parts": {"id": "v_parts", "kind": "object_set", "label": "Parts",
                                  "object_set": object_set(parts.object_type_id)}},
        "events": {},
    })
    return mod


def test_the_object_table_draws_each_object_s_picture(page, api, parts) -> None:
    with_classes(api, parts, ["hubble:icon"])
    open_module(page, table(api, parts, "Type classes table"))
    rows = page.locator(".data-grid tbody tr")
    expect(rows).to_have_count(3, timeout=20000)
    icons = page.get_by_test_id("object-table-icon")
    # Only the one with an http(s) URL: a script is not a picture, and a blank
    # is none.
    expect(icons).to_have_count(1)
    expect(icons).to_have_attribute("src", "https://example.com/pump.png")
    expect(rows.filter(has=icons)).to_contain_text("P1")


def test_no_picture_without_the_type_class(page, api, parts) -> None:
    with_classes(api, parts, ["team:photo"])
    open_module(page, table(api, parts, "Type classes table none"))
    expect(page.locator(".data-grid tbody tr")).to_have_count(3, timeout=20000)
    expect(page.get_by_test_id("object-table-icon")).to_have_count(0)
