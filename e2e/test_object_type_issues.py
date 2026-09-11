"""p.29's issue column, on the screen (§313; `ontology-manager` p.29).

    "Object types whose backing datasources are unregistered or have failed to
     reindex into Object Storage v1 (Phonograph) will have red error messages
     in the issue column of the object type page." (p.29)

The counting is in `apps/api/tests/test_object_type_issues.py` and the wording
in `apps/web/src/lib/object-type-issues.test.ts`. What needs a browser is the
seam and the one thing neither can assert: that the failure's **own words**
reach the reader, which is the difference between a column that says something
is wrong and one that says what to do.

**Broken through the database**, like §300's check in the `error` state: there
is no route that makes a sync fail on demand, and a test that could only drive
the happy path would be a test of the path p.29 is not about.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from api import Module
from conftest import ADMIN_DSN, WEB_BASE, eventually
from ontology_page import find_type_row


@pytest.fixture(scope="module")
def ontology(api):
    """A type with a source, so there is something to break.

    `object_type` uploads a dataset and maps it, which is exactly the state
    p.29 is about — a type whose backing datasource can stop working.
    """
    mod = Module(api, "Type issues")
    mod.object_type(columns=["id", "town"], rows=[{"id": "1", "town": "Ely"}],
                    key="id", title="town")
    return mod


def break_the_source(object_type_id: str, message: str) -> None:
    """Mark this type's sources as having failed.

    Through the admin connection, because the point is a state no API produces
    on request.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        c.execute(
            "UPDATE object_type_sources SET sync_status = 'error', last_error = %s,"
            " last_synced_at = now() WHERE object_type_id = %s",
            (message, object_type_id),
        )


def heal_the_source(object_type_id: str) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        c.execute(
            "UPDATE object_type_sources SET sync_status = 'ok', last_error = NULL"
            " WHERE object_type_id = %s",
            (object_type_id,),
        )


