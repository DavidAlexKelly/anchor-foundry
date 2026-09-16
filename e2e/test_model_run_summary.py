"""p.3's Summary view (parity `datasets-lineage.md` §1.3; Foundry
`dataset-preview` p.3).

> "The History tab view provides historical job (build) information. A
>  **Summary view** on the right side of the page shows aggregated information
>  on job statuses over time." (p.3)

What the counts are is `apps/api/tests/test_models.py`'s, and which days a
window covers is `apps/web/src/lib/run-summary.test.ts`'s — both cheap to make
fail. What needs a browser is the part neither can show: that the aggregate is
**drawn**, and that a model with nothing to aggregate says so in words instead
of drawing thirty empty bars (§214).

Seeded through the database for `test_model_run_logs`'s reason: a run is queued
by the API and executed by the worker, the browser stack runs no worker, and a
summary "over time" needs runs spread across a window that no test can wait
for.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from conftest import ADMIN_DSN, WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


def _run_on(model_id: str, *, status: str, days_ago: int) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO model_runs (model_id, status, trigger_kind, queued_at) "
            "VALUES (%s, %s, 'manual', now() - (%s || ' days')::interval)",
            (model_id, status, days_ago),
        )


@pytest.fixture(scope="module")
def summarised(api):
    """Two models: one with runs spread over the window, one with none.

    Two because the interesting claim is that they read *differently* — a
    screen that drew the same thing for both would satisfy either on its own.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Summary {tag}", "slug": f"summary-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    source = api.upload_csv(f"{base}/datasets/upload", f"Src {tag}", ROWS)
    busy = api.call("POST", f"{base}/models", {
        "name": f"Busy {tag}", "code": "SELECT id FROM t",
        "inputs": [{"dataset_id": source["id"], "input_alias": "t"}],
    })
    api.call("POST", f"{base}/models", {
        "name": f"Idle {tag}", "code": "SELECT id FROM t",
        "inputs": [{"dataset_id": source["id"], "input_alias": "t"}],
    })
    _run_on(busy["id"], status="succeeded", days_ago=1)
    _run_on(busy["id"], status="succeeded", days_ago=1)
    _run_on(busy["id"], status="failed", days_ago=1)
    _run_on(busy["id"], status="succeeded", days_ago=4)
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"]}


def open_runs(page, summarised, model_name: str) -> None:
    page.goto(f"{WEB_BASE}/{summarised['workspace_slug']}/{summarised['project_slug']}/models")
    row = page.locator("tr").filter(has_text=f"{model_name} {summarised['tag']}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_test_id("model-runs").click()
    expect(page.get_by_test_id("run-summary")).to_be_visible()


def test_the_summary_draws_a_bar_for_every_day_of_the_window(page, summarised) -> None:
    """**The gaps are the point.** Only two days had runs; a chart of two bars
    would tell a reader the model ran steadily."""
    open_runs(page, summarised, "Busy")
    expect(page.get_by_test_id("summary-day")).to_have_count(30)
    totals = [
        int(b.get_attribute("data-total") or "0")
        for b in page.get_by_test_id("summary-day").all()
    ]
    assert sum(totals) == 4, totals
    # Two busy days and twenty-eight quiet ones, which is what "over time"
    # means and a pair of bars does not.
    assert sorted(t for t in totals if t) == [1, 3], totals


def test_the_busiest_day_carries_its_own_counts(page, summarised) -> None:
    """Yesterday had two successes and a failure; four days back had one."""
    open_runs(page, summarised, "Busy")
    bars = {
        b.get_attribute("data-day"): int(b.get_attribute("data-total") or "0")
        for b in page.get_by_test_id("summary-day").all()
    }
    assert sorted(day for day, total in bars.items() if total == 3), bars
    # The last bar is today, which had no runs — the window ends at now, not at
    # the last thing that happened.
    assert list(bars.values())[-1] == 0, bars


def test_a_model_that_has_not_run_says_so_in_words(page, summarised) -> None:
    """**§214's half.** Thirty empty bars say "this failed thirty times to run"
    as readily as "nothing happened", and a reader cannot tell which."""
    open_runs(page, summarised, "Idle")
    expect(page.get_by_test_id("summary-empty")).to_contain_text("has not run in the last 30 days")
    expect(page.get_by_test_id("summary-day")).to_have_count(0)


def test_the_window_named_on_the_screen_is_the_one_that_was_counted(page, summarised) -> None:
    """§323's rule: a screen that hard-codes "30 days" is one that lies the day
    the constant moves, so the number comes back with the answer."""
    open_runs(page, summarised, "Busy")
    expect(page.get_by_test_id("run-summary")).to_contain_text("Last 30 days")


def test_a_failed_day_is_drawn_as_failed(page, summarised) -> None:
    """A summary of "job statuses" that drew one colour would be a summary of
    job counts."""
    open_runs(page, summarised, "Busy")
    failed = page.get_by_test_id("summary-failed")
    heights = [
        (f.get_attribute("style") or "") for f in failed.all()
    ]
    assert any("height: 33" in h for h in heights), heights
