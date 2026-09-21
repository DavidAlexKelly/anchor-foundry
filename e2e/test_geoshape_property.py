"""A geoshape property, end to end (§425; `object-link-types` p.127, p.273;
`functions` p.40).

> "Geoshape: A type for defining properties that represent geographic shapes."
>  (p.127)

> "GeoShape represents any valid GeoJSON geometry… Note that positional
>  arguments follow **longitude, latitude** order as per the GeoJSON spec."
>  (`functions` p.40)

What a geometry is, and which ones are refused, is
`apps/api/tests/test_property_types.py`'s; what a cell says about one is
`apps/web/src/lib/geoshape.test.ts`'s. Three things need a browser:

* **the round trip** — a shape declared through the dropdown, synced from a
  column and read back as the geometry it was, which is the only way to know
  the editor, the sync and the API agree about a type none of them typechecks
  against the others;
* **the cell**, because a polygon that stored correctly and drew as
  `[object Object]` is the half the server cannot deliver;
* **the coordinate order said where somebody types one**, which is this type's
  whole hazard: a geopoint is lat,lon and a geoshape is [lon, lat], the two sit
  in the same form, and a value with them swapped is valid and in the wrong
  hemisphere.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

import uuid

from api import Module, layout
from conftest import WEB_BASE, open_module
from ontology_page import find_type_row, save_type

SQUARE = json.dumps({
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
})
LONDON = json.dumps({"type": "Point", "coordinates": [-0.1278, 51.5074]})


@pytest.fixture(scope="module")
def module(api):
    """One column already a geoshape and one still a string.

    Separate columns for the reason `test_array_property_editor` writes down:
    a test that only passes after another one is not a test.
    """
    mod = Module(api, "Geoshape property")
    mod.object_type(
        columns=["code", "outline", "spare"],
        rows=[{"code": "A1", "outline": SQUARE, "spare": LONDON}],
        key="code",
        title="code",
        types={"outline": "geoshape"},
    )
    return mod


def properties(api, module) -> dict[str, dict]:
    detail = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )
    return {p["api_name"]: p for p in detail["properties"]}


def open_type_editor(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = find_type_row(page, f"seed_{module.tag}")
    row.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible()


def property_row(page, api_name: str) -> int:
    names = page.get_by_role("textbox", name="Property")
    for index in range(names.count()):
        box = page.get_by_role("textbox", name=f"Property {index + 1} name")
        if box.input_value() == api_name:
            return index + 1
    raise AssertionError(f"no property row named {api_name!r}")


def test_a_geoshape_is_declared_through_the_dropdown(page, api, module) -> None:
    """**On the dropdown the day it exists**, unlike `struct`: p.127's type is
    a GeoJSON geometry, and a geometry is a value somebody pastes rather than
    a declaration with a shape of its own — so there is no second control to
    wait for.

    Read back from the API rather than from the dialog, because a dialog that
    showed the type while having sent something else would look right.
    """
    open_type_editor(page, module)
    index = property_row(page, "spare")
    page.get_by_role("combobox", name=f"Property {index} type").select_option("geoshape")
    save_type(page)
    assert properties(api, module)["spare"]["data_type"] == "geoshape"


def test_a_geometry_synced_from_a_column_arrives_as_a_geometry(api, module) -> None:
    """The round trip the type exists for: a CSV column holds text, and the
    sync reads it back as the object the API returns."""
    rows = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/"
        f"{module.object_type_id}/instances",
    )
    held = rows["items"][0]["properties"]["outline"]
    assert held["type"] == "Polygon", held
    assert held["coordinates"][0][0] == [0.0, 0.0], held


def test_the_cell_says_what_the_shape_is_rather_than_its_coordinates(
    page, module
) -> None:
    """A polygon's coordinates are a paragraph, and a cell holding them would
    push every other column off the screen — the type and the size are what
    tell a reader whether this is the shape they meant.

    **The coordinates being absent is the assertion**, not the summary being
    present: a cell that fell through to the `json` rendering would contain
    "Polygon" too, and asserting only on that would pass over exactly the bug
    this test is for (`test_array_property_editor` wrote the same sentence).
    """
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}"
        f"/objects/{module.object_type_id}"
    )
    cell = page.get_by_test_id("geoshape-value").first
    expect(cell).to_be_visible(timeout=30000)
    expect(cell).to_have_text("Polygon · 5 points")
    assert "[" not in cell.inner_text(), cell.inner_text()
    # And the value itself is one hover away rather than gone.
    assert '"coordinates"' in (cell.get_attribute("title") or "")


@pytest.fixture(scope="module")
def form(api):
    """An action form with a geoshape parameter on it.

    **This is what makes the type writable at all**, and why §425 added the
    label to `action_parameter_type` as well: every edit to an instance goes
    through an action, so a geoshape that could be declared and synced but
    never typed would be half a type. `action-types` p.131 says the parameter
    exists ("Geoshape | Geoshape | Yes"), so it does here.
    """
    mod = Module(api, "Geoshape form")
    type_id = mod.object_type(
        columns=["code", "outline"],
        rows=[{"code": "A1", "outline": SQUARE}],
        key="code", title="code",
        types={"outline": "geoshape"},
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"redraw_{uuid.uuid4().hex[:8]}",
            "display_name": "Redraw parcel",
            "editable_properties": ["outline"],
        },
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "outline", "display_name": "Outline",
                 "data_type": "geoshape", "required": True},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "outline", "parameter": "outline"}},
            ],
            "criteria": [],
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = type_id
    return mod


def test_the_form_says_which_order_it_wants(page, form) -> None:
    """**The hazard this type carries into every form it appears in.** A
    geopoint is lat,lon (`object-link-types` p.273) and a geoshape's positions
    are [longitude, latitude] (`functions` p.40). The two sit in the same
    form, and a value with them swapped is valid, plottable and in the wrong
    hemisphere — so the control says which it wants rather than leaving a
    reader to remember it.
    """
    open_module(page, form)
    page.locator("form select").select_option(index=1)
    field = page.locator("[data-parameter='outline'] input")
    expect(field).to_be_visible()
    placeholder = field.get_attribute("placeholder") or ""
    assert "longitude, latitude" in placeholder, placeholder
    # And it is not the geopoint's, which is the one wrong answer that would
    # look right: both are coordinate hints and only one names this order.
    assert "lat,lon" not in placeholder, placeholder


def test_a_geometry_typed_into_the_form_is_stored_as_one(page, api, form) -> None:
    """The write path, which is the half a declaration alone does not give:
    the value leaves the form as text and has to arrive as a geometry."""
    open_module(page, form)
    page.locator("form select").select_option(index=1)
    field = page.locator("[data-parameter='outline'] input")
    field.fill(LONDON)
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")

    items = api.call(
        "GET",
        f"/workspaces/{form.workspace_id}/object-types/{form.type_id}/instances",
    )["items"]
    held = items[0]["properties"]["outline"]
    assert held == {"type": "Point", "coordinates": [-0.1278, 51.5074]}, held


def test_a_transposed_pair_is_refused_rather_than_stored(page, form) -> None:
    """**Where the platform can tell, it tells.** 120 is a legal longitude and
    not a legal latitude, so [45, 120] is a pair somebody typed the wrong way
    round — and the refusal says which order it wanted rather than "invalid".
    """
    open_module(page, form)
    page.locator("form select").select_option(index=1)
    page.locator("[data-parameter='outline'] input").fill(
        '{"type":"Point","coordinates":[45,120]}'
    )
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("longitude, latitude")
