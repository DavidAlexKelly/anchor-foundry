"""p.8's histogram helper on the lineage graph (§531; parity
`datasets-lineage.md` Properties and Histogram row).

> "When you select multiple nodes on the graph, you will see the histogram
> helper. The helper displays common properties and their values alongside the
> number of appearances of each value on the graph. By clicking on the values,
> the matching nodes are highlighted. If you want to drill down to just those
> resources, click on Update selection." … "Use the Copy names button in the
> histogram to copy the names of all currently selected resources." (p.8)

The counting is `graph-histogram.test.ts`'s. What needs a browser: a
selection shows it, a value lights its nodes, Update selection keeps them, and
Copy names reaches the clipboard.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def chain(api):
    """A source dataset and two SQL models, each run once: three kinds of
    answer for Kind, Origin and Language to count."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Histogram {tag}", "slug": f"histogram-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    source = api.upload_csv(f"{base}/datasets/upload", f"S {tag}", ROWS)
    a = api.call("POST", f"{base}/models", {
        "name": f"A {tag}", "code": "SELECT id, val * 2 AS doubled FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    first = api.call("POST", f"{base}/models/{a['id']}/run")
    b = api.call("POST", f"{base}/models", {
        "name": f"B {tag}", "code": "SELECT id, doubled + 1 AS bumped FROM raw",
        "inputs": [{"dataset_id": first["output_dataset"]["id"], "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{b['id']}/run")
    return {"workspace_slug": workspace["slug"], "project_slug": project["slug"], "tag": tag}


def open_pipeline(page, chain) -> None:
    page.goto(f"{WEB_BASE}/{chain['workspace_slug']}/{chain['project_slug']}/pipeline")
    expect(page.get_by_test_id("graph-node").first).to_be_visible(timeout=30000)


def card(page, chain, kind: str, key: str):
    return (page.get_by_test_id("graph-node").filter(has_text=kind)
            .filter(has_text=f"{key} {chain['tag']}").first)


def chip(page, row: str, value: str):
    return page.get_by_test_id(f"histogram-{row}").locator(f'button[data-value="{value}"]')


def select_three(page, chain) -> None:
    card(page, chain, "dataset", "S").click()
    card(page, chain, "model", "A").click(modifiers=["Control"])
    card(page, chain, "model", "B").click(modifiers=["Control"])


def test_one_node_has_no_histogram_and_several_do(page, chain) -> None:
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    expect(page.get_by_test_id("graph-histogram")).to_have_count(0)
    card(page, chain, "model", "A").click(modifiers=["Control"])
    card(page, chain, "model", "B").click(modifiers=["Control"])
    histogram = page.get_by_test_id("graph-histogram")
    expect(histogram).to_contain_text("3 selected")
    expect(chip(page, "kind", "model")).to_have_text("model2")
    expect(chip(page, "kind", "dataset")).to_have_text("dataset1")
    expect(chip(page, "language", "sql")).to_have_text("sql2")
    expect(chip(page, "origin", "upload")).to_have_text("upload1")


def test_a_value_lights_its_nodes_and_update_selection_keeps_them(page, chain) -> None:
    open_pipeline(page, chain)
    select_three(page, chain)
    chip(page, "kind", "model").click()
    expect(chip(page, "kind", "model")).to_have_attribute("aria-pressed", "true")
    expect(card(page, chain, "model", "A")).to_have_attribute("data-lit", "true")
    expect(card(page, chain, "dataset", "S")).not_to_have_attribute("data-lit", "true")
    expect(card(page, chain, "dataset", "S")).to_have_css("opacity", "0.35")
    page.get_by_test_id("histogram-update-selection").click()
    expect(page.get_by_test_id("selection-count")).to_contain_text("2")
    expect(page.get_by_test_id("graph-histogram")).to_contain_text("2 selected")
    # Clicking the value again clears the highlight.
    chip(page, "kind", "model").click()
    expect(page.get_by_test_id("histogram-update-selection")).to_have_count(0)
    expect(card(page, chain, "dataset", "S")).to_have_css("opacity", "1")


def test_copy_names_puts_the_selection_on_the_clipboard(page, chain) -> None:
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    open_pipeline(page, chain)
    select_three(page, chain)
    page.get_by_test_id("histogram-copy-names").click()
    expect(page.get_by_test_id("histogram-copied")).to_have_text("Copied 3 names")
    tag = chain["tag"]
    assert page.evaluate("navigator.clipboard.readText()") == f"S {tag}, A {tag}, B {tag}"
