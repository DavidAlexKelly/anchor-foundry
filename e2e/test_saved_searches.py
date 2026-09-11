"""Saving an Object Explorer search, from the screen (§308; `ontology.md` §3).

The capability has existed since db 0040 and is thoroughly tested at the API
layer — 18 tests in `apps/api/tests/test_saved_searches.py`, including the one
the schema comment argues for: **a saved search stores the question, never the
answer**, because "vessels flagged NO" is a question whose answer is different
tomorrow.

**Nothing drove the screen**, and §307's audit is what turned that up: the row
in `ontology.md` had said ○ with an empty Notes cell for long enough that
nobody remembered it was built. This is that gap closed, and it is the half a
browser is needed for — the round trip from *typing a search* to *opening it
again and getting the search back*, which is what separates saving one from
bookmarking it.

**What is here and what is not.** These drive the screen: the round trip from
typing a search to opening it again and getting the search back, and that the
list is read from the server rather than from this browser.

**The empty state is deliberately not here** (§310). Asserting it needs a
workspace nobody has saved a search in, so this file created one — and
`workspaces.list_for_user` orders by name while the suite's `Module` takes
`workspaces[0]`, so the new workspace sorted before the seeded one and every
test built after it landed in the wrong place. It is a sentence, which is the
cheapest thing there is to check without a browser:
`apps/web/src/lib/saved-searches.test.ts`.

Sharing *between people* is not here either — the `page` and `api` fixtures
carry the same token, so a browser test cannot establish it without a second
session this suite has no fixture for. It is checked where it can be:
`apps/api/tests/test_saved_searches.py` saves as the editor and reads back as
the viewer.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def explorer(api):
    """One object type with a word nothing else in the workspace carries.

    The dev workspace holds thousands of types (`STATUS.md`'s note on the
    accumulating database), so a search for anything ordinary matches a
    stranger's fixture. A tagged word is the only query whose result set this
    test can make claims about.
    """
    mod = Module(api, "Saved searches")
    word = f"kestrel{uuid.uuid4().hex[:6]}"
    api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"fleet_{word}",
            "display_name": f"Fleet {word}",
            "properties": [{"api_name": "name", "data_type": "string"}],
        },
    )
    mod.word = word
    return mod


def open_explorer(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore")
    expect(page.get_by_label("Saved searches")).to_be_visible(timeout=30000)


def search_for(page, text: str) -> None:
    page.get_by_role("searchbox").first.fill(text)
    page.get_by_role("button", name="Search", exact=True).click()


def test_a_search_is_saved_and_comes_back_as_the_search(page, explorer) -> None:
    """**The round trip, which is the only thing a browser is needed for.**

    Type a search, save it under a name, and open it again from the list — and
    the search box holds the question again. A test that only checked the row
    appeared would pass against an implementation that stored the *name* and
    forgot the search, which is the failure worth catching: the row would look
    right and open onto nothing.
    """
    name = f"Kestrels {explorer.word}"
    open_explorer(page, explorer)
    search_for(page, explorer.word)

    page.get_by_role("button", name="Save this search").click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    # The dialog spells out what is being saved, because a saved search is a
    # question somebody else runs months later.
    expect(dialog).to_contain_text(explorer.word)
    dialog.get_by_label("Name").fill(name)
    dialog.get_by_role("button", name="Save search").click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=30000)

    saved = page.get_by_label("Saved searches")
    expect(saved).to_contain_text(name, timeout=30000)

    # Clear the box, so opening the saved search has to *restore* the question
    # rather than find it already there — without this the assertion below
    # passes on a saved search that stores nothing at all.
    page.get_by_role("button", name="Clear", exact=True).click()
    expect(page.get_by_role("searchbox").first).to_have_value("")

    # `.ox-saved-open`, not the name: the Delete button's `aria-label` is
    # "Delete <name>", so a name match resolves to both.
    saved.locator(".ox-saved-open").filter(has_text=name).click()
    expect(page.get_by_role("searchbox").first).to_have_value(
        explorer.word, timeout=30000)


def test_a_search_saved_elsewhere_appears_in_the_list(page, api, explorer) -> None:
    """The list is read from the server, not from this browser.

    **It does not prove sharing, and saying so is the point.** The `page` and
    `api` fixtures carry the same token, so this is one person in two clients —
    what it establishes is that a saved search left the browser, which a
    `localStorage` implementation would fail and a reload would not catch.

    Sharing *between* people is checked where it can be: `test_saved_searches.py`
    saves as the editor and reads back as the viewer. Claiming it here would be
    the kind of assertion that passes for the wrong reason.
    """
    name = f"Elsewhere {explorer.word}"
    api.call(
        "POST",
        f"/workspaces/{explorer.workspace_id}/object-searches",
        {"name": name, "description": "",
         "definition": {"q": explorer.word, "type_ids": []}},
    )
    open_explorer(page, explorer)
    expect(page.get_by_label("Saved searches")).to_contain_text(name, timeout=30000)
