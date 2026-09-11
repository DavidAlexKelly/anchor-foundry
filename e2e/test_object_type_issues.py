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
