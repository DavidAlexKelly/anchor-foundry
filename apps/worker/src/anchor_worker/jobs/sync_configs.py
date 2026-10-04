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

import psycopg
from croniter import croniter
from dagster import OpExecutionContext, job, op

from .. import dataset_engine as engine
from .. import egress
from .. import file_sync_rules as rules
from .. import oidc
from ..connectors import ConnectorError, get_connector
from ..resources import PlatformDatabase
from ..storage import StorageKeyError, gateway_from_env, slugify, storage_prefix
from .claims import claim_due

MAX_SYNC_BYTES = 200 * 1024 * 1024  # matches the API's day-one interactive cap


def _stored_schema(value):
    """A dataset's table_schema jsonb as a list - psycopg decodes jsonb for us,
    but be tolerant of a string on either path. Mirrors the API-side helper."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, list) else None


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
    transaction_type: str,
    cursor_value: str | None = None,
    new_id: UUID | None = None,
) -> "tuple[UUID, dict | None]":
    """Create-or-version the connection's managed sync dataset. Same shape
    as jobs/model_runs.py's _record_output, with origin='sync' and
    produced_by_kind='sync' in place of 'model_output'/'model'.

    Returns (dataset id, schema_changes) - the drift against the version this
    one replaces, or None for a first version or an unchanged schema
    (migration 0018).

    `cursor_value` is where an incremental sync had got to (migration 0127,
    §607), recorded on the version so a rollback to it can put the
    connection's cursor back with the data."""
    schema_json = json.dumps([c.as_dict() for c in schema])
    ws_prefix = _workspace_s3_prefix(cur, workspace_id)

    if dataset_id is None:
        # `new_id` when the caller has already written under the dataset's
        # prefix - a file sync's files (§750).
        new_id = new_id or uuid4()
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
        schema_changes = None  # first version: no baseline to drift from
    else:
        # Locked until the version commits (§861): its file is named by the
        # number, and an unlocked read let another writer take it too.
        cur.execute(
            "SELECT current_version, table_schema FROM datasets WHERE id = %s FOR UPDATE",
            (str(dataset_id),),
        )
        row = cur.fetchone()
        if row is None:
            raise engine.DatasetEngineError("the synced dataset no longer exists")
        schema_changes = engine.diff_schemas(_stored_schema(row[1]), schema)
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

    # The dataset's schema policy (migration 0023) is enforced by a trigger
    # here, so a refusal arrives as a database error rather than a check this
    # code made; translated so per-connection isolation records it as this
    # connection's failed run instead of crashing the whole batch.
    try:
        cur.execute(
            """
            INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                          table_schema, row_count, produced_by_kind,
                                          produced_by_id, sync_cursor_value, transaction_type)
            VALUES (%s, %s, %s, %s, %s, 'sync', %s, %s, %s)
            """,
            (str(dataset_id), version, parquet_key, schema_json, row_count, str(connection_id),
             cursor_value, transaction_type),
        )
    except psycopg.Error as exc:
        raise (engine.schema_policy_error(exc) or exc) from exc
    return dataset_id, schema_changes


