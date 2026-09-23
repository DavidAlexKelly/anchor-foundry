"""Filling in a struct parameter on an action form (`action-types` p.66, p.73).

> "Struct property values can be created and modified with actions, through
> values supplied in a struct parameter. A struct parameter is a parameter of
> base type `STRUCT`, where the type contains nested parameter fields that have
> their own individual names and base types." (p.66)

p.66's own example is a `Resolution` parameter on a Create Ticket action whose
nested `summary`, `resolutionTime` and `owner` fields "compile information on
how the ticket was resolved into a single parameter" — which is the fixture
below, in this platform's naming.

**What needs a browser is the shape of the control.** The server's half is
checked in `apps/api/tests/test_action_parameters.py`: `struct` is an allowed
parameter type, the value is coerced against the property's declared fields,
and p.73's limitations are refused at save time. The arithmetic of editing one
field without losing the others is checked in
`apps/web/src/lib/struct-parameter.test.ts`. Neither can see what this file
sees — that a struct parameter draws **one control per declared field**, that
each control is typed as *its own* field rather than as the parameter, and that
what the three of them produce together survives the round trip to the object.

A struct parameter used to be refused outright, and the refusal said why: a
text box is the only thing `pure.inputTypeFor` would have drawn for it, and a
struct typed by hand into one input is a control that can essentially never
produce a valid value (§214). So the assertions here are about the *controls*
first and the stored value second.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_module, settled

# p.66's three nested fields. `resolution_time` is an `integer` so that one
# field has a different base type from its neighbours — the point of asserting
# the controls is that each is typed as itself, and three strings could not
# tell a per-field lookup from a single one applied three times.
FIELDS = [
    {"api_name": "summary", "display_name": "Summary", "data_type": "string"},
    {"api_name": "resolution_time", "display_name": "Resolution time",
     "data_type": "integer"},
    {"api_name": "owner", "display_name": "Owner", "data_type": "string"},
]

SEEDED = {"summary": "Cable reseated", "resolution_time": 20, "owner": "ana"}


@pytest.fixture(scope="module")
def tickets(api):
    """p.66's Resolution parameter, on a type with a matching struct property.

    Four tickets, and **each test names its own**: p.25 seeds a form's
    parameters from the object it is opened on, so a ticket another test has
    already resolved arrives with the struct parameter filled in — which is the
    form behaving correctly and would make the required-gate assertion below
    pass for the wrong reason.
    """
    mod = Module(api, "Struct parameter")
    mod.type_id = mod.object_type(
        columns=["ticket_id", "status", "resolution"],
        rows=[
            {"ticket_id": "s1", "status": "open", "resolution": ""},
            {"ticket_id": "s2", "status": "open", "resolution": ""},
            {"ticket_id": "s3", "status": "open", "resolution": json.dumps(SEEDED)},
            {"ticket_id": "s4", "status": "open", "resolution": json.dumps(SEEDED)},
        ],
        key="ticket_id", title="ticket_id",
        types={"resolution": "struct"},
        struct_fields={"resolution": FIELDS},
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": mod.type_id,
            "api_name": f"resolve_{uuid.uuid4().hex[:8]}",
            "display_name": "Resolve ticket",
            "editable_properties": ["resolution"],
        },
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "resolution", "display_name": "Resolution",
                 "data_type": "struct", "required": True},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "resolution", "parameter": "resolution"}},
            ],
            "criteria": [],
        },
    )
    mod.action = action
    return mod


def build(api, tickets, name: str):
    mod = Module(api, name, beside=tickets)
    mod.type_id = tickets.type_id
    mod.define({
        "format": 2,
        "layout": layout({
            "form": {
                "resolvedName": "CanvasActionForm",
                "props": {"actionTypeId": tickets.action["id"], "objectVariable": None},
            },
        }),
        "variables": {},
        "events": {},
    })
    return mod


def group(page):
    """The struct parameter's own group of controls."""
    return page.locator('[data-parameter="resolution"] [data-testid="struct-fields"]')


