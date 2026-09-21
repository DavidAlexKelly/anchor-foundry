"""p.11's Layout menu (§424).

> "The layout button provide various arrangement option for the nodes on the
>  graph. Layout all nodes applies automatic layout for all the nodes on the
>  graphs. When you select multiple nodes on the graph, you can apply other
>  layouts (vertical, hierarchical, by level, etc.)." (p.11)

> "You can arrange your nodes on the graph by color group under Layouts."
>  (p.11)

Where each arrangement puts a card is `apps/web/src/lib/graph-layout.test.ts`'s.
What needs a browser is the claim that module exists to make true: that
**everything that knows where a card is asks the same question**. The cards,
the edge curves, §354's drag rectangle and §423's exported picture were four
readers of one piece of arithmetic, and a second arrangement is exactly what
turns that into a marquee selecting the node beside the one it was drawn
around — with nothing on the screen to say which copy is wrong.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def arranged(api):
    """A chain three layers deep, so left-to-right and top-to-bottom are
    visibly different arrangements of the same graph."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Layout {tag}", "slug": f"layout-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    raw = api.upload_csv(f"{base}/datasets/upload", f"Raw {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Clean {tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": raw["id"], "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{model['id']}/run")
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "raw": raw["id"]}


def open_graph(page, arranged, query: str = "") -> None:
    page.goto(
        f"{WEB_BASE}/{arranged['workspace_slug']}/{arranged['project_slug']}"
        f"/pipeline{query}"
    )
    expect(page.get_by_test_id("graph-layout")).to_be_visible(timeout=30000)


def boxes(page) -> dict:
    out = {}
    for card in page.get_by_test_id("graph-node").all():
        out[card.get_attribute("data-node")] = card.bounding_box()
    return out


def test_the_graph_opens_on_the_automatic_layout(page, arranged) -> None:
    """p.11's "Layout all nodes", which is what the graph drew before there
    was a menu — a picker whose default rearranged the page the moment it
    appeared would be a new feature wearing a settings control."""
    open_graph(page, arranged)
    expect(page.get_by_test_id("graph-layout")).to_have_value("level")
    # Left to right: the model sits right of the dataset it reads.
    at = boxes(page)
    raw = at[f"dataset:{arranged['raw']}"]
    others = [b for k, b in at.items() if k != f"dataset:{arranged['raw']}"]
    assert all(b["x"] > raw["x"] for b in others), at


def test_vertical_turns_the_pipeline_down_the_page(page, arranged) -> None:
    """The seam: the menu is in the toolbar and the cards are on the canvas."""
    open_graph(page, arranged)
    before = boxes(page)
    page.get_by_test_id("graph-layout").select_option("vertical")
    after = boxes(page)
    raw_key = f"dataset:{arranged['raw']}"
    others = [k for k in after if k != raw_key]
    assert others, after
    # Downstream is now *below* rather than to the right, and every card moved.
    assert all(after[k]["y"] > after[raw_key]["y"] for k in others), after
    assert all(after[k]["x"] == after[raw_key]["x"] for k in others), after
    assert after != before


def test_the_edges_follow_the_cards(page, arranged) -> None:
    """A curve drawn from where a card *used* to be is the failure this unit
    exists to prevent, and it is invisible in any test that only reads card
    positions."""
    open_graph(page, arranged)
    first = page.locator("svg path[marker-end]").first
    level = first.get_attribute("d")
    page.get_by_test_id("graph-layout").select_option("vertical")
    expect(page.locator("svg path[marker-end]").first).not_to_have_attribute("d", level)


def test_the_drag_rectangle_follows_the_cards(page, arranged) -> None:
    """**The claim `nodesInRect` moved modules for.** A band across the top of
    a vertical graph covers the first layer and nothing else; under the level
    layout the same band covers everything. A hit test still asking the old
    arithmetic would select the wrong set and look exactly as convincing.
    """
    open_graph(page, arranged)
    page.get_by_test_id("graph-layout").select_option("vertical")
    page.get_by_test_id("tool-drag-select").click()

    at = boxes(page)
    raw = at[f"dataset:{arranged['raw']}"]
    viewport = page.get_by_test_id("graph-viewport").bounding_box()
    # A band from the top of the canvas to just past the first card's bottom.
    page.mouse.move(viewport["x"] + 2, raw["y"] - 10)
    page.mouse.down()
    page.mouse.move(viewport["x"] + viewport["width"] - 2, raw["y"] + raw["height"] - 4,
                    steps=8)
    page.mouse.up()
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")
    expect(page.locator("[data-selected='true']")).to_have_attribute(
        "data-node", f"dataset:{arranged['raw']}"
    )


def test_the_exported_picture_is_of_the_layout_on_screen(page, arranged) -> None:
    """§423's export is the fourth reader of the same arithmetic, and the one
    a reader would notice last: a picture laid out the old way still looks
    like a graph."""
    open_graph(page, arranged)
    page.get_by_test_id("graph-layout").select_option("vertical")
    with page.expect_download() as caught:
        page.get_by_test_id("graph-export-svg").click()
    svg = open(caught.value.path()).read()
    at = boxes(page)
    for node_id, box in at.items():
        if box is None:
            continue
        assert f'data-node="{node_id}"' in svg, node_id
    # Taller than it is wide, which a left-to-right export of this chain is
    # not — the cheapest statement of "this is the vertical picture".
    width = int(svg.split('width="', 1)[1].split('"', 1)[0])
    height = int(svg.split('height="', 1)[1].split('"', 1)[0])
    assert height > width, (width, height)


def test_by_colour_group_puts_the_same_verdict_together(page, arranged) -> None:
    """p.11's "arrange your nodes on the graph by color group", which only
    means anything beside §419's colouring — the group *is* the swatch."""
    open_graph(page, arranged)
    page.get_by_test_id("graph-colouring").select_option("kind")
    page.get_by_test_id("graph-layout").select_option("colour")
    at = boxes(page)
    rows = {}
    for card in page.get_by_test_id("graph-node").all():
        rows.setdefault(card.get_attribute("data-kind"), set()).add(
            round(card.bounding_box()["y"])
        )
    assert len(rows) >= 2, rows
    # Two kinds, two bands: no y is shared between them.
    bands = list(rows.values())
    assert not (bands[0] & bands[1]), rows


def test_a_pasted_link_opens_at_that_layout(page, arranged) -> None:
    """p.12's share link carries the arrangement: a graph sent with the
    pipeline running down the page, to sit beside a column of text, arrives
    sideways without it."""
    open_graph(page, arranged, "?layout=vertical")
    expect(page.get_by_test_id("graph-layout")).to_have_value("vertical")


def test_a_link_naming_a_layout_this_build_dropped_opens_on_the_default(
    page, arranged
) -> None:
    """§214, and `layoutIn`'s reason for existing: a `<select>` with no
    matching option shows the first one while the graph draws something else.
    """
    open_graph(page, arranged, "?layout=spiral")
    expect(page.get_by_test_id("graph-layout")).to_have_value("level")
