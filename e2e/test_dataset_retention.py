"""A dataset's retention policy, on its History tab (§966; decision 0005).

Which versions a policy removes is the API's and the database's
(`apps/api/tests/test_dataset_retention.py`, `apps/worker/tests/
test_dataset_retention.py`), and the wording is `lib/dataset-retention.ts`'s.
What needs a browser is the order the decision asks for - what a policy would
remove is on the screen before it is saved - and that a version whose data
was removed reads as removed, with nothing on its row offering to read it.
"""
from __future__ import annotations

import psycopg
from playwright.sync_api import expect

from conftest import ADMIN_DSN
from test_dataset_rollback import open_history, versioned  # noqa: F401 (fixture)


def test_a_policy_is_previewed_saved_and_cleared(page, versioned) -> None:
    open_history(page, versioned)
    text = page.get_by_test_id("retention-text")
    expect(text).to_contain_text("Every version is kept")

    page.get_by_test_id("retention-keep").fill("1")
    # Said before it is saved.
    expect(page.get_by_test_id("retention-preview")).to_contain_text(
        "Keeping the newest 1 version would remove v1, v2")
    expect(text).to_contain_text("Every version is kept")

    page.get_by_test_id("retention-save").click()
    expect(text).to_contain_text("The newest 1 version is kept")
    expect(page.get_by_test_id("retention-tonight")).to_contain_text("Tonight v1, v2")
    detail = versioned["api"].call(
        "GET", f"{versioned['base']}/datasets/{versioned['dataset_id']}")
    assert detail["retention_versions"] == 1

    page.get_by_test_id("retention-clear").click()
    expect(text).to_contain_text("Every version is kept")
    expect(page.get_by_test_id("retention-tonight")).to_have_count(0)


def test_a_removed_version_reads_as_removed_and_offers_nothing(page, versioned) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET expired_at = now()"
                     " WHERE dataset_id = %s AND version_number = 1", (versioned["dataset_id"],))
    open_history(page, versioned)
    expect(page.get_by_test_id("expired-version")).to_have_count(1)
    said = "this version's data was removed by the retention policy"
    for action in ("rollback-version", "branch-version"):
        button = page.locator(f"[data-testid='{action}'][data-version='1']")
        expect(button).to_be_disabled()
        expect(button).to_have_attribute("title", said)
    # And the one that was kept still offers itself.
    expect(page.locator("[data-testid='rollback-version'][data-version='2']")).to_be_enabled()
