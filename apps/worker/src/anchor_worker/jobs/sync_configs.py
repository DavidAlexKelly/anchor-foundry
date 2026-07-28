"""Scheduled/incremental connection syncs (spec: day-one connection sync is
full-snapshot and inline via the API; this is the worker half - scheduled
firing on a cron, and a true cursor-based incremental mode).

One op, on its own schedule: for every connection with a due sync_schedule
(db list_due_scheduled_syncs), runs a full or incremental sync - full
replaces the dataset's current version wholesale (same as the API's inline
"trigger sync"); incremental pulls only rows where the cursor column
exceeds the last seen value and upserts them into the existing dataset by
primary key (dataset_engine.merge_incremental), then advances
sync_last_cursor_value and sync_next_run_at (croniter).

Same discover-then-verify pattern as the other jobs: the SECURITY DEFINER
function enumerates candidates across every workspace; the actual read/
write happens through a workspace-scoped connection that re-checks the
connection is still due before touching anything.

Note: deliberately no `from __future__ import annotations` here - see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4

from croniter import croniter
from dagster import OpExecutionContext, job, op

from .. import dataset_engine as engine
from ..connectors import ConnectorError, get_connector
from ..resources import PlatformDatabase
from ..storage import StorageKeyError, gateway_from_env, slugify, storage_prefix

MAX_SYNC_BYTES = 200 * 1024 * 1024  # matches the API's day-one interactive cap


def _workspace_s3_prefix(cur, workspace_id: UUID) -> str:
    cur.execute("SELECT s3_prefix FROM workspaces WHERE id = %s", (str(workspace_id),))
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"workspace {workspace_id} not found")
    return row[0]


def _record_synced_dataset(
    cur,
    storage,
    *,
    connection_id: UUID,
    dataset_name: str,
    dataset_id: UUID | None,
    project_id: UUID,
    workspace_id: UUID,
    parquet_bytes: bytes,
    schema: list[engine.ColumnSchema],
    row_count: int,
) -> UUID:
    """Create-or-version the connection's managed sync dataset. Same shape
    as jobs/model_runs.py's _record_output, with origin='sync' and
    produced_by_kind='sync' in place of 'model_output'/'model'."""
    schema_json = json.dumps([c.as_dict() for c in schema])
    ws_prefix = _workspace_s3_prefix(cur, workspace_id)

    if dataset_id is None:
        new_id = uuid4()
        slug = slugify(dataset_name)
        cur.execute(
            "SELECT 1 FROM datasets WHERE project_id = %s AND slug = %s", (str(project_id), slug)
        )
        if cur.fetchone() is not None:
            raise engine.DatasetEngineError(
                f"a dataset named '{slug}' already exists - rename the scheduled sync or that dataset"
            )
        version = 1
        parquet_key = f"{storage_prefix(ws_prefix, new_id)}v1/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        cur.execute(
            """
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                                  origin, connection_id, s3_location, table_schema, row_count,
                                  current_version, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'sync', %s, %s, %s, %s, 1, NULL)
            """,
            (
                str(new_id), str(project_id), str(workspace_id), dataset_name, slug,
                f"Scheduled sync from connection {connection_id}", str(connection_id),
                parquet_key, schema_json, row_count,
            ),
        )
        cur.execute("UPDATE connections SET sync_dataset_id = %s WHERE id = %s", (str(new_id), str(connection_id)))
        dataset_id = new_id
    else:
        cur.execute("SELECT current_version FROM datasets WHERE id = %s", (str(dataset_id),))
        row = cur.fetchone()
        if row is None:
            raise engine.DatasetEngineError("the synced dataset no longer exists")
        version = int(row[0]) + 1
        parquet_key = f"{storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        cur.execute(
            """
            UPDATE datasets
               SET s3_location = %s, table_schema = %s, row_count = %s, current_version = %s
             WHERE id = %s
            """,
            (parquet_key, schema_json, row_count, version, str(dataset_id)),
        )

    cur.execute(
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind, produced_by_id)
        VALUES (%s, %s, %s, %s, %s, 'sync', %s)
        """,
        (str(dataset_id), version, parquet_key, schema_json, row_count, str(connection_id)),
    )
    return dataset_id


