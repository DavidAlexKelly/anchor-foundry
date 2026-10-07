"""Dagster entrypoint. The single registration point for every job/schedule
this worker runs."""
from __future__ import annotations

import os
from urllib.parse import quote

from dagster import (
    DagsterRunStatus,
    DefaultScheduleStatus,
    Definitions,
    RunsFilter,
    ScheduleDefinition,
    ScheduleEvaluationContext,
)

from .jobs.cleanup import workspace_cleanup
from .jobs.code_preview_runs import scheduled_preview_runs
from .jobs.code_test_runs import scheduled_test_runs
from .jobs.dagster_runs import dagster_run_pruning
from .jobs.export_schedules import scheduled_exports
from .jobs.instance_syncs import scheduled_instance_syncs
from .jobs.listener_archives import scheduled_listener_archives
from .jobs.model_runs import scheduled_model_runs
from .jobs.sync_configs import scheduled_connection_syncs
from .resources import PlatformDatabase


def _resolve_database_url() -> str:
    """WORKER_DATABASE_URL is set directly for local dev/tests. The deployed
    stack instead sets DATABASE_HOST (plain) plus DATABASE_USERNAME/
    DATABASE_PASSWORD (Secrets Manager-backed) — the password never gets
    embedded in a pre-built URL at the CDK level, so it's assembled here."""
    url = os.environ.get("WORKER_DATABASE_URL", "")
    if url:
        return url
    host = os.environ.get("DATABASE_HOST", "")
    username = os.environ.get("DATABASE_USERNAME", "")
    password = os.environ.get("DATABASE_PASSWORD", "")
    if not (host and username and password):
        return ""
    port = os.environ.get("DATABASE_PORT", "5432")
    name = os.environ.get("DATABASE_NAME", "platform")
    return f"postgresql://{username}:{quote(password, safe='')}@{host}:{port}/{name}?sslmode=require"

#: **Every schedule starts running (§883).** Dagster's default is stopped,
#: until somebody turns a schedule on in its web UI. That UI was never
#: reachable on a deployed stack, and whatever it had turned on lived on the
#: task's disk, which a deploy replaces. So no deployed worker ran a scheduled
#: sync, model run, export, test or preview run, listener archive or cleanup.
#: The browser suite drives the ops directly, so nothing saw it.
RUNNING = DefaultScheduleStatus.RUNNING

#: A run that has not finished: queued, launched, or going.
UNFINISHED = [DagsterRunStatus.QUEUED, DagsterRunStatus.NOT_STARTED,
              DagsterRunStatus.STARTING, DagsterRunStatus.STARTED]


#: The tag the worker's instance limits (§894; `apps/worker/dagster.yaml`).
WEIGHT_TAG = "anchor/weight"
#: Jobs that read and write datasets with DuckDB in the worker's own process.
#: Test and preview runs send their code to the transform runner, and the
#: archive and the cleanups move little; those are not limited by this.
HEAVY = {WEIGHT_TAG: "heavy"}


def one_at_a_time(job_name: str, at_most: int = 1):
    """**A tick is skipped while the job's last run has not finished
    (§888).** A poll runs every minute and works through everything due, so
    one that outlasts its minute - a model run, a large sync - had a second
    pass start beside it, then a third. The claims (§853, §854) keep them
    from doing the same work twice. Memory was the problem: each pass is a
    process with its own DuckDB, up to 512 MiB (§875), and a 2 GB worker
    holds about three. The next tick after the run finishes picks up
    whatever is still due.

    `at_most` is for the one job that must not wait behind itself (§902): a
    model pass works through its queue in order, and a Python model waits up
    to fifteen minutes on the transform runner, so with one pass a SQL model
    somebody has just asked for waited behind it. Two passes keep one free.
    The instance's limit on heavy runs still holds the memory."""

    def should_execute(context: ScheduleEvaluationContext) -> bool:
        return len(context.instance.get_run_records(
            filters=RunsFilter(job_name=job_name, statuses=UNFINISHED), limit=at_most)) < at_most

    return should_execute

defs = Definitions(
    jobs=[
        dagster_run_pruning,
        workspace_cleanup,
        scheduled_model_runs,
        scheduled_connection_syncs,
        scheduled_instance_syncs,
        scheduled_exports,
        scheduled_preview_runs,
        scheduled_test_runs,
        scheduled_listener_archives,
    ],
    schedules=[
        ScheduleDefinition(
            default_status=RUNNING,
            job=dagster_run_pruning,
            should_execute=one_at_a_time(dagster_run_pruning.name),
            cron_schedule="40 * * * *",  # hourly: see jobs/dagster_runs.py
            name="prune_dagster_runs",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=workspace_cleanup,
            should_execute=one_at_a_time(workspace_cleanup.name),
            cron_schedule="15 3 * * *",  # nightly, off-peak
            name="nightly_workspace_cleanup",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_model_runs,
            tags=HEAVY,
            should_execute=one_at_a_time(scheduled_model_runs.name, at_most=2),
            cron_schedule="* * * * *",  # every minute: queued python runs and
            # cron-scheduled models should start promptly, not sit for long
            name="poll_model_runs",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_connection_syncs,
            tags=HEAVY,
            should_execute=one_at_a_time(scheduled_connection_syncs.name),
            cron_schedule="*/5 * * * *",  # every 5 minutes - syncs are heavier
            name="poll_scheduled_syncs",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_instance_syncs,
            tags=HEAVY,
            should_execute=one_at_a_time(scheduled_instance_syncs.name),
            cron_schedule="*/5 * * * *",  # every 5 minutes, same cadence as connection syncs
            name="poll_instance_syncs",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_exports,
            tags=HEAVY,
            should_execute=one_at_a_time(scheduled_exports.name),
            # Every 5 minutes, the same cadence as syncs and for the same
            # reason: this is the *poll*, not the schedule. An export's own
            # cron decides when it is due; this decides how long after
            # becoming due it waits, and p.192's skip makes an early poll
            # cheap - a run with nothing new writes nothing (decision 0016 §1).
            cron_schedule="*/5 * * * *",
            name="poll_scheduled_exports",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_test_runs,
            should_execute=one_at_a_time(scheduled_test_runs.name),
            # Every minute, the same cadence as queued model runs and for the
            # same reason: somebody is watching this one. A test run is asked
            # for by a person who has just pressed a button and is looking at
            # a panel, so the poll interval *is* the latency they see - five
            # minutes would make the feature feel broken rather than slow.
            cron_schedule="* * * * *",
            name="poll_test_runs",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_listener_archives,
            should_execute=one_at_a_time(scheduled_listener_archives.name),
            # p.264: "Every few minutes, the listener event stream will
            # archive into a backing dataset" (§519).
            cron_schedule="*/5 * * * *",
            name="archive_listener_events",
        ),
        ScheduleDefinition(
            default_status=RUNNING,
            job=scheduled_preview_runs,
            should_execute=one_at_a_time(scheduled_preview_runs.name),
            # Every minute, for `poll_test_runs`' reason exactly: a preview is
            # asked for by somebody who has just pressed a button and is
            # watching a panel, so the poll interval is the latency they feel.
            cron_schedule="* * * * *",
            name="poll_preview_runs",
        ),
    ],
    resources={
        "platform_db": PlatformDatabase(
            dsn=_resolve_database_url(),
        )
    },
)
