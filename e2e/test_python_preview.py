"""p.13-14's Preview, on a Python transform (§390).

    "a quick way to preview your code changes on real data" (p.13)
    "lets you run your code on a limited sample of the input datasets to
     quickly preview the code without committing your changes" (p.14)

One button, and until §390 it answered SQL and refused Python — decision 0004
confines customer Python to the runner task, so a Python preview cannot be an
HTTP response that waits. It is a queued row (db 0092) the panel watches.

The wording rules are in `apps/web/src/lib/preview-runs.test.ts`, what the job
does with a run is in `apps/worker/tests/test_code_preview_runs_job.py`, and
what the route will and will not queue is in
`apps/api/tests/test_transform_preview.py`. What needs a browser is the
**seam**: press the button on a `.py` file, and the rows arrive.

**This suite drives the worker itself**, for `test_tests_panel.py`'s reason and
in its shape: the dev stack runs no Dagster daemon, so a queued row would sit
there for ever. The op these tests call is the one the deployed schedule calls,
on the same row — what is skipped is the cron, not the work.
"""
from __future__ import annotations

import os
import sys
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import ADMIN_DSN, WEB_BASE, eventually

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "apps", "worker", "src",
    ),
)

#: More than one sample's worth, so "sampled" is a state the fixture reaches
#: rather than a flag nothing sets.
INPUT_ROWS = 1200


def transform(dataset: str, body: str) -> str:
    return (
        f"@transform(output='doubled', inputs={{'orders': '{dataset}'}})\n"
        f"def build(orders):\n{body}"
    )


# **A value that is in the first hundred rows, and could be nothing else.**
# The first version asserted on `id * 2` for a row in the middle of the input,
# which the panel never shows: a preview draws a hundred rows of the thousand
# it produced, so the assertion was about a cell that was correctly absent.
DOUBLES = (
    "    out = orders.copy()\n"
    "    out['doubled'] = out['id'] * 2\n"
    "    out['tag'] = 'marked-' + out['id'].astype(str)\n"
    "    return out\n"
)
RAISES = "    raise ValueError('the region column is missing')\n"


def work_the_queue() -> int:
    """One turn of the worker's poll, against the dev database.

    Imported inside the function rather than at module scope so a machine
    without the worker's dependencies fails on the test that needs them, naming
    the import, rather than failing to collect this file at all.

    **The worker has to be pointed at the API's bytes**, which is this suite's
    one real difference from `test_tests_panel.py`: a test run carries its own
    files and a preview reads *datasets*. Deployed, both sides are the same S3
    bucket; here the API writes under `STORAGE_ROOT` (`routes/datasets.py`) and
    `gateway_from_env` reads `LOCAL_STORAGE_ROOT`, defaulting to a directory
    nothing else uses. Left alone the poll finds every input missing and every
    preview ends `errored` - which reads as a bug in the job rather than as two
    environment variables that were never introduced.
    """
    from dagster import build_op_context

    from anchor_worker.jobs.code_preview_runs import run_queued_preview_runs
    from anchor_worker.resources import PlatformDatabase

    os.environ["LOCAL_STORAGE_ROOT"] = os.environ.get("STORAGE_ROOT", "/tmp/anchor-storage")
    os.environ.pop("DATA_BUCKET", None)

    # The app role, not the admin one: `rls_worker_for_workspace` (db 0006)
    # grants the worker's cross-workspace view to `platform_app`, and that is
    # the connection the deployed worker opens.
    dsn = ADMIN_DSN.replace("platform:devpass", "platform_app:devpass")
    context = build_op_context(resources={"platform_db": PlatformDatabase(dsn=dsn)})
    return run_queued_preview_runs(context)


def fixture(api, name: str) -> tuple[Module, dict, str]:
    """A project with one dataset and one repository. Returns both plus the
    dataset's name, which is what a declaration reads."""
    mod = Module(api, name)
    slug = f"orders_{mod.tag}"
    csv = b"id\n" + b"".join(f"{i}\n".encode() for i in range(INPUT_ROWS))
    api.upload_csv(f"{mod.base}/datasets/upload", slug, csv)
    repo = api.call("POST", f"{mod.base}/repositories", {"name": f"Transforms {mod.tag}"})
    return mod, repo, slug


