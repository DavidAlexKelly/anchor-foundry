"""Scheduled object-type-source sync (spec: object instances materialised
from a mapped dataset). Day-one sync (apps/api's routes/objects.py
`POST .../{source_id}/sync`) is interactive and capped at
MAX_INSTANCE_SYNC_ROWS (20,000) - this is the worker half: a cron-scheduled
version of the identical mark-and-sweep upsert, with a far larger row cap
since it isn't bounded by one HTTP request/response.

Not incremental, deliberately: the mapped dataset's Parquet file is replaced
wholesale on every upload/sync/model run (a snapshot, not an append log), so
there is no "rows changed since a cursor" to filter the way connection sync
(jobs/sync_configs.py) can. Reprocessing the full current snapshot and
upserting by primary key is already the correct approach for this domain -
see migration 0016's docstring.

Same discover-then-verify pattern as the other scheduled jobs: the
SECURITY DEFINER function (list_due_object_source_syncs) enumerates
candidates across every workspace; the actual read/write happens through a
workspace-scoped connection that re-checks the source is still due and
still configured before touching anything.

Note: deliberately no `from __future__ import annotations` here - see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from dagster import OpExecutionContext, job, op

from .. import dataset_engine as engine
from .. import instance_index, property_values
from ..resources import PlatformDatabase
from ..storage import StorageKeyError, gateway_from_env


#: Rows per statement (§805), the API's `instances.UPSERT_BATCH`.
UPSERT_BATCH = 1000

#: The API's `instances.ANALYZE_AFTER_ROWS` (§817).
ANALYZE_AFTER_ROWS = 10_000


def upsert_rows(cur, object_type_id, source_id, rows, synced_at) -> None:
    """Write a sync's rows the way the API's sync does (`instances.
    upsert_instances`), a thousand to a statement (§805).

    **Merging, not replacing.** This wrote `properties = EXCLUDED.properties`,
    which the API's own sync stopped doing when it found the cost: an
    edit-only property (`object-link-types` p.113) has no dataset column, so
    every sync deleted it. The API was fixed and this, the half that runs on a
    schedule - and the only half that takes a table past 20,000 rows - was
    not. The dataset's values are layered over what is stored, so a sync owns
    exactly what it maps and no more.

    **A statement per thousand rows**, because one per row is a million round
    trips for a million-row table. A key repeated within a batch is collapsed
    to its later row first, since one `ON CONFLICT DO UPDATE` may not touch a
    row twice.
    """
    for start in range(0, len(rows), UPSERT_BATCH):
        # The later row of a repeated key wins whole: every row of one sync
        # carries every mapped key (a null is a key holding None), so this is
        # what the row-at-a-time loop's merge came to.
        merged = dict(rows[start:start + UPSERT_BATCH])
        cur.execute(
            """
            INSERT INTO object_instances
                (object_type_id, source_id, primary_key, properties, updated_at)
            SELECT %s, %s, r.pk, r.props, %s
              FROM jsonb_to_recordset(%s::jsonb) AS r(pk text, props jsonb)
            ON CONFLICT (source_id, primary_key)
            DO UPDATE SET properties = object_instances.properties || EXCLUDED.properties
            -- updated_at is the BEFORE UPDATE trigger's to set (db 0012).
            """,
            (str(object_type_id), str(source_id), synced_at,
             json.dumps([{"pk": pk, "props": props} for pk, props in merged.items()])),
        )


@op
def run_due_object_source_syncs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    storage = gateway_from_env()
    index = instance_index.from_env()
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
                    continue  # deleted or unscheduled since discovery - re-verified
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
            # The declared property types are applied here, exactly as the
            # API's inline sync does (roadmap Objects item 4). Without this a
            # geopoint synced by the worker would be whatever the column
            # held while one synced interactively was a {lat, lon} object -
            # the same source producing two shapes depending on who ran it.
            with platform_db.connect_scoped_to(workspace_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT api_name, data_type, struct_fields, array_of "
                        "FROM object_type_properties WHERE object_type_id = %s",
                        (str(object_type_id),),
                    )
                    declared = cur.fetchall()
                    property_types = {name: str(dtype) for name, dtype, _, _ in declared}
                    # A struct is the one type whose name does not carry its
                    # meaning (db 0064): the fields it declares are what a
                    # value is checked against, so they travel with the label.
                    struct_by_property = {
                        name: fields for name, _, fields, _ in declared if fields is not None
                    }
                    # An array is the other (db 0087): "array" says a list and
                    # its element type says of what. Never passed here until
                    # §809, so every scheduled sync of a type with an array
                    # property failed while the API's sync of it worked.
                    array_by_property = {
                        name: str(element) for name, _, _, element in declared
                        if element is not None
                    }
                    cur.execute("SELECT search_prefix FROM workspaces WHERE id = %s",
                                (str(workspace_id),))
                    search_prefix = cur.fetchone()[0]
                conn.commit()
            rows = property_values.coerce_rows(
                rows, property_types, struct_by_property, array_by_property)

            if index is not None:
                # Where the API reads objects from, when it has an index
                # (§811): writing Postgres here would be a sync that reports
                # "ok" into a table nobody reads.
                upserted = index.upsert(
                    search_prefix=search_prefix, object_type_id=object_type_id,
                    source_id=source_id, rows=rows, synced_at=synced_at,
                    declared=[{"api_name": name, "data_type": dtype, "array_of": element}
                              for name, dtype, _, element in declared],
                )
                removed = index.delete_stale(
                    search_prefix=search_prefix, object_type_id=object_type_id,
                    source_id=source_id, synced_before=synced_at,
                )
            else:
                with platform_db.connect_scoped_to(workspace_id) as conn:
                    with conn.cursor() as cur:
                        upsert_rows(cur, object_type_id, source_id, rows, synced_at)
                        upserted = len(rows)
                        cur.execute(
                            "DELETE FROM object_instances WHERE source_id = %s AND updated_at < %s",
                            (str(source_id), synced_at),
                        )
                        removed = cur.rowcount
                        if upserted >= ANALYZE_AFTER_ROWS:
                            # The API's rule (§817, db 0158): a write this
                            # large brings the planner's statistics up to date
                            # now, not at autovacuum's next pass.
                            cur.execute("SELECT analyze_object_instances()")
                    conn.commit()
        except (engine.DatasetEngineError, LookupError, OSError, StorageKeyError,
                property_values.PropertyValueError, instance_index.InstanceIndexError) as exc:
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
    if index is not None:
        index.close()
    return ran


@job
def scheduled_instance_syncs():
    run_due_object_source_syncs()
