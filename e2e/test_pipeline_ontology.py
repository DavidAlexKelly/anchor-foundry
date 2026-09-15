"""Ontology entities on the lineage graph (parity `datasets-lineage.md` §2.4;
Foundry `data-lineage` p.30-32, TOC §7).

> "Find object types defined by datasets in your lineage graph by selecting the
>  dataset and opening the View node properties panel in the right sidebar."
>  (p.31)

> "You can then view link types related to the object type and use the graph to
>  visualize connections between your datasets and the newly added object
>  type." (p.32)

The shape of the graph is `apps/api/tests/test_pipeline.py`'s: which nodes,
which edges, which links, and what a focus narrows to. What needs a browser is
the half neither of those can reach — that the graph **draws** a kind it has
learned to return, and that the node opens somewhere.

That is not a hypothetical split. `PipelineGraphView` is drawn from three
places, each with its own `onOpen` written out by hand, so a new kind is
exactly the thing that becomes a node two of the three cannot navigate to —
which is why the rule now lives in `lib/pipeline-graph` and why this test
presses the button rather than reading the DOM for a label.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def backed(api):
    """Two object types on this project's data, joined by a link type."""
    sites = Module(api, "Lineage ontology")
    sites.object_type(
        columns=["id", "town"],
        rows=[{"id": "1", "town": "Ely"}],
        key="id", title="town",
    )
    visits = Module(api, "Lineage ontology visits", beside=sites)
    visits.object_type(
        columns=["id", "note"],
        rows=[{"id": "1", "note": "first"}],
        key="id", title="note",
        slug=f"visit_{sites.tag}",
    )
    api.call(
        "POST",
        f"/workspaces/{sites.workspace_id}/link-types",
        {
            "api_name": f"visited_{sites.tag}",
            "display_name": f"Visited {sites.tag}",
            "from_type_id": sites.object_type_id,
            "to_type_id": visits.object_type_id,
            "cardinality": "one_to_many",
        },
    )
    return sites


def object_type_node(page, tag: str):
    """The object type's card, told apart from the dataset's by its **kind**.

    Not by name: `Module.object_type` names the type after the dataset that
    backs it, which is the ordinary case rather than a fixture quirk — an
    object type built from `orders` is called Orders. A locator that matched on
    the name alone took the dataset card and then asked why it did not say
    "object type", which is this file's own first draft.
    """
    return (
        page.locator("button")
        .filter(has_text="object type")
        .filter(has_text=f"seed_{tag}")
        .first
    )


def test_an_object_type_is_drawn_on_the_project_pipeline(page, backed) -> None:
    """p.31's claim, on the screen. The node carries its kind so a reader can
    tell it from the dataset beside it, and its api_name so somebody writing a
    transform against it has the name they would type."""
    page.goto(f"{WEB_BASE}/{backed.workspace_slug}/{backed.project_slug}/pipeline")
    node = object_type_node(page, backed.tag)
    expect(node).to_be_visible(timeout=30000)
    # The dataset is still its own card, which is what makes the graph an
    # answer to "what does this dataset back" rather than a renaming of it.
    expect(
        page.locator("button").filter(has_text="dataset").filter(
            has_text=f"seed_{backed.tag}"
        ).first
    ).to_be_visible()


def test_a_link_type_is_drawn_and_a_dataset_edge_is_not_dashed(page, backed) -> None:
    """p.32's link, and the distinction the server draws by keeping it out of
    `edges`: a link is a relationship, an edge is a flow. Drawn dashed and
    without an arrowhead so the graph does not claim the ontology is part of
    the build order.

    Presence *and* the difference: asserting only that a dashed path exists
    would pass against a build that drew every edge dashed."""
    page.goto(f"{WEB_BASE}/{backed.workspace_slug}/{backed.project_slug}/pipeline")
    link = page.get_by_test_id("pipeline-link").first
    expect(link).to_be_visible(timeout=30000)
    assert link.get_attribute("stroke-dasharray"), "a link is dashed"
    assert not link.get_attribute("marker-end"), "and carries no arrowhead"

    # An ordinary edge, for contrast: solid and arrowed.
    edges = page.locator("path[marker-end]")
    assert edges.count() > 0, "the graph still has real edges"
    assert not edges.first.get_attribute("stroke-dasharray")


def test_opening_an_object_type_node_lands_in_the_ontology_manager(
    page, backed
) -> None:
    """p.32: "click the Settings icon next to the object type to view its
    configuration in a new Ontology manager tab".

    **The button is pressed rather than the handler read**, because the bug
    this guards against is a node three graphs draw and two of them cannot
    open — which no amount of reading one call site would show."""
    page.goto(f"{WEB_BASE}/{backed.workspace_slug}/{backed.project_slug}/pipeline")
    node = object_type_node(page, backed.tag)
    expect(node).to_be_visible(timeout=30000)
    node.click()
    page.get_by_role("button", name="Open object type").click()
    expect(page).to_have_url(
        f"{WEB_BASE}/{backed.workspace_slug}/{backed.project_slug}/objects",
        timeout=30000,
    )
