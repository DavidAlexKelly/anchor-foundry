"""Uploading an attachment through an action (`action-types` p.127–128).

> "In the parameter configuration view, select Attachment as the parameter
> type. Attachments can only be uploaded using attachment parameter types. The
> corresponding column in the object-backing dataset must be a String and the
> edited object property must be of type Attachment." (p.127)

> "Attachments are immediately uploaded to Foundry once they are added to an
> action form." (p.128)

**The thing this checks is that the control can produce a value the server will
take.** Every piece existed before §237 — the `attachment` property type (db
0029), `POST /attachments` (§39, §223), `attachment` in
`actions._PARAMETER_TYPES` — and the Canvas Action Form still rendered a *text
box* for the parameter, because `pure.inputTypeFor` answers `"text"` for
anything it does not name. A text box cannot produce what
`property_values._coerce_attachment` requires: the object the upload endpoint
returned, with all four of its fields. So the widget offered a control that
could only ever fail, which is the shape §214 refuses for settings.

Asserted through the object rather than through the form: the form saying
"Attached: x.txt" is the form agreeing with itself.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_module, settled


@pytest.fixture(scope="module")
def tickets(api):
    """A ticket type with an `attachment` property, and an action that writes
    it from an attachment parameter — p.127's two halves."""
    mod = Module(api, "Action attachment")
    mod.type_id = mod.object_type(
        columns=["ticket_id", "status", "evidence"],
        # **Two tickets, and each test names the one it uses.** The submit test
        # writes an attachment onto its ticket, and p.25's seeding then fills
        # the parameter from the object — so a later test sharing that ticket
        # would find the required parameter already satisfied and Submit
        # already enabled. That is the form behaving correctly; it is the
        # *fixture* that would be lying. Selecting by label rather than by
        # index keeps the two apart whatever order the instances come back in.
        rows=[
            {"ticket_id": "1", "status": "open", "evidence": ""},
            {"ticket_id": "2", "status": "open", "evidence": ""},
        ],
        key="ticket_id", title="ticket_id",
        types={"evidence": "attachment"},
    )
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {
            "object_type_id": mod.type_id,
            "api_name": f"attach_{uuid.uuid4().hex[:8]}",
            "display_name": "Attach evidence",
            "editable_properties": ["evidence"],
        },
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "evidence", "display_name": "Evidence",
                 "data_type": "attachment", "required": True},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "evidence", "parameter": "evidence"}},
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


def field(page):
    return page.locator('[data-parameter="evidence"]')


def test_an_attachment_parameter_draws_a_file_picker(page, api, tickets) -> None:
    """p.127: attachments are uploaded "using attachment parameter types".

    **The assertion is the input's `type`**, because that is exactly what was
    wrong: a text box here is a control a viewer cannot satisfy, and it looked
    like a working form.
    """
    mod = build(api, tickets, "Attach picker")
    open_module(page, mod)
    settled(page)

    control = field(page).locator("input")
    expect(control).to_have_attribute("type", "file")


def test_submitting_writes_the_reference_the_upload_returned(
    page, api, tickets, tmp_path
) -> None:
    """p.128: the file is uploaded when it is added, and the action writes the
    reference.

    **Read back off the object**, not off the form. `property_values`
    `_coerce_attachment` refuses anything that is not the four-field object the
    upload endpoint returned, so a stored value with a `key` and the right
    filename is proof the whole path held: file picked, uploaded, reference
    carried through the form, coerced, written.
    """
    mod = build(api, tickets, "Attach submit")
    open_module(page, mod)
    settled(page)

    # Ticket 1 is this test's; see the fixture. The Record dropdown has no test
    # id, and the attachment parameter renders a file input rather than a
    # select, so `form select` is unambiguous here.
    page.locator("form select").select_option(label="1")
    upload = tmp_path / "evidence.txt"
    upload.write_text("the evidence")
    field(page).locator("input").set_input_files(str(upload))

    # p.128's "immediately uploaded" — the form holds a reference before Submit
    # is pressed, which is what makes the button become pressable at all.
    expect(page.get_by_role("button", name="Submit")).to_be_enabled()
    page.get_by_role("button", name="Submit").click()

    def stored():
        rows = api.call(
            "POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
            {"definition": {"object_type_id": mod.type_id, "filters": []}, "limit": 5},
        )["instances"]
        one = next(r for r in rows if (r.get("properties") or {}).get("ticket_id") == "1")
        return (one.get("properties") or {}).get("evidence")

    got = eventually(stored, lambda v: isinstance(v, dict) and bool(v.get("key")),
                     what="the attachment reference on the object")
    assert got["filename"] == "evidence.txt", got
    assert got["content_type"], got
    assert got["size"] == len("the evidence"), got


def test_a_required_attachment_blocks_submission_until_one_is_picked(
    page, api, tickets, tmp_path
) -> None:
    """p.25's required check, at the parameter type that made the old rule
    accidentally correct.

    The form used to ask `!String(values[name] ?? "").trim()`, which said
    "supplied" for an attachment because `"[object Object]"` is non-blank rather
    than because an object is a value. `pure.hasValue` states the rule; this is
    the end of it a browser can see.
    """
    mod = build(api, tickets, "Attach required")
    open_module(page, mod)
    settled(page)

    # **Ticket 2, which no other test writes to.** p.25's seeding fills a
    # parameter from the object, so a ticket that already carries an attachment
    # has the required parameter satisfied before anything is picked — which is
    # right, and would make this assertion pass for the wrong reason.
    page.locator("form select").select_option(label="2")
    expect(page.get_by_role("button", name="Submit")).to_be_disabled()

    upload = tmp_path / "later.txt"
    upload.write_text("x")
    field(page).locator("input").set_input_files(str(upload))
    expect(page.get_by_role("button", name="Submit")).to_be_enabled()


def test_the_picker_is_inert_in_the_builder(page, api, tickets) -> None:
    """Uploading from the builder would put a file on an object while somebody
    is editing the module that shows it."""
    from conftest import open_builder

    mod = build(api, tickets, "Attach builder")
    open_builder(page, mod)
    settled(page)

    expect(field(page).locator("input")).to_be_disabled()
