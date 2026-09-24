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


def _plain_type(api, world, name: str, key: str, column: str, rows: bytes) -> str:
    """An object type whose **key column is not a required property**.

    `Module.object_type` marks it required, which is right for a table that is
    only ever read: p.116 then refuses a *create* that does not set it, and
    every create here would be about that rather than about p.60. The key is a
    dataset column and not a property (`object_creations`' own argument), so a
    type that maps only its data columns is the honest fixture for a create.
    """
    tag = uuid.uuid4().hex[:6]
    dataset = api.upload_csv(
        f"/workspaces/{world.workspace_id}/projects/{world.project_id}/datasets/upload",
        f"{name} {tag}", rows,
    )
    declared = api.call(
        "POST", f"/workspaces/{world.workspace_id}/object-types",
        {"api_name": f"{name}{tag}", "display_name": f"{name} {tag}",
         "properties": [{"api_name": column, "display_name": column.title(),
                         "data_type": "string"}]},
    )
    source = api.call(
        "POST", f"/workspaces/{world.workspace_id}/projects/{world.project_id}"
                f"/object-type-sources",
        {"object_type_id": declared["id"], "dataset_id": dataset["id"],
         "primary_key_column": key, "column_mappings": {column: column}},
    )
    api.call(
        "POST", f"/workspaces/{world.workspace_id}/projects/{world.project_id}"
                f"/object-type-sources/{source['id']}/sync", None,
    )
    return declared["id"]


def test_a_create_on_an_interface_asks_which_object_type_to_make(
    page, api, world
) -> None:
    """`action-types` p.60: "an 'Object type' parameter will be automatically
    generated to indicate the object type that should be created. If using a
    form or a table, the user will be prompted to **pick an object type from a
    list**."

    **The list is the interface's implementations**, and both halves are
    asserted: either alone passes for a picker that offered every object type
    in the workspace, which is a control whose extra options can only ever be
    refused (§214).

    Then the submission, read back off the type that was chosen — because
    p.59's example is one action making bugs *and* feature requests, and a
    picker that drew correctly while the create ignored it would look
    identical.
    """
    interface = api.call(
        "POST", f"/workspaces/{world.workspace_id}/interfaces",
        {"api_name": f"Raisable{world.tag}", "display_name": f"Raisable {world.tag}",
         "properties": [{"api_name": "raised_on", "display_name": "Raised on",
                         "data_type": "string", "required": True}]},
    )
    bugs = _plain_type(api, world, "Bugs", "bug_id", "found_on",
                       b"bug_id,found_on\nB0,2020-01-01\n")
    wishes = _plain_type(api, world, "Wishes", "wish_id", "asked_on",
                         b"wish_id,asked_on\nW0,2020-01-01\n")
    for type_id, column in ((bugs, "found_on"), (wishes, "asked_on")):
        api.call(
            "PUT",
            f"/workspaces/{world.workspace_id}/object-types/{type_id}/interfaces",
            [{"interface_id": interface["id"],
              "property_mapping": {"raised_on": column}}],
        )
    action = api.call(
        "POST", f"/workspaces/{world.workspace_id}/action-types",
        {"interface_id": interface["id"],
         "api_name": f"raise_{uuid.uuid4().hex[:8]}",
         "display_name": "Raise", "editable_properties": ["raised_on"]},
    )
    api.call(
        "PUT", f"/workspaces/{world.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "kind", "display_name": "Object type",
                 "data_type": "object_type", "required": True},
                {"api_name": "key", "display_name": "Key",
                 "data_type": "string", "required": True},
                {"api_name": "when", "display_name": "When",
                 "data_type": "string", "required": True},
            ],
            "rules": [{"kind": "create_object",
                       "config": {"object_type_parameter": "kind",
                                  "primary_key": "key",
                                  "properties": {"raised_on": "when"}}}],
            "criteria": [],
        },
    )
    mod = Module(api, "Interface create form", beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {"resolvedName": "CanvasActionForm",
                     "props": {"actionTypeId": action["id"], "objectVariable": None}},
        }),
        "variables": {},
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    picker = page.get_by_test_id("object-type-parameter")
    expect(picker).to_be_visible(timeout=30000)
    # Both implementing types, and nothing else: "Choose an object type…" plus
    # the two. A third would be a type this action's rules cannot describe.
    expect(picker.locator("option")).to_have_count(3)

    record(page).select_option(index=1)
    picker.select_option(value=wishes)
    page.get_by_label("Key", exact=True).fill("W-NEW")
    page.get_by_label("When", exact=True).fill("2031-07-07")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("text=Saved.")).to_be_visible(timeout=15000)

    made = eventually(
        lambda: stored(api, world, wishes, "W-NEW", "asked_on"),
        lambda v: v == "2031-07-07",
        what="the wish the form created",
    )
    assert made == "2031-07-07", made


