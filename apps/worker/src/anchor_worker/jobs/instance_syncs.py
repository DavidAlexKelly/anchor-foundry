"""Scheduled object-type-source sync (spec: object instances materialised
from a mapped dataset). Day-one sync (apps/api's routes/objects.py
`POST .../{source_id}/sync`) is interactive and capped at
MAX_INSTANCE_SYNC_ROWS (20,000) — this is the worker half: a cron-scheduled
version of the identical mark-and-sweep upsert, with a far larger row cap
since it isn't bounded by one HTTP request/response.

Not incremental, deliberately: the mapped dataset's Parquet file is replaced
wholesale on every upload/sync/model run (a snapshot, not an append log), so
there is no "rows changed since a cursor" to filter the way connection sync
(jobs/sync_configs.py) can. Reprocessing the full current snapshot and
upserting by primary key is already the correct approach for this domain —
see migration 0016's docstring.

Same discover-then-verify pattern as the other scheduled jobs: the
SECURITY DEFINER function (list_due_object_source_syncs) enumerates
candidates across every workspace; the actual read/write happens through a
workspace-scoped connection that re-checks the source is still due and
still configured before touching anything.

Note: deliberately no `from __future__ import annotations` here — see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from dagster import OpExecutionContext, job, op

from .. import dataset_engine as engine
from ..resources import PlatformDatabase
from ..storage import StorageKeyError, gateway_from_env


@op
def run_due_object_source_syncs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    storage = gateway_from_env()
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT source_id, workspace_id FROM list_due_object_source_syncs()")
            candidates = cur.fetchall()

    ran = 0
    for source_id, workspace_id in candidates:
        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.object_type_id, s.dataset_id, s.primary_key_column,
                           s.column_mappings, s.sync_schedule, d.s3_location
                      FROM object_type_sources s
                      JOIN datasets d ON d.id = s.dataset_id
                     WHERE s.id = %s
                    """,
                    (source_id,),
                )
                row = cur.fetchone()
                if row is None or row[4] is None:
                    continue  # deleted or unscheduled since discovery — re-verified
                object_type_id, dataset_id, primary_key_column, column_mappings, _schedule, s3_location = row
                if isinstance(column_mappings, str):
                    column_mappings = json.loads(column_mappings)
            conn.commit()

        ok, error = True, None
        upserted = removed = 0
        synced_at = datetime.now(timezone.utc)
        try:
            local_path = storage.local_path(s3_location)
            rows = engine.extract_instance_rows(local_path, primary_key_column, column_mappings)

            with platform_db.connect_scoped_to(workspace_id) as conn:
                with conn.cursor() as cur:
                    for primary_key, properties in rows:
                        cur.execute(
                            """
                            INSERT INTO object_instances
                                (object_type_id, source_id, primary_key, properties, updated_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (source_id, primary_key)
                            DO UPDATE SET properties = EXCLUDED.properties, updated_at = EXCLUDED.updated_at
                            """,
                            (str(object_type_id), str(source_id), primary_key, json.dumps(properties), synced_at),
                        )
                    upserted = len(rows)
                    cur.execute(
                        "DELETE FROM object_instances WHERE source_id = %s AND updated_at < %s",
                        (str(source_id), synced_at),
                    )
                    removed = cur.rowcount
                conn.commit()
        except (engine.DatasetEngineError, LookupError, OSError, StorageKeyError) as exc:
            ok, error = False, str(exc)

        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE object_type_sources
                       SET sync_status = %s,
                           last_synced_at = CASE WHEN %s THEN now() ELSE last_synced_at END,
                           last_error = %s
                     WHERE id = %s
                    """,
                    ("ok" if ok else "error", ok, error, str(source_id)),
                )
                cur.execute("SELECT sync_schedule FROM object_type_sources WHERE id = %s", (source_id,))
                schedule = cur.fetchone()[0]
                try:
                    next_run = croniter(schedule, datetime.now(timezone.utc)).get_next(datetime)
                    cur.execute(
                        "UPDATE object_type_sources SET sync_next_run_at = %s WHERE id = %s",
                        (next_run, source_id),
                    )
                except (ValueError, KeyError):
                    context.log.warning("source %s has an invalid sync_schedule %r", source_id, schedule)
            conn.commit()

        context.log.info(
            "object source sync %s: %s (upserted=%s removed=%s)",
            source_id, "succeeded" if ok else f"failed ({error})", upserted, removed,
        )
        ran += 1
    return ran


@job
def scheduled_instance_syncs():
    run_due_object_source_syncs()
