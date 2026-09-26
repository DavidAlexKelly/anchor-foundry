"""p.402's Track user edit history, and the Edit History widget (parity
`workshop.md` §10, `ontology.md`; §470, §471).

> "The Edit History widget displays the list of user edits made to an object's
> properties after Track user edit history has been enabled for the object type
> within Ontology Manager." (p.402)

What is recorded is `apps/api/tests/test_object_edits.py`, which drives the
three action paths. What needs a browser is the switch an author finds in the
type's editor, and what a reader sees.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE
from ontology_page import find_type_row, save_type


@pytest.fixture(scope="module")
def people(api):
    mod = Module(api, "Edit history")
    mod.object_type(
        columns=["id", "name", "email"],
        rows=[{"id": "p1", "name": "Ada", "email": "ada@example.com"},
              {"id": "p2", "name": "Grace", "email": "grace@example.com"}],
        key="id", title="name",
    )
    return mod


def setting(api, mod) -> str | None:
    return api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.object_type_id}/edit-history",
    )["since"]


def test_the_type_editor_switches_tracking_on_and_off(page, api, people) -> None:
    """p.402's "within Ontology Manager": the type's own editor, saved with
    the rest of it, and read back from the API rather than from the dialog."""
    assert setting(api, people) is None
    page.goto(f"{WEB_BASE}/{people.workspace_slug}/{people.project_slug}/objects")
    find_type_row(page, f"seed_{people.tag}").get_by_role("button", name="Edit").click()
    box = page.get_by_test_id("type-track-edit-history")
    expect(box).to_be_enabled()
    expect(box).not_to_be_checked()
    box.check()
    save_type(page)
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert setting(api, people) is not None

    find_type_row(page, f"seed_{people.tag}").get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("type-track-edit-history")).to_be_checked()
    expect(page.get_by_text("Tracked since")).to_be_visible()
    page.get_by_test_id("type-track-edit-history").uncheck()
    save_type(page)
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert setting(api, people) is None