def test_the_editor_offers_only_object_type_parameters_as_the_chooser(
    page, api, world
) -> None:
    """p.60's chooser, in the dialog that wires it.

    The rule names the parameter that will say which type to create, and only
    an `object_type` parameter can — a string one would collect the id
    perfectly well and the form would draw a text box for it, which is §214's
    control that can only be satisfied by somebody who already knows a UUID.
    The server refuses that; this is the half that means nobody meets the
    refusal.

    **Both halves asserted**, because a dropdown offering every parameter
    contains the right one too.
    """
    action = api.call(
        "POST", f"/workspaces/{world.workspace_id}/action-types",
        {"interface_id": world.interface["id"],
         "api_name": f"wire_{uuid.uuid4().hex[:8]}",
         "display_name": "Wire up", "editable_properties": ["last_inspection_date"]},
    )
    api.call(
        "PUT", f"/workspaces/{world.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "kind", "display_name": "Object type",
                 "data_type": "object_type", "required": True},
                {"api_name": "key", "display_name": "Key",
                 "data_type": "string", "required": True},
                {"api_name": "when", "display_name": "When",
                 "data_type": "string", "required": True},
            ],
            "rules": [{"kind": "create_object",
                       "config": {"object_type_parameter": "kind",
                                  "primary_key": "key",
                                  "properties": {"last_inspection_date": "when"}}}],
            "criteria": [],
        },
    )

    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible(
        timeout=30000
    )
    row = page.locator("tbody tr").filter(has_text="Wire up").first
    row.get_by_role("button", name="Parameters").click()

    chooser = page.get_by_role("combobox", name="Rule 1 creates type from")
    expect(chooser).to_be_visible(timeout=15000)
    options = set(chooser.locator("option").all_text_contents())
    assert "kind" in options, options
    assert {"key", "when"}.isdisjoint(options), options


def test_an_interface_reference_offers_objects_of_every_implementing_type(
    page, api, world
) -> None:
    """`action-types` p.62: "the 'interface reference' parameter shows objects
    of any type that implements the interface. If using a form or a table, the
    user could then pick an object from a list."

    **The population, not a member** (§440): a list holding only one type's
    objects satisfies any assertion about one of them. And the label says which
    type each object is — the one thing a heterogeneous list has to carry and a
    single-type one never does.
    """
    action = api.call(
        "POST", f"/workspaces/{world.workspace_id}/action-types",
        {"object_type_id": world.facility,
         "api_name": f"byref_{uuid.uuid4().hex[:8]}",
         "display_name": "Retire by reference",
         "editable_properties": ["surveyed_on"]},
    )
    api.call(
        "PUT", f"/workspaces/{world.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "subject", "display_name": "Which object",
                 "data_type": "object", "required": True,
                 "interface_id": world.interface["id"]},
            ],
            "rules": [{"kind": "delete_object", "config": {"object": "subject"}}],
            "criteria": [],
        },
    )
    mod = Module(api, "Interface reference form", beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {"resolvedName": "CanvasActionForm",
                     "props": {"actionTypeId": action["id"], "objectVariable": None}},
        }),
        "variables": {},
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    picker = page.get_by_role("combobox", name="Which object")
    expect(picker).to_be_visible(timeout=30000)
    texts = " ".join(picker.locator("option").all_text_contents())
    # Both implementing types' objects, from two different datasets.
    assert "F1" in texts and "F2" in texts and "V1" in texts, texts
    # And each says what it is, because the list is heterogeneous.
    assert "·" in texts, texts


