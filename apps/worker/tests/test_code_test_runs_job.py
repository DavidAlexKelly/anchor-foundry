"""The worker half of a unit test run (§294; db 0071).

`test_code_tests.py` holds what the runner produces. What needs a database is
the *job*: that a queued row is claimed exactly once, that its answer lands in
the shape the panel reads, and — the one that matters — that **a failing test
and a broken run end in different statuses**.

That distinction is `transform_runner.py`'s result-file rule arriving in the
schema, and it decides who goes looking when something is wrong. A run that
collapsed them would tell an author their tests failed every time the platform
could not start pytest.
"""
from __future__ import annotations

import json
import os
import sys
import uuid

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import anchor_worker.jobs.code_test_runs as code_test_runs  # noqa: E402
from anchor_worker.dataset_engine import DatasetEngineError  # noqa: E402
from anchor_worker.jobs.code_test_runs import run_queued_test_runs  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]

PASSING = {
    "src/daily.py": (
        "import anchor\n\n\n"
        '@anchor.transform(output="positive", inputs={"orders": "raw"})\n'
        "def build(orders):\n"
        "    return [row for row in orders if row > 0]\n"
    ),
    "tests/test_daily.py": (
        "from src.daily import build\n\n\n"
        "def test_drops_the_negatives():\n"
        "    assert build([-1, 2]) == [2]\n"
    ),
}


