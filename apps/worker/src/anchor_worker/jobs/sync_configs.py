"""Scheduled/incremental connection syncs (spec: day-one connection sync is
full-snapshot and inline via the API; this is the worker half — scheduled
firing on a cron, and a true cursor-based incremental mode).

One op, on its own schedule: for every connection with a due sync_schedule
(db list_due_scheduled_syncs), runs a full or incremental sync — full
replaces the dataset's current version wholesale (same as the API's inline
"trigger sync"); incremental pulls only rows where the cursor column
exceeds the last seen value and upserts them into the existing dataset by
primary key (dataset_engine.merge_incremental), then advances
sync_last_cursor_value and sync_next_run_at (croniter).

Same discover-then-verify pattern as the other jobs: the SECURITY DEFINER
function enumerates candidates across every workspace; the actual read/
write happens through a workspace-scoped connection that re-checks the
connection is still due before touching anything.

Note: deliberately no `from __future__ import annotations` here — see
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
from psycopg import sql

from .. import dataset_engine as engine
from ..resources import PlatformDatabase
from ..storage import gateway_from_env, slugify, storage_prefix

MAX_SYNC_BYTES = 200 * 1024 * 1024  # matches the API's day-one interactive cap


def _workspace_s3_prefix(cur, workspace_id: UUID) -> str:
    cur.execute("SELECT s3_prefix FROM workspaces WHERE id = %s", (str(workspace_id),))
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"workspace {workspace_id} not found")
    return row[0]


def _snapshot_to_csv(
    conninfo: dict,
    source_schema: str,
    source_table: str,
    dest_csv: str,
    cursor_column: str | None,
    cursor_value: str | None,
) -> None:
    """COPY the table (optionally filtered to rows newer than cursor_value)
    to a CSV file, byte-capped. Synchronous; called from a Dagster op, which
    is itself synchronous, so no thread offload is needed here."""
    import psycopg

    qualified = sql.SQL("{}.{}").format(sql.Identifier(source_schema), sql.Identifier(source_table))
    if cursor_column and cursor_value is not None:
        query = sql.SQL("COPY (SELECT * FROM {} WHERE {} > {}) TO STDOUT (FORMAT csv, HEADER true)").format(
            qualified, sql.Identifier(cursor_column), sql.Literal(cursor_value)
        )
    else:
        query = sql.SQL("COPY (SELECT * FROM {}) TO STDOUT (FORMAT csv, HEADER true)").format(qualified)

    written = 0
    try:
        with psycopg.connect(**conninfo) as conn:
            with conn.cursor() as cur, open(dest_csv, "wb") as out:
                with cur.copy(query) as copy:
                    for chunk in copy:
                        written += len(chunk)
                        if written > MAX_SYNC_BYTES:
                            cap_mb = MAX_SYNC_BYTES // (1024 * 1024)
                            raise engine.DatasetEngineError(
                                f"table exceeds the {cap_mb} MB scheduled-sync limit"
                            )
                        out.write(bytes(chunk))
    except psycopg.errors.UndefinedTable as exc:
        raise engine.DatasetEngineError(f"table {source_schema}.{source_table} does not exist") from exc
    except psycopg.errors.InsufficientPrivilege as exc:
        raise engine.DatasetEngineError(
            f"the connection's user cannot read {source_schema}.{source_table}"
        ) from exc
    except psycopg.OperationalError as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        raise engine.DatasetEngineError(reason) from exc


def _max_cursor_value(conninfo: dict, source_schema: str, source_table: str, cursor_column: str) -> str | None:
    import psycopg

    qualified = sql.SQL("{}.{}").format(sql.Identifier(source_schema), sql.Identifier(source_table))
    query = sql.SQL("SELECT max({}) FROM {}").format(sql.Identifier(cursor_column), qualified)
    try:
        with psycopg.connect(**conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
    except psycopg.errors.UndefinedTable as exc:
        raise engine.DatasetEngineError(f"table {source_schema}.{source_table} does not exist") from exc
    except psycopg.OperationalError as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        raise engine.DatasetEngineError(reason) from exc
    return None if row is None or row[0] is None else str(row[0])


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
                f"a dataset named '{slug}' already exists — rename the scheduled sync or that dataset"
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
                           sync_last_cursor_value
                      FROM connections WHERE id = %s
                    """,
                    (connection_id,),
                )
                row = cur.fetchone()
                if row is None or row[4] is None:
                    continue  # unscheduled since discovery — re-verified
                (project_id, config, secret_arn, mode, _schedule, source_schema, source_table,
                 dataset_name, dataset_id, primary_key_column, cursor_column, last_cursor) = row
                if not source_schema or not source_table:
                    context.log.warning("connection %s has a schedule but no sync target set", connection_id)
                    continue
            conn.commit()

        ok, error, rows_synced = True, None, 0
        secret = _read_secret(secret_arn)
        conninfo = {
            "host": config["host"], "port": config["port"], "dbname": config["database"],
            "user": config["user"], "password": secret.get("password", ""),
            "sslmode": config.get("sslmode", "prefer"), "connect_timeout": 8,
        }
        new_cursor_value = last_cursor
        try:
            with tempfile.TemporaryDirectory() as tmp:
                csv_path = os.path.join(tmp, "snapshot.csv")
                cursor_for_query = cursor_column if mode == "incremental" else None
                _snapshot_to_csv(conninfo, source_schema, source_table, csv_path, cursor_for_query, last_cursor)
                if mode == "incremental" and cursor_column:
                    new_cursor_value = _max_cursor_value(conninfo, source_schema, source_table, cursor_column) or last_cursor

                new_parquet = os.path.join(tmp, "new.parquet")
                schema, new_row_count = _ingest_csv(csv_path, new_parquet)

                nothing_new = mode == "incremental" and dataset_id is not None and new_row_count == 0
                if nothing_new:
                    # Steady state for a cron-scheduled sync between source
                    # writes. An empty CSV (header only) gives DuckDB nothing
                    # to infer column types from — it falls back to VARCHAR
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
        except (engine.DatasetEngineError, LookupError, OSError) as exc:
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

        # Advance the schedule regardless of outcome — a failing source
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


def _ingest_csv(csv_path: str, dest_parquet: str) -> tuple[list, int]:
    import duckdb

    con = duckdb.connect()
    try:
        con.execute(f"CREATE VIEW src AS SELECT * FROM read_csv_auto({csv_path!r})")
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
