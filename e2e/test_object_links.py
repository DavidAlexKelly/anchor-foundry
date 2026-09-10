"""A link to one object (§309; `ontology.md` §3; `getting-started` p.34).

The Object Explorer's *search* has been linkable since saved searches were
built — "send me the link to that" is the reason they exist. The object you
open **from** that search was not: it lived in `useState`, so somebody who
found a thing and wanted to show a colleague could send them the search and a
sentence saying which row.

The grammar of the parameter is in `apps/web/src/lib/object-links.test.ts`.
What needs a browser is the **seam**, and it is the only place the claim can be
made: that the URL an open object produces, opened fresh, shows that object —
which is the whole meaning of a link, and is exactly what `useState` could not
do.

**This is also the prerequisite for favouriting an object** (p.34: "select the
star next to its title to save it as a favorite"). A favourite is a shortcut,
and a shortcut needs somewhere to point.
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

ROWS = [
    {"id": "1", "town": "Ely"},
    {"id": "2", "town": "Wells"},
]


@pytest.fixture(scope="module")
def objects(api):
    """One object type of this fixture's own, with two objects in it.

    Its own, because the Explorer is workspace-wide and this dev database
    carries every object every previous run created — "the first row" is
    somebody else's object, which is `test_configured_object_view.py`'s note
    and the reason that suite filters too.
    """
    mod = Module(api, "Object links")
    mod.object_type(columns=["id", "town"], rows=ROWS, key="id")
    return mod


def open_explorer(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(ROWS),
               what="this type's objects, and only this type's")


def test_opening_an_object_puts_it_in_the_url(page, objects) -> None:
    """The half that was missing. Clicking Explore is now a navigation."""
    open_explorer(page, objects)
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)
    # **`wait_for_url`, not `eventually(lambda: page.url, ...)`** — and
    # `conftest.eventually`'s own docstring says why: `page.url` is a cached
    # property updated on a navigation event, and a poll loop that never yields
    # gives the driver no turn, so the same stale string comes back for the
    # whole timeout. Written the wrong way first, and it failed three of these
    # tests while the address bar had changed a second after the click.
    page.wait_for_url(re.compile(r"object="), timeout=30000)
    # Both halves, because the instance store is partitioned by object type and
    # there is no read that takes an instance id alone.
    assert objects.object_type_id in page.url


def test_that_url_opened_fresh_shows_the_same_object(page, objects) -> None:
    """**The claim a browser is needed for**, and the one `useState` could not
    make: a link is only a link if it works somewhere else.

    Asserted through `page.goto` rather than a reload, because the value being
    tested is a URL somebody pastes — and it is fetched from the server, since
    the row that carried the instance is not on screen when a link is followed
    cold.
    """
    open_explorer(page, objects)
    rows = page.locator("tbody tr")
    first = rows.first
    town = first.locator("td").nth(2).inner_text()
    first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)
    page.wait_for_url(re.compile(r"object="), timeout=30000)
    link = page.url

    page.goto(f"{WEB_BASE}/home")
    expect(page.get_by_test_id("standard-object-view")).to_have_count(0)

    page.goto(link)
    view = page.get_by_test_id("standard-object-view")
    expect(view).to_be_visible(timeout=30000)
    expect(view).to_contain_text(town, timeout=30000)


def test_closing_the_object_takes_it_out_of_the_url(page, objects) -> None:
    """The URL is the state, so closing has to change it.

    If it did not, copying the link after closing would send somebody a link to
    a dialog you had shut — and pressing Back would reopen nothing.
    """
    open_explorer(page, objects)
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)
    page.wait_for_url(re.compile(r"object="), timeout=30000)

    # Escape, because `Dialog` closes on Escape or the backdrop rather than
    # carrying a button — which is the platform's own convention, not this
    # dialog's.
    page.keyboard.press("Escape")
    page.wait_for_url(lambda url: "object=" not in url, timeout=30000)
    # Asserted after the URL rather than before it: the dialog is drawn from
    # the URL, so its absence follows and an absence asserted first is one that
    # cannot fail (§291).
    expect(page.get_by_test_id("standard-object-view")).to_have_count(0)


def test_the_link_does_not_bury_the_page_the_reader_came_from(page, objects) -> None:
    """**Opening an object replaces rather than pushes**, which is a choice.

    `useUrlState` writes with `router.replace` for a reason it states: flicking
    between views should not bury the page somebody arrived from under a stack
    of back-button steps. So opening an object is shareable but is *not* a
    history step, and Back leaves the Explorer rather than closing the dialog.

    The first version of this test asserted the opposite — that Back closes the
    object — which is what you would expect if the parameter were pushed. It is
    written down here because "Back closes it" is the intuition, and the code
    deliberately does something else.
    """
    before = page.url
    open_explorer(page, objects)
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)
    page.wait_for_url(re.compile(r"object="), timeout=30000)

    page.go_back()
    # Back leaves the Explorer entirely, because opening the object added no
    # history entry to go back *to*.
    page.wait_for_url(lambda url: "explore" not in url or url == before, timeout=30000)


def test_a_link_to_an_object_that_is_gone_says_which(page, objects) -> None:
    """Ordinary rather than exceptional.

    Links get truncated on the way through a chat client and objects get
    deleted between somebody sending a link and somebody following it — so the
    page says which of the two happened, and leaves the search underneath
    rather than replacing it with an error.
    """
    gone = f"{objects.object_type_id}:{uuid.uuid4()}"
    page.goto(f"{WEB_BASE}/{objects.workspace_slug}/explore"
              f"?type={objects.object_type_id}&object={gone}")
    note = page.get_by_test_id("object-link-missing")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("no longer here")
    expect(page.get_by_test_id("standard-object-view")).to_have_count(0)


def test_a_link_cut_short_blames_the_link_rather_than_the_object(page, objects) -> None:
    """The other of the two, and the reason they are told apart: an object that
    is gone is gone, while a link that arrived broken can be asked for again."""
    cut = f"{objects.object_type_id}:aabbccdd-7777"
    page.goto(f"{WEB_BASE}/{objects.workspace_slug}/explore"
              f"?type={objects.object_type_id}&object={cut}")
    note = page.get_by_test_id("object-link-missing")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("cut short")
    expect(note).not_to_contain_text("deleted")


def test_the_search_the_object_was_found_by_survives_the_link(page, objects) -> None:
    """A link carries both the question and the answer.

    The object parameter is added *beside* the search rather than replacing it,
    so following the link lands on the same list with the same object open —
    which is what somebody sending it meant to share.
    """
    open_explorer(page, objects)
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)
    page.wait_for_url(re.compile(r"object="), timeout=30000)
    assert re.search(rf"type={objects.object_type_id}", page.url), page.url
