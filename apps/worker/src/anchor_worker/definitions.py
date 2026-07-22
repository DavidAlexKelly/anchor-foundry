"""Dagster entrypoint. Jobs beyond cleanup (connection sync, dataset builds,
model runs — spec §5 layers 1-2) land here in later milestones; the module
stays the single registration point."""
from __future__ import annotations

import os

from dagster import Definitions, ScheduleDefinition

from .jobs.cleanup import workspace_cleanup
from .resources import PlatformDatabase

defs = Definitions(
    jobs=[workspace_cleanup],
    schedules=[
        ScheduleDefinition(
            job=workspace_cleanup,
            cron_schedule="15 3 * * *",  # nightly, off-peak
            name="nightly_workspace_cleanup",
        )
    ],
    resources={
        "platform_db": PlatformDatabase(
            dsn=os.environ.get("WORKER_DATABASE_URL", ""),
        )
    },
)
