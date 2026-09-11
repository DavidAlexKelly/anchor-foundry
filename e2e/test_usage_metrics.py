"""p.33's usage summary, on the screen (§320; `ontology-manager` p.32-34).

    "A usage graph on the Overview tab: High-level summary of usage over the
     last 30 days, enabling Ontology users to quickly understand the
     implications of making a breaking change to this resource." (p.33)

The counting rules and the four numbers are in
`apps/api/tests/test_object_type_usage.py`, and the wording in
`apps/web/src/lib/usage-metrics.test.ts`. What needs a browser is the sentence
p.32 spends a clause on and no API test can reach:

    "any object type or link type usage happening in Ontology Manager is not
     included."

That is a claim about **which screen you are looking at**, not about a request.
The Ontology Manager's type page and the Object Explorer list a type's objects
through the same route, so an API test can only check that the server honours
a label it is handed. Whether the type page actually hands it over is a fact
about the page — and getting it wrong would make the person deciding on a
rename the type's most active user, silently, for having looked.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture(scope="module")
def counted(api):
    """A type with rows, in its own module so the counts are this test's."""
    mod = Module(api, "Usage metrics")
    mod.object_type(
        columns=["id", "town"],
        rows=[{"id": "1", "town": "Ely"}, {"id": "2", "town": "Ripon"}],
        key="id", title="town",
    )
    return mod


def type_page(page, module) -> None:
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}"
        f"/objects/{module.object_type_id}"
    )
    expect(page.get_by_test_id("usage-panel")).to_be_visible(timeout=30000)


def reads(api, module) -> int:
    return api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}/usage",
    )["reads"]


def test_a_type_nobody_has_used_says_so(page, api, counted) -> None:
    """p.33's "No usage for the last 30 days", as a sentence.

    **A blank panel and a failed one look identical**, which is why this is
    drawn rather than omitted — and p.33 attaches a warning to exactly this
    state, so people do see it and wonder.
    """
    type_page(page, counted)
    expect(page.get_by_test_id("usage-empty")).to_be_visible()
    expect(page.get_by_test_id("usage-empty")).to_contain_text("No usage")
    expect(page.get_by_test_id("usage-figures")).to_have_count(0)


def test_opening_the_type_page_does_not_count_as_usage(page, api, counted) -> None:
    """**p.32's exclusion, and the only place it can be checked.**

    The Ontology Manager's type page lists this type's objects through the same
    route the Explorer uses. An API test can check that the server honours the
    label it is given; only a browser can check that this page gives it.

    The read really happens — the rows are on screen — and the number does not
    move.
    """
    before = reads(api, counted)
    type_page(page, counted)
    # The rows are the proof the read happened, and the positive wait that
    # makes the assertion below about the product rather than about timing
    # (§318).
    expect(page.get_by_test_id("instances-table")).to_contain_text(
        "Ely", timeout=30000
    )
    assert reads(api, counted) == before


def test_the_explorer_s_reads_are_counted_and_shown(page, api, counted) -> None:
    """The other half, and the one that makes the exclusion mean something.

    Without this, "the type page does not count" is satisfied by a platform
    that counts nothing at all — which is the shape §302 found in five
    specifications and §315 found in a browser test three units later.
    """
    before = reads(api, counted)
    page.goto(
        f"{WEB_BASE}/{counted.workspace_slug}/explore?type={counted.object_type_id}"
    )
    expect(page.get_by_text("Ely").first).to_be_visible(timeout=30000)
    eventually(lambda: reads(api, counted), lambda n: n > before,
               what="the Explorer's read to be counted")

    type_page(page, counted)
    expect(page.get_by_test_id("usage-figures")).to_be_visible(timeout=30000)
    # p.33's "in which Foundry applications", with the Explorer named — and
    # the Ontology Manager absent from the breakdown, because its reads were
    # never recorded to group.
    row = page.get_by_test_id("usage-app-explorer")
    expect(row).to_be_visible()
    expect(row).to_contain_text("Object Explorer")
    expect(page.get_by_test_id("usage-app-ontology_manager")).to_have_count(0)


def test_the_headline_leads_with_people(page, api, counted) -> None:
    """p.33 frames the whole feature as understanding "the implications of
    making a breaking change", and the number that decides that is how many
    people would notice — not how many times."""
    page.goto(
        f"{WEB_BASE}/{counted.workspace_slug}/explore?type={counted.object_type_id}"
    )
    expect(page.get_by_text("Ely").first).to_be_visible(timeout=30000)
    eventually(lambda: reads(api, counted), lambda n: n > 0, what="a recorded read")

    type_page(page, counted)
    headline = page.get_by_test_id("usage-headline")
    expect(headline).to_contain_text("last 30 days")
    expect(headline).to_contain_text("person")
    expect(page.get_by_test_id("usage-active-users")).to_have_text("1")


def test_a_failure_says_so_rather_than_reading_as_no_usage(page, api, counted) -> None:
    """**The two states a surviving mutant showed were interchangeable.**

    Replacing the error branch with `return null` — draw nothing when the
    request fails — passed every other test in this file. And "nothing" is
    exactly what p.33's "No usage for the last 30 days" looks like from across
    the room, so a reader would take a broken panel for a definite answer and
    rename the property.

    The failure is manufactured by refusing the request, which is the only way
    to reach a branch the server has no way to produce on demand.
    """
    page.route("**/usage", lambda route: route.abort())
    try:
        page.goto(
            f"{WEB_BASE}/{counted.workspace_slug}/{counted.project_slug}"
            f"/objects/{counted.object_type_id}"
        )
        problem = page.get_by_text("Couldn't load usage for this type")
        expect(problem).to_be_visible(timeout=30000)
        # And it is **not** mistakable for the empty state: that sentence is
        # the one a reader would act on.
        expect(page.get_by_test_id("usage-empty")).to_have_count(0)
        expect(page.get_by_test_id("usage-figures")).to_have_count(0)
    finally:
        page.unroute("**/usage")
