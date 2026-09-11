"""Favouriting an object, from the screen (§312; `getting-started` p.34).

    "When you navigate to an individual object view, you can select the star
     next to its title to save it as a favorite. This will add the object to
     your sidebar… Think of favorites as shortcuts that you can add and remove
     to keep frequently used resources close at hand." (p.34)

The refusals, the cap and the privacy are in
`apps/api/tests/test_object_favourites.py`, and the wording in
`apps/web/src/lib/favourites.test.ts`. What needs a browser is p.34's sentence
end to end: **star an object, and find a shortcut back to it** — which is only
a shortcut if following it returns to the object, and that is what §309's link
was built to make possible.

**The star is on the object view rather than literally beside the title**, and
that is a divergence with a reason: the title lives inside the standard view,
and a configured view has no title of ours at all — it is somebody's Workshop
module. Putting the star in either rendering would give it to one kind of
object and not the other.
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
    """This fixture's own type, for `test_object_links.py`'s reason: the
    Explorer is workspace-wide and the dev database carries every object every
    previous run created."""
    mod = Module(api, "Object favourites")
    # **`title="town"`, and the title property is the point of this fixture.**
    # db 0074 stores the label an object had when it was starred, and that
    # label is the title property's value — so a type whose title is its key
    # would put "1" in the sidebar and every assertion below could be
    # satisfied by an implementation that stored the primary key and nothing
    # else. The first version of this file did exactly that and asserted
    # "Ely" against a row reading "1".
    mod.object_type(columns=["id", "town"], rows=ROWS, key="id", title="town")
    return mod


def sidebar(page):
    """p.34's sidebar.

    By landmark role rather than by label: the star's own `aria-label` is
    "Remove from favourites", so `get_by_label("Favourites")` resolves to both
    the aside and the button — a strict-mode violation that reads as the
    sidebar being empty.
    """
    return page.get_by_role("complementary", name="Favourites")


def open_explorer(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(ROWS),
               what="this type's objects, and only this type's")


def open_first_object(page, module) -> None:
    open_explorer(page, module)
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)
    page.wait_for_url(re.compile(r"object="), timeout=30000)


def unstar_everything(api, module) -> None:
    """Leave the list as this test found it.

    The dev database is never reset and the browser and API fixtures share a
    user, so a favourite left behind is one the next run's empty-state
    assertion has to contend with — which is §310's lesson about shared state,
    applied before it costs anything.
    """
    for f in api.call("GET", f"/workspaces/{module.workspace_id}/object-favourites"):
        api.call(
            "DELETE",
            f"/workspaces/{module.workspace_id}/object-favourites"
            f"/{f['object_type_id']}/{f['instance_id']}",
        )


def test_starring_an_object_puts_a_shortcut_in_the_sidebar(page, api, objects) -> None:
    """**p.34's sentence, end to end.**

    A test that only checked the star filled in would pass against an
    implementation that stored nothing — the button would look right and the
    sidebar would stay empty, which is the failure worth catching.
    """
    unstar_everything(api, objects)
    open_first_object(page, objects)

    star = page.get_by_test_id("favourite-star")
    expect(star).to_be_visible(timeout=30000)
    expect(star).to_have_attribute("aria-pressed", "false")
    star.click()
    expect(star).to_have_attribute("aria-pressed", "true", timeout=30000)

    favourites = sidebar(page)
    expect(favourites).to_contain_text("Ely", timeout=30000)


def test_the_shortcut_opens_the_object_it_points_at(page, api, objects) -> None:
    """**A favourite is only a favourite if it comes back**, which is the whole
    reason §309 came first: the object view is drawn from the address bar, so a
    shortcut *is* a link.

    Asserted after closing the object, so following the shortcut has to reopen
    it rather than find it already there — without that the assertion passes
    against a list that does nothing at all.
    """
    unstar_everything(api, objects)
    open_first_object(page, objects)
    page.get_by_test_id("favourite-star").click()
    expect(sidebar(page)).to_contain_text("Ely", timeout=30000)

    page.keyboard.press("Escape")
    page.wait_for_url(lambda url: "object=" not in url, timeout=30000)
    expect(page.get_by_test_id("standard-object-view")).to_have_count(0)

    sidebar(page).locator(".ox-saved-open").first.click()
    view = page.get_by_test_id("standard-object-view")
    expect(view).to_be_visible(timeout=30000)
    expect(view).to_contain_text("Ely")


def test_the_star_comes_off(page, api, objects) -> None:
    """p.34's shortcuts are ones you "add and remove". A star that only ever
    fills in is a list that only ever grows."""
    unstar_everything(api, objects)
    open_first_object(page, objects)

    star = page.get_by_test_id("favourite-star")
    star.click()
    expect(star).to_have_attribute("aria-pressed", "true", timeout=30000)
    expect(sidebar(page)).to_contain_text("Ely", timeout=30000)

    star.click()
    expect(star).to_have_attribute("aria-pressed", "false", timeout=30000)
    expect(sidebar(page)).to_contain_text("None yet", timeout=30000)


def test_the_star_survives_reopening_the_object(page, api, objects) -> None:
    """The state is the server's, not the button's.

    Read back on a fresh visit rather than after a click, because a star that
    only remembers within one page load is a favourite that is not kept.
    """
    unstar_everything(api, objects)
    open_first_object(page, objects)
    page.get_by_test_id("favourite-star").click()
    expect(page.get_by_test_id("favourite-star")).to_have_attribute(
        "aria-pressed", "true", timeout=30000)
    link = page.url

    page.goto(f"{WEB_BASE}/home")
    page.goto(link)
    expect(page.get_by_test_id("favourite-star")).to_have_attribute(
        "aria-pressed", "true", timeout=30000)


def test_the_empty_sidebar_says_where_the_star_is(page, api, objects) -> None:
    """A star on an object view is not something somebody finds by looking at
    an empty panel, so the empty state names the verb and where it lives."""
    unstar_everything(api, objects)
    open_explorer(page, objects)
    empty = page.get_by_test_id("favourites-empty")
    expect(empty).to_be_visible(timeout=30000)
    expect(empty).to_contain_text("star")


def test_a_shortcut_to_a_deleted_object_says_so_rather_than_vanishing(
    page, api, objects
) -> None:
    """**A real state, and §309's dead-link message is what it lands on.**

    An instance is not a row db 0074 can reference, so nothing cleans a
    favourite up when the object goes. p.34 calls these shortcuts; a shortcut
    to something deleted is an ordinary thing to hold, and the honest answer is
    to keep the row and say what happened when it is followed — not to hide it
    and leave somebody wondering where it went.
    """
    unstar_everything(api, objects)
    api.call(
        "PUT", f"/workspaces/{objects.workspace_id}/object-favourites",
        {"object_type_id": objects.object_type_id,
         "instance_id": str(uuid.uuid4()), "label": "Gone"},
    )
    open_explorer(page, objects)
    favourites = sidebar(page)
    expect(favourites).to_contain_text("Gone", timeout=30000)

    favourites.locator(".ox-saved-open").first.click()
    note = page.get_by_test_id("object-link-missing")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("no longer here")
    unstar_everything(api, objects)
