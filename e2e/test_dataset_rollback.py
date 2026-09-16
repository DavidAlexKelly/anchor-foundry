"""Rolling a dataset back to an earlier version (parity `datasets-lineage.md`
§2.3; Foundry `data-lineage` p.73, p.75-76).

> "Select the transaction to roll back to. Select **Rollback to transaction**.
>  A confirmation dialog will be displayed." (p.75-76)

What a rollback does to the data and what it refuses is
`apps/api/tests/test_dataset_rollback.py`'s; the wording of the confirmation is
`apps/web/src/lib/dataset-rollback.test.ts`'s. What needs a browser is the part
neither can reach: that **the row you pressed is the version that comes back**,
and that the screen you were reading says so afterwards.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture()
def versioned(api):
    """A dataset with **three** versions, each with a different row count.

    Built by a model, since that is how a dataset gets a second version here
    (`test_dataset_forks.py` and `test_column_profile.py` both record it).
    Function-scoped rather than module-scoped because these tests *change* the
    dataset — a shared one would make each test's starting point depend on
    which ran first.

    **Three rather than two, and that is the fixture doing work.** With two,
    only one row can be rolled back to, so "the version you pressed" and "the
    first version" are the same answer and a build that ignored the row
    entirely would pass — §190 recorded the same trap in a test about keying.
    Three gives two pressable rows with different data behind them.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Rolling {tag}", "slug": f"rolling-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"

    source = api.upload_csv(f"{base}/datasets/upload", f"Src {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Filter {tag}", "code": "SELECT id, val FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    first = api.call("POST", f"{base}/models/{model['id']}/run")
    output = first["output_dataset"]["id"]
    assert first["output_dataset"]["row_count"] == 3

    # Each build keeps a different number of rows, so which version a screen is
    # showing — and which one a rollback restored — is readable from the data.
    api.call("PATCH", f"{base}/models/{model['id']}", {"code": "SELECT id, val FROM raw WHERE id = 1"})
    second = api.call("POST", f"{base}/models/{model['id']}/run")
    assert second["output_dataset"]["current_version"] == 2
    assert second["output_dataset"]["row_count"] == 1

    api.call("PATCH", f"{base}/models/{model['id']}", {"code": "SELECT id, val FROM raw WHERE id < 3"})
    third = api.call("POST", f"{base}/models/{model['id']}/run")
    assert third["output_dataset"]["current_version"] == 3
    assert third["output_dataset"]["row_count"] == 2

    name = api.call("GET", f"{base}/datasets/{output}")["name"]
    resources = api.call("GET", f"{base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == name)
    return {"tag": tag, "base": base, "dataset_id": output,
            "name": name, "resource_id": resource["id"], "api": api}


def open_history(page, versioned) -> None:
    page.goto(f"{WEB_BASE}/r/{versioned['resource_id']}?tab=history")
    expect(page.get_by_test_id("rollback-version").first).to_be_visible(timeout=30000)


def rollback_button(page, version: int):
    return page.locator(f'[data-testid="rollback-version"][data-version="{version}"]')


def dataset(versioned) -> dict:
    return versioned["api"].call(
        "GET", f"{versioned['base']}/datasets/{versioned['dataset_id']}"
    )


def test_every_earlier_transaction_offers_a_rollback(page, versioned) -> None:
    """p.75's placement, and the refusal that comes with it: the action is on
    each transaction, and the one you are already on cannot be pressed."""
    open_history(page, versioned)
    expect(page.get_by_test_id("rollback-version")).to_have_count(3)
    expect(rollback_button(page, 1)).to_be_enabled()
    expect(rollback_button(page, 2)).to_be_enabled()
    expect(rollback_button(page, 3)).to_be_disabled()
    expect(rollback_button(page, 3)).to_have_attribute(
        "title", "this is the version the dataset is on"
    )


def test_the_dialog_is_about_the_row_that_was_pressed(page, versioned) -> None:
    """The version is the row, not a field — and the dialog says what is true
    here rather than repeating p.76's "cannot easily be undone"."""
    open_history(page, versioned)
    rollback_button(page, 1).click()
    expect(page.get_by_role("heading", name="Roll back to v1")).to_be_visible()
    summary = page.get_by_test_id("rollback-summary")
    expect(summary).to_contain_text("as a new v4")
    expect(summary).to_contain_text("Nothing is deleted")
    # This dataset is built by a model, so p.74's sentence about the logic is
    # true of it and is shown.
    expect(summary).to_contain_text("next build")

    # The other pressable row gives the other answer, which is what says the
    # row reaches the dialog at all rather than a constant being drawn twice.
    page.get_by_role("button", name="Cancel").click()
    rollback_button(page, 2).click()
    expect(page.get_by_role("heading", name="Roll back to v2")).to_be_visible()


def test_rolling_back_brings_the_data_back(page, versioned) -> None:
    """**The assertion the placement exists for.** v1 has three rows and v2 has
    one; a rollback taken from v1's row that left the dataset at one row would
    have rolled back something other than what was pressed.

    Read from the server afterwards rather than from the screen: a table can be
    made to say anything, and what matters is what the dataset now holds.
    """
    open_history(page, versioned)
    assert dataset(versioned)["row_count"] == 2

    # v2, not v1: the row that is neither the newest nor the first is the only
    # one a build that ignored the press could not land on by luck.
    rollback_button(page, 2).click()
    page.get_by_test_id("rollback-confirm").click()
    # The dialog closes on success, and the history grows a row.
    expect(page.get_by_test_id("rollback-summary")).to_have_count(0)
    expect(page.get_by_test_id("rollback-version")).to_have_count(4)

    after = dataset(versioned)
    assert after["current_version"] == 4
    assert after["row_count"] == 1, "v2's single row, not v1's three"


def test_the_history_says_where_the_new_version_came_from(page, versioned) -> None:
    """Foundry crosses the skipped transactions out (p.70). This says the same
    thing forwards, which is what stops the new version reading as a build
    nobody can account for."""
    open_history(page, versioned)
    rollback_button(page, 2).click()
    page.get_by_test_id("rollback-confirm").click()
    expect(page.get_by_test_id("rollback-version")).to_have_count(4)

    expect(page.get_by_test_id("rolled-back-to")).to_have_count(1)
    expect(page.get_by_test_id("rolled-back-to")).to_have_text("→ v2")


def test_the_screen_you_were_reading_catches_up(page, versioned) -> None:
    """The preview is a different version's data now, and a tab still showing
    the old rows would be the §214 failure: a control that appears to have done
    nothing."""
    # **Read the preview first.** A tab that was never open fetches when it
    # mounts, so a build that invalidated nothing would still look right — the
    # claim is about a screen that already holds the *old* answer, so the test
    # has to make it hold one.
    page.goto(f"{WEB_BASE}/r/{versioned['resource_id']}?tab=preview")
    expect(page.locator("table.ds-table tbody tr")).to_have_count(2, timeout=30000)

    page.get_by_role("button", name="History").click()
    expect(page.get_by_test_id("rollback-version").first).to_be_visible()
    rollback_button(page, 1).click()
    page.get_by_test_id("rollback-confirm").click()
    expect(page.get_by_test_id("rollback-version")).to_have_count(4)

    page.get_by_role("button", name="Preview").click()
    expect(page.locator("table.ds-table tbody tr")).to_have_count(3)
