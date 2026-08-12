"""Previewing a linked object without going to it (parity `ontology.md` §4.1;
Foundry `object-views` p.11).

The Linked objects component's point is that a relationship is answerable *in
place*: "which team owns this ticket, and what region is that team in" should
not cost a hop you then have to come back from. Traversing was the only thing
a link row did; this is the other click.

It also closes a leak. The row summary used to read straight off the
instance's stored properties, so a property marked **hidden** (p.111) appeared
next to every linked object that had one - honoured by the standard Object View
and by the Explorer's columns, and by nothing here. Both now go through one
rule, `components/object-properties.ts`, which is unit-tested.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

TICKETS = [
    {"id": "T1", "summary": "Alpha ticket", "owner": "north"},
    {"id": "T2", "summary": "Beta ticket", "owner": "south"},
]
TEAMS = [
    {"code": "north", "region": "Northern", "internal_note": "DO NOT SHOW"},
    {"code": "south", "region": "Southern", "internal_note": "DO NOT SHOW"},
]


@pytest.fixture(scope="module")
def linked(api):
    """A Ticket type and a Team type in one project, joined on owner = code.

    The Team carries a **hidden** property, which is the whole point of the
    second half of this file: a hidden property is what a preview and a summary
    must not show, and a fixture without one cannot tell a working rule from a
    missing one.
    """
    tickets = Module(api, "Linked preview")
    ticket_type = tickets.object_type(
        columns=["id", "summary", "owner"], rows=TICKETS, key="id", title="summary",
    )
    teams = Module(api, "Linked preview far", beside=tickets)
    team_type = teams.object_type(
        columns=["code", "region", "internal_note"],
        rows=TEAMS,
        key="code",
        title="code",
        visibility={"region": "prominent", "internal_note": "hidden"},
    )
    api.call(
        "POST",
        f"/workspaces/{tickets.workspace_id}/link-types",
        {
            "api_name": f"owned_by_{tickets.tag}",
            "display_name": "Owned by",
            "from_type_id": ticket_type,
            "to_type_id": team_type,
            "cardinality": "one_to_many",
            "from_property": "owner",
            "to_property": "code",
        },
    )
    return tickets


def open_first_ticket(page, module):
    """Open the Explorer filtered to the ticket type, and click into a ticket.

    Filtered for `test_standard_object_view.py`'s reason: the Explorer is
    workspace-wide and this dev database carries every object every previous
    run created.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(TICKETS),
               what="this type's tickets, and only this type's")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_text("Linked objects", exact=True)).to_be_visible()


def test_a_linked_object_previews_without_navigating(page, linked):
    """p.11's inline preview. The trail is the evidence it did not navigate:
    a hop would have pushed a second stop onto it, and this asserts the
    properties arrived with the trail still where it was."""
    open_first_ticket(page, linked)
    preview = page.get_by_role("button", name="Preview north")
    expect(preview).to_be_visible()
    preview.click()

    table = page.locator("[data-testid^='link-preview-']")
    expect(table).to_be_visible()
    expect(table.locator("[data-property='region']")).to_contain_text("Northern")
    # Still on the ticket: previewing is not traversing, so no breadcrumb trail
    # appeared and the dialog title has not changed.
    expect(page.get_by_label("Traversal trail")).to_have_count(0)


def test_the_preview_closes_again(page, linked):
    open_first_ticket(page, linked)
    page.get_by_role("button", name="Preview north").click()
    expect(page.locator("[data-testid^='link-preview-']")).to_be_visible()
    page.get_by_role("button", name="Preview north").click()
    expect(page.locator("[data-testid^='link-preview-']")).to_have_count(0)


def test_a_hidden_property_is_not_in_the_preview(page, linked):
    """p.111's visibility, on the surface that did not honour it. Presence
    before absence: the preview has drawn, so "no DO NOT SHOW" is about the
    rule rather than about an empty panel."""
    open_first_ticket(page, linked)
    page.get_by_role("button", name="Preview north").click()
    table = page.locator("[data-testid^='link-preview-']")
    expect(table).to_contain_text("Northern")
    expect(table).not_to_contain_text("DO NOT SHOW")
    expect(table.locator("[data-property='internal_note']")).to_have_count(0)


def test_a_hidden_property_is_not_in_the_row_summary_either(page, linked):
    """**The leak this unit found.** The summary read straight off the
    instance's stored properties, with no visibility rule anywhere near it, so
    a hidden value appeared on the row itself - before anybody clicked
    anything."""
    open_first_ticket(page, linked)
    row = page.get_by_role("button", name="Preview north").locator("xpath=..")
    expect(row).to_contain_text("north")
    expect(row).not_to_contain_text("DO NOT SHOW")


def test_the_summary_leads_with_the_prominent_property(page, linked):
    """p.10: prominent is the object type saying "this is what identifies one
    of these", which is exactly the question a one-line summary asks. `region`
    is declared second and is what shows first."""
    open_first_ticket(page, linked)
    row = page.get_by_role("button", name="Preview north").locator("xpath=..")
    expect(row).to_contain_text("Region: Northern")
