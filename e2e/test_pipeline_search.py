"""Finding nodes on the lineage graph (parity `datasets-lineage.md` §2.2;
Foundry `data-lineage` p.8).

> "Use the search helper to find Foundry resources **and add them to the
>  graph**. Use the free-text search or browse the tree to find resources. Add
>  a resource by clicking on it or use the buttons at the bottom of the view to
>  **add all search results**... Use the **Advanced** tab to add filters to
>  your search and sort your results." (p.8)

**Find carries over; add does not.** p.8's helper does two things, and the
adding is only there because Foundry's graph starts empty over an enterprise.
This graph is a project drawn whole — §355 settled that and wrote the reasoning
onto the row — so every result is already on it, which leaves *finding* one by
name and turns "add all search results" into **select all of them**, where
§354's histogram and §355's expansions can take it further.

Which nodes match is `apps/web/src/lib/pipeline-graph.test.ts`'s. What needs a
browser is that typing reaches the graph at all, and that a reader can see
which cards the count is talking about: a match nothing draws is a number.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n"


@pytest.fixture(scope="module")
def findable(api):
    """Two uploads and a model that has been **run**, so four nodes.

    `Orders` names three of the four — the source, the model reading it and
    the dataset the model wrote — and `Invoices` names the fourth, so a query
    has something to exclude and the kind filter has a model *and* a dataset
    to tell apart within the same match.

    The run is load-bearing rather than tidiness: a model that has never run
    has no output dataset at all (`models.output_dataset_id` is NULL until the
    first run, which is what §352's sweep found), so without it there would be
    nothing downstream for the last test to reach.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Find {tag}", "slug": f"find-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    orders = api.upload_csv(f"{base}/datasets/upload", f"Orders raw {tag}", ROWS)
    api.upload_csv(f"{base}/datasets/upload", f"Invoices raw {tag}", ROWS)
    clean = api.call("POST", f"{base}/models", {
        "name": f"Orders clean {tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": orders["id"], "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{clean['id']}/run")
    return {"workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "tag": tag}


def open_pipeline(page, findable) -> None:
    page.goto(f"{WEB_BASE}/{findable['workspace_slug']}/{findable['project_slug']}/pipeline")
    expect(page.get_by_test_id("graph-search")).to_be_visible(timeout=30000)


def matches(page):
    return page.locator("[data-match]")


def test_typing_finds_the_nodes_that_match(page, findable) -> None:
    """p.8's free-text search, as far as the graph.

    Asserted as the *difference*: `Orders` is in two of the three nodes and
    `Invoices` in the other, so a build that matched everything — or nothing —
    fails here.
    """
    open_pipeline(page, findable)
    expect(matches(page)).to_have_count(0)

    page.get_by_test_id("search-query").fill("orders")
    # The source, the model reading it, and the dataset the model wrote.
    expect(matches(page)).to_have_count(3)
    expect(page.get_by_test_id("search-count")).to_have_text("3 of 4")

    page.get_by_test_id("search-query").fill("invoices")
    expect(matches(page)).to_have_count(1)
    expect(matches(page).first).to_contain_text(f"Invoices raw {findable['tag']}")


def test_the_graph_says_nothing_until_it_is_asked(page, findable) -> None:
    """**The state the page opens in.** A search that starts by matching the
    whole graph has said nothing, and would dim nothing while claiming to have
    found three things — so the count is absent too, not zero."""
    open_pipeline(page, findable)
    expect(matches(page)).to_have_count(0)
    expect(page.get_by_test_id("search-count")).to_have_count(0)
    expect(page.get_by_test_id("search-select-all")).to_have_count(0)


def test_a_search_dims_what_it_did_not_find(page, findable) -> None:
    """Dimming is what makes a match readable on a graph with forty cards —
    the same contrast p.55's column highlight uses, and deliberately the same
    one, because a second dimming language would have a reader guessing which
    faded card faded for which reason."""
    open_pipeline(page, findable)
    page.get_by_test_id("search-query").fill("invoices")
    faded = page.get_by_test_id("graph-node").filter(
        has_text=f"Orders raw {findable['tag']}"
    ).first
    assert "0.35" in (faded.get_attribute("style") or ""), faded.get_attribute("style")
    # And the one it found is not dimmed, which is the half that says the
    # dimming is a distinction rather than a curtain.
    found = matches(page).first
    assert "opacity: 0.35" not in (found.get_attribute("style") or "")


def test_a_kind_filter_is_a_question_on_its_own(page, findable) -> None:
    """p.8's Advanced tab. A kind with the box empty is "show me the models",
    which is a question — so the nothing-matches-nothing rule is about *both*
    being empty rather than about the text alone."""
    open_pipeline(page, findable)
    page.get_by_test_id("search-kind-model").click()
    expect(page.get_by_test_id("search-count")).to_have_text("1 of 4")
    expect(matches(page)).to_have_count(1)
    expect(matches(page).first).to_contain_text(f"Orders clean {findable['tag']}")
    # The model, not the dataset it wrote — they share a name, and the filter
    # is the only thing that tells them apart.
    expect(matches(page).first).to_contain_text("model")


def test_a_kind_filter_narrows_a_search(page, findable) -> None:
    """The two together, which is what "filters to your search" means.

    `orders` alone is two nodes; `orders` restricted to datasets is one. A
    build that applied only one of the two lands on a different number.
    """
    open_pipeline(page, findable)
    page.get_by_test_id("search-query").fill("orders")
    expect(page.get_by_test_id("search-count")).to_have_text("3 of 4")

    page.get_by_test_id("search-kind-dataset").click()
    # The source and the model's output; the model itself drops out.
    expect(page.get_by_test_id("search-count")).to_have_text("2 of 4")
    expect(matches(page).first).to_contain_text(f"Orders raw {findable['tag']}")

    # And it comes off again — a filter nothing can clear is a mode.
    page.get_by_test_id("search-kind-dataset").click()
    expect(page.get_by_test_id("search-count")).to_have_text("3 of 4")


def test_a_match_is_marked_even_when_nothing_is_dimmed(page, findable) -> None:
    """**Why a match says so on its own as well as by everything else fading.**

    Filter to a kind that covers the whole graph and there is nothing left to
    dim, so dimming alone would leave a reader looking at undimmed cards
    wondering which ones the count meant.
    """
    open_pipeline(page, findable)
    page.get_by_test_id("search-kind-dataset").click()
    page.get_by_test_id("search-kind-model").click()
    page.get_by_test_id("search-kind-object_type").click()
    expect(page.get_by_test_id("search-count")).to_have_text("4 of 4")
    expect(matches(page)).to_have_count(4)
    everything = page.get_by_test_id("graph-node")
    for i in range(everything.count()):
        assert "opacity: 0.35" not in (everything.nth(i).get_attribute("style") or "")
    # **The mark itself, not the attribute that stands for it.** `data-match`
    # is how this file finds the cards; asserting only that would pass on a
    # build that drew nothing at all, which is the whole failure this test
    # exists to catch (§214).
    style = matches(page).first.get_attribute("style") or ""
    assert "outline: 2px solid var(--accent)" in style, style


def test_select_all_takes_the_results(page, findable) -> None:
    """p.8's "buttons at the bottom of the view to add all search results",
    which here means select them — the results are already drawn, and a
    selection is what §354's histogram and §355's expansions carry further.
    """
    open_pipeline(page, findable)
    page.get_by_test_id("search-query").fill("orders")
    page.get_by_test_id("search-select-all").click()
    expect(page.get_by_test_id("selection-count")).to_have_text("3 nodes selected")
    expect(page.locator("[data-selected]")).to_have_count(3)


def test_selecting_search_results_hands_them_to_the_expansions(page, findable) -> None:
    """The join between this and §355, which is the reason "add all results"
    became "select all results" rather than being dropped.

    `Orders raw` is the only node whose name contains it, and expanding
    downstream from that one picks up the model and the dataset it wrote —
    two nodes the search itself never reached.
    """
    open_pipeline(page, findable)
    page.get_by_test_id("search-query").fill("orders raw")
    page.get_by_test_id("search-select-all").click()
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")

    page.get_by_test_id("expand-all-downstream").click()
    expect(page.get_by_test_id("selection-count")).to_have_text("3 nodes selected")
