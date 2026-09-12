"""Changing a parameter under specific circumstances, on the screen (§329;
`action-types` p.43-46).

    "While assignees can change the status, managers will have to provide a
     justification. Using overrides, the Justification reason parameter can be
     made **required and visible for managers, while it is hidden and optional
     for the assignee**." (p.43)

The blocks and the resolution are tested in
`apps/api/tests/test_action_overrides.py` and the wording in
`apps/web/src/lib/action-overrides.test.ts`. What needs a browser is the thing
that separates this unit from §328:

**an override changes what the form asks for, and what the submission is
refused for, together.**

A section changes what a form looks like and nothing else. These tests watch a
field appear *and* the submission it enables be accepted — and the same field
refuse a submission when the block does not hold. Only asserting the drawing
would pass for a form that applied p.43's rule cosmetically, which is the one
way of getting this wrong that looks right.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, open_module


def when(parameter: str, value: str) -> dict:
    return {"left": {"kind": "parameter", "parameter": parameter},
            "operator": "is", "right": {"kind": "value", "value": value}}


def build(api, name: str, *, overrides: list[dict] | None = None) -> Module:
    """p.43's own example: a ticket whose status somebody changes, and a
    justification that is required only under some circumstances."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status", "justification"],
        rows=[{"ticket_id": "1", "status": "open", "justification": ""}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"close_{uuid.uuid4().hex[:8]}",
         "display_name": "Close ticket",
         "editable_properties": ["status", "justification"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "New status",
                 "data_type": "string"},
                # Hidden and optional to begin with, which is p.43's assignee.
                {"api_name": "justification", "display_name": "Justification",
                 "data_type": "string", "hidden": True,
                 "overrides": overrides if overrides is not None else []},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "modify_object",
                 "config": {"property": "justification",
                            "parameter": "justification"}},
            ],
            "criteria": [],
        },
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "OVERRIDDEN FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = type_id
    mod.action = action
    return mod


#: p.43's block: when the status is being closed, the justification is shown
#: and required.
WHEN_CLOSING = [{
    "conditions": [when("status", "closed")],
    "set_hidden": False,
    "set_required": True,
}]


def field(page, name: str):
    return page.locator(f"[data-parameter='{name}'] input")


def choose_the_ticket(page) -> None:
    page.locator("form select").first.select_option(index=1)
    expect(field(page, "status")).not_to_have_value("")


def stored(api, mod: Module) -> dict:
    items = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"]
    return items[0]["properties"]


# ---- p.43's example, both halves ----------------------------------------------
def test_a_block_that_does_not_hold_leaves_the_parameter_as_configured(page, api):
    """p.43's assignee: hidden and optional, which is what the stored row says.

    Asserted first so the test below is about the *change* rather than about a
    form that draws everything.
    """
    mod = build(api, "Override quiet", overrides=WHEN_CLOSING)
    open_module(page, mod)
    choose_the_ticket(page)
    expect(field(page, "justification")).to_have_count(0)
    expect(page.get_by_role("button", name="Submit")).to_be_enabled()


def test_a_block_that_holds_shows_and_requires_the_parameter(page, api):
    """**p.43's manager, and the two halves that make this not a section.**

    The field appears — which a section could also do — *and* the submission is
    now refused without it, which a section could not. Only asserting the first
    would pass for a form that applied p.43's rule cosmetically, and that is
    the one way of getting this wrong that looks right from a screenshot.
    """
    mod = build(api, "Override loud", overrides=WHEN_CLOSING)
    open_module(page, mod)
    choose_the_ticket(page)
    expect(field(page, "justification")).to_have_count(0)

    field(page, "status").fill("closed")
    expect(field(page, "justification")).to_be_visible(timeout=30000)

    submit = page.get_by_role("button", name="Submit")
    expect(submit).to_be_disabled()
    expect(page.get_by_test_id("action-form-missing")).to_contain_text("Justification")

    field(page, "justification").fill("the customer asked")
    expect(submit).to_be_enabled()
    submit.click()
    expect(page.locator("form")).to_contain_text("Saved.")
    assert stored(api, mod)["justification"] == "the customer asked"


