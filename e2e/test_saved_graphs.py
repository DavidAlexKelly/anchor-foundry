"""Save and share a lineage graph (parity `datasets-lineage.md` §2.1; Foundry
`data-lineage` p.12).

> "You can save and share your lineage graph with other Foundry users in the
>  following ways: **Save / Open**: Save your Data Lineage graph and re-open it
>  by clicking on Open graph. **Get quick share link**: Generates a shareable
>  link that provides read-only access to your graph." (p.12)

What a view may hold, and what happens when it cannot open, is
`apps/api/tests/test_saved_graphs.py`'s; the URL round-trip is
`apps/web/src/lib/graph-link.test.ts`'s. What needs a browser is the claim
neither can make: that the graph **arrives at the view** — saved, reopened, or
pasted into an address bar.
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def graphs(api):
    """Three datasets, so a selection is a choice rather than everything."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Saved {tag}", "slug": f"saved-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    for name in ("Alpha", "Beta", "Gamma"):
        api.upload_csv(f"{base}/datasets/upload", f"{name} {tag}", ROWS)
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"]}


def open_pipeline(page, graphs, query: str = "") -> None:
    page.goto(
        f"{WEB_BASE}/{graphs['workspace_slug']}/{graphs['project_slug']}/pipeline{query}"
    )
    expect(page.get_by_test_id("graph-save")).to_be_visible(timeout=30000)


def card(page, graphs, name: str):
    return page.locator(f'button[title="{name} {graphs["tag"]}"]')


def test_the_view_goes_into_the_address_bar(page, graphs) -> None:
    """**What makes the share link honest.** `CopyLinkButton` copies the
    address bar rather than rebuilding a link from state, so the URL has to be
    true — and until §360 this page put nothing in it at all, so a reload lost
    everything."""
    open_pipeline(page, graphs)
    card(page, graphs, "Alpha").click()
    expect(page).to_have_url(re.compile(r"[?&]sel="))

    page.get_by_test_id("search-query").fill("beta")
    expect(page).to_have_url(re.compile(r"[?&]q=beta"))


def test_a_pasted_link_opens_at_that_view(page, graphs) -> None:
    """p.12's share link, from the far end: the parameters are the view, so
    somebody who was sent them sees what the sender saw."""
    open_pipeline(page, graphs, "?q=alpha")
    expect(page.get_by_test_id("search-query")).to_have_value("alpha")
    expect(page.locator("[data-match]")).to_have_count(1)
    expect(page.locator("[data-match]").first).to_contain_text(f"Alpha {graphs['tag']}")


def test_a_reload_keeps_the_view(page, graphs) -> None:
    """The side effect worth having on its own: this page used to lose
    everything on refresh, because none of it was anywhere."""
    open_pipeline(page, graphs)
    page.get_by_test_id("search-query").fill("gamma")
    expect(page.locator("[data-match]")).to_have_count(1)
    # Wait for the address bar, not just the graph: `router.replace` does not
    # land synchronously, and reloading before it does would reload the URL
    # from *before* the search — which is a race in the test, not a page that
    # forgets.
    expect(page).to_have_url(re.compile(r"[?&]q=gamma"))

    page.reload()
    expect(page.get_by_test_id("search-query")).to_have_value("gamma")
    expect(page.locator("[data-match]")).to_have_count(1)


def test_saving_a_graph_and_opening_it_again(page, graphs) -> None:
    """p.12's Save / Open, end to end and through the browser."""
    open_pipeline(page, graphs)
    page.get_by_test_id("search-query").fill("beta")
    card(page, graphs, "Beta").click()

    name = f"Beta only {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("graph-save").click()
    page.get_by_test_id("graph-name").fill(name)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_test_id("graph-name")).to_have_count(0)

    # Somewhere else entirely, then back through Open graph.
    open_pipeline(page, graphs)
    expect(page.get_by_test_id("search-query")).to_have_value("")
    page.get_by_test_id("graph-open").click()
    page.locator(f'[data-testid="saved-graph"][data-name="{name}"]') \
        .get_by_test_id("open-saved-graph").click()

    expect(page.get_by_test_id("search-query")).to_have_value("beta")
    expect(page.locator("[data-selected]")).to_have_count(1)


def test_opening_a_saved_graph_puts_the_whole_view_back(page, graphs) -> None:
    """**Including into the address bar.** Copy link copies the URL, so a graph
    opened out of the list while the address bar still described the *last*
    view would hand the next person something nobody was looking at — the one
    way this page can lie, and the reason the URL is written on open as well as
    on change.

    The kind filter and the column highlight are here because they are the two
    parts of a view nothing else in this file exercises, and a saved graph that
    dropped either would reopen looking deliberate rather than wrong."""
    open_pipeline(page, graphs)
    page.get_by_test_id("search-kind-dataset").click()
    page.get_by_test_id("column-val").click()
    expect(page.get_by_test_id("column-val")).to_have_attribute("aria-pressed", "true")

    name = f"Whole {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("graph-save").click()
    page.get_by_test_id("graph-name").fill(name)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_test_id("graph-name")).to_have_count(0)

    # A graph with nothing chosen, so what comes back came from the save.
    open_pipeline(page, graphs)
    expect(page.get_by_test_id("column-val")).to_have_attribute("aria-pressed", "false")
    page.get_by_test_id("graph-open").click()
    page.locator(f'[data-testid="saved-graph"][data-name="{name}"]') \
        .get_by_test_id("open-saved-graph").click()

    expect(page.get_by_test_id("search-kind-dataset")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("column-val")).to_have_attribute("aria-pressed", "true")
    expect(page).to_have_url(re.compile(r"[?&]kind=dataset"))
    expect(page).to_have_url(re.compile(r"[?&]col=val"))


def test_a_saved_graph_is_shared_with_the_project(page, graphs) -> None:
    """db 0040's decision, seen from the screen: a saved graph is in the list
    for anybody who can read the project, not just whoever saved it."""
    open_pipeline(page, graphs)
    name = f"Shared {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("graph-save").click()
    page.get_by_test_id("graph-name").fill(name)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_test_id("graph-name")).to_have_count(0)

    page.get_by_test_id("graph-open").click()
    expect(page.locator(f'[data-testid="saved-graph"][data-name="{name}"]')).to_have_count(1)


def test_a_name_already_taken_is_refused_where_it_was_typed(page, graphs) -> None:
    """A Save button that appears to do nothing is worse than one that is
    absent (§214)."""
    open_pipeline(page, graphs)
    name = f"Twice {uuid.uuid4().hex[:6]}"
    for attempt in (1, 2):
        page.get_by_test_id("graph-save").click()
        page.get_by_test_id("graph-name").fill(name)
        page.get_by_role("button", name="Save", exact=True).click()
        if attempt == 1:
            expect(page.get_by_test_id("graph-name")).to_have_count(0)
    expect(page.get_by_test_id("graph-save-error")).to_contain_text("already exists")


def test_a_project_with_no_saved_graphs_says_so(page, api) -> None:
    """The empty state, in a project of its own so the tests above cannot make
    it non-empty."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Empty graphs {tag}", "slug": f"empty-graphs-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    api.upload_csv(f"{base}/datasets/upload", f"Only {tag}", ROWS)

    page.goto(f"{WEB_BASE}/{workspace['slug']}/{project['slug']}/pipeline")
    expect(page.get_by_test_id("graph-open")).to_be_visible(timeout=30000)
    page.get_by_test_id("graph-open").click()
    expect(page.get_by_test_id("no-saved-graphs")).to_contain_text("Nothing saved yet")
