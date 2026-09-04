"""The action form, rendered from parameters (decision 0007; Foundry p.25–27, p.56).

The half a unit test cannot see. What a *document* decides — p.512's title and
local defaults, p.513's invalid-state — is
`apps/web/src/components/canvas/action-form.test.ts`, and `seedActionForm`'s
precedence order is in `pure.test.ts`. **This docstring used to claim the
seeding was unit-tested in a file that did not exist**, and it was not tested
anywhere until §217; the claim is corrected rather than quietly dropped.

What is here is what a browser actually draws and submits:

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
from conftest import open_builder, open_module, settled


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


def test_a_required_parameter_says_so_on_the_control_itself(page, readonly):
    """`required` on the input, which the disabled button does not say.

    **Two different claims, and only one of them was tested.** The button
    reports the *form's* state — "something, somewhere, is missing" — and the
    test above asserts that. The attribute reports the *field's*, which is what
    a screen reader announces as somebody moves through the inputs and what
    native validation acts on. A mutant deleting it from `PropertyInput` left
    every existing test green (§237).
    """
    open_module(page, readonly)
    choose_the_ticket(page)
    expect(field(page, "status")).to_have_attribute("required", "")
    expect(field(page, "status")).to_have_attribute("aria-required", "true")


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


# ---- the widget's own settings (Workshop p.512-513) -------------------------
def build_widget(api, name: str, props: dict | None = None, *, blocked: bool = False,
                 events: dict | None = None) -> Module:
    """A form whose *widget* is configured, over a ticket that is open.

    `blocked` adds a criterion the **seeded** values fail — the ticket's status
    is "open" and the criterion demands it is not — which is what p.513's
    invalid state is about: an action that cannot be submitted for this object,
    known before anything is typed.
    """
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status", "note"],
        rows=[{"ticket_id": "1", "status": "open", "note": "keep me"}],
        key="ticket_id", title="ticket_id",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"widget_{uuid.uuid4().hex[:8]}",
         "display_name": "Close ticket", "editable_properties": ["status"]},
    )
    api.call(
        "PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "New status", "data_type": "string"},
                {"api_name": "note", "display_name": "Note", "data_type": "string"},
                # **A parameter no property is named after**, so the object has
                # nothing to say about it and a local default is the only thing
                # that can fill it. Without one, both of p.512's tests below
                # were about the object's value winning — which happens whether
                # or not the default is passed at all, and the harness said so.
                {"api_name": "reason", "display_name": "Reason", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
            ],
            "criteria": (
                [{"message": "This ticket is already open.",
                  "config": {"left": {"kind": "parameter", "parameter": "status"},
                             "operator": "is_not",
                             "right": {"kind": "value", "value": "open"}}}]
                if blocked else []
            ),
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Fired: {{v_done}}"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"], **(props or {})}},
        }),
        "variables": {"v_done": {"id": "v_done", "kind": "string", "label": "Done"}},
        "events": events or {},
    })
    mod.type_id = type_id
    return mod


def test_the_title_can_be_replaced_and_falls_back(page, api):
    """p.512's "Set custom Action title": "replacing the default title with your
    own text"."""
    default = build_widget(api, "Action title default")
    open_module(page, default)
    expect(page.get_by_test_id("action-form-title")).to_have_text("Close ticket")

    # **A whitespace-only title, not an empty one.** `""` is falsy whether or
    # not it has been read through the model, so it asks nothing (§214).
    blank = build_widget(api, "Action title blank", {"title": "   "})
    open_module(page, blank)
    expect(page.get_by_test_id("action-form-title")).to_have_text("Close ticket")

    custom = build_widget(api, "Action title custom", {"title": "  Resolve  "})
    open_module(page, custom)
    title = page.get_by_test_id("action-form-title")
    expect(title).to_be_visible()
    # `text_content`, not `to_have_text`: that matcher normalises whitespace and
    # could not see the trim (§214).
    assert title.text_content() == "Resolve", repr(title.text_content())


def test_the_header_can_be_hidden(page, api):
    """p.513's Hide header, asserted both ways round on the same action."""
    shown = build_widget(api, "Action header shown")
    open_module(page, shown)
    expect(page.get_by_test_id("action-form-title")).to_be_visible()

    hidden = build_widget(api, "Action header hidden", {"hideHeader": True})
    open_module(page, hidden)
    # The form is drawn — what is missing is its heading.
    expect(page.locator("form")).to_be_visible()
    expect(page.get_by_test_id("action-form-title")).to_have_count(0)


def test_a_local_default_seeds_a_parameter_the_object_says_nothing_about(page, api):
    """p.512: "Set local default values for parameters in the Inline Action
    view. If unspecified, the action type parameter configurations from the
    Ontology will apply."

    `note` is a parameter the object *does* have a value for, so the case that
    separates a default from an override is a parameter it does not — this
    action's `status` parameter is named after a property, and a third one
    would be needed to test the other order. That order is unit-tested in
    `pure.test.ts`, where it is cheap.
    """
    plain = build_widget(api, "Action default none")
    open_module(page, plain)
    choose_the_ticket(page)
    # Seeded from the object, because the parameter is named after a property.
    expect(field(page, "note")).to_have_value("keep me")

    seeded = build_widget(api, "Action default local",
                          {"parameterDefaults": {"status": "triaged"}})
    open_module(page, seeded)
    choose_the_ticket(page)
    # **Still the object's value**, because a default is what applies when
    # there is nothing to show — and `status` is a property this ticket has.
    expect(field(page, "status")).to_have_value("open")


