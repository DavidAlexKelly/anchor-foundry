"""What a model run printed, on the screen (parity `datasets-lineage.md` §1.3;
Foundry `dataset-preview` p.3).

> "On the left panel, a list of jobs appears with their statuses and durations.
>  Upon selection, a detailed Job view appears on the right showing detailed
>  job information, including progress, specification, **build logs**, files and
>  the resulting schema." (p.3)

Whether a run's output is captured and stored is the worker's
(`apps/worker/tests/test_model_runs.py`); what the endpoint says when asked for
one is the API's (`apps/api/tests/test_models.py`). What needs a browser is the
half neither can show: that a person can **get to** a past run at all.
`modelApi.runs` had existed since the models layer was written and nothing on
the front end had ever called it, so the last run's status badge was the whole
of a model's history.

**The rows are seeded through the database, and that is not a shortcut.** A
Python run is *queued* by the API and executed by the worker, and the browser
stack runs no worker — so a run started here would sit in 'queued' forever and
never produce the thing this file is about. `e2e/api.py` reaches past the API
in exactly one other place for exactly this kind of reason, and says so there.
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from conftest import ADMIN_DSN, WEB_BASE

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/tmp/anchor-storage")
ROWS = b"id,val\n1,10\n2,20\n"


def _seed_run(model_id: str, *, status: str, log_key: str | None,
              error: str | None = None, seconds: float = 2.0,
              minutes_ago: int = 0) -> str:
    """One finished run.

    `minutes_ago` is load-bearing rather than decoration: the list is ordered
    by `queued_at DESC`, and three rows written in the same instant come back
    in whatever order the database felt like — which is a test that passes
    until it does not.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return str(conn.execute(
            "INSERT INTO model_runs (model_id, status, trigger_kind, queued_at, "
            "started_at, finished_at, rows_produced, error_message, log_s3_key) "
            "VALUES (%s, %s, 'manual', now() - (%s || ' minutes')::interval, "
            "now() - (%s || ' minutes')::interval, "
            "now() - (%s || ' minutes')::interval + (%s || ' seconds')::interval, "
            "%s, %s, %s) RETURNING id",
            (model_id, status, minutes_ago, minutes_ago, minutes_ago, seconds,
             2 if status == "succeeded" else None, error, log_key),
        ).fetchone()[0])


def _write_log(workspace_slug: str, text: str) -> str:
    key = f"workspaces/{workspace_slug}/runs/{uuid.uuid4()}/log.txt"
    path = os.path.join(STORAGE_ROOT, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as handle:
        handle.write(text)
    return key


@pytest.fixture(scope="module")
def logged(api):
    """A Python model with three runs: one that printed, one that failed after
    printing, and one that printed nothing.

    Three because the interesting claim is that they read *differently* — a
    dialog that showed the same thing for all three would satisfy any one of
    them on its own.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Logs {tag}", "slug": f"logs-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    source = api.upload_csv(f"{base}/datasets/upload", f"Src {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Printer {tag}", "language": "python",
        "code": "print('rows in:', len(t))\noutput = t.copy()",
        "inputs": [{"dataset_id": source["id"], "input_alias": "t"}],
    })
    sql_model = api.call("POST", f"{base}/models", {
        "name": f"Quiet SQL {tag}", "language": "sql",
        "code": "SELECT id FROM t",
        "inputs": [{"dataset_id": source["id"], "input_alias": "t"}],
    })
    slug = workspace["slug"]
    printed = _seed_run(model["id"], status="succeeded",
                        log_key=_write_log(slug, "rows in: 2\n"),
                        seconds=1.5, minutes_ago=1)
    failed = _seed_run(
        model["id"], status="failed",
        log_key=_write_log(slug, "before the fall\n\n--- stderr ---\nboom\n"),
        error="ZeroDivisionError: division by zero", seconds=0.4, minutes_ago=2,
    )
    quiet = _seed_run(model["id"], status="succeeded", log_key=None,
                      seconds=3.0, minutes_ago=3)
    _seed_run(sql_model["id"], status="succeeded", log_key=None, seconds=1.0)
    return {"tag": tag, "workspace_slug": slug, "project_slug": project["slug"],
            "printed": printed, "failed": failed, "quiet": quiet}


def run_row(page, run_id: str):
    """One run's row, by its id.

    By id rather than by position: which row is first is the server's ordering,
    and a test that encodes it is testing the fixture's insertion order.
    """
    return page.locator(f'[data-testid="run-row"][data-run-id="{run_id}"]')


def open_runs(page, logged, model_name: str) -> None:
    page.goto(f"{WEB_BASE}/{logged['workspace_slug']}/{logged['project_slug']}/models")
    row = page.locator("tr").filter(has_text=f"{model_name} {logged['tag']}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_test_id("model-runs").click()
    expect(page.get_by_test_id("run-row").first).to_be_visible()


def test_a_model_has_a_run_history_at_all(page, logged) -> None:
    """The endpoint existed and nothing called it, so a model's past runs were
    unreachable — the status badge for the latest one was the whole record."""
    open_runs(page, logged, "Printer")
    expect(page.get_by_test_id("run-row")).to_have_count(3)
    # Statuses and durations, which is what p.3 says the list is for.
    assert {r.get_attribute("data-run-status") for r in
            page.get_by_test_id("run-row").all()} == {"succeeded", "failed"}
    expect(run_row(page, logged["printed"]).get_by_test_id("run-duration")).to_have_text("1.5s")
    expect(run_row(page, logged["quiet"]).get_by_test_id("run-duration")).to_have_text("3.0s")
    # Newest first, which is what "every run, newest first" promises.
    assert page.get_by_test_id("run-row").first.get_attribute("data-run-id") == logged["printed"]


def test_opening_a_run_shows_what_it_printed(page, logged) -> None:
    """p.3's job detail, and the reason any of this was built."""
    open_runs(page, logged, "Printer")
    run_row(page, logged["printed"]).get_by_test_id("open-run").click()
    expect(page.get_by_test_id("run-log")).to_contain_text("rows in: 2")


def test_a_failed_run_shows_its_output_and_its_error_separately(page, logged) -> None:
    """**A log is not a summary.** `error_message` is one line and is what the
    list view shows; the log is everything the transform said before it got
    there, and collapsing the two would lose whichever the reader needed."""
    open_runs(page, logged, "Printer")
    run_row(page, logged["failed"]).get_by_test_id("open-run").click()
    expect(page.get_by_test_id("run-error")).to_contain_text("ZeroDivisionError")
    log = page.get_by_test_id("run-log")
    expect(log).to_contain_text("before the fall")
    expect(log).to_contain_text("--- stderr ---")


def test_a_run_that_printed_nothing_says_which_kind_of_nothing(page, logged) -> None:
    """**§214's half of the feature.** The control is absent with a reason
    rather than present and empty, and the reason is specific: this one printed
    nothing, which is a different answer from a SQL model that never could."""
    open_runs(page, logged, "Printer")
    run_row(page, logged["quiet"]).get_by_test_id("open-run").click()
    expect(page.get_by_test_id("run-no-log")).to_contain_text("printed nothing")
    expect(page.get_by_test_id("run-log")).to_have_count(0)


def test_a_sql_model_is_told_apart_from_one_that_printed_nothing(page, logged) -> None:
    """The distinction the sentence exists for: one says come back after adding
    a print, the other says there is nowhere to put one."""
    open_runs(page, logged, "Quiet SQL")
    page.get_by_test_id("run-row").first.get_by_test_id("open-run").click()
    expect(page.get_by_test_id("run-no-log")).to_contain_text("query, not a program")