def open_types(page, module, api_name: str) -> None:
    """Open the ontology page and put this type's row on it.

    **Searched for, not scrolled to** (§256): the table is a page of the
    ontology and this suite's workspace holds over a thousand types, so a row
    is only on screen if it was asked for. Without this the assertions below
    were about whichever thousand rows the first page happened to hold.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    find_type_row(page, api_name)


def test_a_working_type_has_no_issue_on_its_row(page, ontology) -> None:
    """The column is silent when there is nothing to say.

    A column that always says something is one people stop reading, and this
    is the assertion that keeps the interesting cases meaning anything.
    """
    heal_the_source(ontology.object_type_id)
    open_types(page, ontology, f"seed_{ontology.tag}")
    expect(page.get_by_test_id(f"type-issue-seed_{ontology.tag}")).to_have_count(0)


def test_a_failing_source_is_marked_and_says_why(page, ontology) -> None:
    """**p.29's red error message, carrying the failure's own words.**

    The cell counts and the hover explains: "1 source failing" says there is a
    problem, and the sync's message is the only part that says what to fix.
    """
    break_the_source(ontology.object_type_id, "the dataset no longer has column 'town'")
    open_types(page, ontology, f"seed_{ontology.tag}")

    cell = page.get_by_test_id(f"type-issue-seed_{ontology.tag}")
    expect(cell).to_be_visible(timeout=30000)
    expect(cell).to_have_text("1 source failing")
    # p.29's word is "error", and this is what makes it red rather than grey.
    expect(cell).to_have_class("chip brass")
    eventually(lambda: cell.get_attribute("title"),
               lambda t: t is not None and "column 'town'" in t,
               what="the failure's own words on the hover")
    heal_the_source(ontology.object_type_id)


def test_the_mark_clears_when_the_source_recovers(page, ontology) -> None:
    """A red mark that never clears is one people learn to ignore, which is
    worse than not having it — the same argument §300 made about a branch's
    checks."""
    break_the_source(ontology.object_type_id, "temporarily broken")
    open_types(page, ontology, f"seed_{ontology.tag}")
    expect(page.get_by_test_id(f"type-issue-seed_{ontology.tag}")).to_be_visible(
        timeout=30000)

    heal_the_source(ontology.object_type_id)
    open_types(page, ontology, f"seed_{ontology.tag}")
    expect(page.get_by_test_id(f"type-issue-seed_{ontology.tag}")).to_have_count(0)


def test_a_type_nobody_has_sourced_says_so_without_being_an_error(page, api) -> None:
    """**p.29's other condition, and the decision on this row.**

    A type nobody has pointed at data is the ordinary state of one somebody is
    still building. Marking it red would make the column red on every new type
    and teach people to ignore it, so it says "No source" in the same voice the
    rest of the row uses — and the hover says what to do about it.
    """
    mod = Module(api, "Unsourced type")
    tag = uuid.uuid4().hex[:8]
    api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {"api_name": f"bare_{tag}", "display_name": f"Bare {tag}",
         "properties": [{"api_name": "code", "display_name": "Code",
                         "data_type": "string", "required": True}]},
    )
    open_types(page, mod, f"bare_{tag}")
    cell = page.get_by_test_id(f"type-issue-bare_{tag}")
    expect(cell).to_be_visible(timeout=30000)
    expect(cell).to_have_text("No source")
    expect(cell).not_to_have_class("chip brass")
    eventually(lambda: cell.get_attribute("title"),
               lambda t: t is not None and "Add a source" in t,
               what="the hover to say what to do")


# --- p.29's third home-page filter (§315; the test rewritten in §318) ---------


def test_the_issue_filter_narrows_to_types_that_need_attention(page, api) -> None:
    """p.29: "filtering object types … based on their visibility, development
    status, and **indexing issues**".

    **Both types are named so one search finds both**, and that is the whole
    shape of this test rather than a convenience. Three traps had to be met to
    get here, and the third is the one that matters.

    1. This page has **four tables** — object types, link types, action types
       and dataset mappings — and `tbody tr` matches rows in all of them. The
       mappings table carries the seeded dataset's name, which is the tagged
       string this test looks for, so the first version read a different table
       and reported the filter as broken while it was working.

    2. The listing is a **page** (§256) into a workspace every run adds to, so
       "the filter returned two rows" is a claim about how many other types
       happen to match. The search box is what makes an assertion about one
       row.

    3. **And then every negative assertion was vacuous** (§318, found by a
       surviving mutant). Filling the search box starts a debounced fetch; the
       row count was read straight afterwards, so "the healthy type is not in
       the list" was true about a list that had not arrived yet. `eventually`'s
       own docstring says it in so many words — *nothing is absent more
       convincingly than something that has not rendered* — and three mutants
       that disconnected the filter entirely sailed through, because a filter
       that does nothing and a fetch that has not landed look identical from a
       count of zero.

    So the two types share a prefix, one search finds both, and **the row that
    must be present is the proof that the fetch landed**. The absence next to
    it is then about the product. Asserted as a pair on every value, because a
    pair cannot be satisfied by a list that is not there.
    """
    mod = Module(api, "Issue filter")
    mod.object_type(columns=["id", "town"], rows=[{"id": "1", "town": "Ely"}],
                    key="id", title="town")
    healthy = f"seed_{mod.tag}"
    # **Named to share the seeded type's prefix**, so one search returns both
    # and neither assertion below can be satisfied by an empty table.
    bare = f"seed_{mod.tag}_bare"
    api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {"api_name": bare, "display_name": f"Bare {mod.tag}",
         "properties": [{"api_name": "code", "display_name": "Code",
                         "data_type": "string", "required": True}]},
    )

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    chooser = page.get_by_test_id("issue-filter")
    expect(chooser).to_be_visible(timeout=30000)
    page.get_by_test_id("type-search").fill(f"seed_{mod.tag}")

    def rows(issue: str) -> tuple[int, int]:
        """(the healthy type's rows, the bare one's) under this filter."""
        chooser.select_option(issue)
        return (page.get_by_test_id(f"select-{healthy}").count(),
                page.get_by_test_id(f"select-{bare}").count())

    # Unsourced: the bare one is in and the healthy one is out — **as one
    # observation**, so the zero is read off a table that is demonstrably
    # showing results.
    eventually(lambda: rows("unsourced"), lambda r: r == (0, 1),
               what="only the unsourced type, under `unsourced`")

    # Failing is a broken source, not an absent one, which is why p.29's two
    # conditions are two values here rather than one.
    break_the_source(mod.object_type_id, "the dataset went away")
    eventually(lambda: rows("failing"), lambda r: r == (1, 0),
               what="only the failing type, under `failing`")

    # `any` is both, which is the question somebody opening this is asking.
    eventually(lambda: rows("any"), lambda r: r == (1, 1),
               what="both types, under `any`")

    # And the unfiltered list still holds both, so the three answers above are
    # narrowings of something rather than three different searches.
    eventually(lambda: rows(""), lambda r: r == (1, 1),
               what="both types, unfiltered")
    heal_the_source(mod.object_type_id)