def test_the_requirement_is_the_servers_and_not_the_screens(page, api):
    """**The claim a browser test cannot make on its own, made here anyway.**

    The form is drawn from what the server resolved, so a submission that skips
    the form entirely must be refused the same way. If the rule lived only in
    the browser this call would succeed — which is exactly what would happen if
    `resolve` were applied for drawing and not inside `bind_parameters`.
    """
    mod = build(api, "Override server", overrides=WHEN_CLOSING)
    # No browser at all: the API, with the values p.43's block makes incomplete.
    with pytest.raises(Exception) as refused:
        api.call(
            "POST",
            f"/workspaces/{mod.workspace_id}/projects/{mod.project_id}"
            f"/actions/{mod.action['id']}/execute",
            {"instance_id": first_instance(api, mod), "values": {"status": "closed"}},
        )
    assert "justification" in str(refused.value), refused.value

    # And the same submission is accepted when the block does not hold, which
    # is what makes the refusal above about the override rather than about a
    # parameter that was always required.
    api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/projects/{mod.project_id}"
        f"/actions/{mod.action['id']}/execute",
        {"instance_id": first_instance(api, mod), "values": {"status": "open"}},
    )
    assert stored(api, mod)["status"] == "open"


def first_instance(api, mod: Module) -> str:
    items = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"]
    return items[0]["id"]


def test_a_form_with_no_overrides_is_the_form_it_always_was(page, api):
    """The shape every action in this platform already has. **The check that a
    unit added for overrides did not quietly change the forms nobody
    overrode.**"""
    mod = build(api, "No overrides", overrides=[])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(field(page, "justification")).to_have_count(0)
    field(page, "status").fill("closed")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")
    assert stored(api, mod)["status"] == "closed"


def test_only_the_first_block_that_holds_is_applied(page, api):
    """p.45 and p.46, on two pages: "if more than one is true, only the first
    one will be executed".

    Both blocks hold. The first shows the field and the second would have
    required it — so a form that merged them would disable Submit, and one that
    took the last would too. Only the first-match reading leaves it enabled.
    """
    mod = build(api, "Override first match", overrides=[
        {"conditions": [when("status", "closed")], "set_hidden": False,
         "set_required": None, "set_default": None},
        {"conditions": [when("status", "closed")], "set_hidden": None,
         "set_required": True, "set_default": None},
    ])
    open_module(page, mod)
    choose_the_ticket(page)
    field(page, "status").fill("closed")
    expect(field(page, "justification")).to_be_visible(timeout=30000)
    expect(page.get_by_role("button", name="Submit")).to_be_enabled()


def test_a_block_can_set_a_default_the_form_starts_at(page, api):
    """p.45 lists default values among what an override may change.

    Observed as a value in the box rather than as a stored row, because a
    default that only appeared after submission would be indistinguishable from
    a rule writing it — and p.45's is about what the form *offers*.
    """
    mod = build(api, "Override default", overrides=[{
        "conditions": [when("status", "closed")],
        "set_hidden": False, "set_required": None,
        "set_default": "see the ticket",
    }])
    open_module(page, mod)
    choose_the_ticket(page)
    field(page, "status").fill("closed")
    expect(field(page, "justification")).to_have_value(
        "see the ticket", timeout=30000
    )


def test_a_plain_form_does_not_ask_the_server_what_its_parameters_are(page, api):
    """**A claim about the network, which no assertion about the screen can
    reach** — §327's finding, and the shape §328's sweep caught twice.

    A form whose parameters carry no blocks resolves to itself, so asking would
    be a round trip whose answer is already on the page. The positive control
    is a second module that *does* override, opened on the same page, because
    "nothing was asked" passes just as well for a listener attached to the
    wrong thing.
    """
    plain = build(api, "Override none", overrides=[])
    overridden = build(api, "Override some", overrides=WHEN_CLOSING)

    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url)
            if "effective-parameters" in r.url else None)

    open_module(page, plain)
    choose_the_ticket(page)
    field(page, "status").fill("closed")
    expect(page.get_by_role("button", name="Submit")).to_be_enabled()
    assert asked == [], asked

    open_module(page, overridden)
    choose_the_ticket(page)
    expect(field(page, "status")).to_be_visible()
    assert len(asked) >= 1, "the listener fires for a form that does override"


