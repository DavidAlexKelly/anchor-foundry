"""The schedules that will update a dataset (§508; `dataset-preview` p.3).

    "Schedules: Information about any configured build schedules that will
     run to update the dataset." (p.3)

Two things here write a dataset on their own, and both carry their schedule
on themselves rather than in a scheduler table (db 0014):

- the **transform** whose output it is (`models.output_dataset_id`), when its
  trigger is `cron` (p.3's build schedule) or `upstream` (it runs when an
  input updates, db 0021);
- the **sync** that feeds it (`connections.sync_dataset_id`), when it has a
  `sync_schedule`.

A transform on `manual` and a sync with no schedule are not schedules, and
are left out: p.3 asks what "will run", and nothing will. Exports read a
dataset and never write it, so they are not here either.

`next_run_at` is passed through as stored, including NULL. With a schedule
set, NULL means "never fired yet", and the worker treats that as due now
(db 0014). That is the worker's rule, so the reader is told it rather than
shown a computed time the worker would not use.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all


async def for_dataset(conn: AsyncConnection, dataset_id: UUID) -> list[dict[str, Any]]:
    models = await fetch_all(conn, """
        SELECT m.id, m.name, m.resource_id, m.trigger_mode, m.cron_schedule, m.next_run_at,
               ARRAY(
                   SELECT d.name FROM model_inputs i JOIN datasets d ON d.id = i.dataset_id
                    WHERE i.model_id = m.id ORDER BY d.name
               ) AS inputs
          FROM models m
         WHERE m.output_dataset_id = :id AND m.trigger_mode IN ('cron', 'upstream')
         ORDER BY m.name
    """, {"id": str(dataset_id)})
    syncs = await fetch_all(conn, """
        SELECT name, resource_id, sync_mode, sync_schedule, sync_next_run_at
          FROM connections
         WHERE sync_dataset_id = :id AND sync_schedule IS NOT NULL
         ORDER BY name
    """, {"id": str(dataset_id)})
    out: list[dict[str, Any]] = []
    for m in models:
        cron = m["trigger_mode"] == "cron"
        out.append({
            "kind": "transform",
            "name": m["name"],
            "resource_id": m["resource_id"],
            "trigger": str(m["trigger_mode"]),
            "cron": m["cron_schedule"] if cron else None,
            "next_run_at": m["next_run_at"] if cron else None,
            # For an upstream trigger, what it waits on is the schedule.
            "watches": [] if cron else list(m["inputs"]),
            "mode": None,
        })
    for s in syncs:
        out.append({
            "kind": "sync",
            "name": s["name"],
            "resource_id": s["resource_id"],
            "trigger": "cron",
            "cron": s["sync_schedule"],
            "next_run_at": s["sync_next_run_at"],
            "watches": [],
            "mode": str(s["sync_mode"]),
        })
    return out
