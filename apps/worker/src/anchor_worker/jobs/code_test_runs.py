"""Running a repository's queued unit tests (§294; db 0071).

**This job exists because the API must not do this.** Running a repository's
unit tests is running customer Python, and
`docs/decisions/0004-running-customer-code.md` confines that to a process that
cannot obtain the platform's credentials. §286's Problems panel could answer
from the API because it parses and reads names and executes nothing; a test
runs. So the API writes a queued row and this picks it up — the same
discover-then-verify shape every other job here uses.

**The distinction this job's whole error handling is built around** is the one
`transform_runner.py` keeps with `result.json`, and db 0071 keeps in the status
column: *a failing test and a broken run are different problems.* Tests that ran
and did not pass are `failed`, with their outcomes; a run that could not happen
is `errored`, with a sentence about the platform. Only the first is an answer
about the author's code, and collapsing them would send the wrong person
looking every time.

Note: deliberately no `from __future__ import annotations` here - see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
from dataclasses import asdict
from datetime import datetime, timezone

from dagster import OpExecutionContext, job, op

from ..dataset_engine import DatasetEngineError
from ..python_sandbox import run_python_tests
from ..resources import PlatformDatabase


def _files(value):
    """The stored working set as a dict whichever way the driver returned it.

    Same normalisation `export_schedules._json` makes, and for the same reason
    it gives: a caller that forgot would get `"{}".get(...)`, an AttributeError
    a long way from its cause.
    """
    if isinstance(value, str):
        return json.loads(value or "{}")
    return value or {}


@op
def run_queued_test_runs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT run_id, workspace_id FROM list_queued_test_runs()")
            candidates = cur.fetchall()

    ran = 0
    for run_id, workspace_id in candidates:
        try:
            if _run_one(context, platform_db, run_id, workspace_id):
                ran += 1
        except Exception as exc:  # pragma: no cover - one run must not end the op
            # The §263 lesson: whatever went wrong outside the run itself, the
            # next candidate still gets its turn.
            context.log.warning("test run %s could not be processed: %s", run_id, exc)
    return ran


def _run_one(context, platform_db, run_id, workspace_id) -> bool:
    """One run, start to finish. Returns whether it ran at all."""
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            # **Claimed, not just read.** Two workers polling the same minute
            # would otherwise both run the same tests and both write an answer.
            # The `status = 'queued'` in the WHERE is the claim: whoever's
            # UPDATE lands first gets the row, and the other sees no row and
            # moves on.
            cur.execute(
                """
                UPDATE code_test_runs
                   SET status = 'running', started_at = now()
                 WHERE id = %s AND status = 'queued'
             RETURNING files
                """,
                (str(run_id),),
            )
            claimed = cur.fetchone()
            if claimed is None:
                return False
            (raw_files,) = claimed
        conn.commit()

        files = _files(raw_files)
        try:
            report = run_python_tests(files)
        except DatasetEngineError as exc:
            # The run did not happen. Not the author's answer, so not `failed`.
            _finish(conn, run_id, status="errored", outcomes=None, error=str(exc)[:1000])
            context.log.warning("test run %s could not run: %s", run_id, exc)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            _finish(
                conn, run_id, status="errored", outcomes=None,
                error=f"the platform could not run these tests: {exc}"[:1000],
            )
            return True

        # **An empty report is `failed`, not `succeeded`.** A repository with no
        # tests has nothing failing in it, and `TestReport.ok` says so; writing
        # 'succeeded' here would be the green-suite-that-ran-nothing this
        # feature is written against. db 0071's terminal-has-an-answer
        # constraint keeps the row honest either way.
        outcomes = [asdict(o) for o in report.outcomes]
        _finish(
            conn, run_id,
            status="succeeded" if report.ok else "failed",
            outcomes=outcomes,
            error=None,
        )
        context.log.info(
            "test run %s: %s passed, %s failed, %s skipped",
            run_id, report.passed, report.failed, report.skipped,
        )
        return True


def _finish(conn, run_id, *, status, outcomes, error) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE code_test_runs
               SET status = %s,
                   outcomes = CAST(%s AS jsonb),
                   error = %s,
                   finished_at = %s
             WHERE id = %s
            """,
            (
                status,
                None if outcomes is None else json.dumps(outcomes),
                error,
                datetime.now(timezone.utc),
                str(run_id),
            ),
        )
    conn.commit()


@job
def scheduled_test_runs():
    run_queued_test_runs()