# ---- p.43's panel -------------------------------------------------------------
def open_editor(page, mod: Module) -> None:
    """The dialog for *this* action, by api_name — the Actions table is
    workspace-wide and the dev database has carried "Close ticket" for a
    while."""
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def definition(api, mod: Module) -> dict:
    return {
        p["api_name"]: p
        for p in api.call(
            "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
        )["parameters"]
    }


def test_a_block_written_in_the_panel_reaches_the_form(page, api):
    """**p.43's loop end to end**: write the override in the dialog, then find
    the form asking for the thing it makes required.

    Both ends through the screen, because what a builder types and what a
    submitter is asked for are the two halves this unit joins.
    """
    mod = build(api, "Override panel", overrides=[])
    open_editor(page, mod)

    page.get_by_label("Add an override to justification").click()
    page.get_by_label("justification override 1 parameter").select_option("status")
    page.get_by_label("justification override 1 value").fill("closed")
    page.get_by_label("justification override 1 visibility").select_option("false")
    page.get_by_label("justification override 1 requiredness").select_option("true")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    [saved] = definition(api, mod)["justification"]["overrides"]
    assert saved["set_required"] is True
    assert saved["set_hidden"] is False
    assert saved["conditions"] == [when("status", "closed")]

    open_module(page, mod)
    choose_the_ticket(page)
    expect(field(page, "justification")).to_have_count(0)
    field(page, "status").fill("closed")
    expect(field(page, "justification")).to_be_visible(timeout=30000)


def test_the_panel_offers_only_the_parameters_a_block_may_read(page, api):
    """p.45: "only parameters which appear above the current parameter in the
    form hierarchy can be referenced".

    A narrowing rather than a validation — the server refuses a block that
    reads below itself, and this is why nobody meets that refusal by the
    obvious route. Both directions, because a dropdown offering nothing at all
    would pass a check that only looked for the absence of one name.
    """
    mod = build(api, "Override narrowing", overrides=[])
    open_editor(page, mod)

    # `justification` is second, so it may read `status`.
    page.get_by_label("Add an override to justification").click()
    below = page.get_by_label("justification override 1 parameter")
    expect(below.locator("option")).to_contain_text(["Choose", "current user", "status"])

    # `status` is first, so it may read no parameter at all — only p.50's other
    # template, which is not a parameter and is always available.
    page.get_by_label("Add an override to status").click()
    top = page.get_by_label("status override 1 parameter")
    expect(top.locator("option")).to_have_count(2)
    expect(top.locator("option")).to_contain_text(["Choose", "current user"])


def test_the_panel_warns_about_a_block_that_changes_nothing(page, api):
    """p.45: "If an override is configured to take on the same value as the
    default already set on the parameter, a warning will be shown on the
    override itself."

    A warning rather than a refusal, which is p.45's own choice: the block is
    legal and simply does nothing, and refusing would stop somebody saving a
    form over a line that harms nothing.
    """
    mod = build(api, "Override warning", overrides=[])
    open_editor(page, mod)
    page.get_by_label("Add an override to justification").click()

    warning = page.get_by_test_id("override-same-as-default")
    expect(warning).to_have_count(0)
    # The parameter is already hidden, so a block hiding it changes nothing.
    page.get_by_label("justification override 1 visibility").select_option("true")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("hidden")

    page.get_by_label("justification override 1 visibility").select_option("false")
    expect(warning).to_have_count(0)


def test_the_panel_says_p45s_first_match_rule_only_where_it_can_happen(page, api):
    """A note that is always on screen is one nobody reads when it matters."""
    mod = build(api, "Override order note", overrides=[])
    open_editor(page, mod)
    page.get_by_label("Add an override to justification").click()
    expect(page.get_by_test_id("override-order-note")).to_have_count(0)
    page.get_by_label("Add an override to justification").click()
    expect(page.get_by_test_id("override-order-note")).to_contain_text("only the first")
