"""Connection sync (spec §"Connections" sync modes; §17 trigger sync).

Full-snapshot sync of one source table into the datasets layer:

    source table --COPY csv--> temp file --DuckDB--> parquet --> storage
                                                      |
                                    dataset row (origin='sync') + version

First sync of a table creates the dataset; later syncs of the same table via
the same connection append a version and roll current_version forward — the
dataset_versions machinery from the upload path, exercised for real.

Incremental mode: pulls only rows where the connection's configured cursor
column exceeds its stored sync_last_cursor_value, then upserts them into the
existing dataset by primary key (dataset_engine.merge_incremental) rather
than replacing it outright. Progress (sync_last_cursor_value) and the
schedule (sync_next_run_at) are the same columns the worker's
scheduled_connection_syncs job advances on its own cadence (migration
0014) — this module's run_incremental_sync is what a manual "run now"
click uses; the worker runs the identical steps on a timer.

Scope in this slice (each flagged where it bites):
  * CSV as the wire format between source and DuckDB: types are re-inferred,
    which is faithful for common shapes (numbers, timestamps, text) but
    flattens exotic types to text. Flagged for review: the Iceberg writer in
    the production data plane preserves source types.
  * Size cap mirrors the interactive cap; beyond it the answer is the worker
    path, not a 30-minute request.

Identifier safety: source schema/table names must match a strict pattern and
are then double-quoted — user input never reaches SQL unquoted.
"""
from __future__ import annotations

import os
import re
import tempfile
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError
from . import dataset_engine as engine
from . import datasets as ds_service
from .connectors import ConnectorOperationError, PostgresConfig
from .secrets import SecretsGateway
from .storage import StorageGateway

MAX_SYNC_BYTES = 200 * 1024 * 1024  # flag: worker/Athena path beyond this

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]{0,62}$")


class SyncError(RuntimeError):
    """User-safe sync failure."""


def _quote_ident(name: str) -> str:
    if not _IDENT_RE.match(name):
        raise SyncError(f"invalid identifier {name!r}")
    return '"' + name.replace('"', '""') + '"'


def _conninfo(config: dict[str, Any], secret: dict[str, str]) -> dict[str, Any]:
    cfg = PostgresConfig(**config)
    return {
        "host": cfg.host,
        "port": cfg.port,
        "dbname": cfg.database,
        "user": cfg.user,
        "password": secret.get("password", ""),
        "sslmode": cfg.sslmode,
        "connect_timeout": 8,
    }


def snapshot_source_table(
    config: dict[str, Any],
    secret: dict[str, str],
    source_schema: str,
    source_table: str,
    dest_csv: str,
    cursor_column: str | None = None,
    cursor_value: str | None = None,
) -> None:
    """COPY the table (optionally filtered to rows newer than cursor_value)
    to a CSV file, byte-capped. Synchronous; run in a worker thread."""
    import psycopg
    from psycopg import sql

    qualified = f"{_quote_ident(source_schema)}.{_quote_ident(source_table)}"
    conninfo = _conninfo(config, secret)
    if cursor_column and cursor_value is not None:
        query = sql.SQL(
            "COPY (SELECT * FROM {} WHERE {} > {}) TO STDOUT (FORMAT csv, HEADER true)"
        ).format(sql.SQL(qualified), sql.Identifier(cursor_column), sql.Literal(cursor_value))
    else:
        query = sql.SQL("COPY (SELECT * FROM {}) TO STDOUT (FORMAT csv, HEADER true)").format(
            sql.SQL(qualified)
        )

    written = 0
    try:
        with psycopg.connect(**conninfo) as conn:
            with conn.cursor() as cur, open(dest_csv, "wb") as out:
                with cur.copy(query) as copy:
                    for chunk in copy:
                        written += len(chunk)
                        if written > MAX_SYNC_BYTES:
                            cap_mb = MAX_SYNC_BYTES // (1024 * 1024)
                            raise SyncError(
                                f"table exceeds the {cap_mb} MB interactive sync limit — "
                                "scheduled worker syncs handle larger tables"
                            )
                        out.write(bytes(chunk))
    except psycopg.errors.UndefinedTable as exc:
        raise SyncError(f"table {source_schema}.{source_table} does not exist") from exc
    except psycopg.errors.InsufficientPrivilege as exc:
        raise SyncError(
            f"the connection's user cannot read {source_schema}.{source_table}"
        ) from exc
    except psycopg.OperationalError as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        raise ConnectorOperationError(reason) from exc


