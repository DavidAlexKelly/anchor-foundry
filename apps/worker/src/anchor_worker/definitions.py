"""Dagster entrypoint. The single registration point for every job/schedule
this worker runs."""
from __future__ import annotations

import os

from dagster import Definitions, ScheduleDefinition

from .jobs.cleanup import workspace_cleanup
from .jobs.instance_syncs import scheduled_instance_syncs
from .jobs.model_runs import scheduled_model_runs
from .jobs.sync_configs import scheduled_connection_syncs
from .resources import PlatformDatabase

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
            cron_schedule="*/5 * * * *",  # every 5 minutes — syncs are heavier
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
            dsn=os.environ.get("WORKER_DATABASE_URL", ""),
        )
    },
)
