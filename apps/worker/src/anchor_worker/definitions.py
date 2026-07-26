"""Dagster entrypoint. The single registration point for every job/schedule
this worker runs."""
from __future__ import annotations

import os
from urllib.parse import quote

from dagster import Definitions, ScheduleDefinition

from .jobs.cleanup import workspace_cleanup
from .jobs.instance_syncs import scheduled_instance_syncs
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

defs = Definitions(
    jobs=[workspace_cleanup, scheduled_model_runs, scheduled_connection_syncs, scheduled_instance_syncs],
    schedules=[
        ScheduleDefinition(
            job=workspace_cleanup,
            cron_schedule="15 3 * * *",  # nightly, off-peak
            name="nightly_workspace_cleanup",
        ),
        ScheduleDefinition(
            job=scheduled_model_runs,
            cron_schedule="* * * * *",  # every minute: queued python runs and
            # cron-scheduled models should start promptly, not sit for long
            name="poll_model_runs",
        ),
        ScheduleDefinition(
            job=scheduled_connection_syncs,
            cron_schedule="*/5 * * * *",  # every 5 minutes - syncs are heavier
            name="poll_scheduled_syncs",
        ),
        ScheduleDefinition(
            job=scheduled_instance_syncs,
            cron_schedule="*/5 * * * *",  # every 5 minutes, same cadence as connection syncs
            name="poll_instance_syncs",
        ),
    ],
    resources={
        "platform_db": PlatformDatabase(
            dsn=_resolve_database_url(),
        )
    },
)
