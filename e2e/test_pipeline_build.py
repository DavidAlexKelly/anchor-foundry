"""Building from the lineage graph (§386; `data-lineage` p.9).

> "The builds helper offers you three build strategies:
>  Build only selected datasets /
>  Build all datasets between the selected datasets /
>  Build the selected datasets and all of their ancestors" (p.9)

**Two of the three selections were already on this bar**, which is what sized
this unit: §354's multi-select is the first strategy and §355's `All upstream`
chip is the third. So what is added is the one selection that was missing —
`Between` — and the build itself. p.9's strategies are a *selection* plus a
build, and here the selection is the graph's existing vocabulary.

Which nodes a plan reaches, and what the summary says about it, are
`apps/web/src/lib/graph-builds.test.ts`'s, where a cycle and an upload cost
nothing to build. What needs a browser is the **seam**: that the button runs
the transforms the summary counted, in the order the graph reads, and that a
dataset nothing builds is reported rather than silently skipped.

SQL throughout, so `POST /run` executes inline and no worker turn is needed.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def chain(api):
    """S → A → `A`'s output → B → `B`'s output.

    `S` is an upload: nothing builds it, which is the §214 case. `B` is left
    **never run**, so "it built" is observable as a version appearing rather
    than as a number that was already there.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Build {tag}", "slug": f"build-{tag}"},
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
    # B is deliberately not run here.
    return {"workspace_slug": workspace["slug"], "project_slug": project["slug"],
            "tag": tag, "base": base, "a": a["id"], "b": b["id"]}


def open_pipeline(page, chain) -> None:
    page.goto(f"{WEB_BASE}/{chain['workspace_slug']}/{chain['project_slug']}/pipeline")
    expect(page.get_by_test_id("graph-node").first).to_be_visible(timeout=30000)


def card(page, chain, kind: str, key: str):
    """One node's card, by its kind **and** name — a model and its output
    dataset share a name here, so the pair is the identity, not the name."""
    return (
        page.get_by_test_id("graph-node")
        .filter(has_text=kind)
        .filter(has_text=f"{key} {chain['tag']}")
        .first
    )


def runs(api, chain, model_id: str) -> int:
    return len(api.call("GET", f"{chain['base']}/models/{model_id}/runs"))


def test_building_a_selected_transform_runs_it(page, api, chain) -> None:
    """**The seam.** The summary counts transforms, the button runs them, and
    the run history is where that is visible — a build nobody can see the
    result of is the half this row was missing."""
    before = runs(api, chain, chain["b"])
    open_pipeline(page, chain)
    card(page, chain, "model", "B").click()
    expect(page.get_by_test_id("selection-build-summary")).to_have_text("build 1 transform")

    page.get_by_test_id("selection-build-run").click()
    # Positive first (§318): the button reports it finished before the count
    # is read, so a passing assertion cannot be one taken too early.
    expect(page.get_by_test_id("selection-build-run")).to_have_text("Build", timeout=60000)
    expect(page.get_by_test_id("pipeline-build-error")).to_have_count(0)
    assert runs(api, chain, chain["b"]) == before + 1


def test_selecting_a_dataset_builds_the_transform_that_writes_it(page, api, chain) -> None:
    """p.9 says *datasets* and a build runs a transform; they meet one hop up.

    Selecting `A`'s output must run `A` — not `B`, which reads it, and not
    nothing.
    """
    before = runs(api, chain, chain["a"])
    open_pipeline(page, chain)
    card(page, chain, "dataset", "A").click()
    expect(page.get_by_test_id("selection-build-summary")).to_have_text("build 1 transform")

    page.get_by_test_id("selection-build-run").click()
    expect(page.get_by_test_id("selection-build-run")).to_have_text("Build", timeout=60000)
    assert runs(api, chain, chain["a"]) == before + 1


def test_an_uploaded_dataset_is_reported_rather_than_silently_skipped(page, chain) -> None:
    """**§214, and the reason the summary is beside the button rather than in
    it.** `S` is an upload: nothing on this graph builds it. A control that
    said "Build" over two selected cards and ran one would be the reading this
    prevents."""
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    summary = page.get_by_test_id("selection-build-summary")
    # Selected alone, it is not a thing that builds at all — and the button
    # says so by being unusable rather than by failing when pressed.
    expect(summary).to_have_text("nothing here is built by a transform")
    expect(page.get_by_test_id("selection-build-run")).to_be_disabled()

    # Beside something that does build, both facts are on the screen at once.
    card(page, chain, "dataset", "A").click(modifiers=["ControlOrMeta"])
    expect(summary).to_contain_text("build 1 transform")
    expect(summary).to_contain_text("uploaded, not built")
    expect(page.get_by_test_id("selection-build-run")).to_be_enabled()


def test_between_takes_the_path_and_the_build_follows_the_graph_order(page, chain) -> None:
    """p.9's middle strategy, which was the only selection not already here.

    From the source to the last dataset is the whole chain, and the summary
    then counts both transforms rather than the five cards selected.
    """
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    card(page, chain, "dataset", "B").click(modifiers=["ControlOrMeta"])
    expect(page.get_by_test_id("selection-count")).to_have_text("2 nodes selected")

    page.get_by_test_id("expand-between").click()
    expect(page.get_by_test_id("selection-count")).to_have_text("5 nodes selected")
    # Five cards, two transforms: the count that matters is of what will run.
    expect(page.get_by_test_id("selection-build-summary")).to_contain_text("build 2 transforms")


def test_between_is_offered_only_when_there_are_two_ends(page, chain) -> None:
    """The negative control for the chip. "Between" needs two ends, and a
    chip that did nothing on one node would be a control that looks like it
    works."""
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    expect(page.get_by_test_id("selection-count")).to_have_text("1 node selected")
    expect(page.get_by_test_id("expand-between")).to_have_count(0)
    # And it appears as soon as there is a second end.
    card(page, chain, "dataset", "A").click(modifiers=["ControlOrMeta"])
    expect(page.get_by_test_id("expand-between")).to_be_visible()