def max_cursor_value(
    config: dict[str, Any],
    secret: dict[str, str],
    source_schema: str,
    source_table: str,
    cursor_column: str,
) -> str | None:
    """The highest cursor value currently in the source table — becomes the
    connection's new sync_last_cursor_value once the sync succeeds."""
    import psycopg
    from psycopg import sql

    qualified = f"{_quote_ident(source_schema)}.{_quote_ident(source_table)}"
    query = sql.SQL("SELECT max({}) FROM {}").format(sql.Identifier(cursor_column), sql.SQL(qualified))
    try:
        with psycopg.connect(**_conninfo(config, secret)) as conn:
            with conn.cursor() as cur:
                cur.execute(query)
                row = cur.fetchone()
    except psycopg.OperationalError as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else "connection failed"
        raise ConnectorOperationError(reason) from exc
    return None if row is None or row[0] is None else str(row[0])


async def find_existing_sync_dataset(
    conn: AsyncConnection, project_id: UUID, connection_id: UUID, slug: str
) -> dict[str, Any] | None:
    return await fetch_one(
        conn,
        """
        SELECT id, name, slug, origin, connection_id, current_version
          FROM datasets
         WHERE project_id = :pid AND slug = :slug
        """,
        {"pid": str(project_id), "slug": slug},
    )


async def run_full_sync(
    conn: AsyncConnection,
    storage: StorageGateway,
    secrets: SecretsGateway,
    *,
    connection_row: dict[str, Any],
    workspace_id: UUID,
    project_id: UUID,
    source_schema: str,
    source_table: str,
    dataset_name: str | None,
    requested_by: UUID,
    snapshot_csv_path: str,
) -> tuple[dict[str, Any], int, bool]:
    """DB half of a sync, called after snapshot_source_table produced the CSV.
    Returns (dataset row, rows_synced, created_new_dataset)."""
    name = dataset_name or source_table
    slug = ds_service.slugify(name)

    with tempfile.TemporaryDirectory() as tmp:
        parquet_tmp = os.path.join(tmp, "data.parquet")
        try:
            schema, row_count = engine.ingest_to_parquet(
                snapshot_csv_path, ".csv", parquet_tmp
            )
        except engine.DatasetEngineError as exc:
            raise SyncError(str(exc)) from exc
        with open(parquet_tmp, "rb") as handle:
            parquet_bytes = handle.read()

    existing = await find_existing_sync_dataset(
        conn, project_id, UUID(str(connection_row["id"])), slug
    )
    ws_prefix = await ds_service.workspace_s3_prefix(conn, workspace_id)

    import json

    schema_json = json.dumps([c.as_dict() for c in schema])

    if existing is None:
        dataset_id = uuid4()
        parquet_key = f"{ds_service.storage_prefix(ws_prefix, dataset_id)}v1/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        row = await fetch_one(
            conn,
            """
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                                  origin, connection_id, s3_location, table_schema,
                                  row_count, current_version, created_by)
            VALUES (:id, :pid, :wid, :name, :slug, :descr, 'sync', :cid, :loc,
                    CAST(:schema AS jsonb), :rows, 1, :by)
            RETURNING id, name, slug, row_count, current_version
            """,
            {
                "id": str(dataset_id),
                "pid": str(project_id),
                "wid": str(workspace_id),
                "name": name,
                "slug": slug,
                "descr": f"Synced from {source_schema}.{source_table}",
                "cid": str(connection_row["id"]),
                "loc": parquet_key,
                "schema": schema_json,
                "rows": row_count,
                "by": str(requested_by),
            },
        )
        assert row is not None
        version = 1
        created = True
    else:
        # Re-sync: the slug must belong to this connection's synced dataset —
        # a name collision with an upload or another connection is a conflict,
        # not an overwrite.
        if existing["origin"] != "sync" or str(existing["connection_id"]) != str(
            connection_row["id"]
        ):
            raise ConflictError(
                f"a different dataset already uses the name '{slug}' in this project"
            )
        version = int(existing["current_version"]) + 1
        dataset_id = UUID(str(existing["id"]))
        parquet_key = (
            f"{ds_service.storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
        )
        storage.put(parquet_key, parquet_bytes)
        row = await fetch_one(
            conn,
            """
            UPDATE datasets
               SET s3_location = :loc,
                   table_schema = CAST(:schema AS jsonb),
                   row_count = :rows,
                   current_version = :version
             WHERE id = :id
            RETURNING id, name, slug, row_count, current_version
            """,
            {
                "loc": parquet_key,
                "schema": schema_json,
                "rows": row_count,
                "version": version,
                "id": str(dataset_id),
            },
        )
        assert row is not None
        created = False

    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind,
                                      produced_by_id, created_by)
        VALUES (:did, :version, :key, CAST(:schema AS jsonb), :rows, 'sync', :cid, :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id),
            "version": version,
            "key": parquet_key,
            "schema": schema_json,
            "rows": row_count,
            "cid": str(connection_row["id"]),
            "by": str(requested_by),
        },
    )
    return dict(row), row_count, created