def open_on(page, mod, ticket: str) -> None:
    open_module(page, mod)
    settled(page)
    # The Record dropdown has no test id of its own. `.first` rather than a
    # bare `form select`, because a struct parameter whose fields include a
    # boolean would put a second select inside the form — this fixture has
    # none, and a locator that depends on the fixture not growing one is a
    # locator that breaks for a reason nobody will connect to the change.
    page.locator("form select").first.select_option(label=ticket)


def stored(api, mod, ticket: str):
    rows = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
        {"definition": {"object_type_id": mod.type_id, "filters": []}, "limit": 10},
    )["instances"]
    one = next(r for r in rows if (r.get("properties") or {}).get("ticket_id") == ticket)
    return (one.get("properties") or {}).get("resolution")


def test_a_struct_parameter_draws_one_control_per_declared_field(
    page, api, tickets
) -> None:
    """p.66: the type "contains nested parameter fields that have their own
    individual names and base types".

    **The count is the assertion.** One control is what a struct parameter got
    before the fields could reach the form, and it is exactly what a reader
    cannot fill in: three declared fields, three boxes, named apart.
    """
    mod = build(api, tickets, "Struct controls")
    open_on(page, mod, "s1")

    expect(group(page).locator("input")).to_have_count(3)
    for label in ("Resolution — Summary", "Resolution — Resolution time",
                  "Resolution — Owner"):
        expect(page.get_by_label(label, exact=True)).to_have_count(1)
    # p.68's "rendered as a group in the form instead of individually", to a
    # reader who cannot see the rule down the side of it: the fieldset carries
    # the parameter's name, so somebody arriving at the first box is told which
    # answer these three boxes belong to.
    expect(group(page)).to_have_attribute("aria-label", "Resolution")


def test_each_field_is_typed_as_itself_rather_than_as_the_parameter(
    page, api, tickets
) -> None:
    """p.66's "their own individual names and base types", at the one end that
    can tell the difference.

    `pure.inputTypeFor` is asked once per *field* here, not once for the
    parameter — so the integer field must come out a number box while its two
    neighbours stay text. A nested lookup that read the parameter's type
    instead would give three identical controls and still pass a count.
    """
    mod = build(api, tickets, "Struct field types")
    open_on(page, mod, "s1")

    expect(page.get_by_label("Resolution — Resolution time", exact=True)).to_have_attribute(
        "type", "number"
    )
    expect(page.get_by_label("Resolution — Summary", exact=True)).to_have_attribute(
        "type", "text"
    )


def test_what_the_fields_collect_is_written_onto_the_object(
    page, api, tickets
) -> None:
    """p.66's whole claim: "struct property values can be created and modified
    with actions, through values supplied in a struct parameter".

    **Read back off the object, never off the form.** `property_values`
    `_coerce_struct` refuses a value whose fields do not match the declaration,
    so a stored struct with all three keys and the integer stored *as* an
    integer is proof of the whole path: three controls, one value assembled,
    carried through the form, coerced against the property, written.
    """
    mod = build(api, tickets, "Struct submit")
    open_on(page, mod, "s1")

    page.get_by_label("Resolution — Summary", exact=True).fill("Replaced the PSU")
    page.get_by_label("Resolution — Resolution time", exact=True).fill("45")
    page.get_by_label("Resolution — Owner", exact=True).fill("wren")
    page.get_by_role("button", name="Submit").click()

    got = eventually(
        lambda: stored(api, mod, "s1"),
        lambda v: isinstance(v, dict) and bool(v),
        what="the struct written onto ticket s1",
    )
    assert got["summary"] == "Replaced the PSU", got
    # Coerced, not carried as the string the box held.
    assert got["resolution_time"] == 45, got
    assert got["owner"] == "wren", got


