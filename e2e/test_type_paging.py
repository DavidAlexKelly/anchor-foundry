"""The bounded object type listing and the pickers over it (§256).

`ontology.list_types` had no `LIMIT`, and eight call sites — seven of them
dropdowns — read it. §209 measured a development workspace of ~1,400 object
types taking seven seconds to open a dialog; this suite's own workspace holds
791, and the unbounded read of it is 253ms and 379KB against 17ms and 24KB for
a page.

**Bounding it alone would have made things worse**, which is why this file
exists rather than a one-line `LIMIT`: fifty of six hundred types looks exactly
like a workspace with fifty, so every truncation has to say so and every picker
has to be able to reach past it. Those are browser claims. The server's half —
that the page and the count agree, that the search is not a pattern, that `ids`
narrows rather than widens — is in `apps/api/tests/test_object_type_groups.py`,
where a wrong answer is a value rather than a screen.

This file runs against the shared development workspace **on purpose**. It is
the only place in this build with an ontology big enough for a page to be a
page, which is the same reason §248 found its defect there.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE
from ontology_page import find_type_row, pick_type


@pytest.fixture(scope="module")
def module(api):
    types = Module(api, "Type paging")
    types.object_type(
        columns=["id", "name"],
        rows=[{"id": "A1", "name": "Alpha"}],
        key="id", title="name",
    )
    return types


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_test_id("type-search")).to_be_visible(timeout=30000)


def test_the_table_says_which_slice_of_the_ontology_it_is_showing(page, module):
    """**A table that stops at fifty without saying so is a workspace that
    looks smaller than it is.** The paging row is the whole of what makes the
    bound honest rather than a silent truncation."""
    open_objects(page, module)
    paging = page.get_by_test_id("type-paging")
    expect(paging).to_be_visible(timeout=30000)
    # "1–50 of 791", whatever the numbers happen to be: a range and a total.
    text = paging.inner_text()
    assert "of" in text, text
    assert "–" in text, text
    expect(page.get_by_test_id("types-previous")).to_be_disabled()
    expect(page.get_by_test_id("types-next")).to_be_enabled()


def test_next_moves_through_the_ontology_rather_than_redrawing_it(page, module):
    """Two-sided: the range moves *and* the rows change. A Next button that
    refetched the same page would satisfy either check alone."""
    open_objects(page, module)
    expect(page.get_by_test_id("type-paging")).to_be_visible(timeout=30000)
    rows = page.locator("table").filter(
        has=page.get_by_role("columnheader", name="Object type")
    ).first.locator("tbody tr")
    first_page = rows.first.inner_text()
    first_range = page.get_by_test_id("type-paging").inner_text()

    page.get_by_test_id("types-next").click()
    expect(page.get_by_test_id("types-previous")).to_be_enabled(timeout=15000)
    expect(page.get_by_test_id("type-paging")).not_to_have_text(first_range)
    assert rows.first.inner_text() != first_page


def test_the_search_reaches_a_type_no_page_would_have_shown(page, module):
    """The reason the endpoint has a search at all.

    This fixture's type is created moments before the test and named after a
    random tag; on 791 alphabetically ordered types there is no reason for it
    to be on any particular page. Finding it is the claim.
    """
    open_objects(page, module)
    row = find_type_row(page, f"seed_{module.tag}")
    expect(row).to_contain_text(f"seed_{module.tag}")
    # And the paging row now describes the *search*, not the ontology.
    expect(page.get_by_test_id("type-paging")).to_have_count(0)


def test_a_fruitless_search_is_not_an_empty_ontology(page, module):
    """**The empty state has to tell them apart.** Falling through to "The
    ontology starts here" would tell somebody with 791 object types that they
    have none, and offer them a Define button as the way out of a search."""
    open_objects(page, module)
    page.get_by_test_id("type-search").fill(f"nothing-matches-{uuid.uuid4().hex}")
    empty = page.get_by_test_id("empty-group-filter")
    expect(empty).to_be_visible(timeout=15000)
    expect(empty).to_contain_text("Nothing matches these filters")
    page.get_by_test_id("clear-group-filter").click()
    expect(page.get_by_test_id("type-paging")).to_be_visible(timeout=15000)


def test_a_picker_searches_the_ontology_rather_than_its_page(page, module):
    """p.66's dialogs are useless if they can only offer fifty types.

    The link type dialog's From picker is the case: this fixture's own type is
    not on the first page of 791, and the picker has to reach it.
    """
    open_objects(page, module)
    page.get_by_role("button", name="New link type").click()
    pick_type(page, "link-from-type", {
        "id": module.object_type_id, "api_name": f"seed_{module.tag}",
    })
    expect(page.get_by_test_id("link-from-type")).to_have_value(
        module.object_type_id
    )


def test_a_picker_says_how_much_it_is_not_showing(page, module):
    """A dropdown that stops at fifty and says nothing is the lying picker this
    unit exists to avoid. The note is what makes the bound visible."""
    open_objects(page, module)
    page.get_by_role("button", name="New link type").click()
    note = page.get_by_test_id("link-from-type-note")
    expect(note).to_be_visible(timeout=20000)
    assert "Showing" in note.inner_text()
    assert "search" in note.inner_text()


def test_a_chosen_type_stays_on_the_list_when_a_search_would_drop_it(page, module):
    """**The invariant that keeps a picker from changing its own value.**

    A `<select>` whose value is not among its options renders blank, and the
    next save writes the blank — so a type chosen and then searched away would
    be silently un-chosen by a search box somebody typed into and cleared.
    """
    open_objects(page, module)
    page.get_by_role("button", name="New link type").click()
    pick_type(page, "link-from-type", {
        "id": module.object_type_id, "api_name": f"seed_{module.tag}",
    })

    # A search that matches nothing at all: the chosen type is still the value,
    # and still an option, so the control still reads as what was chosen.
    page.get_by_test_id("link-from-type-search").fill(
        f"nothing-{uuid.uuid4().hex[:8]}"
    )
    expect(page.get_by_test_id("link-from-type")).to_have_value(
        module.object_type_id, timeout=15000
    )
    expect(
        page.get_by_test_id("link-from-type").locator("option")
    ).to_have_count(2)  # the placeholder, and the type that was chosen
