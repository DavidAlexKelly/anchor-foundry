"""The Versions dialog (parity `workshop.md` §6; Foundry p.191–192).

`STATUS.md` §88 made publishing mean something: saving does not move viewers,
publishing does. That is only an improvement if a builder can *see* it and act
on it, which is what this dialog is for:

    "The Versions dialog is where builders can view a history of the saved
     versions for a module. Each saved version displays a timestamp, editor,
     and description if available." (p.191)

The API half is tested in `apps/api/tests/test_canvas.py` — publishing a named
version, reverting, the generated description, auto-publish. What needs a
browser is the part that is a *screen*: that the history is legible, that
viewing an old version does not put you in an editor pointed at it, and that
the warning banner appears when it should and not when it should not.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, no_console_errors, open_builder, settled


def three_saves(api, name: str):
    """A module with three versions, so there is a history rather than a row."""
    mod = Module(api, name)
    for text in ("FIRST", "SECOND", "THIRD"):
        mod.define({
            "format": 2,
            "layout": layout({
                "t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": text}},
            }),
            "variables": {},
            "events": {},
        })
    return mod


# **One module per mutating test**, which is the lesson from the config-tabs
# suite: publishing and reverting change what the *next* test would read, and a
# claim about "the published version" cannot be checked against a module some
# earlier test has already published something else on. The read-only tests
# share one.
@pytest.fixture(scope="module")
def module(api):
    return three_saves(api, "Versions read")


@pytest.fixture(scope="module")
def publishable(api):
    return three_saves(api, "Versions publish")


@pytest.fixture(scope="module")
def viewable(api):
    return three_saves(api, "Versions view")


@pytest.fixture(scope="module")
def published_view(api):
    return three_saves(api, "Versions view published")


@pytest.fixture(scope="module")
def revertible(api):
    return three_saves(api, "Versions revert")


def open_versions(page, module):
    open_builder(page, module)
    page.get_by_role("button", name="Versions", exact=True).click()
    expect(page.get_by_test_id("versions-table")).to_be_visible()


def rows(page):
    return page.get_by_test_id("versions-table").locator("tbody tr")


def test_the_dialog_lists_every_saved_version_newest_first(page, module):
    open_versions(page, module)
    eventually(lambda: rows(page).count(), lambda n: n == 3, what="three saved versions")
    first = rows(page).first
    expect(first).to_have_attribute("data-version", "3")
    assert not no_console_errors(page)


def test_each_version_names_its_editor(page, module):
    """p.191 lists "a timestamp, editor, and description". A uuid where a
    person belongs is a dialog nobody reads twice, so the *name* is asserted."""
    open_versions(page, module)
    text = rows(page).first.inner_text()
    assert "@" not in text, text  # not an email either — a display name
    # The dev fixture's editor. Any non-empty name would do; a uuid would not.
    assert any(c.isalpha() for c in text.split("\t")[2]), text


def test_publishing_a_named_version_moves_the_marker_to_it(page, publishable):
    """"Publish this version" (p.191) — viewers move to a version somebody
    chose, not to whatever is newest."""
    open_versions(page, publishable)
    page.get_by_test_id("publish-v1").click()

    marker = page.get_by_test_id("published-pill")
    eventually(lambda: marker.count(), lambda n: n == 1, what="exactly one published marker")
    row = rows(page).filter(has=marker)
    expect(row).to_have_attribute("data-version", "1")


def test_viewing_an_unpublished_version_warns_and_does_not_edit(page, viewable):
    """p.191: "When viewing a non-published version, a warning banner will
    appear at the top of the module."

    The second half is ours rather than Foundry's wording, and it is the one
    that matters: a historic document in an editable canvas is one Save away
    from silently becoming current.
    """
    open_versions(page, viewable)
    page.get_by_test_id("publish-v1").click()
    eventually(lambda: page.get_by_test_id("published-pill").count(), lambda n: n == 1,
               what="v1 published")

    page.get_by_role("button", name="View", exact=True).first.click()

    view = page.get_by_test_id("version-view")
    expect(view).to_be_visible()
    expect(view).to_have_attribute("data-version", "3")
    expect(page.get_by_test_id("unpublished-banner")).to_be_visible()

    # Presence before absence: the old document is drawn, *then* there is no
    # editing surface — otherwise "no Save button" would pass on a blank page.
    expect(page.get_by_text("THIRD")).to_be_visible()
    expect(page.get_by_role("button", name="Save", exact=True)).to_have_count(0)


def test_viewing_the_published_version_shows_no_warning(page, published_view):
    """The banner is conditional exactly as p.191 documents it. One that
    appeared every time is one people learn to ignore."""
    open_versions(page, published_view)
    page.get_by_test_id("publish-v3").click()
    eventually(lambda: page.get_by_test_id("published-pill").count(), lambda n: n == 1,
               what="v3 published")

    page.get_by_role("button", name="View", exact=True).first.click()
    expect(page.get_by_test_id("version-view")).to_be_visible()
    # Drawn first, so the absence is about the banner rather than the page.
    expect(page.get_by_text("THIRD")).to_be_visible()
    expect(page.get_by_test_id("unpublished-banner")).to_have_count(0)


def test_a_description_can_be_added_from_the_dialog(page, module):
    """p.192: descriptions "can be viewed, added, and edited in the module's
    Versions dialog"."""
    open_versions(page, module)
    row = rows(page).first
    row.get_by_text("Add a description").click()
    page.get_by_test_id("description-input").fill("Renamed the heading")
    page.keyboard.press("Enter")

    eventually(lambda: rows(page).first.inner_text(),
               lambda t: "Renamed the heading" in t, what="the saved description")

    # And it survives a reload, which is what makes it a record rather than a
    # field on a form.
    page.reload()
    settled(page)
    page.get_by_role("button", name="Versions", exact=True).click()
    eventually(lambda: rows(page).first.inner_text(),
               lambda t: "Renamed the heading" in t, what="the description after a reload")


def test_reverting_makes_the_old_document_the_newest_one(page, revertible):
    """p.192: revert "saves the historic version as the newest version" — a new
    version, not a rewind, so the history in between survives."""
    open_versions(page, revertible)
    # Waited for rather than read straight away: a bare `count()` on a table
    # that has not finished rendering gives a number the rest of the test then
    # measures against, and the failure reads as "revert added the wrong number
    # of versions" rather than "the baseline was wrong".
    before = eventually(lambda: rows(page).count(), lambda n: n == 3,
                        what="the three saved versions, before reverting")

    page.get_by_test_id("revert-v1").click()
    settled(page)

    # The canvas now shows what v1 showed.
    eventually(lambda: page.get_by_text("FIRST").count(), lambda n: n >= 1,
               what="the reverted document on the canvas")

    page.get_by_role("button", name="Versions", exact=True).click()
    eventually(lambda: rows(page).count(), lambda n: n == before + 1,
               what="one more version, not one fewer")
    assert "Reverted to version 1" in rows(page).first.inner_text()
