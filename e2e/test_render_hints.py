"""A property's render hints in the Ontology Manager (§724;
`object-link-types` p.91, p.182, p.188, p.248-252).

> "You can select and deselect render hints in the properties pane of the
> property editor" (p.248)

The list and its rule are `render-hints.test.ts` and `render_hints.py`; that
they are kept through a save, a restore and an import is
`test_render_hints.py` (API). What needs a browser is the checklist keeping
p.250-251's rule as it is ticked, p.91's bulk edit, and a shared property's
hints standing in for the property's (p.188) with the row's control disabled.
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import eventually
from test_object_type_editor_carry import open_type_editor
from test_shared_properties import open_objects, property_index

ROWS = [{"id": "N1", "name": "Pump", "body": "Runs hot in summer", "code": "17"}]
DEFAULT = ["selectable", "sortable", "searchable"]


@pytest.fixture(scope="module")
def notes(api):
    mod = Module(api, "Render hints")
    mod.object_type_id = mod.object_type(columns=["id", "name", "body", "code"], rows=ROWS,
                                         key="id", title="name", types={"code": "integer"})
    return mod


def hints(api, mod) -> dict:
    got = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}")
    return {p["api_name"]: p["render_hints"] for p in got["properties"]}


def names_of(page) -> list[str]:
    boxes = page.get_by_role("textbox", name=re.compile(r"^Property \d+ name$"))
    return [b.input_value() for b in boxes.all()]


def test_the_checklist_keeps_p250_s_rule_as_it_is_ticked(page, api, notes) -> None:
    assert hints(api, notes)["body"] == DEFAULT
    open_type_editor(page, notes)
    names = names_of(page)
    row = names.index("body") + 1
    button = page.get_by_role("button", name=f"Property {row} render hints")
    # What is set, by count; the names are in the tooltip.
    expect(button).to_have_text("Hints (3)")
    button.click()
    dialog = page.locator(".render-hints")
    # Turning Searchable off turns off what needs it (p.251).
    dialog.get_by_test_id("render-hint-searchable").uncheck()
    for key in ("selectable", "sortable", "searchable"):
        expect(dialog.get_by_test_id(f"render-hint-{key}")).not_to_be_checked()
    # And ticking one that needs it brings it back (p.250).
    dialog.get_by_test_id("render-hint-regex").check()
    expect(dialog.get_by_test_id("render-hint-searchable")).to_be_checked()
    dialog.get_by_test_id("render-hint-long_text").check()
    page.get_by_role("button", name="Done").click()
    expect(button).to_have_text("Hints (3)")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    eventually(lambda: hints(api, notes)["body"],
               lambda got: got == ["long_text", "searchable", "regex"],
               what="the hints saved")
    # Opened again, the checklist holds what was saved.
    open_type_editor(page, notes)
    page.get_by_role("button", name=f"Property {row} render hints").click()
    dialog = page.locator(".render-hints")
    expect(dialog.get_by_test_id("render-hint-long_text")).to_be_checked()
    expect(dialog.get_by_test_id("render-hint-sortable")).not_to_be_checked()


def test_p91_s_bulk_edit_changes_render_hints(page, api, notes) -> None:
    """p.91: "Once multiple properties are selected, the following bulk
    editing actions become available: … Changing render hints." """
    open_type_editor(page, notes)
    names = names_of(page)
    for name in ("name", "code"):
        page.get_by_label(f"Select property {names.index(name) + 1}").check()
    bar = page.get_by_test_id("property-bulk")
    bar.get_by_label("Turn a render hint on").select_option("identifier")
    bar.get_by_label("Turn a render hint off").select_option("sortable")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    eventually(lambda: hints(api, notes),
               lambda got: got["name"] == got["code"] == ["identifier", "selectable", "searchable"],
               what="the bulk edit saved")


def test_a_shared_property_s_hints_stand_in_for_the_property_s(page, api) -> None:
    """p.188: "using the shared property will override the configuration
    values of the selected property" - so the row's own control is disabled
    while attached, as Format is."""
    people = Module(api, "Shared hints")
    type_id = people.object_type(columns=["id", "name", "began"], rows=[
        {"id": "P1", "name": "Ada", "began": "2020-01-05"}], key="id", title="name",
        types={"began": "date"})
    name = f"Hinted {uuid.uuid4().hex[:4]}"
    open_objects(page, people)
    page.get_by_test_id("new-shared-property").click()
    page.get_by_test_id("shared-name").fill(name)
    page.get_by_test_id("shared-type").select_option("date")
    page.get_by_test_id("shared-hint-sortable").uncheck()
    page.get_by_test_id("shared-hint-keywords").check()
    page.get_by_test_id("shared-save").click()
    api_name = name.lower().replace(" ", "_")
    expect(page.get_by_test_id("shared-table")).to_contain_text(api_name)

    open_type_editor(page, people)
    index = property_index(page, "began")
    page.get_by_role("button", name=f"Property {index} shared").click()
    page.get_by_test_id("shared-choice").select_option(label=f"{name} ({api_name})")
    page.get_by_test_id("shared-apply").click()
    hinted = page.get_by_role("button", name=f"Property {index} render hints")
    expect(hinted).to_be_disabled()
    expect(hinted).to_have_text("Hints (3)")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    got = api.call("GET", f"/workspaces/{people.workspace_id}/object-types/{type_id}")
    began = next(p for p in got["properties"] if p["api_name"] == "began")
    assert began["render_hints"] == ["keywords", "selectable", "searchable"]
