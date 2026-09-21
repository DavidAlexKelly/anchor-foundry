"""p.38's node colouring (§419; `data-lineage` p.38-39).

> "There are several built-in options for coloring graph nodes to give you more
> information about your pipeline." (p.38)

Which bucket a node lands in is `apps/web/src/lib/node-colouring.test.ts`'s, and
what a saved view may carry is `apps/api/tests/test_saved_graphs.py`'s. What
needs a browser is the seam those two cannot reach: that choosing a colouring
**changes what the cards on screen say**, that the legend beside them counts
the same cards, and that a colouring survives the round trip out to a link and
back — which is three layers and no unit test anywhere in the middle.
"""
from __future__ import annotations

import re
import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def coloured(api):
    """An upload, two models that have run, and **the first one run again**.

    Every part of that is load-bearing. The runs are what give the models
    output datasets, without which every dataset on the graph is an upload — a
    graph on which a legend has one row, and a key with one row in it cannot
    show that the picker did anything. The second run of A is what makes B's
    output genuinely older than its input, so the out-of-date colouring has two
    buckets to sort rather than one (the shape `test_pipeline_out_of_date.py`
    settled on: produced, not asserted into existence).
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Colour {tag}", "slug": f"colour-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    raw = api.upload_csv(f"{base}/datasets/upload", f"Raw {tag}", ROWS)
    a = api.call("POST", f"{base}/models", {
        "name": f"A {tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": raw["id"], "input_alias": "raw"}],
    })
    first = api.call("POST", f"{base}/models/{a['id']}/run")
    a_out = first["output_dataset"]["id"]
    b = api.call("POST", f"{base}/models", {
        "name": f"B {tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": a_out, "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{b['id']}/run")
    # The line the out-of-date half turns on.
    api.call("POST", f"{base}/models/{a['id']}/run")
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"]}


def open_graph(page, coloured, query: str = "") -> None:
    page.goto(
        f"{WEB_BASE}/{coloured['workspace_slug']}/{coloured['project_slug']}"
        f"/pipeline{query}"
    )
    expect(page.get_by_test_id("graph-colouring")).to_be_visible(timeout=30000)


def colours(page) -> list[str]:
    """Every card's verdict, as the colouring decided it.

    The attribute rather than the border colour: what p.38 changes is which
    bucket a card is in, and a test written against `var(--danger)` would pass
    on a build that put every node in the wrong bucket and kept the palette.
    """
    return [
        card.get_attribute("data-colour")
        for card in page.get_by_test_id("graph-node").all()
    ]


def test_the_graph_opens_on_what_it_coloured_by_before_there_was_a_choice(
    page, coloured
) -> None:
    """A picker whose default changed the page the moment it appeared would be
    a new feature wearing a settings control. Build status is what this graph
    always drew."""
    open_graph(page, coloured)
    expect(page.get_by_test_id("graph-colouring")).to_have_value("status")
    # A stale dataset outranks its health under this rule (§352), and both
    # models succeeded: three verdicts, which is what the graph drew before
    # §419 gave the reading a name.
    assert set(colours(page)) == {"unknown", "ok", "stale"}, colours(page)


def test_choosing_a_colouring_repaints_the_cards(page, coloured) -> None:
    """The seam: the select is in the toolbar and the verdict is on the card,
    with the whole of `swatchFor` in between."""
    open_graph(page, coloured)
    page.get_by_test_id("graph-colouring").select_option("kind")
    expect(page.locator("[data-colour='object_type']")).to_have_count(0)
    # Three datasets — one upload and two model outputs — and two models.
    expect(page.locator("[data-colour='dataset']")).to_have_count(3)
    expect(page.locator("[data-colour='model']")).to_have_count(2)


def test_the_legend_counts_the_cards_it_is_a_key_for(page, coloured) -> None:
    """**A colour with no legend is a code.** And a legend whose counts came
    from somewhere other than the cards would be a key to a different graph —
    which is the one thing that cannot be caught by looking at either alone."""
    open_graph(page, coloured)
    page.get_by_test_id("graph-colouring").select_option("kind")
    expect(page.get_by_test_id("graph-legend")).to_be_visible()
    expect(page.get_by_test_id("legend-dataset")).to_have_attribute("data-count", "3")
    expect(page.get_by_test_id("legend-model")).to_have_attribute("data-count", "2")
    # And it lists what is there rather than the vocabulary: no object types
    # on this graph means no row for them.
    expect(page.get_by_test_id("legend-object_type")).to_have_count(0)


def test_the_legend_reads_worst_first(page, coloured) -> None:
    """The order is written down rather than taken from the order nodes happen
    to arrive in, because that is what somebody opens a pipeline graph to
    find — and a key that reshuffles as the graph grows is one people stop
    looking at."""
    open_graph(page, coloured)
    page.get_by_test_id("graph-colouring").select_option("out_of_date")
    # Waited for rather than read straight off: the graph has just re-rendered,
    # and a list read mid-render would be an order nobody chose (§318).
    expect(page.get_by_test_id("legend-current")).to_be_visible()
    rows = page.locator("[data-testid^='legend-']").all()
    keys = [row.get_attribute("data-testid") for row in rows]
    # Two buckets, which is what the fixture's second run of A is for: an
    # order over one row is not an order.
    assert keys == ["legend-parent", "legend-current"], keys


def test_no_colour_takes_the_colours_off(page, coloured) -> None:
    """p.38's first option, which is a choice and not an absence (§210). The
    cards keep their borders; what goes is the reading."""
    open_graph(page, coloured)
    page.get_by_test_id("graph-colouring").select_option("none")
    expect(page.get_by_test_id("graph-legend")).to_have_count(0)
    # §318: the legend's disappearance is waited for above, so what follows is
    # about the cards rather than about a page that has not re-rendered. The
    # count is asserted first — "every card is uncoloured" over an empty graph
    # is true and says nothing (§226).
    verdicts = colours(page)
    assert len(verdicts) == 5, verdicts
    assert set(verdicts) == {None}, verdicts


def test_a_colouring_goes_into_the_address_bar(page, coloured) -> None:
    """p.12's share link copies the address bar, so a graph shared to say
    "these are out of date with an ancestor" has to carry the reading that
    sentence depends on."""
    open_graph(page, coloured)
    page.get_by_test_id("graph-colouring").select_option("health")
    expect(page).to_have_url(re.compile(r"[?&]colour=health"))


def test_a_pasted_link_opens_at_that_colouring(page, coloured) -> None:
    """The far end of the same link."""
    open_graph(page, coloured, "?colour=health")
    expect(page.get_by_test_id("graph-colouring")).to_have_value("health")


def test_a_link_naming_a_colouring_this_build_dropped_opens_on_the_default(
    page, coloured
) -> None:
    """**§214, and the reason `colouringIn` exists at all.** `swatchFor` would
    draw the default whatever the link said; without narrowing at the boundary
    the picker would sit there showing an unrelated option beside cards drawn
    by a rule it does not name."""
    open_graph(page, coloured, "?colour=spark_usage")
    expect(page.get_by_test_id("graph-colouring")).to_have_value("status")
    assert set(colours(page)) == {"unknown", "ok", "stale"}, colours(page)
