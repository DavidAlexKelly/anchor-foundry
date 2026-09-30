"""A parameter's default taken from an object (§588; `action-types` p.27,
p.29).

> "...configuring the value of each parameter to be prefilled from the
>  currently selected object... In Object Explorer, the Change Airplane
>  Details action will be prefilled with current values. In this case, users
>  could choose to modify just one property and keep the rest the same."
>  (p.29)

Set in the editor, then met in a Workshop form: choosing a plane fills the
parameters that read it, a value somebody typed is left alone, and what is
submitted is the plane's values plus the one change.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_module, settled
from test_action_definition_editor import definition, open_editor


@pytest.fixture(scope="module")
def planes(api):
    mod = Module(api, "Object defaults")
    mod.type_id = mod.object_type(
        columns=["key", "model", "hours"],
        rows=[{"key": "P1", "model": "A320", "hours": "1200"},
              {"key": "P2", "model": "A380", "hours": "800"},
              {"key": "P3", "model": "B737", "hours": "300"}],
        key="key", title="key", types={"hours": "integer"},
    )
    mod.action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"details_{uuid.uuid4().hex[:8]}",
        "display_name": "Change airplane details", "editable_properties": ["model", "hours"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition", {
        "parameters": [
            {"api_name": "plane", "display_name": "Plane", "data_type": "object",
             "object_type_id": mod.type_id},
            {"api_name": "model", "display_name": "Model", "data_type": "string"},
            {"api_name": "hours", "display_name": "Hours", "data_type": "integer"},
        ],
        "rules": [{"kind": "modify_object", "config": {"property": p, "parameter": p}}
                  for p in ("model", "hours")],
        "criteria": [],
    })
    return mod


def test_p29_in_the_editor(page, api, planes) -> None:
    open_editor(page, planes)
    row = page.locator('[data-default-from="model"]')
    row.get_by_label("Default for model from").select_option("plane")
    row.get_by_label("Default for model property").select_option("model")
    page.locator('[data-default-from="hours"]').get_by_label(
        "Default for hours from").select_option("plane")
    page.locator('[data-default-from="hours"]').get_by_label(
        "Default for hours property").select_option("hours")
    # A fixed default and one from an object are one or the other (p.27).
    expect(page.get_by_label("Parameter 2 default")).to_be_disabled()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    by_name = {p["api_name"]: p for p in definition(api, planes)["parameters"]}
    assert by_name["model"]["default_from"] == {"parameter": "plane", "property": "model"}
    assert by_name["hours"]["default_from"] == {"parameter": "plane", "property": "hours"}
    # Reopened, it is still there: the dialog saves parameters whole.
    open_editor(page, planes)
    expect(page.locator('[data-default-from="model"]').get_by_label(
        "Default for model from")).to_have_value("plane")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert {p["api_name"]: p for p in definition(api, planes)["parameters"]}[
        "model"]["default_from"]


def build(api, planes, name: str) -> Module:
    mod = Module(api, name, beside=planes)
    mod.type_id = planes.type_id
    mod.define({
        "format": 2,
        "layout": layout({"form": {"resolvedName": "CanvasActionForm", "props": {
            "actionTypeId": planes.action["id"], "objectVariable": None}}}),
        "variables": {}, "events": {},
    })
    return mod


def stored(api, mod, key: str):
    def read():
        found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                         {"definition": {"object_type_id": mod.type_id, "filters": []},
                          "limit": 10})["instances"]
        return next(i for i in found if i["properties"]["key"] == key)["properties"]
    return read


def test_choosing_the_object_fills_what_reads_it(page, api, planes) -> None:
    api.call("PUT", f"/workspaces/{planes.workspace_id}/action-types/"
                    f"{planes.action['id']}/definition", {
        "parameters": [
            {"api_name": "plane", "display_name": "Plane", "data_type": "object",
             "object_type_id": planes.type_id},
            {"api_name": "model", "display_name": "Model", "data_type": "string",
             "default_from": {"parameter": "plane", "property": "model"}},
            {"api_name": "hours", "display_name": "Hours", "data_type": "integer",
             "default_from": {"parameter": "plane", "property": "hours"}},
        ],
        "rules": [{"kind": "modify_object", "config": {"property": p, "parameter": p}}
                  for p in ("model", "hours")],
        "criteria": [],
    })
    mod = build(api, planes, "Object defaults form")
    open_module(page, mod)
    settled(page)
    page.locator("form select").first.select_option(label="P3")
    # Typed before the plane is chosen: somebody's answer, left alone.
    page.locator('[data-parameter="hours"] input').fill("5")
    page.locator('[data-parameter="plane"] select').select_option(label="P2")
    expect(page.locator('[data-parameter="model"] input')).to_have_value("A380")
    expect(page.locator('[data-parameter="hours"] input')).to_have_value("5")
    page.get_by_role("button", name="Submit").click()
    eventually(stored(api, mod, "P3"),
               lambda v: (v.get("model"), v.get("hours")) == ("A380", 5),
               what="the plane's model and the one typed change")