@op
def run_due_scheduled_syncs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    storage = gateway_from_env()
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT connection_id, workspace_id FROM list_due_scheduled_syncs()")
            candidates = cur.fetchall()

    ran = 0
    for connection_id, workspace_id in candidates:
        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, config, secret_arn, sync_mode, sync_schedule,
                           sync_source_schema, sync_source_table, sync_dataset_name,
                           sync_dataset_id, sync_primary_key_column, sync_cursor_column,
                           sync_last_cursor_value, source_type
                      FROM connections WHERE id = %s
                    """,
                    (connection_id,),
                )
                row = cur.fetchone()
                if row is None or row[4] is None:
                    continue  # unscheduled since discovery - re-verified
                (project_id, config, secret_arn, mode, _schedule, source_schema, source_table,
                 dataset_name, dataset_id, primary_key_column, cursor_column, last_cursor,
                 source_type) = row
                # Only the table half is required. An empty source_schema is
                # legitimate for object storage - it means "at the root of the
                # connection's configured prefix" - so testing it for
                # truthiness here would silently skip every root-level file
                # sync, logging "no sync target set" about a target that is
                # perfectly well set.
                if not source_table:
                    context.log.warning("connection %s has a schedule but no sync target set", connection_id)
                    continue
                source_schema = source_schema or ""
            conn.commit()

        ok, error, rows_synced = True, None, 0
        secret = _read_secret(secret_arn)
        new_cursor_value = last_cursor
        try:
            connector = get_connector(source_type)
            with tempfile.TemporaryDirectory() as tmp:
                cursor_for_query = cursor_column if mode == "incremental" else None
                extract = connector.snapshot(
                    config, secret,
                    source_schema=source_schema, source_table=source_table,
                    dest_dir=tmp, max_bytes=MAX_SYNC_BYTES,
                    cursor_column=cursor_for_query, cursor_value=last_cursor,
                )
                if mode == "incremental":
                    new_cursor_value = connector.max_cursor_value(
                        config, secret,
                        source_schema=source_schema, source_table=source_table,
                        cursor_column=cursor_column,
                    ) or last_cursor

                new_parquet = os.path.join(tmp, "new.parquet")
                if extract.empty:
                    # The connector already knows nothing changed (an object
                    # store with no rewritten object writes no file at all),
                    # so there is nothing to ingest.
                    schema, new_row_count = [], 0
                else:
                    schema, new_row_count = _ingest_file(
                        extract.path, extract.extension, new_parquet
                    )

                nothing_new = (
                    mode == "incremental"
                    and dataset_id is not None
                    and (new_row_count == 0 or extract.empty)
                )
                if nothing_new:
                    # Steady state for a cron-scheduled sync between source
                    # writes. An empty CSV (header only) gives DuckDB nothing
                    # to infer column types from - it falls back to VARCHAR
                    # for every column, which then fails to compare against
                    # the existing (correctly-typed) dataset in the primary
                    # key anti-join. Skip the merge/write entirely instead.
                    with platform_db.connect_scoped_to(workspace_id) as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT row_count FROM datasets WHERE id = %s", (str(dataset_id),))
                            rows_synced = cur.fetchone()[0]
                        conn.commit()
                elif mode == "incremental" and dataset_id is not None:
                    storage_local = _local_path_of_current_version(
                        platform_db, workspace_id, connection_id, dataset_id
                    )
                    merged_parquet = os.path.join(tmp, "merged.parquet")
                    schema, rows_synced = engine.merge_incremental(
                        storage_local, new_parquet, primary_key_column, merged_parquet
                    )
                    final_parquet = merged_parquet
                else:
                    final_parquet = new_parquet
                    rows_synced = new_row_count

                if not nothing_new:
                    with open(final_parquet, "rb") as handle:
                        parquet_bytes = handle.read()

            with platform_db.connect_scoped_to(workspace_id) as conn:
                with conn.cursor() as cur:
                    if nothing_new:
                        new_dataset_id = dataset_id
                    else:
                        new_dataset_id = _record_synced_dataset(
                            cur, storage,
                            connection_id=UUID(str(connection_id)),
                            dataset_name=dataset_name or source_table,
                            dataset_id=UUID(str(dataset_id)) if dataset_id else None,
                            project_id=UUID(str(project_id)), workspace_id=UUID(str(workspace_id)),
                            parquet_bytes=parquet_bytes, schema=schema, row_count=rows_synced,
                        )
                    cur.execute(
                        "INSERT INTO sync_runs (connection_id, dataset_id, mode, source_table, "
                        "status, rows_synced, finished_at) VALUES (%s, %s, %s, %s, 'succeeded', %s, now())",
                        (str(connection_id), str(new_dataset_id), mode, f"{source_schema}.{source_table}", rows_synced),
                    )
                conn.commit()
        # Every exception type on the call path, enumerated deliberately (the
        # standing checklist item from instance_syncs.py's own history): a
        # driver/extract failure (ConnectorError, including an unregistered
        # source type), a DuckDB failure, a missing workspace (LookupError), a
        # filesystem failure (OSError), or a malformed storage key
        # (StorageKeyError, a ValueError subclass none of the others cover).
        # Anything missed here crashes the whole batch and leaves every other
        # due connection unprocessed instead of failing just this one.
        except (
            ConnectorError,
            engine.DatasetEngineError,
            LookupError,
            OSError,
            StorageKeyError,
        ) as exc:
            ok, error = False, str(exc)
            with platform_db.connect_scoped_to(workspace_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sync_runs (connection_id, mode, source_table, status, error, finished_at) "
                        "VALUES (%s, %s, %s, 'failed', %s, now())",
                        (str(connection_id), mode, f"{source_schema}.{source_table}", error),
                    )
                conn.commit()

        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE connections
                       SET last_synced_at = CASE WHEN %s THEN now() ELSE last_synced_at END,
                           last_error = %s,
                           status = %s,
                           sync_last_cursor_value = %s
                     WHERE id = %s
                    """,
                    (ok, error, "ok" if ok else "error", new_cursor_value, connection_id),
                )
            conn.commit()

        # Advance the schedule regardless of outcome - a failing source
        # shouldn't be retried every poll cycle faster than its own cadence.
        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT sync_schedule FROM connections WHERE id = %s", (connection_id,))
                schedule = cur.fetchone()[0]
                try:
                    next_run = croniter(schedule, datetime.now(timezone.utc)).get_next(datetime)
                    cur.execute("UPDATE connections SET sync_next_run_at = %s WHERE id = %s", (next_run, connection_id))
                except (ValueError, KeyError):
                    context.log.warning("connection %s has an invalid sync_schedule %r", connection_id, schedule)
            conn.commit()

        context.log.info("scheduled sync %s: %s", connection_id, "succeeded" if ok else f"failed ({error})")
        ran += 1
    return ran


