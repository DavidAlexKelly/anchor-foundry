"""Finding datasets with a given column (parity `datasets-lineage.md` §2.3;
Foundry `data-lineage` p.54-55).

> "Under the **Frequent Columns** section, you can see the most frequent
>  columns by name in your selection. Click one of the columns to **highlight
>  the datasets in your selection that contain this column**." (p.55)

Which columns, in which order, and which datasets have each one is
`apps/api/tests/test_pipeline.py`'s. What needs a browser is p.55's second
sentence, which is the whole point of the feature: **clicking does something
to the graph**. A list of column names that highlights nothing is a list.

p.54's flow selects datasets with drag-select first. This platform's graph has
single selection — multi-select is its own ○ row — so the *graph as drawn* is
the selection, which is p.54's own first instruction ("ensure you added all
datasets of interest in your pipeline to your lineage graph") and leaves the
narrowing to the row that owns it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE


@pytest.fixture(scope="module")
def columns(api):
    """Three uploads sharing some columns and not others.

    `id` is in all three and `only` in one, so the ordering has something to
    sort and the highlight has something to *exclude*.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Columns {tag}", "slug": f"columns-{tag}"},
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


def open_pipeline(page, columns) -> None:
    page.goto(
        f"{WEB_BASE}/{columns['workspace_slug']}/{columns['project_slug']}/pipeline"
    )
    expect(page.get_by_test_id("frequent-columns")).to_be_visible(timeout=30000)


def test_the_columns_are_listed_most_frequent_first(page, columns) -> None:
    """p.55's section, with the count beside each name — a list sorted by
    something invisible reads as arbitrary."""
    open_pipeline(page, columns)
    chips = page.get_by_test_id("frequent-columns").locator("button")
    # Read from `data-column` rather than the text: the count sits beside the
    # name with only CSS between them, so `inner_text` is "id3".
    assert [
        chips.nth(i).get_attribute("data-column") for i in range(chips.count())
    ] == ["id", "val", "only"]
    expect(page.get_by_test_id("column-id")).to_contain_text("3")
    expect(page.get_by_test_id("column-only")).to_contain_text("1")


def test_clicking_a_column_highlights_the_datasets_that_have_it(page, columns) -> None:
    """**p.55's second sentence, which is the whole feature.** A list of names
    that highlights nothing is a list.

    Asserted as the *difference*: `All` has `only` and the other two do not, so
    a build that lit every node — or none — fails here. The dimming is what
    makes the highlight readable on a graph with forty nodes, so it is part of
    the claim rather than decoration.
    """
    open_pipeline(page, columns)
    lit = page.locator("button[data-lit]")
    expect(lit).to_have_count(0)

    page.get_by_test_id("column-only").click()
    expect(lit).to_have_count(1)
    expect(lit.first).to_contain_text(f"All {columns['tag']}")
    # And the others are dimmed rather than merely un-lit.
    others = page.locator("button").filter(has_text=f"Two {columns['tag']}").first
    assert "0.35" in (others.get_attribute("style") or ""), others.get_attribute("style")


def test_clicking_the_same_column_again_clears_it(page, columns) -> None:
    """A highlight nothing can turn off is a mode rather than a question."""
    open_pipeline(page, columns)
    page.get_by_test_id("column-id").click()
    expect(page.locator("button[data-lit]")).to_have_count(3)
    expect(page.get_by_test_id("column-id")).to_have_attribute("aria-pressed", "true")

    page.get_by_test_id("column-id").click()
    expect(page.locator("button[data-lit]")).to_have_count(0)
    expect(page.get_by_test_id("column-id")).to_have_attribute("aria-pressed", "false")
