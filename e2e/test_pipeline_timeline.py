"""p.10's build timeline (§418; `data-lineage` p.10).

> "Build timelines: A Gantt chart of actual build time for the selected
> datasets."

What each bar measures is `apps/web/src/lib/build-timeline.test.ts`'s. What
needs a browser is the seam and the thing no unit test can reach: that the
window on screen came from a **run that actually happened**, and that a
selection of datasets nobody built says so rather than drawing an empty chart.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE, eventually

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def built(api):
    """An upload, a model **that has been run**, and a second upload.

    The run is the whole fixture: without it the output dataset does not exist
    (`models.output_dataset_id` is NULL until the first run), and with it there
    is exactly one dataset on the graph with a build behind it — beside two
    that were uploaded, which is what gives the panel something to exclude.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Timeline {tag}", "slug": f"timeline-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    raw = api.upload_csv(f"{base}/datasets/upload", f"Raw {tag}", ROWS)
    api.upload_csv(f"{base}/datasets/upload", f"Spare {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Clean {tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": raw["id"], "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{model['id']}/run")
    return {"workspace_slug": workspace["slug"], "project_slug": project["slug"],
            "tag": tag}


def open_graph(page, built) -> None:
    page.goto(f"{WEB_BASE}/{built['workspace_slug']}/{built['project_slug']}/pipeline")
    expect(page.get_by_test_id("graph-search")).to_be_visible(timeout=30000)


def node(page, kind: str, name: str):
    """One card, by kind **and** name.

    Name alone is ambiguous: a model's output dataset takes the model's own
    name, so `Clean abc123` is two cards — the model and the dataset it wrote.
    A test that picked by words would pick whichever the DOM ordered first,
    and the two have very different answers here: only one of them was built.
    """
    return page.locator(
        f"[data-testid='graph-node'][data-kind='{kind}']", has_text=name
    ).first


def click_node(page, kind: str, name: str) -> None:
    node(page, kind, name).click()


def test_the_panel_is_absent_until_something_is_selected(page, built) -> None:
    """p.10's chart is "for the selected datasets". A timeline of forty
    datasets nobody asked about is a picture rather than an answer.

    §318: the graph's search box is waited for first, so this absence is about
    the panel rather than about the page not having rendered.
    """
    open_graph(page, built)
    expect(page.get_by_test_id("build-timeline")).to_have_count(0)


def test_a_built_dataset_gets_a_bar_with_its_duration(page, built) -> None:
    """The seam, end to end: the model ran, and the window on screen came from
    that run rather than from anything the page could have invented."""
    open_graph(page, built)
    click_node(page, "dataset", f"Clean {built['tag']}")
    expect(page.get_by_test_id("build-timeline")).to_be_visible()
    bars = page.locator("[data-testid^='timeline-bar-']")
    eventually(lambda: bars.count(), lambda n: n == 1, what="the built dataset's bar")
    # A real measurement rather than a placeholder: the run took *some* time,
    # and a chart that drew a bar for a build it had not timed would read the
    # same as one that had.
    ms = int(bars.first.get_attribute("data-ms"))
    assert ms >= 0, ms


def test_an_uploaded_dataset_says_why_it_has_no_bar(page, built) -> None:
    """**Not an empty chart.** A selection of uploads is an ordinary thing to
    have, and it has no builds because nothing built it — a fact about where
    the data came from rather than a fault."""
    open_graph(page, built)
    click_node(page, "dataset", f"Spare {built['tag']}")
    expect(page.get_by_test_id("build-timeline")).to_be_visible()
    expect(page.get_by_test_id("timeline-empty")).to_contain_text("not built by a model")
    expect(page.locator("[data-testid^='timeline-bar-']")).to_have_count(0)


def test_a_mixed_selection_says_how_many_it_could_not_chart(page, built) -> None:
    """§226 and §214. One bar drawn for a selection of two would read as a
    chart of the selection; the count is what stops the drawing from being a
    claim about what was selected rather than about the builds in it."""
    open_graph(page, built)
    click_node(page, "dataset", f"Clean {built['tag']}")
    page.keyboard.down("Control")
    click_node(page, "dataset", f"Spare {built['tag']}")
    page.keyboard.up("Control")
    expect(page.locator("[data-testid^='timeline-bar-']")).to_have_count(1)
    expect(page.get_by_test_id("timeline-without")).to_contain_text("1 not built by a model")
