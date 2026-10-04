"""Forget Dagster's own record of finished runs (§883).

Every poll is a Dagster run, and the schedules start about 5,500 a day: three
every minute and five every five minutes. Each one leaves its events in
Dagster's storage and a directory of step outputs on the task's disk, and
nothing removed either. §883 measured about 35 KB a run with the consolidated
event log (`apps/worker/dagster.yaml`) and 150 KB without it. Unpruned, that
is a disk the task shares with the S3 cache and DuckDB's spill filling in
months, or in weeks.

So once an hour, finished runs older than a day are deleted, failed ones
after a week: long enough to look at a failure, which also reaches the
platform's own tables and the logs. Deleting a run removes its events, and
the freed pages are reused, so the event log stays at about a day's size.
The run's output directory is removed here, because Dagster leaves it.
"""
import os
import re
import shutil
from datetime import datetime, timedelta, timezone

from dagster import DagsterRunStatus, OpExecutionContext, RunsFilter, job, op

KEEP_SUCCEEDED = timedelta(days=1)
KEEP_FAILED = timedelta(days=7)
#: Runs deleted per pass. The first pass on a full disk can have days of them;
#: the rest wait for the next hour rather than holding this one open.
PER_PASS = 2000
_RUN_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


@op
def prune_dagster_runs(context: OpExecutionContext) -> int:
    instance = context.instance
    now = _now()
    doomed: list[str] = []
    for statuses, keep in (
        ([DagsterRunStatus.SUCCESS], KEEP_SUCCEEDED),
        ([DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED], KEEP_FAILED),
    ):
        records = instance.get_run_records(
            filters=RunsFilter(statuses=statuses, updated_before=now - keep),
            limit=PER_PASS - len(doomed),
        )
        doomed += [r.dagster_run.run_id for r in records]
    storage = instance.storage_directory()
    for run_id in doomed:
        instance.delete_run(run_id)
        outputs = os.path.join(storage, run_id)
        if _RUN_ID.match(run_id) and os.path.isdir(outputs):
            shutil.rmtree(outputs, ignore_errors=True)
    context.log.info("forgot %d finished runs", len(doomed))
    return len(doomed)


@job
def dagster_run_pruning():
    prune_dagster_runs()
