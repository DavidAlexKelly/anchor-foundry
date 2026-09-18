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

from conftest import WEB_BASE, eventually

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def chain(api):
    """S → A → `A`'s output → B → `B`'s output: five nodes in a line.

    `S` is an upload: nothing builds it, which is the §214 case.

    **Both models are run here**, so all five nodes exist. The first draft left
    `B` unrun so that "it built" would show up as a dataset appearing — but an
    unrun model has no output node at all, so three tests then looked for a
    card that was never going to be there. What a build did is read from the
    run history instead, which is a fact about the model rather than about the
    graph's shape.
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
    api.call("POST", f"{base}/models/{b['id']}/run")
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
    # **Waited for, not assumed.** The first draft waited for the button to
    # read "Build" again — which it also reads *before* the click, so the wait
    # was satisfied at once and the run count was read before anything had
    # run. A check that cannot fail is not a check (§213); this polls the run
    # history, which only moves when a build actually happened.
    eventually(lambda: runs(api, chain, chain["b"]), lambda n: n == before + 1,
               what="the build to run")
    expect(page.get_by_test_id("pipeline-build-error")).to_have_count(0)


def test_selecting_a_dataset_builds_the_transform_that_writes_it(page, api, chain) -> None:
    """p.9 says *datasets* and a build runs a transform; they meet one hop up.

    Selecting `A`'s output must run `A` — not `B`, which reads it, and not
    nothing.
    """
    before = runs(api, chain, chain["a"])
    b_before = runs(api, chain, chain["b"])
    open_pipeline(page, chain)
    card(page, chain, "dataset", "A").click()
    expect(page.get_by_test_id("selection-build-summary")).to_have_text("build 1 transform")

    page.get_by_test_id("selection-build-run").click()
    eventually(lambda: runs(api, chain, chain["a"]), lambda n: n == before + 1,
               what="A to be the transform that ran")
    # And `B`, which reads A's output, was not run by this: p.9's first
    # strategy builds what was selected, and reaching further is its own
    # strategy.
    assert runs(api, chain, chain["b"]) == b_before


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


def test_a_build_runs_every_transform_the_summary_counted_and_upstream_first(
    page, api, chain
) -> None:
    """**The claim this row is actually about**, and nothing pinned it until a
    sweep said so: building only the first model of the plan passed every
    other test here, because none of them pressed Build with more than one
    transform to run (§213).

    Two things are asserted, and they are different claims. That *both* ran is
    p.9's strategy doing what it says. That `A` finished before `B` started is
    the **order**, which is the reason the page awaits each run rather than
    firing them together: a transform reads its inputs' current versions, so
    `B` reading `A`'s output has to run after `A` replaced it.
    """
    a_before = runs(api, chain, chain["a"])
    b_before = runs(api, chain, chain["b"])
    open_pipeline(page, chain)
    card(page, chain, "dataset", "S").click()
    card(page, chain, "dataset", "B").click(modifiers=["ControlOrMeta"])
    page.get_by_test_id("expand-between").click()
    expect(page.get_by_test_id("selection-build-summary")).to_contain_text("build 2 transforms")

    page.get_by_test_id("selection-build-run").click()
    eventually(lambda: (runs(api, chain, chain["a"]), runs(api, chain, chain["b"])),
               lambda pair: pair == (a_before + 1, b_before + 1),
               what="both transforms to run")
    expect(page.get_by_test_id("pipeline-build-error")).to_have_count(0)

    # Upstream first. The history is newest-first, so the run each build added
    # is the one at the front.
    a_run = api.call("GET", f"{chain['base']}/models/{chain['a']}/runs")[0]
    b_run = api.call("GET", f"{chain['base']}/models/{chain['b']}/runs")[0]
    assert a_run["finished_at"] <= b_run["started_at"], (
        f"A finished {a_run['finished_at']}, B started {b_run['started_at']}"
    )


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
