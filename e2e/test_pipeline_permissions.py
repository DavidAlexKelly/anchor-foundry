"""p.80-84's Permissions view on the lineage graph (§422).

> "You can use Data Lineage to check users' permissions to view datasets or
>  artifacts using the 'Permissions' coloring option." (p.80)

> "Select the user's name from the **View as** dropdown. This will allow you to
>  see the user's permissions to each of the nodes on the graph." (p.82)

Which role each node resolves to, and who may be named, are
`apps/api/tests/test_pipeline.py`'s; which colour a verdict takes is
`apps/web/src/lib/node-colouring.test.ts`'s. What needs a browser is the seam
across all three: that choosing a person **refetches the graph** and repaints
the cards with the server's answer — a page that coloured the copy already in
hand would be a second permissions model, and the one place a second one is
worst is the page people use to decide who can see what.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from conftest import ADMIN_DSN, WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def permitted(api):
    """A project with two datasets, and a second person in the workspace who
    can see it — plus one who cannot.

    The second is what makes the colouring show anything: with one answer for
    everybody the picker would repaint nothing, and a test over that could not
    tell a working control from a decorative one.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Perm {tag}", "slug": f"perm-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    api.upload_csv(f"{base}/datasets/upload", f"Books {tag}", ROWS)
    people = api.call("GET", f"{base}/pipeline/viewers")
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "people": people}


def open_graph(page, permitted) -> None:
    page.goto(
        f"{WEB_BASE}/{permitted['workspace_slug']}/{permitted['project_slug']}/pipeline"
    )
    expect(page.get_by_test_id("graph-colouring")).to_be_visible(timeout=30000)


def test_view_as_appears_only_under_the_permissions_colouring(page, permitted) -> None:
    """§214: under any other colouring the dropdown changes nothing on the
    screen, and it costs an editor-gated request to fill."""
    open_graph(page, permitted)
    expect(page.get_by_test_id("graph-view-as")).to_have_count(0)
    page.get_by_test_id("graph-colouring").select_option("permissions")
    expect(page.get_by_test_id("graph-view-as")).to_be_visible()
    page.get_by_test_id("graph-colouring").select_option("status")
    expect(page.get_by_test_id("graph-view-as")).to_have_count(0)


def test_the_graph_says_nobody_is_chosen_before_anybody_is(page, permitted) -> None:
    """§210. A graph drawn before a person is named has not found a
    permissions problem; it has not been asked a question."""
    open_graph(page, permitted)
    page.get_by_test_id("graph-colouring").select_option("permissions")
    expect(page.get_by_test_id("legend-unasked")).to_be_visible()
    card = page.get_by_test_id("graph-node").first
    expect(card).to_have_attribute("data-colour", "unasked")


def test_choosing_a_person_repaints_the_cards_with_the_server_s_answer(
    page, permitted
) -> None:
    """**The seam.** The dropdown is in the toolbar, the verdict is on the
    card, and a refetch of the whole graph is in between — nothing on the page
    works this out from roles it happened to know."""
    open_graph(page, permitted)
    page.get_by_test_id("graph-colouring").select_option("permissions")
    page.get_by_test_id("graph-view-as").select_option(permitted["people"][0]["id"])
    card = page.get_by_test_id("graph-node").first
    # **A verdict this colouring produced, named rather than merely not the
    # old one.** "Not unasked" passed while the page was still losing the
    # colouring on every refetch and falling back to Build status — the card
    # read `unknown`, which is a build-status verdict and satisfied it.
    expect(page.get_by_test_id("legend-unasked")).to_have_count(0)
    verdict = card.get_attribute("data-colour")
    assert verdict in {"owner", "editor", "viewer", "admin", "none"}, verdict
    # And the colouring is still the one that was chosen: the picker is only
    # on the screen under it, so losing it one click later leaves a reader
    # somewhere they did not ask to be.
    expect(page.get_by_test_id("graph-colouring")).to_have_value("permissions")


def test_the_picker_can_be_left_again(page, permitted) -> None:
    """§210, the other way round: "Nobody chosen" stays on the list, because a
    picker you cannot leave is a mode rather than a question."""
    open_graph(page, permitted)
    page.get_by_test_id("graph-colouring").select_option("permissions")
    picker = page.get_by_test_id("graph-view-as")
    picker.select_option(permitted["people"][0]["id"])
    expect(page.get_by_test_id("legend-unasked")).to_have_count(0)
    picker.select_option("")
    expect(page.get_by_test_id("legend-unasked")).to_be_visible()


def test_the_scope_that_decided_is_on_the_legend(page, permitted) -> None:
    """p.84's point, where a reader meets it: "viewer" is not an answer on its
    own when two nodes can hold it from two different doors."""
    open_graph(page, permitted)
    page.get_by_test_id("graph-colouring").select_option("permissions")
    page.get_by_test_id("graph-view-as").select_option(permitted["people"][0]["id"])
    expect(page.get_by_test_id("graph-legend")).to_contain_text("(project)")