# ---- sync_runs bookkeeping ---------------------------------------------------
async def run_incremental_sync(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    connection_row: dict[str, Any],
    workspace_id: UUID,
    project_id: UUID,
    source_schema: str,
    source_table: str,
    dataset_name: str | None,
    primary_key_column: str,
    new_cursor_value: str | None,
    requested_by: UUID,
    snapshot_csv_path: str,
) -> tuple[dict[str, Any], int, bool]:
    """DB half of an incremental sync, called after snapshot_source_table
    (cursor-filtered) produced the CSV of just the new/changed rows.
    Upserts them into the connection's existing sync_dataset_id by primary
    key (dataset_engine.merge_incremental) rather than replacing the
    dataset outright. Returns (dataset row, row count in the result,
    created_new_dataset). Shares its versioning shape with run_full_sync;
    kept separate because the merge step has no full-sync equivalent."""
    import json

    name = dataset_name or source_table
    slug = ds_service.slugify(name)
    existing_dataset_id = connection_row.get("sync_dataset_id")

    with tempfile.TemporaryDirectory() as tmp:
        new_parquet = os.path.join(tmp, "new.parquet")
        try:
            _, new_row_count = engine.ingest_to_parquet(snapshot_csv_path, ".csv", new_parquet)
        except engine.DatasetEngineError as exc:
            raise SyncError(str(exc)) from exc

        if new_row_count == 0 and existing_dataset_id is not None:
            # Nothing changed since the last cursor value — the steady state
            # for a cron-scheduled sync between source writes. Skip the merge
            # outright: an empty CSV (header only) gives DuckDB nothing to
            # infer column types from, so it falls back to VARCHAR for every
            # column, which then fails to compare against the existing
            # (correctly-typed) dataset in the primary-key anti-join.
            existing = await fetch_one(
                conn, "SELECT id, name, slug, row_count, current_version FROM datasets WHERE id = :did",
                {"did": str(existing_dataset_id)},
            )
            if existing is None:
                raise SyncError("the synced dataset no longer exists")
            from sqlalchemy import text as _text_noop

            await conn.execute(
                _text_noop("UPDATE connections SET sync_last_cursor_value = :cur WHERE id = :cid"),
                {"cur": new_cursor_value, "cid": str(connection_row["id"])},
            )
            return dict(existing), int(existing["row_count"]), False

        existing_local_path = None
        if existing_dataset_id is not None:
            existing_row = await fetch_one(
                conn, "SELECT s3_location FROM datasets WHERE id = :did",
                {"did": str(existing_dataset_id)},
            )
            if existing_row is None:
                raise SyncError("the synced dataset no longer exists")
            existing_local_path = storage.local_path(existing_row["s3_location"])

        merged_parquet = os.path.join(tmp, "merged.parquet")
        try:
            schema, row_count = engine.merge_incremental(
                existing_local_path, new_parquet, primary_key_column, merged_parquet
            )
        except engine.DatasetEngineError as exc:
            raise SyncError(str(exc)) from exc
        with open(merged_parquet, "rb") as handle:
            parquet_bytes = handle.read()

    ws_prefix = await ds_service.workspace_s3_prefix(conn, workspace_id)
    schema_json = json.dumps([c.as_dict() for c in schema])

    if existing_dataset_id is None:
        dataset_id = uuid4()
        parquet_key = f"{ds_service.storage_prefix(ws_prefix, dataset_id)}v1/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        row = await fetch_one(
            conn,
            """
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                                  origin, connection_id, s3_location, table_schema,
                                  row_count, current_version, created_by)
            VALUES (:id, :pid, :wid, :name, :slug, :descr, 'sync', :cid, :loc,
                    CAST(:schema AS jsonb), :rows, 1, :by)
            RETURNING id, name, slug, row_count, current_version
            """,
            {
                "id": str(dataset_id), "pid": str(project_id), "wid": str(workspace_id),
                "name": name, "slug": slug,
                "descr": f"Incremental sync from {source_schema}.{source_table}",
                "cid": str(connection_row["id"]), "loc": parquet_key,
                "schema": schema_json, "rows": row_count, "by": str(requested_by),
            },
        )
        assert row is not None
        version = 1
        created = True
        from sqlalchemy import text as _text

        await conn.execute(
            _text("UPDATE connections SET sync_dataset_id = :did WHERE id = :cid"),
            {"did": str(dataset_id), "cid": str(connection_row["id"])},
        )
    else:
        dataset_id = UUID(str(existing_dataset_id))
        existing = await fetch_one(
            conn, "SELECT current_version FROM datasets WHERE id = :did", {"did": str(dataset_id)}
        )
        if existing is None:
            raise SyncError("the synced dataset no longer exists")
        version = int(existing["current_version"]) + 1
        parquet_key = f"{ds_service.storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        row = await fetch_one(
            conn,
            """
            UPDATE datasets
               SET s3_location = :loc, table_schema = CAST(:schema AS jsonb),
                   row_count = :rows, current_version = :version
             WHERE id = :did
            RETURNING id, name, slug, row_count, current_version
            """,
            {
                "loc": parquet_key, "schema": schema_json, "rows": row_count,
                "version": version, "did": str(dataset_id),
            },
        )
        assert row is not None
        created = False

    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind,
                                      produced_by_id, created_by)
        VALUES (:did, :version, :key, CAST(:schema AS jsonb), :rows, 'sync', :cid, :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id), "version": version, "key": parquet_key,
            "schema": schema_json, "rows": row_count,
            "cid": str(connection_row["id"]), "by": str(requested_by),
        },
    )
    from sqlalchemy import text as _text2

    await conn.execute(
        _text2("UPDATE connections SET sync_last_cursor_value = :cur WHERE id = :cid"),
        {"cur": new_cursor_value, "cid": str(connection_row["id"])},
    )
    return dict(row), row_count, created


