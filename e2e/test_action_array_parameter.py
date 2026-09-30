"""Array parameters in an action form (§580; db 0118; `object-link-types`
p.86, p.116; `action-types` p.127).

> "Array properties cannot be empty: Setting an array property to required
>  ensures the presence of at least one item." (p.116)

An array parameter draws one control per element, each the element type's
own, with Add and Remove - the control that collects several values the
parameter waited for. Asserted through the object, not the form: an array
written element by element and coerced against its element type is the whole
path holding.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_module, settled
from test_action_definition_editor import definition, open_editor

ROWS = [
    {"site_id": "1", "tags": '["seed"]', "counts": "[1]", "docs": "[]"},
    {"site_id": "2", "tags": "[]", "counts": "[]", "docs": "[]"},
    {"site_id": "3", "tags": "[]", "counts": "[]", "docs": "[]"},
    {"site_id": "4", "tags": "[]", "counts": "[5, 6]", "docs": "[]"},
]


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Action arrays")
    mod.type_id = mod.object_type(
        columns=["site_id", "tags", "counts", "docs"], rows=ROWS, key="site_id",
        title="site_id", types={"tags": "array", "counts": "array", "docs": "array"},
        array_of={"tags": "string", "counts": "integer", "docs": "attachment"},
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"tag_{uuid.uuid4().hex[:8]}",
        "display_name": "Tag site", "editable_properties": ["tags"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [
            {"api_name": "tags", "display_name": "Tags", "data_type": "array",
             "array_of": "string", "required": True},
            {"api_name": "counts", "display_name": "Counts", "data_type": "array",
             "array_of": "integer"},
            {"api_name": "docs", "display_name": "Docs", "data_type": "array",
             "array_of": "attachment"},
        ],
        "rules": [{"kind": "modify_object", "config": {"property": p, "parameter": p}}
                  for p in ("tags", "counts", "docs")],
        "criteria": [],
    })
    mod.action = action
    return mod


def build(api, sites, name: str) -> Module:
    mod = Module(api, name, beside=sites)
    mod.type_id = sites.type_id
    mod.define({
        "format": 2,
        "layout": layout({"form": {"resolvedName": "CanvasActionForm", "props": {
            "actionTypeId": sites.action["id"], "objectVariable": None}}}),
        "variables": {}, "events": {},
    })
    return mod


def field(page, name: str):
    return page.locator(f'[data-parameter="{name}"]')


def rows(page, name: str):
    return field(page, name).get_by_test_id("array-item")


def add(page, name: str) -> None:
    field(page, name).get_by_test_id("array-item-add").click()


def stored(api, mod, site: str, prop: str):
    def read():
        found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": mod.type_id, "filters": []},
                          "limit": 10})["instances"]
        return next(i for i in found if i["properties"]["site_id"] == site)["properties"].get(prop)
    return read


def test_rows_are_added_typed_and_sent_without_the_blank_ones(page, api, sites) -> None:
    mod = build(api, sites, "Array form rows")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="2")
    add(page, "tags")
    rows(page, "tags").nth(0).locator("input").fill("north")
    add(page, "tags")  # left blank: somebody pressed Add and changed their mind
    add(page, "tags")
    rows(page, "tags").nth(2).locator("input").fill("coastal")
    add(page, "counts")
    counts = rows(page, "counts").nth(0).locator("input")
    expect(counts).to_have_attribute("type", "number")
    counts.fill("7")
    page.get_by_role("button", name="Submit").click()
    eventually(stored(api, mod, "2", "tags"), lambda v: v == ["north", "coastal"],
               what="the tags, without the blank row")
    # The integer is the assertion: the element type reached the coercer.
    eventually(stored(api, mod, "2", "counts"), lambda v: v == [7], what="the counts")


def test_a_required_array_needs_a_row_with_something_in_it(page, api, sites) -> None:
    mod = build(api, sites, "Array form required")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="3")
    submit = page.get_by_role("button", name="Submit")
    expect(submit).to_be_disabled()
    add(page, "tags")
    expect(submit).to_be_disabled()
    rows(page, "tags").nth(0).locator("input").fill("x")
    expect(submit).to_be_enabled()


def test_an_objects_array_is_its_rows_and_a_row_can_go(page, api, sites) -> None:
    """p.25's seeding fills the form from the object, so an edit form shows
    the array it would change; removing a row is how an element goes."""
    mod = build(api, sites, "Array form seeded")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="4")
    expect(rows(page, "counts")).to_have_count(2)
    expect(rows(page, "counts").nth(1).locator("input")).to_have_value("6")
    field(page, "counts").get_by_test_id("array-item-remove").first.click()
    expect(rows(page, "counts")).to_have_count(1)
    add(page, "tags")
    rows(page, "tags").nth(0).locator("input").fill("kept")
    page.get_by_role("button", name="Submit").click()
    eventually(stored(api, mod, "4", "counts"), lambda v: v == [6], what="one count left")


def test_several_attachments_through_one_parameter(page, api, sites, tmp_path) -> None:
    """p.127's "Allow multiple values" for an attachment parameter: an array
    of attachments, each row its own upload."""
    mod = build(api, sites, "Array form attachments")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="1")
    for n, text in enumerate(("first", "second")):
        add(page, "docs")
        upload = tmp_path / f"{text}.txt"
        upload.write_text(text)
        picker = rows(page, "docs").nth(n).locator("input[type=file]")
        picker.set_input_files(str(upload))
        expect(rows(page, "docs").nth(n)).to_contain_text(f"Attached: {text}.txt")
    page.get_by_role("button", name="Submit").click()
    got = eventually(stored(api, mod, "1", "docs"),
                     lambda v: isinstance(v, list) and len(v) == 2, what="two attachments")
    assert [d["filename"] for d in got] == ["first.txt", "second.txt"]


def test_the_editor_declares_an_array_and_what_it_holds(page, api) -> None:
    from test_action_definition_editor import build as build_editor

    mod = build_editor(api, "Array editor")
    open_editor(page, mod)
    page.get_by_label("Parameter 1 type").select_option("array")
    element = page.get_by_label("Parameter 1 element type")
    expect(element).to_have_value("string")
    element.select_option("attachment")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, mod)["parameters"]
    assert (parameter["data_type"], parameter["array_of"]) == ("array", "attachment")
    # Reopened, the element type is still there: the dialog saves parameters
    # whole, so one it did not load it would overwrite with nothing.
    open_editor(page, mod)
    expect(page.get_by_label("Parameter 1 element type")).to_have_value("attachment")
    page.get_by_label("Parameter 1 label").fill("Evidence")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, mod)["parameters"]
    assert parameter["array_of"] == "attachment"
    # And a type that is not an array carries no element type: a switch away
    # that kept it would save a declaration the server refuses.
    open_editor(page, mod)
    page.get_by_label("Parameter 1 type").select_option("string")
    expect(page.get_by_label("Parameter 1 element type")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    [parameter] = definition(api, mod)["parameters"]
    assert (parameter["data_type"], parameter["array_of"]) == ("string", None)