@pytest.fixture()
def repository():
    """One org/workspace/project/repository. No commits: a test run carries its
    own working set (db 0071), so there is nothing for a branch to hold."""
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"TestsOrg {tag}", f"tests-org-{tag}"),
        ).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role,
                                  cognito_sub, status)
               VALUES (%s,%s,%s,'owner',%s,'active') RETURNING id""",
            (org, f"tests-{tag}@example.com", "Tests", f"sub-tests-{tag}"),
        ).fetchone()[0]
        wid = uuid.uuid4()
        short = wid.hex[:12]
        conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                       pg_schema, search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (wid, org, f"W {tag}", f"w-{tag}", f"workspaces/w-{tag}/",
             f"ws_{short}", f"ws-{short}-", user),
        )
        pid = conn.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by) "
            "VALUES (%s,%s,%s,%s) RETURNING id",
            (wid, f"P {tag}", f"p-{tag}", user),
        ).fetchone()[0]
        rid = conn.execute(
            """INSERT INTO code_repos (project_id, name, slug, s3_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s) RETURNING id""",
            (pid, f"Transforms {tag}", f"transforms-{tag}",
             f"workspaces/w-{tag}/repos/{tag}/", user),
        ).fetchone()[0]
    return {"workspace_id": wid, "project_id": pid, "repo_id": rid, "user_id": user}


def queue(repository: dict, files: dict[str, str], branch: str = "main") -> uuid.UUID:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return conn.execute(
            """INSERT INTO code_test_runs (repo_id, branch, files, requested_by)
               VALUES (%s,%s,CAST(%s AS jsonb),%s) RETURNING id""",
            (repository["repo_id"], branch, json.dumps(files), repository["user_id"]),
        ).fetchone()[0]


def row(run_id: uuid.UUID) -> dict:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        got = conn.execute(
            "SELECT status, outcomes, error, started_at, finished_at "
            "  FROM code_test_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
    return {
        "status": got[0], "outcomes": got[1], "error": got[2],
        "started_at": got[3], "finished_at": got[4],
    }


def poll() -> int:
    """One turn of the worker's poll.

    The resource goes in the context and *not* also as a kwarg - Dagster
    refuses "resources in both context and kwargs", which is the shape
    `test_export_schedules.py` already uses.
    """
    context = build_op_context(resources={"platform_db": PlatformDatabase(dsn=APP_DSN)})
    return run_queued_test_runs(context)


def test_a_queued_run_is_picked_up_and_answered(repository) -> None:
    run_id = queue(repository, PASSING)
    assert poll() >= 1

    got = row(run_id)
    assert got["status"] == "succeeded"
    assert got["error"] is None
    assert got["started_at"] is not None and got["finished_at"] is not None
    (outcome,) = got["outcomes"]
    assert outcome["id"] == "tests/test_daily.py::test_drops_the_negatives"
    assert outcome["outcome"] == "passed"


def test_a_failing_test_ends_failed_with_its_outcomes(repository) -> None:
    """The author's answer, and it has to carry the failure with it - a status
    with no outcomes would tell somebody their tests failed and not which."""
    run_id = queue(repository, {"tests/test_it.py": "def test_it():\n    assert 3 == 4\n"})
    poll()

    got = row(run_id)
    assert got["status"] == "failed"
    assert got["error"] is None, "a failing test is a result, not an error"
    (outcome,) = got["outcomes"]
    assert outcome["outcome"] == "failed"
    assert outcome["message"] == "assert 3 == 4"


def test_a_run_that_could_not_happen_ends_errored_and_not_failed(
    repository, monkeypatch
) -> None:
    """**The distinction the whole job is built around.**

    pytest missing, a time limit, a report that will not parse: none of these
    is an answer about the author's code, and a status that said `failed` would
    send them looking at tests that never ran.
    """
    def refuse(files, timeout_s=None):
        raise DatasetEngineError("the tests exceeded the 300s time limit")

    monkeypatch.setattr(code_test_runs, "run_python_tests", refuse)
    run_id = queue(repository, PASSING)
    poll()

    got = row(run_id)
    assert got["status"] == "errored"
    assert got["outcomes"] is None, "there is no answer about their code here"
    assert "time limit" in got["error"]


def test_a_repository_with_no_tests_does_not_end_succeeded(repository) -> None:
    """"Nothing failed" and "everything passed" are the same number, and only
    one of them is true. `code-repositories.md` §10 names this feature
    specifically: a suite that cannot fail is not accepted."""
    run_id = queue(repository, {"src/daily.py": PASSING["src/daily.py"]})
    poll()

    got = row(run_id)
    assert got["status"] == "failed"
    assert got["outcomes"] == []


def test_a_run_is_claimed_once_even_when_two_workers_found_it(repository) -> None:
    """**Two workers polling the same minute must not both run it.**

    The claim is the `status = 'queued'` in the UPDATE's WHERE: whoever lands
    first gets the row, and the other's UPDATE matches nothing and returns no
    row. `_run_one` says so by returning False.

    **Called directly, twice, and a survivor is why.** The first version of
    this polled twice and asserted the answer did not change - which it cannot,
    because `list_queued_test_runs()` only returns queued rows, so the second
    poll never saw the finished one at all. The claim was doing nothing the
    discovery filter was not already doing, in *that* test. It is doing
    something here, which is the case it exists for: both workers discovered
    the row while it was still queued, and only one may act on it.
    """
    run_id = queue(repository, PASSING)
    db = PlatformDatabase(dsn=APP_DSN)
    context = build_op_context(resources={"platform_db": db})

    first = code_test_runs._run_one(context, db, run_id, repository["workspace_id"])
    second = code_test_runs._run_one(context, db, run_id, repository["workspace_id"])
    assert first is True
    assert second is False, "the second worker ran a row the first had claimed"

    got = row(run_id)
    assert got["status"] == "succeeded"
    assert len(got["outcomes"]) == 1


def test_a_candidate_that_blows_up_outside_the_run_does_not_end_the_batch(
    repository, monkeypatch
) -> None:
    """§263's lesson, at the level it actually applies.

    **A survivor found that the earlier version of this tested the wrong
    handler.** It made `run_python_tests` raise, which `_run_one` catches
    itself and records as `errored` - so the op's own `except` was never
    reached and could be narrowed to `ZeroDivisionError` with nothing noticing.
    What that handler is for is a candidate failing *outside* `_run_one`
    entirely: a connection that will not open, a row that vanished. So this
    breaks `_run_one`.
    """
    first = queue(repository, PASSING)
    second = queue(repository, PASSING)

    real = code_test_runs._run_one
    seen: list = []

    def explode_once(context, db, run_id, workspace_id):
        seen.append(run_id)
        if len(seen) == 1:
            raise RuntimeError("the connection went away")
        return real(context, db, run_id, workspace_id)

    monkeypatch.setattr(code_test_runs, "_run_one", explode_once)
    poll()

    assert len(seen) == 2, "the second candidate never got its turn"
    # The one that got through has an answer; the one that blew up is still
    # queued, which is right - nothing ran it, so nothing may claim it did.
    statuses = {row(first)["status"], row(second)["status"]}
    assert statuses == {"queued", "succeeded"}, statuses


def test_a_run_that_raised_something_unexpected_is_errored_not_lost(
    repository, monkeypatch
) -> None:
    """`_run_one`'s own defensive handler. Whatever went wrong inside the run,
    the row gets an answer - a queued row nobody will ever pick up again is
    worse than a bad answer, because the panel polls it for ever."""
    run_id = queue(repository, PASSING)

    def explode(files, timeout_s=None):
        raise RuntimeError("something inside the run")

    monkeypatch.setattr(code_test_runs, "run_python_tests", explode)
    poll()

    got = row(run_id)
    assert got["status"] == "errored"
    assert "could not run these tests" in got["error"]
