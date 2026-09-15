"""Selecting several nodes on the lineage graph (parity `datasets-lineage.md`
§2.1; Foundry `data-lineage` p.7, p.54, p.55).

> "Click and drag to pan around the graph when in the default **Panning**
>  mode. To use the cursor to select multiple nodes, switch to **Drag select**
>  mode in the graph tools or hold `Shift` while clicking and dragging. You can
>  select a node by clicking it, or select multiple nodes with `Ctrl/Cmd` +
>  click." (p.7)

> "...select all datasets of interest by using **Drag select** mode... You can
>  also hold down `Ctrl` / `Command` to select multiple nodes at once, or use
>  `Ctrl` / `Command` + A  to select all nodes." (p.54)

Which nodes a rectangle covers, and what narrowing does to the histogram, is
`apps/web/src/lib/pipeline-graph.test.ts`'s — that is arithmetic and it is
tested where it can be made to fail cheaply. What needs a browser is the part
the arithmetic cannot show: that a **gesture** reaches it. A hit test nothing
drags a rectangle into is a hit test.

§353 left this row deliberately, and this is the half it left: it built p.55's
histogram over the graph as drawn, which is p.54's *first* instruction
("ensure you added all datasets of interest in your pipeline to your lineage
graph") with the second one missing. "In your selection" appears three times
across pp.54-55, and now it means something.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE


@pytest.fixture(scope="module")
def selectable(api):
    """Three uploads sharing some columns and not others.

    The same shape as `test_pipeline_columns`, because the assertion that
    matters here is what *narrowing* does to that list: `only` belongs to one
    dataset, so a selection that leaves it out has to lose the column.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Select {tag}", "slug": f"select-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    for key, csv in (
        ("All", b"id,val,only\n1,10,x\n"),
        ("Two", b"id,val\n1,10\n"),
        ("One", b"id\n1\n"),
    ):
        api.upload_csv(f"{base}/datasets/upload", f"{key} {tag}", csv)
    return {"workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "tag": tag}


def open_pipeline(page, selectable) -> None:
    page.goto(
        f"{WEB_BASE}/{selectable['workspace_slug']}/{selectable['project_slug']}/pipeline"
    )
    expect(page.get_by_test_id("frequent-columns")).to_be_visible(timeout=30000)


def card(page, selectable, key):
    """A node card by its exact name.

    `title` rather than text: the card's text runs the kind, the name and the
    subtitle together, and §351 recorded that a name filter on this graph can
    take a different node than the one meant.
    """
    return page.locator(f'button[title="{key} {selectable["tag"]}"]')


def cards_top_down(page):
    """Every node card, in the order they are drawn down the screen.

    The server decides which dataset sits at which `position`, and three
    independent uploads have no order this test is entitled to assume — so the
    geometry is read off the page rather than predicted.
    """
    cards = page.get_by_test_id("graph-node")
    boxes = [
        (cards.nth(i).bounding_box(), cards.nth(i).get_attribute("title"))
        for i in range(cards.count())
    ]
    return sorted([b for b in boxes if b[0]], key=lambda b: b[0]["y"])


def drag(page, x1, y1, x2, y2) -> None:
    page.mouse.move(x1, y1)
    page.mouse.down()
    # In steps, because one jump from corner to corner is a `mousemove` the
    # graph may never see between the press and the release.
    page.mouse.move(x2, y2, steps=8)
    page.mouse.up()


def column_names(page) -> list[str]:
    chips = page.get_by_test_id("frequent-columns").locator("button")
    return [chips.nth(i).get_attribute("data-column") for i in range(chips.count())]


def test_a_rectangle_in_drag_select_mode_takes_the_nodes_under_it(page, selectable) -> None:
    """p.7's Drag select mode, as a gesture rather than a hit test.

    Drawn tight around **one** card so the assertion is about which node the
    rectangle covered: a build that selected everything under the pointer's
    path, or everything on the graph, names a different node here.
    """
    open_pipeline(page, selectable)
    page.get_by_test_id("tool-drag-select").click()
    box, title = cards_top_down(page)[0]
    drag(page, box["x"] - 5, box["y"] - 5,
         box["x"] + box["width"] + 5, box["y"] + box["height"] - 5)

    # One node selected is the detail bar, and the bar names it — which is the
    # assertion that says the rectangle took *that* card. A count would have
    # read the same for any one of the three.
    expect(page.get_by_test_id("details-name")).to_have_text(title)
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")
    # And the graph draws the one it took, rather than leaving the detail bar
    # to be the only place the selection exists.
    selected = page.locator("[data-selected]")
    expect(selected).to_have_count(1)
    assert selected.first.get_attribute("title") == title


def test_a_rectangle_over_the_whole_graph_takes_every_node(page, selectable) -> None:
    """The other end of the same gesture, and the count is what says so."""
    open_pipeline(page, selectable)
    page.get_by_test_id("tool-drag-select").click()
    boxes = [b for b, _ in cards_top_down(page)]
    left = min(b["x"] for b in boxes) - 8
    top = min(b["y"] for b in boxes) - 8
    right = max(b["x"] + b["width"] for b in boxes) + 8
    bottom = max(b["y"] + b["height"] for b in boxes) + 8
    drag(page, left, top, right, bottom)
    expect(page.get_by_test_id("selection-count")).to_have_text("3 nodes selected")
    # The count says how many; the cards say which, and a selection the graph
    # does not draw is a number in a bar.
    expect(page.locator("[data-selected]")).to_have_count(3)


def test_the_same_drag_in_pan_mode_selects_nothing(page, selectable) -> None:
    """**The negative control for the mode toggle**, and the reason the toggle
    exists at all: p.7's default is Panning, and a graph that selected while
    you were trying to look further right would be a graph you could not read.

    A toggle that changed nothing would pass every assertion above.
    """
    open_pipeline(page, selectable)
    expect(page.get_by_test_id("tool-pan")).to_have_attribute("aria-pressed", "true")
    boxes = [b for b, _ in cards_top_down(page)]
    left = min(b["x"] for b in boxes) - 8
    top = min(b["y"] for b in boxes) - 8
    right = max(b["x"] + b["width"] for b in boxes) + 8
    bottom = max(b["y"] + b["height"] for b in boxes) + 8
    before = boxes[0]["x"]
    drag(page, left, top, right, bottom)
    expect(page.get_by_test_id("selection-summary")).to_have_count(0)
    expect(page.get_by_test_id("graph-marquee")).to_have_count(0)
    expect(page.get_by_test_id("details-name")).to_have_count(0)
    # And it panned, which is the half that says the mode did the *other*
    # thing rather than nothing at all: the same drag moved the graph.
    assert cards_top_down(page)[0][0]["x"] != before


def test_shift_drags_a_rectangle_without_leaving_pan_mode(page, selectable) -> None:
    """p.7's second way in: "or hold `Shift` while clicking and dragging"."""
    open_pipeline(page, selectable)
    boxes = [b for b, _ in cards_top_down(page)]
    left = min(b["x"] for b in boxes) - 8
    top = min(b["y"] for b in boxes) - 8
    right = max(b["x"] + b["width"] for b in boxes) + 8
    bottom = max(b["y"] + b["height"] for b in boxes) + 8
    page.keyboard.down("Shift")
    drag(page, left, top, right, bottom)
    page.keyboard.up("Shift")
    expect(page.get_by_test_id("selection-count")).to_have_text("3 nodes selected")
    # And the mode itself is untouched, which is what "without leaving" means.
    expect(page.get_by_test_id("tool-pan")).to_have_attribute("aria-pressed", "true")


def test_ctrl_click_adds_a_node_and_narrows_the_histogram(page, selectable) -> None:
    """**p.55's sentence, finally with a selection in it.**

    On the whole graph the list is `id`(3), `val`(2), `only`(1). Selecting the
    two datasets that do not have `only` has to lose that column and drop
    `id` to two — a build that kept computing over the graph shows all three
    names here, and one that merely filtered without re-counting shows the
    wrong numbers.
    """
    open_pipeline(page, selectable)
    assert column_names(page) == ["id", "val", "only"]

    card(page, selectable, "Two").click()
    card(page, selectable, "One").click(modifiers=["Control"])

    expect(page.get_by_test_id("selection-count")).to_have_text("2 nodes selected")
    assert column_names(page) == ["id", "val"]
    expect(page.get_by_test_id("column-id")).to_contain_text("2")
    expect(page.get_by_test_id("column-val")).to_contain_text("1")


def test_ctrl_a_selects_every_node(page, selectable) -> None:
    """p.54's "Ctrl / Command + A to select all nodes", which is the shortcut
    for the rectangle nobody wants to draw around a large graph."""
    open_pipeline(page, selectable)
    card(page, selectable, "One").click()
    page.keyboard.press("Control+a")
    expect(page.get_by_test_id("selection-count")).to_have_text("3 nodes selected")
    # Every node selected is the whole graph again, so the histogram is back to
    # what it was — the assertion that `columnsIn` treats "all" and "none"
    # alike rather than by accident of which branch it took.
    assert column_names(page) == ["id", "val", "only"]


def test_a_selection_can_be_put_down(page, selectable) -> None:
    """A selection nothing clears is a mode rather than a question (§353's own
    note, one panel over)."""
    open_pipeline(page, selectable)
    card(page, selectable, "Two").click()
    card(page, selectable, "One").click(modifiers=["Control"])
    assert column_names(page) == ["id", "val"]

    page.get_by_test_id("selection-clear").click()
    expect(page.get_by_test_id("selection-summary")).to_have_count(0)
    assert column_names(page) == ["id", "val", "only"]


def test_a_click_in_drag_select_mode_is_still_a_click(page, selectable) -> None:
    """**The reason `DRAG_FLOOR` exists.**

    Pressing on a card in Drag select mode is both gestures at once: the card's
    own handler runs *and* a zero-sized rectangle closes over it, and the two
    cancel out — the node a person clicked ends up unselected. A build without
    the floor leaves nothing selected here.
    """
    open_pipeline(page, selectable)
    page.get_by_test_id("tool-drag-select").click()
    card(page, selectable, "Two").click()
    expect(page.get_by_test_id("details-name")).to_have_text(f"Two {selectable['tag']}")


def test_ctrl_held_through_a_drag_adds_to_the_selection(page, selectable) -> None:
    """Two rectangles, one selection (p.54's Ctrl/Cmd, applied to the drag
    rather than only to the click).

    Whether a drag extends the selection is decided by the modifier held when
    it *started* — a build that read the keyboard at mouse-up would throw the
    first rectangle away here, because the drag ends with Ctrl still down
    either way.
    """
    open_pipeline(page, selectable)
    page.get_by_test_id("tool-drag-select").click()
    boxes = [b for b, _ in cards_top_down(page)]
    for index, extra in ((0, False), (1, True)):
        box = boxes[index]
        if extra:
            page.keyboard.down("Control")
        drag(page, box["x"] - 5, box["y"] - 5,
             box["x"] + box["width"] + 5, box["y"] + box["height"] - 5)
        if extra:
            page.keyboard.up("Control")
    expect(page.get_by_test_id("selection-count")).to_have_text("2 nodes selected")


def test_a_rectangle_lands_where_it_is_drawn_on_a_zoomed_graph(page, selectable) -> None:
    """**The transform, which is the part a hit test gets wrong quietly.**

    The cards are drawn inside a panned and scaled canvas, and the pointer is
    not. A build that tested the rectangle against unscaled coordinates selects
    a plausible number of nodes at 100% and the wrong ones at any other zoom.

    Drawn around the **last** card rather than the first, because that is where
    the error is big enough to see: the mistake is proportional to the distance
    from the canvas origin, so a rectangle around the top node still overlaps
    the right card either way and proves nothing (which is what the first
    draft of this test did).
    """
    open_pipeline(page, selectable)
    for _ in range(2):
        page.get_by_role("button", name="−").click()
    expect(page.get_by_role("button", name="70%")).to_be_visible()
    page.get_by_test_id("tool-drag-select").click()
    box, title = cards_top_down(page)[-1]
    drag(page, box["x"] - 4, box["y"] - 4,
         box["x"] + box["width"] + 4, box["y"] + box["height"] - 4)
    expect(page.get_by_test_id("details-name")).to_have_text(title)


def test_a_rectangle_lands_where_it_is_drawn_on_a_panned_graph(page, selectable) -> None:
    """The other half of the transform, and the more likely one: panning is
    the default mode, so most rectangles are drawn on a graph that has already
    been moved.

    A build that forgot the pan selects the node that *was* under the pointer
    before the graph moved, which is the neighbour — a wrong answer that looks
    like a working feature.
    """
    open_pipeline(page, selectable)
    viewport = page.get_by_test_id("graph-viewport").bounding_box()
    page.mouse.move(viewport["x"] + viewport["width"] - 30, viewport["y"] + 20)
    page.mouse.down()
    page.mouse.move(viewport["x"] + viewport["width"] - 30, viewport["y"] + 120, steps=8)
    page.mouse.up()

    page.get_by_test_id("tool-drag-select").click()
    box, title = cards_top_down(page)[-1]
    drag(page, box["x"] - 4, box["y"] - 4,
         box["x"] + box["width"] + 4, box["y"] + box["height"] - 4)
    expect(page.get_by_test_id("details-name")).to_have_text(title)


def test_a_rectangle_dragged_off_the_edge_keeps_what_it_covered(page, selectable) -> None:
    """Dragging past the edge of a graph is p.7's own reason for the mode —
    the graphs it is for are bigger than the window.

    The rectangle is committed when the pointer leaves rather than thrown
    away: a gesture that silently does nothing because the pointer crossed a
    border is §214's control that looks like it works.
    """
    open_pipeline(page, selectable)
    page.get_by_test_id("tool-drag-select").click()
    viewport = page.get_by_test_id("graph-viewport").bounding_box()
    boxes = [b for b, _ in cards_top_down(page)]
    left = min(b["x"] for b in boxes) - 8
    top = min(b["y"] for b in boxes) - 8
    right = max(b["x"] + b["width"] for b in boxes) + 8
    bottom = max(b["y"] + b["height"] for b in boxes) + 8

    page.mouse.move(left, top)
    page.mouse.down()
    page.mouse.move(right, bottom, steps=8)
    # Out through the bottom of the viewport, still holding.
    page.mouse.move(right, viewport["y"] + viewport["height"] + 60, steps=6)
    page.mouse.up()
    expect(page.get_by_test_id("selection-count")).to_have_text("3 nodes selected")
