"""An action type on an interface, on the screens (`action-types` p.59-64;
§451).

> "Actions created with interface action rules can be applied to objects whose
> object type implements the interface, just like any object-specific action
> type. For a given object, all object-type-specific and interface-based
> actions that can be applied to that object will appear in the action
> dropdown." (p.64)

> "An 'interface reference' parameter will be generated, constrained to the
> selected interface… the 'interface reference' parameter shows objects of any
> type that implements the interface. If using a form or a table, the user
> could then pick an object from a list." (p.62)

**What needs a browser is that one form reaches two types.** The rename itself
is a pure function and is tested as one; the executor is checked in
`apps/api/tests/test_interface_actions.py`. Neither can see the thing this file
sees: a Record dropdown holding objects from two different datasets, a
submission that lands in whichever column the picked object's type calls the
interface's property, and an Actions table that has a name to show for an
action with no object type at all.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, eventually, open_module, settled

FACILITIES = [
    {"code": "F1", "surveyed_on": "2026-01-04"},
    {"code": "F2", "surveyed_on": "2026-02-02"},
]
VEHICLES = [
    {"vin": "V1", "checked_on": "2026-03-03"},
]


@pytest.fixture(scope="module")
def world(api):
    """`ontology` p.60-62's own example: `Inspectable`, implemented by two
    types that keep its property in differently named columns of different
    datasets.

    **Staged through the API rather than the dialogs.** Declaring an interface
    and implementing it are `test_interfaces.py`'s subject and are checked
    there; repeating them here would make this file's failures ambiguous
    between "the action is wrong" and "the fixture never got built".
    """
    mod = Module(api, "Interface actions")
    facility = mod.object_type(
        columns=["code", "surveyed_on"], rows=FACILITIES,
        key="code", title="code", slug=f"facilities_{mod.tag}",
    )
    vehicle = mod.object_type(
        columns=["vin", "checked_on"], rows=VEHICLES,
        key="vin", title="vin", slug=f"vehicles_{mod.tag}",
    )
    interface = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/interfaces",
        {
            "api_name": f"Inspectable{mod.tag}",
            "display_name": f"Inspectable {mod.tag}",
            "properties": [
                {"api_name": "last_inspection_date",
                 "display_name": "Last inspection",
                 "data_type": "string", "required": True},
            ],
        },
    )
    for type_id, column in ((facility, "surveyed_on"), (vehicle, "checked_on")):
        api.call(
            "PUT", f"/workspaces/{mod.workspace_id}/object-types/{type_id}/interfaces",
            [{"interface_id": interface["id"],
              "property_mapping": {"last_inspection_date": column}}],
        )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"interface_id": interface["id"],
         "api_name": f"inspect_{uuid.uuid4().hex[:8]}",
         "display_name": "Record inspection",
         "editable_properties": ["last_inspection_date"]},
    )
    mod.interface = interface
    mod.facility = facility
    mod.vehicle = vehicle
    mod.action = action
    return mod


def form(api, world, name: str):
    mod = Module(api, name, beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {
                "resolvedName": "CanvasActionForm",
                "props": {"actionTypeId": world.action["id"], "objectVariable": None},
            },
        }),
        "variables": {},
        "events": {},
    })
    return mod


def record(page):
    return page.locator("form select").first


def stored(api, world, type_id: str, key: str, column: str):
    rows = api.call(
        "POST", f"/workspaces/{world.workspace_id}/object-sets/evaluate",
        {"definition": {"object_type_id": type_id, "filters": []}, "limit": 10},
    )["instances"]
    one = next(r for r in rows if r["primary_key"] == key)
    return (one.get("properties") or {}).get(column)


def test_the_record_list_holds_objects_of_every_implementing_type(
    page, api, world
) -> None:
    """p.62: the interface reference "shows objects of any type that implements
    the interface".

    **Both types, asserted together.** Either alone passes for a dropdown that
    read one type and stopped — which is exactly what the form did before
    §451, because it asked for the action's `object_type_id` and an interface
    action has none.
    """
    mod = form(api, world, "Interface record list")
    open_module(page, mod)
    settled(page)

    options = record(page).locator("option")
    expect(options).to_have_count(4)  # "Choose…" plus F1, F2 and V1
    texts = set(options.all_text_contents())
    assert {"F1", "F2", "V1"} <= texts, texts


def test_submitting_writes_whichever_column_the_picked_type_uses(
    page, api, world
) -> None:
    """**p.59's promise, through one form.**

    The same action, submitted twice against objects of two types, lands in
    `surveyed_on` on one and `checked_on` on the other — which is the
    implementation's mapping doing its work. Read back off each object, because
    a form that says "Saved." is the form agreeing with itself.
    """
    mod = form(api, world, "Interface submit")
    open_module(page, mod)
    settled(page)

    for key, type_id, column, said in (
        ("F1", world.facility, "surveyed_on", "2027-05-05"),
        ("V1", world.vehicle, "checked_on", "2027-06-06"),
    ):
        record(page).select_option(label=key)
        page.get_by_label("Last inspection", exact=True).fill(said)
        page.get_by_role("button", name="Submit").click()
        expect(page.locator("text=Saved.")).to_be_visible(timeout=15000)
        got = eventually(
            lambda t=type_id, k=key, c=column: stored(api, world, t, k, c),
            lambda v, s=said: v == s,
            what=f"the inspection date on {key}",
        )
        assert got == said, got


def test_the_actions_table_names_the_interface_it_acts_on(page, api, world) -> None:
    """The Ontology Manager's Actions table has a *subject* column, and an
    interface action has no object type to fill it.

    **The cell, not the row.** A row that merely appears passes for a table
    that renders an empty subject — which is what `object_type_name` gives for
    an interface action, and TypeScript is perfectly happy with it.
    """
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible(
        timeout=30000
    )
    row = page.locator("tbody tr").filter(has_text="Record inspection").first
    expect(row).to_be_visible(timeout=30000)
    expect(row).to_contain_text(world.interface["display_name"])


def test_the_rule_editor_offers_the_interfaces_shared_properties(
    page, api, world
) -> None:
    """p.59: "you can use interface action rules only to modify the interface
    shared properties".

    The picker asked for `action.object_type_id`, which on an interface action
    is `null` — and `String(null)` is `"null"`, so it looked up an object type
    by that name and offered nothing. **The assertion is what it offers**, not
    that the dialog opens: an empty dropdown opens perfectly well.
    """
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible(
        timeout=30000
    )
    row = page.locator("tbody tr").filter(has_text="Record inspection").first
    row.get_by_role("button", name="Parameters").click()

    picker = page.get_by_role("combobox", name="Rule 1 property")
    expect(picker).to_be_visible(timeout=15000)
    expect(picker.locator("option")).to_contain_text(["Last inspection"])


def test_the_explorer_does_not_offer_an_interface_action_for_inline_editing(
    page, api, world
) -> None:
    """p.135's inline edit writes one object type's dataset.

    An interface action is refused by `inline_edit_refusals`, so the Explorer —
    which offers only eligible actions — has nothing to offer on a type whose
    *only* action is this one. **The results table is the positive** this
    absence is measured against (§318): without it the assertion passes on a
    page that has not drawn.
    """
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/explore?type={world.vehicle}")
    expect(page.locator("tbody tr").first).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("explorer-edit-start")).to_have_count(0)


def test_an_ordinary_actions_form_never_asks_for_an_interface_set(
    page, api, world
) -> None:
    """**A claim about the network that no assertion about the screen can
    reach** (§327).

    The form asks §254's interface set only for an interface action. An
    unguarded query would fire it for every action too — with `undefined` where
    the interface id goes — and nothing on the page would look any different,
    because the dropdown does not read that answer for an object action.

    So the request is watched, and a *positive* is waited for first: the
    ordinary form's own Record list, which is drawn from the read this one is
    asserted not to replace (§318).
    """
    ordinary = api.call(
        "POST", f"/workspaces/{world.workspace_id}/action-types",
        {"object_type_id": world.facility,
         "api_name": f"plain_{uuid.uuid4().hex[:8]}",
         "display_name": "Facility only",
         "editable_properties": ["surveyed_on"]},
    )
    mod = Module(api, "Ordinary action form", beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {"resolvedName": "CanvasActionForm",
                     "props": {"actionTypeId": ordinary["id"], "objectVariable": None}},
        }),
        "variables": {},
        "events": {},
    })

    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/evaluate" in r.url
            and "/interfaces/" in r.url else None)
    open_module(page, mod)
    settled(page)
    expect(record(page).locator("option")).to_have_count(3)  # Choose…, F1, F2
    assert asked == [], asked
