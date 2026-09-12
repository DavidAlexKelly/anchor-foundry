"""The Ontology cleanup queue, on the screen (§325; `ontology-manager` p.68-74).

    "The Ontology cleanup tool is a safe way to delete object types… The tool
     aims to help Ontology editors determine the safety of deleting an object
     type and provides a deprecation option which informs object type users of
     its future removal." (p.68)

    "**Snooze**: Hide object types from your cleanup queue for a configurable
     amount of time." (p.71)

    "Once you act on an object type in your queue, it disappears from the
     queue." (p.71)

The flags are computed and tested in `apps/api/tests/test_ontology_cleanup.py`
and the wording in `apps/web/src/lib/ontology-cleanup.test.ts`. What needs a
browser is the loop p.71 describes and neither of those can reach: **a row you
act on leaves the queue, and stays gone when you come back**.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture
def candidate(api):
    """One object type that is obviously a cleanup candidate.

    **Its own, per test.** Every test here acts on the row it makes — snoozing
    it, deleting it — and a shared type would mean each test depended on which
    of the others had already run.
    """
    mod = Module(api, "Cleanup")
    tag = uuid.uuid4().hex[:8]
    declared = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {"api_name": f"stale_{tag}",
         # p.74's marker, so this type is flagged for a reason a test can name
         # rather than for whatever the fixture happened to produce.
         "display_name": f"[test] Leftover {tag}",
         "description": "",
         "properties": [{"api_name": "name", "display_name": "Name",
                         "data_type": "string"}]},
    )
    mod.object_type_id = declared["id"]
    mod.api_name = declared["api_name"]
    mod.display_name = declared["display_name"]
    return mod


def open_queue(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/cleanup")
    expect(page.get_by_test_id("cleanup-queue")).to_be_visible(timeout=30000)


def row(page, module):
    return page.get_by_test_id(f"cleanup-{module.api_name}")


def still_declared(api, module) -> bool:
    """Whether the ontology still has this object type.

    **Asked by id, because the listing is a page** (§256). Reading
    `/object-types` and looking for the row was the shape both delete tests
    started with, and it is worse than useless: this workspace has thousands of
    types, the default page is a fraction of them ordered by display name, and
    a type created moments ago is almost never on it. So "not in the list" was
    true before the delete as well as after — the check could not fail, and the
    one asserting the type *survived* a cancel failed for the same reason.

    `ids` exists for exactly this, and the route says so: "A screen that has
    already chosen some has to be able to read them back now that the listing
    is a page."
    """
    page_of = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types"
        f"?ids={module.object_type_id}",
    )
    items = page_of["items"] if isinstance(page_of, dict) else page_of
    return module.object_type_id in [t["id"] for t in items]


def test_a_leftover_type_is_in_the_queue_with_a_reason(page, candidate) -> None:
    """p.69's list, and p.70's headline.

    The row says *why* rather than only that it is a candidate: a queue whose
    rows all read "needs attention" is a queue somebody has to open every row
    of to use.
    """
    open_queue(page, candidate)
    mine = row(page, candidate)
    expect(mine).to_be_visible(timeout=30000)
    # p.74's regex flag at its own default, and it is not the *worst* flag —
    # so this also checks the row lists more than its headline.
    expect(mine).to_contain_text("more")
    expect(mine.get_by_test_id("cleanup-headline")).not_to_have_text("No flags")


def test_the_queue_can_be_narrowed_to_one_flag(page, api, candidate) -> None:
    """p.69: "The list can be filtered to specific flags".

    **Two types, and one of them must lack the flag.** The first version of
    this test filtered to a flag nothing in the workspace had, and the
    dropdown — which offers only flags the answer actually contains, so it
    never lists a filter that empties the table (§214) — had no such option.
    That is the component being right, so the test builds the pair it needs:
    one type marked `[test]` and one not, both otherwise candidates.
    """
    plain_tag = uuid.uuid4().hex[:8]
    plain = api.call(
        "POST", f"/workspaces/{candidate.workspace_id}/object-types",
        {"api_name": f"plain_{plain_tag}",
         "display_name": f"Ordinary {plain_tag}",
         "description": "",
         "properties": [{"api_name": "name", "display_name": "Name",
                         "data_type": "string"}]},
    )
    plain_row = page.get_by_test_id(f"cleanup-{plain['api_name']}")

    open_queue(page, candidate)
    expect(row(page, candidate)).to_be_visible(timeout=30000)
    expect(plain_row).to_be_visible(timeout=30000)

    page.get_by_test_id("cleanup-flag").select_option(label="Marked temporary")
    # The marked one stays — the positive half, and the wait that makes the
    # absence below a fact about the filter rather than about a page mid-fetch
    # (§318).
    expect(row(page, candidate)).to_be_visible(timeout=30000)
    eventually(lambda: plain_row.count(), lambda n: n == 0,
               what="the unmarked type to leave a filter it does not match")


def test_snoozing_takes_the_row_out_of_the_queue(page, candidate) -> None:
    """**p.71's loop, which is the whole reason this file needs a browser**:
    "Once you act on an object type in your queue, it disappears from the
    queue."

    And it stays gone on a reload — a row hidden only in React state would look
    identical until somebody came back.
    """
    open_queue(page, candidate)
    expect(row(page, candidate)).to_be_visible(timeout=30000)

    page.get_by_test_id(f"cleanup-snooze-{candidate.api_name}").click()
    eventually(lambda: row(page, candidate).count(), lambda n: n == 0,
               what="the snoozed row to leave the queue")

    page.reload()
    expect(page.get_by_test_id("cleanup-queue")).to_be_visible(timeout=30000)
    expect(row(page, candidate)).to_have_count(0)


def test_a_snoozed_row_can_still_be_found_and_brought_back(page, candidate) -> None:
    """p.71: "Use the table filters to view all the actions you have already
    selected." Hidden from the queue is not gone."""
    open_queue(page, candidate)
    page.get_by_test_id(f"cleanup-snooze-{candidate.api_name}").click()
    eventually(lambda: row(page, candidate).count(), lambda n: n == 0,
               what="the snoozed row to leave the queue")

    page.get_by_test_id("cleanup-show-snoozed").check()
    mine = row(page, candidate)
    expect(mine).to_be_visible(timeout=30000)
    expect(mine.get_by_test_id("cleanup-snoozed")).to_contain_text("Back in")

    mine.get_by_role("button", name="Un-snooze").click()
    page.get_by_test_id("cleanup-show-snoozed").uncheck()
    expect(row(page, candidate)).to_be_visible(timeout=30000)