def test_changing_one_field_leaves_the_others_alone(page, api, tickets) -> None:
    """**The arithmetic every nested form gets wrong**, seen through the object.

    p.25 seeds the parameter from the ticket, so the form opens holding all
    three of `SEEDED`. Typing in one box must produce a *new* struct with that
    one field replaced — not a struct containing only it, which is what an
    `onChange` that sends `{field: next}` produces and what nothing in a form
    that shows its own state would ever reveal.
    """
    mod = build(api, tickets, "Struct partial edit")
    open_on(page, mod, "s3")

    # The seed, before anything is typed — otherwise the assertion below is
    # about a form that never filled in, and every field would be "unchanged".
    expect(page.get_by_label("Resolution — Summary", exact=True)).to_have_value(
        SEEDED["summary"]
    )
    page.get_by_label("Resolution — Owner", exact=True).fill("bo")
    page.get_by_role("button", name="Submit").click()

    got = eventually(
        lambda: stored(api, mod, "s3"),
        lambda v: isinstance(v, dict) and v.get("owner") == "bo",
        what="the edited owner on ticket s3",
    )
    assert got["summary"] == SEEDED["summary"], got
    assert got["resolution_time"] == SEEDED["resolution_time"], got


def test_a_required_struct_with_every_field_cleared_is_not_answered(
    page, api, tickets
) -> None:
    """p.25's required check, at the one parameter type whose empty value is an
    object.

    `pure.hasValue` answers `true` for any object, which is right for the
    attachment reference it was written for and wrong here: clearing all three
    boxes leaves `{}`, and a form that called that an answer would submit a
    struct with nothing in it against a parameter marked required.
    """
    mod = build(api, tickets, "Struct required")
    open_on(page, mod, "s4")

    # Seeded, so Submit is live before anything is cleared — the positive this
    # absence is measured against (§318).
    expect(page.get_by_role("button", name="Submit")).to_be_enabled()
    for label in ("Resolution — Summary", "Resolution — Resolution time",
                  "Resolution — Owner"):
        page.get_by_label(label, exact=True).fill("")
    expect(page.get_by_role("button", name="Submit")).to_be_disabled()


def test_a_struct_parameter_no_rule_writes_says_so_instead_of_drawing_a_box(
    page, api, tickets
) -> None:
    """**The one state that reaches the note**, and the reason there is one.

    The fields are the *property's*, found through the rule that writes it
    (p.73: one struct parameter per struct property). A parameter no rule
    names has no property, so there is nothing to draw — the half-wired state
    a builder is in while putting an action together, which is exactly when
    somebody is looking at this form.

    It is the only way in. p.73's pairing is enforced at save time, and the
    ontology refuses to retype a property an action writes (`type_impact`), so
    a wired struct parameter cannot lose its fields afterwards.

    A text box is what `pure.inputTypeFor` would draw here, and a struct typed
    by hand into one input can essentially never produce a valid value (§214).
    So the form says what it does not know, and names the rule rather than the
    box, because that is where somebody can act.
    """
    action = api.call(
        "POST", f"/workspaces/{tickets.workspace_id}/action-types",
        {"object_type_id": tickets.type_id, "api_name": f"half_{uuid.uuid4().hex[:8]}",
         "display_name": "Half-wired", "editable_properties": ["status"]},
    )
    api.call(
        "PUT", f"/workspaces/{tickets.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "Status",
                 "data_type": "string", "required": False},
                # Declared, and nothing writes it yet.
                {"api_name": "resolution", "display_name": "Resolution",
                 "data_type": "struct", "required": False},
            ],
            "rules": [{"kind": "modify_object",
                       "config": {"property": "status", "parameter": "status"}}],
            "criteria": [],
        },
    )
    mod = Module(api, "Struct half wired", beside=tickets)
    mod.type_id = tickets.type_id
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
    page.locator("form select").first.select_option(label="s2")

    note = page.get_by_test_id("struct-fields-unknown")
    expect(note).to_be_visible()
    expect(note).to_contain_text("Resolution")
    # And no control beside it, which is the whole point of the note. The
    # positive this absence is measured against is the note itself, drawn by
    # the same render (§318).
    expect(group(page)).to_have_count(0)