async def open_run(
    conn: AsyncConnection, *, connection_id: UUID, source_table: str, requested_by: UUID
) -> UUID:
    row = await fetch_one(
        conn,
        """
        INSERT INTO sync_runs (connection_id, mode, source_table, requested_by)
        VALUES (:cid, 'full', :table, :by)
        RETURNING id
        """,
        {"cid": str(connection_id), "table": source_table, "by": str(requested_by)},
    )
    assert row is not None
    return UUID(str(row["id"]))


async def close_run(
    conn: AsyncConnection,
    run_id: UUID,
    *,
    ok: bool,
    rows_synced: int,
    dataset_id: UUID | None,
    error: str | None,
) -> None:
    await fetch_one(
        conn,
        """
        UPDATE sync_runs
           SET status = :status, rows_synced = :rows, dataset_id = :did,
               error = :error, finished_at = now()
         WHERE id = :id
        RETURNING id
        """,
        {
            "status": "succeeded" if ok else "failed",
            "rows": rows_synced,
            "did": str(dataset_id) if dataset_id else None,
            "error": error,
            "id": str(run_id),
        },
    )


async def list_runs(conn: AsyncConnection, connection_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT r.id, r.mode, r.source_table, r.status, r.rows_synced, r.error,
               r.started_at, r.finished_at, r.dataset_id, d.name AS dataset_name
          FROM sync_runs r
          LEFT JOIN datasets d ON d.id = r.dataset_id
         WHERE r.connection_id = :cid
         ORDER BY r.started_at DESC
         LIMIT 50
        """,
        {"cid": str(connection_id)},
    )
