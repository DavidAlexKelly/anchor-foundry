"""The action form, rendered from parameters (decision 0007; Foundry p.25–27, p.56).

The half a unit test cannot see. `seedActionForm` is checked directly in
`apps/web/src/components/canvas/action-form.test.ts`; what is here is what a
browser actually draws and submits:

  * **a hidden parameter is not in the form and is still applied** — both
    halves, because a hidden parameter that silently did nothing would pass a
    check that only looked at the fields (p.25: "each parameter can be
    individually configured as to whether they are exposed in the form or
    not");
  * a required parameter blocks submission until it has a value (p.25);
  * a refused submission shows the criterion's **own** failure message, which
    is what p.56 says the message is for.

The action's definition is set through `PUT .../definition` (§129) rather than
by reaching into the database, so this drives the same path an editor will.

**Each test that writes gets its own module and its own ticket.** Sharing one
across a mutating suite has bitten this repo twice (§118 and the versions
dialog); a form test is a write test by definition.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_module


def build(api, name: str) -> Module:
    """A module holding one action form over one ticket."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status", "note"],
        rows=[{"ticket_id": "1", "status": "open", "note": "keep me"}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": type_id,
            "api_name": f"close_{uuid.uuid4().hex[:8]}",
            "display_name": "Close ticket",
            "editable_properties": ["status", "note"],
        },
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "New status", "data_type": "string",
                 "required": True},
                # Hidden, and named after a real property, so the form seeds it
                # from the object and the rule writes it back - p.25's own
                # shape, where a hidden parameter carries a value the rules use.
                {"api_name": "note", "display_name": "Note", "data_type": "string",
                 "hidden": True},
            ],
            "rules": [
                {"kind": "modify_object", "config": {"property": "status", "parameter": "status"}},
                {"kind": "modify_object", "config": {"property": "note", "parameter": "note"}},
            ],
            "criteria": [
                {"message": "Tickets cannot be marked deleted.",
                 "config": {"left": {"kind": "parameter", "parameter": "status"},
                            "operator": "is_not",
                            "right": {"kind": "value", "value": "deleted"}}},
                # **A criterion over the hidden parameter**, which is p.25's own
                # use for one: it carries a value from the object that the
                # logic compares against. It is also what makes "hidden is
                # still sent" observable at all - a hidden parameter that is
                # merely *written back unchanged* produces the same stored row
                # whether the form sent it or dropped it, so a test built on
                # that could not fail. This one refuses when it never arrives.
                {"message": "A ticket with no note cannot be updated.",
                 "config": {"left": {"kind": "parameter", "parameter": "note"},
                            "operator": "is_not", "right": {"kind": "none"}}},
            ],
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "ACTION FORM MODULE"}},
            # Unbound, so the form draws its own Record dropdown: one widget
            # rather than a table plus a row_select event plus a variable, and
            # the thing under test is the *form*.
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = type_id
    return mod


@pytest.fixture(scope="module")
def readonly(api):
    """Shared by the tests that never submit."""
    return build(api, "Action form")


def field(page, name: str):
    return page.locator(f"[data-parameter='{name}'] input")


def choose_the_ticket(page) -> None:
    """Pick the one record, which is what gives the form something to edit."""
    page.locator("form select").select_option(index=1)
    expect(field(page, "status")).not_to_have_value("")


def stored(api, mod: Module) -> dict:
    items = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"]
    return items[0]["properties"]


def test_a_hidden_parameter_is_not_drawn(page, readonly):
    """p.25. The visible field is asserted first, so "no note field" is about
    the rule rather than about a form that never rendered."""
    open_module(page, readonly)
    choose_the_ticket(page)
    expect(field(page, "status")).to_be_visible()
    expect(field(page, "note")).to_have_count(0)


def test_the_form_starts_at_what_the_object_says(page, readonly):
    """An edit form showing blanks beside the thing being edited is how
    somebody blanks a property they only meant to look at."""
    open_module(page, readonly)
    choose_the_ticket(page)
    expect(field(page, "status")).to_have_value("open")


def test_a_required_parameter_blocks_submission_until_it_has_a_value(page, readonly):
    """p.25's `required`. The button is disabled rather than the submission
    refused, because this is the one rule the form can decide by itself."""
    open_module(page, readonly)
    choose_the_ticket(page)
    field(page, "status").fill("")

    submit = page.get_by_role("button", name="Submit")
    expect(submit).to_be_disabled()
    expect(page.get_by_test_id("action-form-missing")).to_contain_text("New status")

    field(page, "status").fill("open")
    expect(submit).to_be_enabled()


def test_a_refused_submission_shows_the_criterion_s_own_message(page, api, readonly):
    """p.56: "The failure message informs the user about why they are blocked
    from submitting an Action."

    The form deliberately does **not** evaluate criteria itself to grey the
    button out in advance: that would be a second implementation of a rule
    governing writes, in another language, free to disagree with the first. It
    submits, and draws what the server refused with.

    Safe to share the read-only module because a refused action writes nothing
    — which is the other half of what this asserts.
    """
    open_module(page, readonly)
    choose_the_ticket(page)
    field(page, "status").fill("deleted")
    page.get_by_role("button", name="Submit").click()

    expect(page.get_by_test_id("action-form-refused")).to_contain_text(
        "Tickets cannot be marked deleted."
    )
    assert stored(api, readonly)["status"] == "open"


def test_the_hidden_parameter_is_still_applied(page, api):
    """The other half of the first test, and the reason both exist: a hidden
    parameter that quietly did nothing would pass "it is not drawn".

    `note` is never typed - it is seeded from the object and submitted with the
    rest - and a criterion refuses the action when it does not arrive. That
    criterion is the only reason this test can fail: a hidden parameter that is
    merely written back unchanged leaves the same stored row whether the form
    sent it or dropped it, so the first version of this test passed against a
    form that filtered hidden parameters out of its submission entirely. Found
    by mutation, fixed in the fixture rather than in the assertion.
    """
    mod = build(api, "Action form write")
    open_module(page, mod)
    choose_the_ticket(page)
    field(page, "status").fill("triaged")
    page.get_by_role("button", name="Submit").click()
    expect(page.get_by_text("Saved.")).to_be_visible()

    properties = stored(api, mod)
    assert properties["status"] == "triaged"
    assert properties["note"] == "keep me"