def test_opening_and_saving_the_dialog_keeps_the_interface_constraint(
    page, api, world
) -> None:
    """**The trap §329, §331 and §333 each fell into, one field later.**

    This dialog saves the parameters whole, so a field it does not read is one
    it overwrites with nothing the moment somebody opens it to fix a label. The
    constraint is read into its state and drawn in a control; neither is worth
    anything unless the round trip is asserted, and the round trip is the thing
    that broke three times before.

    Saving without touching the control is the case, because that is what
    somebody editing a different parameter does.
    """
    action = api.call(
        "POST", f"/workspaces/{world.workspace_id}/action-types",
        {"object_type_id": world.facility,
         "api_name": f"keep_{uuid.uuid4().hex[:8]}",
         "display_name": "Keeps its constraint",
         "editable_properties": ["surveyed_on"]},
    )
    api.call(
        "PUT", f"/workspaces/{world.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "subject", "display_name": "Which object",
                 "data_type": "object", "required": True,
                 "interface_id": world.interface["id"]},
            ],
            "rules": [{"kind": "delete_object", "config": {"object": "subject"}}],
            "criteria": [],
        },
    )

    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible(
        timeout=30000
    )
    row = page.locator("tbody tr").filter(has_text="Keeps its constraint").first
    row.get_by_role("button", name="Parameters").click()

    # Drawn in the state it is actually in — a control that always reads "Not
    # said" is §214's, and it is also what a mutant leaves behind.
    picker = page.get_by_role("combobox", name="Parameter 1 interface")
    expect(picker).to_have_value(world.interface["id"], timeout=15000)

    page.get_by_role("button", name="Save", exact=True).click()
    saved = eventually(
        lambda: api.call(
            "GET", f"/workspaces/{world.workspace_id}/action-types/{action['id']}",
        )["parameters"][0].get("interface_id"),
        lambda v: v == world.interface["id"],
        what="the interface constraint after a save that did not touch it",
    )
    assert saved == world.interface["id"], saved


def test_picking_an_interface_clears_the_object_type_beside_it(
    page, api, world
) -> None:
    """The two constraints are exclusive, and the server refuses both — so the
    dialog has to clear one when the other is chosen, or a reader can build a
    definition whose only outcome is that refusal (§214).

    **Asserted through the save**, because the state the dialog holds is not
    the claim: what matters is the document it writes.
    """
    action = api.call(
        "POST", f"/workspaces/{world.workspace_id}/action-types",
        {"object_type_id": world.facility,
         "api_name": f"swap_{uuid.uuid4().hex[:8]}",
         "display_name": "Swaps its constraint",
         "editable_properties": ["surveyed_on"]},
    )
    api.call(
        "PUT", f"/workspaces/{world.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "subject", "display_name": "Which object",
                 "data_type": "object", "required": True,
                 "object_type_id": world.vehicle},
            ],
            "rules": [{"kind": "delete_object", "config": {"object": "subject"}}],
            "criteria": [],
        },
    )

    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_role("heading", name="Actions", exact=True)).to_be_visible(
        timeout=30000
    )
    row = page.locator("tbody tr").filter(has_text="Swaps its constraint").first
    row.get_by_role("button", name="Parameters").click()

    picker = page.get_by_role("combobox", name="Parameter 1 interface")
    expect(picker).to_be_visible(timeout=15000)
    picker.select_option(value=world.interface["id"])
    page.get_by_role("button", name="Save", exact=True).click()

    saved = eventually(
        lambda: api.call(
            "GET", f"/workspaces/{world.workspace_id}/action-types/{action['id']}",
        )["parameters"][0],
        lambda p: p.get("interface_id") == world.interface["id"],
        what="the swapped constraint",
    )
    assert saved["object_type_id"] is None, saved