def open_file(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def commit(api, mod: Module, repo: dict, files: dict[str, str]) -> None:
    api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "transform"},
    )


def test_a_python_transform_is_previewed_rather_than_refused(page, api) -> None:
    """**The seam, end to end**, and the sentence §390 exists to delete.

    The button queues a run (db 0092), the worker executes it in the process
    decision 0004 requires, and the panel - which polls, because a job's answer
    arrives in a table and there is nothing to push to it - draws the rows in
    the same table a SQL preview uses.
    """
    mod, repo, dataset = fixture(api, "Python preview")
    commit(api, mod, repo, {"src/build.py": transform(dataset, DOUBLES)})
    open_file(page, repo, "src/build.py")

    page.get_by_test_id("preview-run").click()
    # Queued, and saying so. A panel that showed an empty table here would be
    # reporting "it produced nothing", which is the one answer nobody has yet.
    expect(page.get_by_test_id("preview-status")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("preview-table")).to_have_count(0)

    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the preview up")

    expect(page.get_by_test_id("preview-table")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("preview-table")).to_contain_text("doubled")
    # The values, not just the column. A job that produced a file with the
    # right schema and never ran the body would pass on the header alone.
    expect(page.get_by_test_id("preview-table")).to_contain_text("marked-7")
    # And the status line stands down once there is a table to read.
    expect(page.get_by_test_id("preview-status")).to_have_count(0)


def test_the_count_says_it_came_from_a_sample(page, api) -> None:
    """1200 rows in, 1000 read, and the panel says so.

    `preview_transform`'s docstring is explicit that a count over a sample "is
    not the answer". The Python path reports the same thing; a number that
    looked whole would be §214 in numeric form - a control that appears to
    work, which is worse than one that is absent.
    """
    mod, repo, dataset = fixture(api, "Python preview sample")
    commit(api, mod, repo, {"src/build.py": transform(dataset, DOUBLES)})
    open_file(page, repo, "src/build.py")

    page.get_by_test_id("preview-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the preview up")
    expect(page.get_by_test_id("preview-table")).to_be_visible(timeout=30000)

    # 1000 rows produced from the sample, 100 of them on screen. Both numbers,
    # because they are different facts: one is about this table, the other is
    # about whether the total is real.
    expect(page.get_by_test_id("preview-rows")).to_contain_text("1,000 rows from the sample")
    expect(page.get_by_test_id("preview-rows")).to_contain_text("showing 100")
    expect(page.locator(".repo-preview-warning")).to_contain_text("not the answer")
    expect(page.locator(".repo-preview-warning")).to_contain_text("orders")


def test_a_transform_that_raises_says_what_it_said(page, api) -> None:
    """The author's answer about their own code. db 0092 keeps `failed` and
    `errored` apart precisely so this message reaches the person who can act on
    it, rather than becoming "the preview could not be run"."""
    mod, repo, dataset = fixture(api, "Python preview raises")
    commit(api, mod, repo, {"src/build.py": transform(dataset, RAISES)})
    open_file(page, repo, "src/build.py")

    page.get_by_test_id("preview-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the preview up")

    expect(page.get_by_test_id("preview-status")).to_contain_text(
        "region column is missing", timeout=30000
    )
    # No table, and this is the assertion that matters: a panel that drew an
    # empty result beside the failure would read as "it ran and produced
    # nothing", which is a different and wrong answer.
    expect(page.get_by_test_id("preview-table")).to_have_count(0)


