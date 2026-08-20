"""Promotion in the Ontology Manager (parity `docs/parity/ontology.md` §1.3;
Foundry `object-link-types` p.255).

> "Only users with the `Ontology Owner` role on the ontology level can directly
> apply the `promoted` status." (p.255)

**Both sides of a permission need a browser, and they need different ones.** An
option that is hidden from the wrong person is a feature; an option hidden from
the *right* person is the feature switched off, and neither shows up in a test
that only ever signs in as one user. So this file opens a second session as the
editor and compares.

The trap it guards is the one §175's tests are named after: the server gates
the *transition*, so an editor may still save an already-promoted type. A
dropdown that hid the option from them would have no entry matching its own
value - a blank select that silently demotes the type on the next save.
"""
from __future__ import annotations

import json
import os
import uuid

import pytest
from playwright.sync_api import expect

from api import Api
from conftest import API_BASE, FIRST_RENDER_MS, TOKENS_FILE, WEB_BASE

ROWS = [{"id": "R1", "name": "Ada"}, {"id": "R2", "name": "Grace"}]


@pytest.fixture(scope="module")
def module(api):
    from api import Module

    things = Module(api, "Promotion")
    things.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    return things


@pytest.fixture(scope="session")
def editor_token() -> str:
    with open(TOKENS_FILE) as handle:
        return json.load(handle)["editor@acme.dev.local"]


@pytest.fixture
def editor_page(browser, editor_token: str):
    """A second signed-in session, as somebody who may *not* promote.

    Deliberately a whole context rather than a re-login: the two sessions run
    side by side in one test, which is what makes "the same screen, two
    people" a single comparison rather than two runs somebody has to line up
    by eye.
    """
    context = browser.new_context(viewport={"width": 1500, "height": 1200})
    opened = context.new_page()
    opened.goto(f"{WEB_BASE}/login")
    opened.fill("input[placeholder='Paste an access token']", editor_token)
    opened.get_by_role("button", name="Use token").click()
    opened.wait_for_url(lambda url: "/login" not in url, timeout=FIRST_RENDER_MS)
    yield opened
    context.close()


def open_editor(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("status-select")).to_be_visible(timeout=15000)


def options_of(page) -> list[str]:
    options = page.get_by_test_id("status-select").locator("option")
    return [options.nth(i).inner_text() for i in range(options.count())]


def test_an_admin_is_offered_promoted(page, module) -> None:
    """The owner token this suite signs in with is an org owner, which
    resolves to workspace `admin` (db 0005) - this platform's ontology
    level."""
    open_editor(page, module)
    assert "Promoted" in options_of(page), options_of(page)


def test_an_editor_is_not(editor_page, module) -> None:
    """p.255's restriction, on the screen. Offering it would be offering a
    save the server refuses, and the hint says who to ask instead."""
    open_editor(editor_page, module)
    assert "Promoted" not in options_of(editor_page), options_of(editor_page)
    expect(editor_page.get_by_test_id("promote-blocked")).to_be_visible()
    expect(editor_page.get_by_test_id("promote-blocked")).to_contain_text(
        "workspace admin"
    )


def test_promoting_shows_the_badge_and_survives_an_editors_save(
    page, editor_page, module, api
) -> None:
    """**The trap, end to end.**

    An admin promotes; then an editor opens the same type and saves an
    unrelated change. The status has to survive - and the editor's dropdown
    has to still show `Promoted`, because a select with no entry matching its
    own value renders blank and demotes the type on the next save.
    """
    open_editor(page, module)
    page.get_by_test_id("status-select").select_option("promoted")
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.text()

    # p.255's own reason for the rule: it becomes more discoverable.
    detail = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )
    assert detail["status"] == "promoted", detail
    assert detail["visibility"] == "prominent", detail

    # Now the editor. The option is still there for them...
    open_editor(editor_page, module)
    assert "Promoted" in options_of(editor_page), options_of(editor_page)
    expect(editor_page.get_by_test_id("status-select")).to_have_value("promoted")

    # ...and an unrelated edit goes through without demoting anything.
    editor_page.get_by_role("textbox", name="Description", exact=False).fill(
        f"Edited {uuid.uuid4().hex[:6]}"
    )
    with editor_page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "PATCH"
    ) as edited:
        editor_page.get_by_role("button", name="Save", exact=True).click()
    assert edited.value.ok, edited.value.text()

    after = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )
    assert after["status"] == "promoted", after