def test_a_delete_asks_first_and_says_what_goes_with_it(page, api, candidate) -> None:
    """p.71's third action, and the only one that cannot be undone.

    "Delete object types from the Ontology **and remove associated data from
    object storage**" — so the confirmation names the type and says what goes
    with it, rather than asking "are you sure?" over a button press.
    """
    open_queue(page, candidate)
    page.get_by_test_id(f"cleanup-delete-{candidate.api_name}").click()

    confirm = page.get_by_test_id("cleanup-confirm")
    expect(confirm).to_be_visible(timeout=30000)
    # **The type's own name**, which is what makes the warning about *this*
    # row. An earlier version sliced the api_name into "Leftove", which is a
    # substring of nothing in particular and would have passed against a dialog
    # naming the wrong type.
    expect(confirm).to_contain_text(candidate.display_name)
    expect(confirm).to_contain_text("storage")
    expect(confirm).to_contain_text("cannot be undone")

    # And backing out leaves the type alone — a confirmation whose Cancel
    # deleted anyway is worse than no confirmation.
    page.get_by_test_id("cleanup-confirm-cancel").click()
    expect(page.get_by_test_id("cleanup-confirm")).to_have_count(0)

    # **Asked of the ontology, not of the table.** The first version asserted
    # the row was still visible right after the click — which is true for a
    # moment even when Cancel deletes, because the request has not come back
    # yet. A mutant wiring Cancel to the delete survived on exactly that race.
    # The server cannot be early.
    assert still_declared(api, candidate), (
        "Cancel must leave the object type where it was"
    )
    expect(row(page, candidate)).to_be_visible()


def test_confirming_the_delete_removes_the_type(page, api, candidate) -> None:
    """p.71's delete, end to end — and checked against the *ontology* rather
    than against the table, which is the thing that just redrew itself."""
    open_queue(page, candidate)
    page.get_by_test_id(f"cleanup-delete-{candidate.api_name}").click()
    page.get_by_test_id("cleanup-confirm-delete").click()
    eventually(lambda: row(page, candidate).count(), lambda n: n == 0,
               what="the deleted row to leave the queue")

    assert not still_declared(api, candidate), (
        "the type is gone from the ontology, not only from the table"
    )


def test_a_viewer_is_told_why_rather_than_shown_an_error(page, candidate) -> None:
    """The server refuses a viewer outright, so a viewer who followed a link
    would otherwise meet a red error where a sentence would do (§214).

    Checked through the page's own read of the role rather than by signing in
    as somebody else: this suite's `page` and `api` share one token, which is
    why the permission itself is asserted in the API suite.
    """
    open_queue(page, candidate)
    # The editor sees the queue, which is the positive half — so the absence of
    # the read-only note below is about the role rather than about the page
    # (§318).
    expect(page.get_by_test_id("cleanup-queue")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("cleanup-read-only")).to_have_count(0)
