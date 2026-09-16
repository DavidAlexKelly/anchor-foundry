"""Branching a dataset from a historical transaction (parity
`datasets-lineage.md` §1.3; Foundry `dataset-preview` p.4).

> "You can use the **History tab** to create branches on historical
>  transactions of your data that have not been deleted by a retention policy.
>  Choose a previous transaction from the left panel and select the ellipsis
>  (...) icon to **Create branch**." (p.4)

**The action is not new; its place is.** Forking a version into an independent
dataset has existed since migration 0025, but it lived on the datasets *list*
behind a dropdown asking which version you meant. p.4 puts it on the
transaction you are already reading — so the version is not a question, it is
the row you pressed.

That is the whole of what this adds, and the split of work follows it:
`apps/api/tests/test_dataset_forks.py` owns what a fork copies and what it
refuses, and this file owns the one thing only a browser can show — that the
row you pressed is the version that gets branched.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def versioned(api):
    """A dataset with two versions whose *schemas* differ.

    Driven through a model, since that is how a dataset gets a second version
    (`test_dataset_forks` records the same). v1 has `id, val` and v2 has `id`
    alone, so which transaction a branch came from is readable from the branch
    itself rather than taken on trust.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Branching {tag}", "slug": f"branching-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"

    source = api.upload_csv(f"{base}/datasets/upload", f"Src {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Shrink {tag}", "code": "SELECT id, val FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    first = api.call("POST", f"{base}/models/{model['id']}/run")
    output = first["output_dataset"]["id"]
    api.call("PATCH", f"{base}/models/{model['id']}", {"code": "SELECT id FROM raw"})
    second = api.call("POST", f"{base}/models/{model['id']}/run")
    assert second["output_dataset"]["current_version"] == 2

    name = api.call("GET", f"{base}/datasets/{output}")["name"]
    resources = api.call("GET", f"{base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == name)
    return {"tag": tag, "base": base, "dataset_id": output,
            "name": name, "resource_id": resource["id"], "api": api}


def open_history(page, versioned) -> None:
    page.goto(f"{WEB_BASE}/r/{versioned['resource_id']}?tab=history")
    expect(page.get_by_test_id("branch-version").first).to_be_visible(timeout=30000)


def branch_button(page, version: int):
    return page.locator(f'[data-testid="branch-version"][data-version="{version}"]')


def branches_of(versioned) -> list[dict]:
    listed = versioned["api"].call("GET", f"{versioned['base']}/datasets")
    return [d for d in listed if d["forked_from_dataset_id"] == versioned["dataset_id"]]


def test_every_transaction_offers_a_branch(page, versioned) -> None:
    """p.4's placement: the action is on each historical transaction, not in a
    dropdown somewhere else asking which one.

    Enabled is asserted rather than assumed — a button drawn permanently
    disabled would satisfy a count on its own.
    """
    open_history(page, versioned)
    expect(page.get_by_test_id("branch-version")).to_have_count(2)
    expect(branch_button(page, 1)).to_be_enabled()
    expect(branch_button(page, 2)).to_be_enabled()


def test_the_dialog_opens_already_about_that_transaction(page, versioned) -> None:
    """**The version is the row, not a field.** Pressing v1's button opens a
    dialog named for v1 and pre-filled for it; asking again is what the
    datasets list's dropdown does, and replacing that is the point.
    """
    open_history(page, versioned)
    branch_button(page, 1).click()
    expect(page.get_by_test_id("branch-name")).to_have_value(f"{versioned['name']} v1")

    page.get_by_role("button", name="Cancel").click()
    branch_button(page, 2).click()
    # The other row gives the other answer, which is what says the row reaches
    # the dialog at all rather than a constant being drawn twice.
    expect(page.get_by_test_id("branch-name")).to_have_value(f"{versioned['name']} v2")


def test_branching_v1_copies_v1_and_not_the_current_data(page, versioned) -> None:
    """**The assertion the placement exists for.**

    v1 has `id, val` and v2 has `id` alone. A branch taken from v1's row that
    came back with v2's schema would have copied "as it is now" — which is what
    a dropdown defaulting to the current version does, and exactly the mistake
    putting the button on the transaction is meant to stop.

    Read back from the server rather than from the dialog: a dialog can be made
    to say anything, and what matters is which version was copied.
    """
    open_history(page, versioned)
    branch_button(page, 1).click()
    name = f"From v1 {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("branch-name").fill(name)
    page.get_by_role("button", name="Create branch").click()
    expect(page.get_by_test_id("branch-made")).to_contain_text(name)

    made = next(d for d in branches_of(versioned) if d["name"] == name)
    assert made["forked_from_version"] == 1
    assert [c["name"] for c in made["table_schema"]] == ["id", "val"]

    # **And the reader is still where they were.** Branching from the history
    # is something you do *while reading the history*; sending them to the new
    # dataset would lose the place they were in, and the confirmation says what
    # happened precisely so it does not have to.
    page.get_by_role("button", name="Done").click()
    expect(page.get_by_test_id("branch-version")).to_have_count(2)


def test_a_refusal_is_shown_rather_than_swallowed(page, versioned) -> None:
    """Branching twice off the same version collides on slug, which the server
    refuses by name. The dialog has to say so: a Create button that appears to
    do nothing is worse than one that is absent (§214).
    """
    open_history(page, versioned)
    branch_button(page, 2).click()
    name = f"Twice {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("branch-name").fill(name)
    page.get_by_role("button", name="Create branch").click()
    expect(page.get_by_test_id("branch-made")).to_be_visible()
    page.get_by_role("button", name="Done").click()

    branch_button(page, 2).click()
    page.get_by_test_id("branch-name").fill(name)
    page.get_by_role("button", name="Create branch").click()
    expect(page.get_by_test_id("branch-error")).to_contain_text("already exists")
    # And nothing was made the second time.
    assert len([d for d in branches_of(versioned) if d["name"] == name]) == 1


def test_cancelling_branches_nothing(page, versioned) -> None:
    """A dialog that acted on close would create a dataset nobody asked for and
    say nothing about it.

    **The negative assertion waits on a positive one** (§318): a stray request
    fired by Cancel is in flight, so reading the datasets back straight away
    races it and passes whether or not it was sent. Branching v2 for real and
    waiting for *that* gives the stray one a full round trip to land in, and
    then the absence means something.

    Named precisely rather than counted: Cancel would have submitted the
    pre-filled name, so that is the dataset that must not exist. A count would
    be wrong here anyway — the tests before this one leave branches behind.
    """
    open_history(page, versioned)
    branch_button(page, 1).click()
    would_have_been = f"{versioned['name']} v1"
    expect(page.get_by_test_id("branch-name")).to_have_value(would_have_been)
    page.get_by_role("button", name="Cancel").click()

    branch_button(page, 2).click()
    keep = f"Kept {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("branch-name").fill(keep)
    page.get_by_role("button", name="Create branch").click()
    expect(page.get_by_test_id("branch-made")).to_contain_text(keep)

    names = [d["name"] for d in branches_of(versioned)]
    assert keep in names, names
    assert would_have_been not in names, names