def test_a_default_applies_to_a_parameter_with_no_property_behind_it(page, api):
    """The other half, and the only one that can observe the setting at all.

    `reason` is named after no property, so nothing seeds it but p.512's
    default — which is why it exists. The first version of this test used
    `note`, a parameter the object *does* have a value for, so it asserted the
    object winning twice and passed against a widget that never passed the
    defaults on. The harness caught it; the fixture was wrong, not the
    assertion.
    """
    plain = build_widget(api, "Action default empty")
    open_module(page, plain)
    choose_the_ticket(page)
    expect(field(page, "reason")).to_have_value("")

    mod = build_widget(api, "Action default spare",
                       {"parameterDefaults": {"reason": "from the module"}})
    open_module(page, mod)
    choose_the_ticket(page)
    expect(field(page, "reason")).to_have_value("from the module")


def test_the_panel_says_whether_the_invalid_state_will_mean_anything(page, api):
    """An action with no submission criteria can never be invalid, so p.513's
    setting is a control that does nothing — and which of those an action is
    cannot be seen from the select itself."""
    plain = build_widget(api, "Action panel plain")
    open_builder(page, plain)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Action form").first.click()
    hint = page.get_by_test_id("action-form-invalid-state").locator("xpath=..")
    expect(hint).to_contain_text("no submission criteria")

    blocked = build_widget(api, "Action panel blocked", blocked=True)
    open_builder(page, blocked)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="Action form").first.click()
    hint = page.get_by_test_id("action-form-invalid-state").locator("xpath=..")
    expect(hint).to_contain_text("before anything is written")


def test_an_action_that_cannot_be_submitted_is_disabled_with_its_own_reason(page, api):
    """p.513's `disabled`, and the point of the check endpoint.

    The criterion refuses a status of "open" and the ticket *is* open, so the
    answer is known before anything is typed. The message shown is the
    criterion's own (p.56) — from the server that would refuse it, not a
    sentence the widget invented about a rule it does not implement.
    """
    mod = build_widget(api, "Action invalid disabled", blocked=True)
    open_module(page, mod)
    choose_the_ticket(page)

    expect(page.get_by_test_id("action-form-invalid")).to_contain_text(
        "This ticket is already open."
    )
    expect(page.get_by_role("button", name="Submit")).to_be_disabled()


def test_the_same_action_is_submittable_when_the_criterion_holds(page, api):
    """Without this, a widget that disabled *everything* would pass the test
    above."""
    mod = build_widget(api, "Action invalid allowed")
    open_module(page, mod)
    choose_the_ticket(page)

    expect(page.get_by_role("button", name="Submit")).to_be_enabled()
    expect(page.get_by_test_id("action-form-invalid")).to_have_count(0)


def test_an_invalid_action_can_be_hidden_instead(page, api):
    """p.513's other state. The form goes; the widget does not pretend to be
    something else."""
    mod = build_widget(api, "Action invalid hidden", {"invalidState": "hidden"},
                       blocked=True)
    open_module(page, mod)
    # Something rendered — the text widget — so the absence below is honest.
    expect(page.get_by_text("Fired:")).to_be_visible()
    choose_the_ticket_if_present(page)
    expect(page.locator("form")).to_have_count(0)


def choose_the_ticket_if_present(page) -> None:
    """The record dropdown lives inside the form, so a hidden form has none."""
    dropdown = page.locator("form select")
    if dropdown.count() == 1:
        dropdown.select_option(index=1)


def test_a_successful_submission_fires_a_workshop_event(page, api):
    """p.513's "On successful action submit"."""
    mod = build_widget(
        api, "Action submit event",
        events={"e_done": {"id": "e_done", "trigger": {"node": "frm", "on": "submit"},
                           "effects": [{"type": "set_variable",
                                        "config": {"variable": "v_done", "value": "yes"}}]}},
    )
    open_module(page, mod)
    expect(page.get_by_text("Fired:")).to_be_visible()
    choose_the_ticket(page)
    field(page, "status").fill("triaged")
    page.get_by_role("button", name="Submit").click()

    expect(page.get_by_text("Saved.")).to_be_visible()
    expect(page.get_by_text("Fired: yes")).to_be_visible()


def test_a_refused_submission_does_not_fire_the_event(page, api):
    """**On success only**, which is what p.513 says and what makes the setting
    usable: an event that also fired on a refusal would navigate away from the
    message explaining why."""
    mod = build_widget(
        api, "Action submit event refused", blocked=True,
        events={"e_done": {"id": "e_done", "trigger": {"node": "frm", "on": "submit"},
                           "effects": [{"type": "set_variable",
                                        "config": {"variable": "v_done", "value": "yes"}}]}},
    )
    open_module(page, mod)
    choose_the_ticket(page)
    # The button is disabled by p.513's default state, so the refusal never
    # even reaches the server — and the event must not fire for that either.
    expect(page.get_by_role("button", name="Submit")).to_be_disabled()
    expect(page.get_by_text("Fired: yes")).to_have_count(0)
