"""p.45-47's Preview and Code tabs, under the lineage graph (§439).

    "To see a preview of a dataset or media set, select it in your data
     lineage graph, then choose the Preview tab in the bottom left of the
     interface." (`data-lineage` p.45)

    "When the dataset preview expands, you can scroll through the first 300
     rows of the selected dataset. You can also search for specific columns
     using the Search columns... field to the right of the preview window.
     …Select the Code tab to view the code logic of the selected dataset or
     media set. From the Code view, you can… open the code in the
     repository." (p.47)

    "Uploaded and writeback datasets do not have associated code to view in
     Data Lineage." (p.47)

Which tabs a node offers and which columns a query keeps are
`apps/web/src/lib/graph-inspector.test.ts`'s. What needs a browser is the
seam — that the rows on screen are *this dataset's* and the code is *this
dataset's transform* — and the thing no unit test reaches: that reading one
node after another keeps the picture, which is the whole reason p.45 puts
these tabs on the graph instead of behind the Open button that was already
there.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

UPLOADED = b"town,county,population\nEly,Cambs,20112\nWells,Somerset,12000\n"


@pytest.fixture(scope="module")
def pipeline(api):
    """One project with all three shapes of node this panel answers for.

    **The transform is published from a repository and then run**, which is
    two fixtures in one on purpose: `models.output_dataset_id` is NULL until
    the first run, so without the run there is no built dataset on the graph
    at all — and without the repository there is no file for p.47's "open the
    code in the repository" to open, which is the one verb a link rather than
    an editor.
    """
    mod = Module(api, "Graph inspector")
    tag = uuid.uuid4().hex[:8]
    # **No spaces in the name**: a transform declares its inputs by dataset
    # name, and a declaration cannot carry one (`test_build_panel.py` learned
    # this the expensive way).
    source = f"orders_{tag}"
    mod.api.upload_csv(f"{mod.base}/datasets/upload", source, UPLOADED)
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Transforms {mod.tag}"})
    built = f"daily_{tag}"
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "a transform",
         "files": {"src/daily.sql":
                   f"-- output: {built}\n-- input: raw = {source}\n"
                   f"SELECT town, population FROM raw\n"}},
    )
    published = mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/publish", {"branch": "main"})
    model_id = published["steps"][0]["model_id"]
    mod.api.call("POST", f"{mod.base}/models/{model_id}/run")
    return {"mod": mod, "source": source, "built": built, "repo": repo,
            "transform": f"daily_{tag}"}


def open_graph(page, pipeline) -> None:
    mod = pipeline["mod"]
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/pipeline")
    expect(page.get_by_test_id("graph-search")).to_be_visible(timeout=30000)


def select(page, kind: str, name: str) -> None:
    """One card, by kind **and** name.

    A transform's output dataset takes the transform's own name, so the built
    name is two cards here — the model and the dataset it wrote — and they
    have different answers: one offers Code alone and the other both tabs.
    Picking by words would pick whichever the DOM ordered first.
    """
    page.locator(
        f"[data-testid='graph-node'][data-kind='{kind}']", has_text=name
    ).first.click()
    expect(page.get_by_test_id("details-name")).to_be_visible(timeout=30000)


def test_a_dataset_a_transform_wrote_offers_both_tabs(page, pipeline) -> None:
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["built"])
    expect(page.get_by_test_id("gi-tab-preview")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("gi-tab-code")).to_be_visible()


def test_the_preview_shows_this_datasets_rows(page, pipeline) -> None:
    """**The seam.** A panel that rendered a table of somebody else's rows
    would look exactly like one that worked — so the assertion is on a value
    only this dataset has."""
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["source"])
    expect(page.get_by_test_id("graph-inspector")).to_contain_text("Ely", timeout=30000)
    expect(page.get_by_test_id("graph-inspector")).to_contain_text("Somerset")


def test_searching_columns_keeps_the_cells_under_their_own_headings(
    page, pipeline
) -> None:
    """p.47's Search columns. The cells are the point: a filter that narrowed
    the headings and left the body alone would put every value under the wrong
    name, which reads as corrupt data rather than as a broken filter."""
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["source"])
    panel = page.get_by_test_id("graph-inspector")
    expect(panel).to_contain_text("Cambs", timeout=30000)

    page.get_by_test_id("gi-column-search").fill("town")
    expect(page.get_by_test_id("gi-columns-note")).to_have_text("1 of 3 columns",
                                                               timeout=30000)
    expect(panel).to_contain_text("Ely")
    expect(panel).not_to_contain_text("Cambs")


def test_a_search_that_matches_nothing_says_so(page, pipeline) -> None:
    """§226: a table of no columns and a dataset with no columns look the
    same on screen."""
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["source"])
    expect(page.get_by_test_id("gi-column-search")).to_be_visible(timeout=30000)
    page.get_by_test_id("gi-column-search").fill("zzz")
    note = page.get_by_test_id("gi-columns-note")
    expect(note).to_contain_text("No column matches", timeout=30000)
    expect(page.get_by_test_id("graph-inspector").locator("table")).to_have_count(0)


def test_the_code_tab_shows_the_transform_behind_the_dataset(page, pipeline) -> None:
    """p.47's "the code logic of the selected dataset" — the transform that
    writes it, not the dataset's own anything."""
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["built"])
    page.get_by_test_id("gi-tab-code").click()
    expect(page.get_by_test_id("gi-code")).to_contain_text(
        "SELECT town, population FROM raw", timeout=30000)


