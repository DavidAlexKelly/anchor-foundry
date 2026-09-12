"""What an object parameter offers, on the screen (§330; `action-types` p.25,
p.33-37).

    "After configuring the filters, the action form will render a dropdown with
     only objects that match the filter. **The value selected is also validated
     before the action is executed.**" (p.34)

The list and the refusal are tested in `apps/api/tests/test_action_choices.py`
and the wording in `apps/web/src/lib/action-choices.test.ts`. What needs a
browser is the thing this unit is for:

**an object parameter was a box you typed a uuid into.**

p.33-37 is about narrowing a dropdown, and there was no dropdown. So these
tests are about the control existing, offering the right objects, and
submitting the one that was picked — and about the parameters nobody has typed
keeping exactly the box they had.
"""
from __future__ import annotations

import json
import uuid

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, open_module
from ontology_page import pick_type


def build(api, name: str, *, typed: bool, teams: int = 2) -> Module:
    """An action over a ticket, with an object parameter naming a *team*.

    Two types, because the whole point of the column is that the parameter's
    type is not the action's own — a fixture where they coincided could not
    tell a working lookup from one that always used the subject type.
    """
    mod = Module(api, name)
    tag = uuid.uuid4().hex[:8]
    team_type = mod.object_type(
        columns=["code", "name"],
        rows=[{"code": f"t{n}", "name": f"Team {n}"} for n in range(1, teams + 1)],
        key="code",
        title="name",
        slug=f"team_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["ticket_id", "note"],
        rows=[{"ticket_id": "1", "note": ""}],
        key="ticket_id",
        title="ticket_id",
        slug=f"ticket_{tag}",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"assign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    team = {"api_name": "team", "display_name": "Team", "data_type": "object"}
    if typed:
        team["object_type_id"] = team_type
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "note", "display_name": "Note", "data_type": "string"},
             team,
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "note"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "CHOICES FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.team_type = team_type
    mod.team_api_name = f"team_{tag}"
    mod.action = action
    return mod


def field(page, name: str):
    return page.locator(f"[data-parameter='{name}'] input")


def picker(page, name: str):
    return page.locator(f"[data-parameter='{name}'] select")


def choose_the_ticket(page) -> None:
    page.locator("form > label select").first.select_option(index=1)
    expect(field(page, "note")).to_have_count(1)


def test_a_typed_object_parameter_is_a_dropdown_of_its_objects(page, api):
    """**The control p.33-37 assumes and this platform did not have.**

    Both halves: there is a select, and there is no longer a text box — the
    first alone would pass for a form that drew both.
    """
    mod = build(api, "Choices typed", typed=True)
    open_module(page, mod)
    choose_the_ticket(page)

    expect(picker(page, "team")).to_have_count(1)
    expect(field(page, "team")).to_have_count(0)
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose a", "Team 1", "Team 2"]
    )


def test_an_untyped_object_parameter_keeps_the_box_it_had(page, api):
    """Every action written before §330 is in this state, and nothing about it
    changed. Offering a *guessed* list would be worse than offering none: a
    reader cannot tell a wrong list from a short one."""
    mod = build(api, "Choices untyped", typed=False)
    open_module(page, mod)
    choose_the_ticket(page)

    expect(field(page, "team")).to_have_count(1)
    expect(picker(page, "team")).to_have_count(0)


def test_the_picked_object_is_what_gets_submitted(page, api):
    """**The control is not decoration.** The option's value is the object's
    id, so what the dropdown sends is what somebody typing into the old box
    would have had to look up — which is the whole point of the unit.

    **Asserted on the request**, because that is where the claim lives. The
    obvious alternative is the run log, and it cannot answer this: on the
    success path `submitted_values` records `apply_rules`' output rather than
    what arrived, so the object parameter is simply absent from it while the
    refusal path records the request faithfully. That is a pre-existing
    inconsistency in the log rather than §330's to fix — the column is read by
    revert — but it is the reason this watches the network.
    """
    mod = build(api, "Choices submit", typed=True)
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.post_data or "")
            if "/execute" in r.url else None)

    open_module(page, mod)
    choose_the_ticket(page)
    field(page, "note").fill("assigned")
    picker(page, "team").select_option(label="Team 2")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")

    teams = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.team_type}/instances"
    )["items"]
    picked = next(t for t in teams if t["properties"]["name"] == "Team 2")
    assert len(sent) == 1, sent
    body = json.loads(sent[0])
    assert body["values"]["team"] == picked["id"], body
    # And it is the object's id rather than its label, which is what makes the
    # dropdown a replacement for the box rather than a second thing to reconcile.
    assert body["values"]["team"] != "Team 2"


def test_a_type_with_no_objects_says_so_rather_than_drawing_an_empty_list(page, api):
    """§214: an empty dropdown is a control that looks like it works — somebody
    opens it, finds nothing, and cannot tell whether the list failed to load."""
    mod = build(api, "Choices empty", typed=True, teams=0)
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.get_by_test_id("choices-empty")).to_be_visible(timeout=30000)


def test_the_dropdown_is_named_for_the_type_it_offers(page, api):
    """A form with two object parameters would otherwise have two identical
    "Choose…" rows and no way to tell which asked for what."""
    mod = build(api, "Choices named", typed=True)
    open_module(page, mod)
    choose_the_ticket(page)
    expect(picker(page, "team").locator("option").first).to_contain_text("Choose a Team")


# ---- the editor ---------------------------------------------------------------
def open_editor(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_the_editor_says_what_an_untyped_object_parameter_is_missing(page, api):
    """Addressed to the person who can fix it, and not called an error: the
    parameter works exactly as it always has."""
    mod = build(api, "Choices editor note", typed=False)
    open_editor(page, mod)
    note = page.get_by_test_id("parameter-untyped")
    expect(note).to_be_visible()
    expect(note).to_contain_text("dropdown")
    expect(note).to_contain_text("checked before the action runs")


def test_typing_a_parameter_in_the_editor_gives_the_form_its_dropdown(page, api):
    """**p.33-37's precondition, end to end through the screen**: say what the
    parameter holds in the dialog, and find the form offering those objects."""
    mod = build(api, "Choices editor loop", typed=False)
    open_editor(page, mod)

    # Through `pick_type`, because a `TypePicker` is a search control (§256):
    # on a workspace whose ontology outgrew a page the option only arrives with
    # the search's response, so selecting by id alone works on a fresh database
    # and not on the one this suite actually runs against.
    pick_type(page, "parameter-2-object-type",
              {"id": mod.team_type, "api_name": mod.team_api_name})
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    team = next(p for p in saved["parameters"] if p["api_name"] == "team")
    assert team["object_type_id"] == mod.team_type

    open_module(page, mod)
    choose_the_ticket(page)
    expect(picker(page, "team")).to_have_count(1)
    expect(picker(page, "team").locator("option")).to_contain_text(["Team 1"])


def test_the_note_goes_once_the_parameter_is_typed(page, api):
    """The other direction, which "the note is shown" alone would not cover:
    a hint that never goes away is one nobody reads."""
    mod = build(api, "Choices editor note gone", typed=True)
    open_editor(page, mod)
    expect(page.get_by_test_id("parameter-untyped")).to_have_count(0)
