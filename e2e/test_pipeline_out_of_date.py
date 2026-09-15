"""Out-of-date datasets on the lineage graph (parity `datasets-lineage.md`
§2.3; Foundry `data-lineage` p.51).

> "There are a few reasons why your dataset may not be up to date. … Is my
>  dataset build failing? Is there an **upstream dataset that hasn't built and
>  isn't up to date**? Have we received up-to-date data from the source?"
>  (p.51)

Which datasets are stale, and which of p.51's reasons each one is, is
`apps/api/tests/test_pipeline.py`'s — it can build a four-stage chain and
re-run the first model, which is the only honest way to make one dataset
genuinely older than another.

What needs a browser is the half that decides whether any of it matters: a
node that is out of date has to **say so on the card**, before anything is
clicked. A field on a JSON response nothing draws is a field nobody reads.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def stale(api):
    """S → A → a_out → B → b_out, with **A run twice**.

    The second run of A writes a new version of `a_out`, which is then newer
    than the `b_out` built from it — p.51's "upstream dataset that hasn't built
    and isn't up to date", produced rather than asserted into existence.
    """
    tag = uuid.uuid4().hex[:6]
    workspaces = api.call("GET", "/workspaces")
    workspace = workspaces[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Stale {tag}", "slug": f"stale-{tag}"},
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
    # The line the whole fixture turns on.
    api.call("POST", f"{base}/models/{a['id']}/run")

    return {
        "workspace_slug": workspace["slug"],
        "project_slug": project["slug"],
        "tag": tag,
    }


def card(page, kind: str, name: str):
    """One node's card, by its **kind and** name.

    Both, because a model and the dataset it writes share a name here —
    `A <tag>` is the model and `A <tag>` is its output — and `.first` takes
    whichever the DOM put first, which is the model. §351's browser test met
    the same collision one node kind over and wrote down the same fix: the
    name is not an identity on this graph, the pair is.
    """
    return (
        page.locator("button").filter(has_text=kind).filter(has_text=name).first
    )


def test_a_stale_dataset_says_so_before_anything_is_clicked(page, stale) -> None:
    """p.51 on the screen. **The note is on the card**, not behind a
    selection: somebody opening a pipeline to ask why a number is wrong should
    see which node to look at without hunting for it.

    Both halves in one test, because the claim is a *difference*: `b_out` is
    stale and `a_out` — rebuilt after its input — is not. Asserting only the
    first would pass against a build that marked every node stale, which is
    exactly what an over-eager downstream walk produces.
    """
    page.goto(f"{WEB_BASE}/{stale['workspace_slug']}/{stale['project_slug']}/pipeline")
    b_out = card(page, "dataset", f"B {stale['tag']}")
    expect(b_out).to_be_visible(timeout=30000)
    expect(b_out.get_by_test_id("node-out-of-date")).to_contain_text(
        "its input is newer"
    )

    rebuilt = card(page, "dataset", f"A {stale['tag']}")
    expect(rebuilt).to_be_visible()
    expect(rebuilt.get_by_test_id("node-out-of-date")).to_have_count(0)


def test_the_source_is_never_the_thing_that_is_out_of_date(page, stale) -> None:
    """p.51's third question — whether the *source* is current — is the one
    this platform has nowhere to record an answer for, so an uploaded dataset
    with nothing feeding it says nothing rather than guessing."""
    page.goto(f"{WEB_BASE}/{stale['workspace_slug']}/{stale['project_slug']}/pipeline")
    source = card(page, "dataset", f"S {stale['tag']}")
    expect(source).to_be_visible(timeout=30000)
    expect(source.get_by_test_id("node-out-of-date")).to_have_count(0)
