"""A link type's status and p.254's note, set where the link is edited (§631;
`object-link-types` p.253-257).

> "A deprecated resource also has metadata that includes: A description for
> why it is being deprecated; A deadline for when it is expected to be deleted
> from the system" (p.254)

What the note is and when it is kept is `apps/api/tests/test_link_deprecation.py`.
What needs a browser is that the link's dialog sets both, that the listing
shows them, and that p.257's cap - which stores less than was asked rather than
refusing - is said rather than silently applied.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture
def linked(api):
    mod = Module(api, "Link status")
    mod.object_type(columns=["id", "name"], rows=[{"id": "A1", "name": "Ada"}],
                    key="id", title="name")
    tag = uuid.uuid4().hex[:6]
    mod.link = api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"mentors_{tag}", "display_name": f"Mentors {tag}",
        "from_type_id": mod.object_type_id, "to_type_id": mod.object_type_id,
        "cardinality": "one_to_many", "from_property": "name", "to_property": "name"})
    return mod


def open_link(page, mod):
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.link["display_name"])
    row.get_by_role("button", name="Edit join").click()
    expect(page.get_by_test_id("status-select")).to_be_visible(timeout=30000)
    return row


def test_a_link_is_deprecated_with_a_note_from_its_dialog(page, api, linked) -> None:
    row = open_link(page, linked)
    expect(page.get_by_test_id("status-select")).to_have_value("experimental")
    page.get_by_test_id("status-select").select_option("deprecated")
    page.get_by_test_id("deprecation-reason").fill("Use the crew roster")
    page.get_by_test_id("deprecation-deadline").fill("2027-01-31")
    page.get_by_role("button", name="Save join").click()
    expect(page.get_by_test_id("status-select")).to_have_count(0)

    expect(row.get_by_test_id("status-badge-deprecated")).to_be_visible()
    expect(row.get_by_test_id(f"link-deprecation-{linked.link['api_name']}")).to_have_text(
        "Use the crew roster, by 2027-01-31")
    stored = next(link for link in api.call(
        "GET", f"/workspaces/{linked.workspace_id}/link-types")
        if link["id"] == linked.link["id"])
    assert stored["deprecation"] == {"reason": "Use the crew roster", "deadline": "2027-01-31"}

    # Back in use, and the note goes with the status.
    open_link(page, linked)
    expect(page.get_by_test_id("deprecation-reason")).to_have_value("Use the crew roster")
    page.get_by_test_id("status-select").select_option("experimental")
    page.get_by_role("button", name="Save join").click()
    expect(page.get_by_test_id("status-select")).to_have_count(0)
    expect(row.get_by_test_id(f"link-deprecation-{linked.link['api_name']}")).to_have_count(0)


def test_a_status_the_cap_does_not_allow_is_said(page, linked) -> None:
    """The link's type is experimental, so the link cannot be active (p.257)."""
    open_link(page, linked)
    page.get_by_test_id("status-select").select_option("active")
    page.get_by_role("button", name="Save join").click()
    expect(page.get_by_test_id("link-status-capped")).to_have_text(
        "Kept as Experimental: a link is no more ready than the object types and "
        "properties it joins (p.257).")
    # The dialog stays, showing what was kept.
    expect(page.get_by_test_id("status-select")).to_have_value("experimental")
