"""The rest of p.12 (§423): Invert selection, and Export graph to SVG.

> "**Invert selection**: De-selects all currently selected nodes and selects
>  the rest of the nodes on the graph." (p.12)

> "**Export graph to SVG**: Generates a static image of your lineage graph."
>  (p.12)

Both were named gaps in rows already at ◑ — the Selection tool had three of
p.12's four and the save-and-share row two of its three.

What each produces is `apps/web/src/lib/pipeline-graph.test.ts`'s and
`graph-svg.test.ts`'s. What needs a browser is the half neither can reach: for
Invert, that it inverts over *this* graph's nodes; for the export, that a file
actually arrives and that the picture in it is of the graph as it looked —
colouring and all, with the palette resolved, since a `var(--…)` in a
standalone file resolves against nothing and no unit test has a document to
resolve against.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def drawn(api):
    """Three uploads and a model that has run: five nodes, enough that an
    inverted selection is neither everything nor nothing."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Export {tag}", "slug": f"export-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    raw = api.upload_csv(f"{base}/datasets/upload", f"Raw {tag}", ROWS)
    api.upload_csv(f"{base}/datasets/upload", f"Spare {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Clean {tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": raw["id"], "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{model['id']}/run")
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "name": f"Export {tag}"}


def open_graph(page, drawn) -> None:
    page.goto(
        f"{WEB_BASE}/{drawn['workspace_slug']}/{drawn['project_slug']}/pipeline"
    )
    expect(page.get_by_test_id("graph-search")).to_be_visible(timeout=30000)


def count(page) -> int:
    return page.get_by_test_id("graph-node").count()


def test_invert_takes_everything_that_was_not_selected(page, drawn) -> None:
    """p.12's fourth selection helper, and the only one that answers "what did
    I leave out"."""
    open_graph(page, drawn)
    total = count(page)
    assert total >= 4, total
    page.get_by_test_id("graph-node").first.click()
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")
    page.get_by_test_id("selection-invert").click()
    expect(page.get_by_test_id("selection-count")).to_have_text(
        f"{total - 1} nodes selected"
    )
    # And the one that was selected is not any more, which is the half a count
    # alone cannot show.
    expect(page.get_by_test_id("graph-node").first).not_to_have_attribute(
        "data-selected", "true"
    )


def test_inverting_twice_comes_back(page, drawn) -> None:
    """The property, said as a round trip rather than as two counts: whatever
    invert means, doing it twice has to be doing nothing."""
    open_graph(page, drawn)
    card = page.get_by_test_id("graph-node").first
    card.click()
    page.get_by_test_id("selection-invert").click()
    page.get_by_test_id("selection-invert").click()
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")
    expect(card).to_have_attribute("data-selected", "true")


def test_invert_is_a_selection_control_and_lives_with_the_selection(page, drawn) -> None:
    """**Absent with nothing selected, and that is the design rather than an
    oversight.** Invert is an operation *on* a selection; with none, "the rest
    of the nodes" is all of them, and p.54's Ctrl/Cmd+A is already the control
    for that — a second button meaning the same thing would be two answers to
    one question.

    The positive half is here beside the negative (§318): the bar and the chip
    both appear the moment there is something to invert.
    """
    open_graph(page, drawn)
    total = count(page)
    expect(page.get_by_test_id("selection-summary")).to_have_count(0)
    expect(page.get_by_test_id("selection-invert")).to_have_count(0)

    page.get_by_test_id("graph-viewport").click()
    page.keyboard.press("ControlOrMeta+a")
    expect(page.get_by_test_id("selection-count")).to_have_text(f"{total} nodes selected")
    expect(page.get_by_test_id("selection-invert")).to_be_visible()


def test_the_export_produces_a_picture_of_this_graph(page, drawn) -> None:
    """**The seam.** A file arrives, it is an SVG, and it is of *this* graph —
    a download nobody reads back is a control that looks like it works."""
    open_graph(page, drawn)
    with page.expect_download() as caught:
        page.get_by_test_id("graph-export-svg").click()
    download = caught.value
    assert download.suggested_filename.endswith(".svg"), download.suggested_filename
    assert download.suggested_filename.startswith("export-"), download.suggested_filename
    svg = open(download.path()).read()
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"'), svg[:80]
    assert f"Raw {drawn['tag']}" in svg
    assert f"Clean {drawn['tag']}" in svg


def test_the_picture_carries_the_colouring_that_was_on_screen(page, drawn) -> None:
    """§419's reading travels with the picture, and the palette is **resolved**
    — a `var(--…)` in a standalone file resolves against nothing, so every
    stroke would fall back to black and the colouring would export flat.

    This is the claim no unit test can make: there is no document to resolve
    against in vitest, so `FALLBACK` is all it can check.
    """
    open_graph(page, drawn)
    page.get_by_test_id("graph-colouring").select_option("kind")
    with page.expect_download() as caught:
        page.get_by_test_id("graph-export-svg").click()
    svg = open(caught.value.path()).read()
    assert "var(--" not in svg, "an unresolved token reached the file"
    # The left bars are there: one per coloured card.
    assert svg.count('width="4"') >= 4, svg.count('width="4"')


def test_no_colour_exports_no_colour(page, drawn) -> None:
    """p.38's first option has to travel too. A picture with bars on it after
    the reader turned the colours off would be a reading nobody chose."""
    open_graph(page, drawn)
    page.get_by_test_id("graph-colouring").select_option("none")
    with page.expect_download() as caught:
        page.get_by_test_id("graph-export-svg").click()
    svg = open(caught.value.path()).read()
    assert 'width="4"' not in svg
    # And it is still a picture of the graph rather than an empty one.
    assert f"Raw {drawn['tag']}" in svg


def test_the_selection_is_in_the_picture(page, drawn) -> None:
    """The export is of the graph *as it looked*, and a selection is part of
    how it looked — an export that dropped it would be a picture of a
    different moment than the one somebody pressed the button in."""
    open_graph(page, drawn)
    with page.expect_download() as first:
        page.get_by_test_id("graph-export-svg").click()
    plain = open(first.value.path()).read()

    page.get_by_test_id("graph-node").first.click()
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")
    with page.expect_download() as second:
        page.get_by_test_id("graph-export-svg").click()
    chosen = open(second.value.path()).read()

    assert chosen.count('stroke-width="2"') == 1, chosen.count('stroke-width="2"')
    assert 'stroke-width="2"' not in plain


def test_the_picture_uses_the_palette_the_page_is_using(page, drawn) -> None:
    """**The one claim no unit test can make**, and the reason the export reads
    the live document instead of hardcoding six hex values.

    `[data-scheme="dark"]` redefines the palette, and a graph inside one has to
    export with the values the document resolves rather than the ones this
    module was written against. Applied to the root here, which is what a
    page-level dark mode does; the fallbacks are pinned against `globals.css`
    by `graph-svg.test.ts`, so what is left to check is that the live document
    is consulted at all.
    """
    open_graph(page, drawn)
    page.evaluate("document.documentElement.setAttribute('data-scheme', 'dark')")
    dark_ink = page.evaluate(
        "getComputedStyle(document.documentElement)"
        ".getPropertyValue('--ink').trim()"
    )
    assert dark_ink, "the dark scheme declared no --ink"
    with page.expect_download() as caught:
        page.get_by_test_id("graph-export-svg").click()
    svg = open(caught.value.path()).read()
    assert f'fill="{dark_ink}"' in svg, (dark_ink, svg[:400])
