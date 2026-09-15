"""Growing a selection along the lineage (parity `datasets-lineage.md` §2.1;
Foundry `data-lineage` p.7, p.52, and p.8's Update selection).

> "After adding nodes to the graph, you can add their related resources by
>  clicking on the **arrows on either side of the node** or by using the
>  **Expand** option in the graph tools." (p.7)

> "Then, select **Expand node**. You can see all of the ancestor nodes for
>  that dataset by clicking the double left arrow above **Expand parents**."
>  (p.52)

**Selection, not addition, and that is the whole translation.** Foundry's
graph is built up from nothing because its scope is an enterprise, so its
arrows *add* resources to the graph; this graph is a project drawn whole, so
there is nothing to add and the same gesture grows the selection instead. The
control keeps what it was for — "show me what this dataset feeds" — and drops
the mechanism it only needed because the graph started empty.

Which nodes a walk reaches is `apps/web/src/lib/pipeline-graph.test.ts`'s,
where a cycle and a dead end cost nothing to build. What needs a browser is
that the buttons are wired to the graph's own edges and that what they grow is
the thing the histogram is computed over (§354) — a walk over the wrong array
returns a plausible number of nodes and the wrong ones.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def chain(api):
    """S → A → `A`'s output → B → `B`'s output: five nodes in a line.

    Long enough that one hop and the whole chain are different answers, which
    is the only arrangement that can tell p.7's single arrow from p.52's
    double one.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Chain {tag}", "slug": f"chain-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"

    source = api.upload_csv(f"{base}/datasets/upload", f"S {tag}", ROWS)
    a = api.call("POST", f"{base}/models", {
        "name": f"A {tag}", "code": "SELECT id, val * 2 AS doubled FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    first = api.call("POST", f"{base}/models/{a['id']}/run")
    a_out = first["output_dataset"]["id"]
    b = api.call("POST", f"{base}/models", {
        "name": f"B {tag}", "code": "SELECT id, doubled + 1 AS bumped FROM raw",
        "inputs": [{"dataset_id": a_out, "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{b['id']}/run")
    return {"workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "tag": tag}


def open_pipeline(page, chain) -> None:
    page.goto(f"{WEB_BASE}/{chain['workspace_slug']}/{chain['project_slug']}/pipeline")
    expect(page.get_by_test_id("graph-node").first).to_be_visible(timeout=30000)


def card(page, chain, kind: str, key: str):
    """One node's card, by its **kind and** name.

    Both, because a model and the dataset it writes share a name here — `A` is
    the model and `A` is its output — and `.first` takes whichever the DOM put
    first (§351's browser test met the same collision one node kind over: the
    name is not an identity on this graph, the pair is).
    """
    return (
        page.get_by_test_id("graph-node")
        .filter(has_text=kind)
        .filter(has_text=f"{key} {chain['tag']}")
        .first
    )


def selected(page):
    return page.get_by_test_id("selection-count")


def test_one_arrow_takes_one_step(page, chain) -> None:
    """p.7's arrow on one side of a node.

    The source feeds exactly one model, so a step downstream is two nodes —
    and the same button pressed again is three, which is what says the step is
    a step rather than a walk that stopped early.
    """
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    expect(selected(page)).to_have_text("1 node selected")

    page.get_by_test_id("expand-downstream").click()
    expect(selected(page)).to_have_text("2 nodes selected")
    page.get_by_test_id("expand-downstream").click()
    expect(selected(page)).to_have_text("3 nodes selected")


def test_the_double_arrow_takes_the_whole_chain(page, chain) -> None:
    """p.52's "all of the ancestor nodes for that dataset", from the far end."""
    open_pipeline(page, chain)
    card(page, chain, "dataset", "B").click()
    page.get_by_test_id("expand-all-upstream").click()
    expect(selected(page)).to_have_text("5 nodes selected")
    expect(page.locator("[data-selected]")).to_have_count(5)


def test_the_two_directions_are_different_questions(page, chain) -> None:
    """**The negative control for the direction**, and the reason there are
    four buttons rather than one: from the middle of a pipeline, "what feeds
    this" and "what does this feed" have different answers, and a build that
    walked both would give the whole component — which is what `focus` already
    draws.
    """
    open_pipeline(page, chain)
    card(page, chain, "dataset", "A").click()
    page.get_by_test_id("expand-all-upstream").click()
    # `A`'s output, the model that wrote it, and the source it read: three.
    expect(selected(page)).to_have_text("3 nodes selected")

    card(page, chain, "dataset", "A").click()
    page.get_by_test_id("expand-all-downstream").click()
    # Itself, model `B`, and `B`'s output: three the other way, and not five.
    expect(selected(page)).to_have_text("3 nodes selected")


def test_the_end_of_the_line_grows_into_nothing(page, chain) -> None:
    """The other negative control: an expansion that always grew would read as
    working on every node on the graph."""
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    page.get_by_test_id("expand-all-upstream").click()
    expect(selected(page)).to_have_text("1 node selected")


def test_expanding_changes_what_the_histogram_answers_about(page, chain) -> None:
    """**Why this belongs with §354 rather than beside it.**

    p.55's Frequent Columns is computed over the selection, so expanding
    downstream from a source is asking "which columns does everything this
    feeds have". `S` alone has `id` and `val`; the whole chain adds `doubled`
    and `bumped`, and `id` goes from one dataset to three.
    """
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    chips = page.get_by_test_id("frequent-columns").locator("button[data-column]")
    assert [
        chips.nth(i).get_attribute("data-column") for i in range(chips.count())
    ] == ["id", "val"]

    page.get_by_test_id("expand-all-downstream").click()
    expect(page.get_by_test_id("column-id")).to_contain_text("3")
    assert sorted(
        chips.nth(i).get_attribute("data-column") for i in range(chips.count())
    ) == ["bumped", "doubled", "id", "val"]


def test_update_selection_drills_down_to_the_highlight(page, chain) -> None:
    """p.8's last sentence about the histogram, which is the step §354 left.

    > "By clicking on the values, the matching nodes are highlighted. If you
    >  want to drill down to just those resources, click on **Update
    >  selection**." (p.8)

    `val` is the source's alone, so drilling into it from the whole graph
    leaves exactly one node selected — a build that took the lit *nodes* of
    the wrong list, or the selection it already had, lands on a different
    number here.
    """
    open_pipeline(page, chain)
    expect(page.get_by_test_id("selection-summary")).to_have_count(0)
    # **There is nothing to drill into until something is highlighted.** A
    # button standing here before the click would narrow the selection to the
    # empty set — §214's control that looks like it works, and the failure it
    # produces is silent: the graph would simply empty itself.
    expect(page.get_by_test_id("update-selection")).to_have_count(0)

    page.get_by_test_id("column-val").click()
    expect(page.locator("button[data-lit]")).to_have_count(1)

    page.get_by_test_id("update-selection").click()
    expect(selected(page)).to_have_text("1 node selected")
    expect(page.get_by_test_id("details-name")).to_have_text(f"S {chain['tag']}")


def test_update_selection_keeps_more_than_one_when_the_column_is_shared(page, chain) -> None:
    """The other half of the same claim: `id` is in all three datasets, so the
    drill-down keeps three. Said separately because the assertion above would
    read the same for a build that always selected a single node."""
    open_pipeline(page, chain)
    page.get_by_test_id("column-id").click()
    page.get_by_test_id("update-selection").click()
    expect(selected(page)).to_have_text("3 nodes selected")
    # And the column stays lit on all three, because they all have it — the
    # drill-down having happened, rather than a highlight that dimmed nothing.
    expect(page.locator("button[data-lit]")).to_have_count(3)
    # The chip stays pressed with it. Clearing the highlight as a side effect
    # of acting on it would leave a reader unable to see which column they
    # drilled into, one click after choosing it.
    expect(page.get_by_test_id("column-id")).to_have_attribute("aria-pressed", "true")
