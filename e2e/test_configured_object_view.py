"""Configured Object Views (parity `ontology.md` §4.2; Foundry `object-views` p.2–4).

    "Configured Object Views are fully customizable representations of an
     object built using Workshop… Standard Object Views remain accessible even
     after a configured Object View is built." (p.2)

Both halves of that sentence need a browser. The API tests can say a row was
written; only this can say the module **renders in place of the generated
view, with the object in it**, and that the standard view is still one click
away.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually

ROWS = [
    {"id": "C1", "name": "Alpha customer", "region": "north"},
    {"id": "C2", "name": "Beta customer", "region": "south"},
]


@pytest.fixture(scope="module")
def module(api):
    """An object type, and a published module that shows one of its properties.

    The module reads the object through a derived variable rather than
    rendering a literal: a text widget with the answer typed into it would pass
    every assertion below without the object ever arriving.
    """
    mod = Module(api, "Configured object view")
    type_id = mod.object_type(
        columns=["id", "name", "region"],
        rows=ROWS,
        key="id",
        title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Region: {{v_region}}"}},
        }),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The customer"},
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                               "config": {"property": "region"}},
            },
        },
        "events": {},
    })
    mod.api.call(
        "PUT", f"{mod.base}/canvas-apps/{mod.app_id}/publish", {"scope": "workspace"},
    )
    mod.api.call(
        "PUT", f"/workspaces/{mod.workspace_id}/object-types/{type_id}/view",
        {"canvas_app_id": mod.app_id, "subject_variable": "v_obj"},
    )
    return mod


def open_first_object(page, module, expected: int = len(ROWS)):
    """Open the Explorer filtered to this fixture's type, and click in.

    Filtered for `test_standard_object_view.py`'s reason: the Explorer is
    workspace-wide and this dev database carries every object every previous
    run created, so "the first row" is somebody else's object.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == expected,
               what="this type's objects, and only this type's")
    rows.first.get_by_role("button", name="Explore").click()


def test_the_configured_view_renders_instead_of_the_generated_one(page, module):
    """p.2: a configured view is what a reader gets. The generated one is not
    drawn underneath it - two views of the same object stacked would be worse
    than either."""
    open_first_object(page, module)
    expect(page.get_by_test_id("configured-object-view")).to_be_visible()
    expect(page.get_by_test_id("standard-object-view")).to_have_count(0)


def test_the_object_reaches_the_module_through_its_subject_variable(page, module):
    """**The binding, and the only thing here the API tests cannot see.** The
    text is derived from the object's `region` through `object_property`, so it
    can only read "north" if the instance actually arrived in `v_obj` - a
    module rendering with an unbound variable shows the interpolation
    unresolved or empty."""
    open_first_object(page, module)
    view = page.get_by_test_id("configured-object-view")
    eventually(lambda: view.inner_text(), lambda t: "Region: north" in t,
               what="the object's own property, resolved inside the module")


def test_the_standard_view_is_still_one_click_away(page, module):
    """p.2: standard views "remain accessible even after a configured Object
    View is built". Not a preference to be found in a settings panel - a
    control on the view itself."""
    open_first_object(page, module)
    expect(page.get_by_test_id("configured-object-view")).to_be_visible()

    page.get_by_role("button", name="Standard view").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    expect(page.get_by_test_id("configured-object-view")).to_have_count(0)
    # And the generated view is the real one, not a placeholder: the title
    # property's value is in it.
    expect(page.get_by_test_id("standard-object-view")).to_contain_text("Alpha customer")


def test_switching_back_returns_to_the_configured_view(page, module):
    """The switch is a reader's, so it goes both ways. A one-way escape hatch
    would mean leaving the object and coming back."""
    open_first_object(page, module)
    page.get_by_role("button", name="Standard view").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    page.get_by_role("button", name=f"App {module.tag}").click()
    expect(page.get_by_test_id("configured-object-view")).to_be_visible()


def test_a_type_with_no_configured_view_shows_no_switch(page, api):
    """The control exists because there is a choice. On a type with only the
    generated view there is none, and a button offering "Standard view" when
    that is all there has ever been would be a question nobody asked."""
    other = Module(api, "No configured view")
    other.object_type(columns=["id", "name"], rows=[{"id": "N1", "name": "Plain"}], key="id")
    open_first_object(page, other, expected=1)
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    expect(page.get_by_role("button", name="Standard view")).to_have_count(0)


def test_the_ontology_manager_nominates_a_module_as_the_view(page, api):
    """The authoring half. Two choices, and the second is a list of *that*
    module's single-object variables - which is why the dialog cannot be
    tested by typing an id: the list is the thing being asserted.
    """
    mod = Module(api, "Object view editor")
    type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "E1", "name": "Editable"}], key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "hello"}},
        }),
        "variables": {
            "v_here": {"id": "v_here", "kind": "single_object", "label": "This object"},
            "v_txt": {"id": "v_txt", "kind": "string", "label": "Some text"},
        },
        "events": {},
    })
    mod.api.call(
        "PUT", f"{mod.base}/canvas-apps/{mod.app_id}/publish", {"scope": "workspace"},
    )

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    # **Filtered by the button, not only by the name.** This page has two tables
    # that mention an object type - the types themselves and the dataset
    # mappings below them - so matching on the name alone is two rows, and
    # Playwright refuses an ambiguous locator rather than picking one. The
    # types table is the one with a View button in it.
    row = page.locator("tr", has_text=f"Seed {mod.tag}").filter(
        has=page.get_by_role("button", name="View")
    )
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="View").click()
    expect(page.get_by_role("dialog")).to_be_visible()

    page.get_by_label("Object view module").select_option(label=f"App {mod.tag}")
    # `v_txt` is a string variable and has no business receiving an object, so
    # it is not offered. Offering it would offer a binding the server refuses.
    subjects = page.get_by_label("Object view subject variable")
    expect(subjects.locator("option")).to_have_text(["Choose…", "This object"])
    subjects.select_option("v_here")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    stored = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{type_id}/view"
    )
    assert stored["canvas_app_id"] == mod.app_id
    assert stored["subject_variable"] == "v_here"