def test_the_button_does_not_offer_a_second_press_while_one_is_in_flight(
    page, api
) -> None:
    """`MAX_QUEUED_PER_REPO` is two and it counts *queued* rows, so a button
    that went back to "Preview" the moment the request returned would invite a
    press the server refuses. The label is the state."""
    mod, repo, dataset = fixture(api, "Python preview button")
    commit(api, mod, repo, {"src/build.py": transform(dataset, DOUBLES)})
    open_file(page, repo, "src/build.py")

    button = page.get_by_test_id("preview-run")
    expect(button).to_have_text("Preview")
    button.click()
    expect(button).to_have_text("Running…", timeout=30000)
    expect(button).to_be_disabled()

    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the preview up")
    expect(button).to_have_text("Preview", timeout=30000)
    expect(button).to_be_enabled()


def test_it_says_what_the_change_would_do_to_the_dataset_it_writes(page, api) -> None:
    """p.14's other question, and the half a Python preview nearly shipped
    without.

    The transform declares the dataset the fixture already uploaded, and
    produces a different shape from it. A SQL preview answers this in its own
    response; a queued run cannot, so the read route computes it against the
    dataset as it stands - `engine.diff_schemas`, which is what migration 0018
    means by a schema change, rather than a second notion of one.
    """
    mod, repo, dataset = fixture(api, "Python preview drift")
    # Writes back to the dataset it reads, dropping `id` for a column that was
    # never there. The input is one column wide, so both halves are visible.
    source = (
        f"@transform(output='{dataset}', inputs={{'orders': '{dataset}'}})\n"
        "def build(orders):\n"
        "    out = orders.copy()\n"
        "    out['surcharge'] = out['id'] * 0.5\n"
        "    return out[['surcharge']]\n"
    )
    commit(api, mod, repo, {"src/drift.py": source})
    open_file(page, repo, "src/drift.py")

    page.get_by_test_id("preview-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the preview up")
    expect(page.get_by_test_id("preview-table")).to_be_visible(timeout=30000)

    drift = page.locator(".repo-preview-drift")
    expect(drift).to_contain_text(f"This would change {dataset}")
    expect(drift).to_contain_text("adds")
    expect(drift).to_contain_text("surcharge")
    expect(drift).to_contain_text("drops")
    expect(drift).to_contain_text("id")


def test_a_preview_of_a_new_dataset_shows_no_drift_block(page, api) -> None:
    """The counterweight, and the assertion that keeps the block meaningful:
    every column of a dataset that does not exist yet is "added", so a drift
    block over a first version is noise on the one preview where there is
    nothing to compare against."""
    mod, repo, dataset = fixture(api, "Python preview no drift")
    commit(api, mod, repo, {"src/build.py": transform(dataset, DOUBLES)})
    open_file(page, repo, "src/build.py")

    page.get_by_test_id("preview-run").click()
    eventually(work_the_queue, lambda n: n >= 1, what="the worker to pick the preview up")
    # Positive wait first (§318): the table is what says the run landed, and a
    # count of zero drift blocks before it would be true of a blank panel.
    expect(page.get_by_test_id("preview-table")).to_be_visible(timeout=30000)
    expect(page.locator(".repo-preview-drift")).to_have_count(0)


def test_a_sql_preview_still_answers_in_the_response(page, api) -> None:
    """**The half that did not change, asserted because it could have.**

    The two languages share every check before the fork - the declaration, the
    datasets, the sampling - so a mistake in the Python branch is a mistake in
    SQL's path to it. This is the differential: no worker turn, and the rows
    are there.
    """
    mod, repo, dataset = fixture(api, "SQL preview unchanged")
    sql = (
        "-- output: doubled\n"
        f"-- input: orders = {dataset}\n"
        "SELECT id, id * 2 AS doubled, 'marked-' || id AS tag FROM orders\n"
    )
    commit(api, mod, repo, {"src/build.sql": sql})
    open_file(page, repo, "src/build.sql")

    page.get_by_test_id("preview-run").click()
    expect(page.get_by_test_id("preview-table")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("preview-table")).to_contain_text("marked-7")
    # Named, unlike the Python path: a SQL preview knows which dataset the
    # alias resolved to, because it resolved it in the same request.
    expect(page.locator(".repo-preview-meta")).to_contain_text(f"orders = {dataset}")