def _read_secret(secret_arn: str | None) -> dict[str, str]:
    if not secret_arn:
        return {}
    import boto3

    client = boto3.client("secretsmanager")
    resp = client.get_secret_value(SecretId=secret_arn)
    return json.loads(resp["SecretString"])


_READERS = {
    ".csv": "read_csv_auto({path!r})",
    ".tsv": "read_csv_auto({path!r}, delim='\\t')",
    ".parquet": "read_parquet({path!r})",
    ".json": "read_json_auto({path!r})",
    ".jsonl": "read_json_auto({path!r}, format='newline_delimited')",
}


def _ingest_file(src_path: str, extension: str, dest_parquet: str) -> tuple[list, int]:
    """Mirrors the API's dataset_engine.ingest_to_parquet reader table - a
    connector that hands back Parquet or JSON (object storage does) must not be
    forced through the CSV reader."""
    import duckdb

    template = _READERS.get((extension or ".csv").lower())
    if template is None:
        raise engine.DatasetEngineError(
            f"unsupported file type {extension!r} (supported: {', '.join(_READERS)})"
        )
    con = duckdb.connect()
    try:
        con.execute(f"CREATE VIEW src AS SELECT * FROM {template.format(path=src_path)}")
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        con.execute(f"COPY src TO {dest_parquet!r} (FORMAT parquet)")
        schema = [engine.ColumnSchema(name=r[0], data_type=r[1]) for r in con.execute("DESCRIBE src").fetchall()]
        row_count = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        return schema, row_count
    finally:
        con.close()


def _local_path_of_current_version(platform_db, workspace_id, connection_id, dataset_id) -> str:
    storage = gateway_from_env()
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT s3_location FROM datasets WHERE id = %s", (str(dataset_id),))
            row = cur.fetchone()
    if row is None:
        raise engine.DatasetEngineError("dataset for incremental merge no longer exists")
    return storage.local_path(row[0])


@job
def scheduled_connection_syncs():
    run_due_scheduled_syncs()