def _run_file_sync(
    platform_db: PlatformDatabase, storage, *, connection_id: UUID, workspace_id: UUID,
    project_id: UUID, config: dict, secret: dict, policies: list, folder: str,
    dataset_name: str, dataset_id: UUID | None, transaction: str, filters: dict,
) -> "tuple[UUID | None, int]":
    """A file sync's scheduled run (§750; decision 0021) - the API's
    `file_syncs.record` and its route, as the worker writes them. Which files
    it takes and what the view becomes is `file_sync_rules`, the same file the
    API runs. Returns (dataset id, rows in the files taken); a run with
    nothing to take writes no version.
    """
    import duckdb

    connector = get_connector("s3")
    with egress.restricted_to(policies):
        listing = connector.list_folder(config, secret, folder=folder)
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT path, size, modified FROM sync_files WHERE connection_id = %s",
                        (str(connection_id),))
            seen = {p: {"size": int(s), "modified": m} for p, s, m in cur.fetchall()}
            held = []
            if dataset_id is not None:
                cur.execute("SELECT filename FROM dataset_files WHERE dataset_id = %s "
                            "ORDER BY uploaded_at, filename", (str(dataset_id),))
                held = [r[0] for r in cur.fetchall()]
            ws_prefix = _workspace_s3_prefix(cur, workspace_id)
        conn.commit()

    taken = rules.select(listing, filters, seen)
    if not taken:
        return dataset_id, 0
    if sum(int(f["size"]) for f in taken) > MAX_SYNC_BYTES:
        raise engine.DatasetEngineError(
            f"the files this run would take exceed the {MAX_SYNC_BYTES // (1024 * 1024)} MB "
            "sync limit - a limit filter takes them a batch at a time")
    if dataset_id is not None and not held:
        # The API's rule: a dataset holding none of this sync's files gets a
        # new view, whatever the sync's type.
        transaction = "SNAPSHOT"
    target = dataset_id or uuid4()
    prefix = storage_prefix(ws_prefix, target)
    view = rules.view_after(transaction, held, [f["path"] for f in taken])

    with tempfile.TemporaryDirectory() as tmp:
        parts, written, rows_taken = {}, {}, 0
        for index, f in enumerate(taken):
            extension = os.path.splitext(f["path"])[1].lower()
            local = os.path.join(tmp, f"{index}{extension}")
            with egress.restricted_to(policies):
                connector.fetch_file(config, secret, folder=folder, path=f["path"], dest=local)
            dest = os.path.join(tmp, f"{index}.parquet")
            try:
                _schema, rows = _ingest_file(local, extension, dest)
            except (duckdb.Error, engine.DatasetEngineError) as exc:
                # Named by the file, as the API names it.
                raise engine.DatasetEngineError(f"{f['path']} could not be read: {exc}") from exc
            rows_taken += rows
            parts[f["path"]] = dest
            written[rules.file_key(prefix, f["path"], f["size"], f.get("modified"))] = dest
        for path in view:
            if path not in parts:
                before = seen[path]
                parts[path] = storage.local_path(
                    rules.file_key(prefix, path, before["size"], before.get("modified")))
        out = os.path.join(tmp, "data.parquet")
        schema, view_rows = engine.combine_parquets([(p, parts[p]) for p in view], out)
        for key, local in written.items():
            with open(local, "rb") as handle:
                storage.put(key, handle.read())
        with open(out, "rb") as handle:
            parquet = handle.read()

    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            dataset, _changes = _record_synced_dataset(
                cur, storage, connection_id=connection_id, dataset_name=dataset_name,
                dataset_id=dataset_id, project_id=project_id, workspace_id=workspace_id,
                parquet_bytes=parquet, schema=schema, row_count=view_rows,
                transaction_type=transaction, new_id=target,
            )
            cur.execute("SELECT current_version FROM datasets WHERE id = %s", (str(dataset),))
            version = int(cur.fetchone()[0])
            if transaction == "SNAPSHOT":
                cur.execute("DELETE FROM dataset_files WHERE dataset_id = %s", (str(dataset),))
            for f in taken:
                cur.execute("""
                    INSERT INTO dataset_files (dataset_id, filename, uploaded_by, version_number)
                    VALUES (%s, %s, NULL, %s)
                    ON CONFLICT (dataset_id, filename) DO UPDATE
                        SET uploaded_by = NULL, uploaded_at = now(),
                            version_number = EXCLUDED.version_number
                """, (str(dataset), f["path"], version))
                cur.execute("""
                    INSERT INTO sync_files (connection_id, path, size, modified)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (connection_id, path) DO UPDATE
                        SET size = EXCLUDED.size, modified = EXCLUDED.modified, synced_at = now()
                """, (str(connection_id), f["path"], int(f["size"]), f.get("modified")))
        conn.commit()
    return dataset, rows_taken


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
                # This pass's, or another's (§854): see claims.py.
                if not claim_due(cur, "connections", connection_id, schedule="sync_schedule",
                                 next_run="sync_next_run_at", warn=context.log.warning):
                    continue
                cur.execute(
                    """
                    SELECT project_id, config, secret_arn, sync_mode, sync_schedule,
                           sync_source_schema, sync_source_table, sync_dataset_name,
                           sync_dataset_id, sync_primary_key_column, sync_cursor_column,
                           sync_last_cursor_value, source_type, resource_id,
                           sync_file_transaction, sync_file_filters
                      FROM connections WHERE id = %s
                    """,
                    (connection_id,),
                )
                row = cur.fetchone()
                if row is None or row[4] is None:
                    continue  # unscheduled since discovery - re-verified
                (project_id, config, secret_arn, mode, _schedule, source_schema, source_table,
                 dataset_name, dataset_id, primary_key_column, cursor_column, last_cursor,
                 source_type, resource_id, file_transaction, file_filters) = row
                # Only the table half is required. An empty source_schema is
                # legitimate for object storage - it means "at the root of the
                # connection's configured prefix" - so testing it for
                # truthiness here would silently skip every root-level file
                # sync, logging "no sync target set" about a target that is
                # perfectly well set.
                if not source_table and mode != "files":
                    context.log.warning("connection %s has a schedule but no sync target set", connection_id)
                    continue
                source_schema = source_schema or ""
                # §263: the source's egress policies, read in the same scoped
                # transaction as the row they belong to. The worker resolves
                # this itself rather than inheriting an ambient scope, because
                # it has no request to inherit one from — a scheduled sync is
                # the one outbound path with no caller at all.
                cur.execute(
                    "SELECT host, port, description FROM egress_policies"
                    " WHERE connection_id = %s",
                    (connection_id,),
                )
                policies = [
                    {"host": h, "port": p, "description": d}
                    for h, p, d in cur.fetchall()
                ]
            conn.commit()

        ok, error, rows_synced = True, None, 0
        # §599: a source configured for OpenID Connect is told who it is, to
        # mint its token when it connects; any other reads what it stored.
        secret = oidc.source_credentials(config, resource_id) or _read_secret(secret_arn)
        new_cursor_value = last_cursor
        if mode == "files":
            # A folder (decision 0021): the API's run, on the schedule.
            try:
                taken_dataset, rows_synced = _run_file_sync(
                    platform_db, storage,
                    connection_id=UUID(str(connection_id)), workspace_id=UUID(str(workspace_id)),
                    project_id=UUID(str(project_id)), config=config, secret=secret,
                    policies=policies, folder=source_schema or "",
                    dataset_name=dataset_name or (source_schema or "files").rsplit("/", 1)[-1],
                    dataset_id=UUID(str(dataset_id)) if dataset_id else None,
                    transaction=file_transaction or "SNAPSHOT", filters=file_filters or {},
                )
                status, error = "succeeded", None
            except (
                ConnectorError,
                egress.EgressRefused,
                engine.DatasetEngineError,
                LookupError,
                OSError,
                StorageKeyError,
            ) as exc:
                ok, error, status, taken_dataset = False, str(exc), "failed", dataset_id
            with platform_db.connect_scoped_to(workspace_id) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sync_runs (connection_id, dataset_id, mode, source_table, "
                        "status, rows_synced, error, finished_at) "
                        "VALUES (%s, %s, 'files', %s, %s, %s, %s, now())",
                        (str(connection_id), str(taken_dataset) if taken_dataset else None,
                         source_schema or "/", status, rows_synced, error),
                    )
                conn.commit()
        else:
            try:
                connector = get_connector(source_type)
                with egress.restricted_to(policies), tempfile.TemporaryDirectory() as tmp:
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

                    # An empty extract means the source had nothing at all (a REST
                    # collection that is simply empty, an object that has not been
                    # rewritten). With a dataset already in place there is nothing
                    # to do in either mode; without one, full mode has no schema to
                    # infer and says so rather than failing inside DuckDB.
                    if extract.empty and dataset_id is None:
                        raise engine.DatasetEngineError(
                            "the source returned no records, so there is nothing to "
                            "create a dataset from yet"
                        )
                    nothing_new = dataset_id is not None and (
                        extract.empty or (mode == "incremental" and new_row_count == 0)
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
                        # Whether this run replaced a row of the view (§747).
                        transaction_type = engine.merge_transaction(
                            storage_local, new_parquet, primary_key_column)
                    else:
                        final_parquet = new_parquet
                        rows_synced = new_row_count
                        transaction_type = "SNAPSHOT"

                    if not nothing_new:
                        with open(final_parquet, "rb") as handle:
                            parquet_bytes = handle.read()

                with platform_db.connect_scoped_to(workspace_id) as conn:
                    with conn.cursor() as cur:
                        if nothing_new:
                            new_dataset_id = dataset_id
                            schema_changes = None
                        else:
                            new_dataset_id, schema_changes = _record_synced_dataset(
                                cur, storage,
                                connection_id=UUID(str(connection_id)),
                                dataset_name=dataset_name or source_table,
                                dataset_id=UUID(str(dataset_id)) if dataset_id else None,
                                project_id=UUID(str(project_id)), workspace_id=UUID(str(workspace_id)),
                                parquet_bytes=parquet_bytes, schema=schema, row_count=rows_synced,
                                cursor_value=new_cursor_value if mode == "incremental" else None,
                                transaction_type=transaction_type,
                            )
                        cur.execute(
                            "INSERT INTO sync_runs (connection_id, dataset_id, mode, source_table, "
                            "status, rows_synced, finished_at, schema_changes) "
                            "VALUES (%s, %s, %s, %s, 'succeeded', %s, now(), %s)",
                            (str(connection_id), str(new_dataset_id), mode,
                             f"{source_schema}.{source_table}", rows_synced,
                             json.dumps(schema_changes) if schema_changes else None),
                        )
                    conn.commit()
            # Every exception type on the call path, enumerated deliberately (the
            # standing checklist item from instance_syncs.py's own history): a
            # driver/extract failure (ConnectorError, including an unregistered
            # source type), a DuckDB failure, a missing workspace (LookupError), a
            # filesystem failure (OSError), a malformed storage key
            # (StorageKeyError, a ValueError subclass none of the others cover), or
            # a destination this source's egress policies do not permit.
            # Anything missed here crashes the whole batch and leaves every other
            # due connection unprocessed instead of failing just this one.
            #
            # **`EgressRefused` is here because §263 put it on the call path and
            # this list did not follow.** It is deliberately not a `ConnectorError`
            # — a refused destination is not a failure to reach one, and the API's
            # four call sites report the two differently — which is exactly what
            # made it slip past a tuple that already covered every connector fault.
            # The consequence was the one the paragraph above describes and worse:
            # one source carrying a policy would end the whole batch, so restricting
            # a single source could stop every other scheduled sync in the
            # deployment. Found by running the worker suite, which until §263
            # nothing could.
            except (
                ConnectorError,
                egress.EgressRefused,
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
