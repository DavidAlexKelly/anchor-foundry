"""A job's detail, on the screen (§507; `dataset-preview` p.3).

> "Upon selection, a detailed Job view appears on the right showing detailed
> job information, including progress, specification, build logs, files and
> the resulting schema." (p.3)

The build log is `test_model_run_logs.py`'s. What is here is the rest of
p.3's list, and the one claim a browser can make that the API suite cannot:
that opening an **older** run shows the code *it* ran, after the model has
been edited, on the same screen that shows today's model.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from conftest import ADMIN_DSN, WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def built(api):
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call("POST", f"/workspaces/{workspace['id']}/projects",
                       {"name": f"Jobs {tag}", "slug": f"jobs-{tag}"})
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    source = api.upload_csv(f"{base}/datasets/upload", f"Src {tag}", ROWS)
    model = api.call("POST", f"{base}/models", {
        "name": f"Shaper {tag}", "language": "sql", "code": "SELECT id, val FROM t",
        "inputs": [{"dataset_id": source["id"], "input_alias": "t"}]})
    api.call("POST", f"{base}/models/{model['id']}/run")
    api.call("PATCH", f"{base}/models/{model['id']}", {"code": "SELECT id FROM t WHERE id > 1"})
    api.call("POST", f"{base}/models/{model['id']}/run")
    runs = api.call("GET", f"{base}/models/{model['id']}/runs")
    broken = api.call("POST", f"{base}/models", {
        "name": f"Broken {tag}", "language": "sql", "code": "SELECT nope FROM t",
        "inputs": [{"dataset_id": source["id"], "input_alias": "t"}]})
    api.call("POST", f"{base}/models/{broken['id']}/run")
    # A run from before model versions: its version is not recorded.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE model_runs SET model_version = NULL WHERE model_id = %s",
                     (broken["id"],))
    return {"tag": tag, "workspace_slug": workspace["slug"], "project_slug": project["slug"],
            "source": source, "newer": runs[0]["id"], "older": runs[1]["id"]}


def open_runs(page, built, model_name: str) -> None:
    page.goto(f"{WEB_BASE}/{built['workspace_slug']}/{built['project_slug']}/models")
    row = page.locator("tr").filter(has_text=f"{model_name} {built['tag']}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_test_id("model-runs").click()
    expect(page.get_by_test_id("run-row").first).to_be_visible()


def open_run(page, run_id: str) -> None:
    page.locator(f'[data-testid="run-row"][data-run-id="{run_id}"]') \
        .get_by_test_id("open-run").click()


def test_a_run_shows_its_progress_code_files_and_schema(page, built) -> None:
    open_runs(page, built, "Shaper")
    open_run(page, built["older"])
    progress = page.get_by_test_id("job-progress")
    expect(progress).to_contain_text("after waiting")
    expect(progress).to_contain_text("succeeded, after running")
    spec = page.get_by_test_id("job-specification")
    expect(spec).to_contain_text(f"Version 1 · sql · reads t (Src {built['tag']})")
    expect(page.get_by_test_id("job-code")).to_have_text("SELECT id, val FROM t")
    output = page.get_by_test_id("job-output")
    expect(output).to_contain_text("Wrote version 1, 3 rows: data.parquet (")
    expect(output).not_to_contain_text("gone from storage")
    columns = page.get_by_test_id("job-schema").locator("li")
    expect(columns).to_have_count(2)
    expect(columns.nth(0)).to_contain_text("id")
    expect(columns.nth(1)).to_contain_text("val")


def test_an_older_run_shows_the_code_it_ran_not_today_s(page, built) -> None:
    """The model has been edited since the first run. Each run shows its own."""
    open_runs(page, built, "Shaper")
    open_run(page, built["newer"])
    expect(page.get_by_test_id("job-code")).to_have_text("SELECT id FROM t WHERE id > 1")
    expect(page.get_by_test_id("job-output")).to_contain_text("Wrote version 2, 2 rows")
    expect(page.get_by_test_id("job-schema").locator("li")).to_have_count(1)
    open_run(page, built["newer"])  # close
    open_run(page, built["older"])
    expect(page.get_by_test_id("job-code")).to_have_text("SELECT id, val FROM t")


def test_a_failed_old_run_says_why_each_part_is_missing(page, built) -> None:
    open_runs(page, built, "Broken")
    page.get_by_test_id("run-row").first.get_by_test_id("open-run").click()
    expect(page.get_by_test_id("job-no-specification")).to_have_text(
        "This run is older than model versions, so the code it ran was not recorded.")
    expect(page.get_by_test_id("job-no-output")).to_have_text(
        "No output: this run failed, so it wrote no version.")
    expect(page.get_by_test_id("job-progress")).to_contain_text("failed, after running")