def test_the_code_tab_links_to_the_file_in_the_repository(page, pipeline) -> None:
    """p.47's "open the code in the repository", and the one verb that is a
    link here rather than an editor."""
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["built"])
    page.get_by_test_id("gi-tab-code").click()
    link = page.get_by_test_id("gi-open-file")
    expect(link).to_be_visible(timeout=30000)
    link.click()
    page.wait_for_url(lambda url: "file=src%2Fdaily.sql" in url
                      or "file=src/daily.sql" in url, timeout=30000)
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def test_an_uploaded_dataset_has_no_code_tab_and_says_why(page, pipeline) -> None:
    """p.47: "Uploaded and writeback datasets do not have associated code to
    view in Data Lineage." The sentence is beside the tabs that *are* there,
    because that is where somebody looking for Code is looking."""
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["source"])
    expect(page.get_by_test_id("gi-tab-preview")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("gi-tab-code")).to_have_count(0)
    expect(page.get_by_test_id("gi-no-code")).to_contain_text("uploaded")


def test_a_transform_offers_its_own_code_and_no_preview(page, pipeline) -> None:
    """A transform holds no rows of its own. A Preview tab on it would open
    onto nothing, which is the control §214 is about."""
    open_graph(page, pipeline)
    select(page, "model", pipeline["transform"])
    expect(page.get_by_test_id("gi-tab-code")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("gi-tab-preview")).to_have_count(0)
    expect(page.get_by_test_id("gi-code")).to_contain_text("SELECT town", timeout=30000)


def test_the_open_tab_follows_the_reader_down_the_pipeline(page, pipeline) -> None:
    """**p.45's workflow, and the bug that would break it.**

    Reading rows hop by hop is the reason these tabs are on the graph. A panel
    that reset to Preview on every selection would undo half of it; one that
    simply kept its state would sit on Code over an uploaded dataset and draw
    nothing under a highlighted tab.
    """
    open_graph(page, pipeline)
    select(page, "dataset", pipeline["built"])
    page.get_by_test_id("gi-tab-code").click()
    expect(page.get_by_test_id("gi-code")).to_be_visible(timeout=30000)

    # A dataset with no code: the panel has to move rather than stay on a tab
    # this node does not have.
    select(page, "dataset", pipeline["source"])
    expect(page.get_by_test_id("gi-tab-code")).to_have_count(0)
    expect(page.get_by_test_id("gi-tab-preview")).to_have_attribute(
        "aria-selected", "true", timeout=30000)
    expect(page.get_by_test_id("graph-inspector")).to_contain_text("Ely", timeout=30000)


def test_the_panel_is_absent_until_one_node_is_selected(page, pipeline) -> None:
    """§318: the graph's search box is waited for first, so this absence is
    about the panel rather than about the page not having drawn."""
    open_graph(page, pipeline)
    expect(page.get_by_test_id("graph-inspector")).to_have_count(0)
