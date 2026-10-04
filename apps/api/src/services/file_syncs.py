"""File-based syncs (decision 0021; `data-connection` p.160-164; §749).

> "Each run will ingest all files nested in the external system's
>  subdirectory, including files ingested in previous runs, and commit a
>  SNAPSHOT transaction to the output dataset containing exactly those files."
>  (p.160)

A connection whose managed sync is of mode `files` syncs a **subfolder**: each
run lists it, takes the files p.164's filters leave, reads each into its own
Parquet, and commits the dataset's files as one version of p.160's transaction
type. The pure half (`file_sync_rules`, which the worker runs as the same file)
decides which files and what the view becomes; `record` writes it.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from . import dataset_engine as engine
from . import datasets as ds_service
from .file_sync_rules import (  # noqa: F401 (the rules, re-exported for callers)
    MAX_PATTERN, TRANSACTIONS, FileSyncError, check, file_key, parse_filters, select,
    view_after,
)
from .storage import StorageGateway


async def seen(conn: AsyncConnection, connection_id: UUID) -> dict[str, dict[str, Any]]:
    rows = await fetch_all(
        conn, "SELECT path, size, modified FROM sync_files WHERE connection_id = :cid",
        {"cid": str(connection_id)})
    return {str(r["path"]): {"size": int(r["size"]), "modified": r["modified"]} for r in rows}


async def record(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    connection_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    folder: str,
    dataset_name: str,
    transaction: str,
    taken: list[tuple[dict[str, Any], str]],
    requested_by: UUID,
) -> tuple[dict[str, Any], int, bool]:
    """Commit one run: `taken` is each file (as `select` chose it) and where it
    was downloaded. Returns (dataset row, rows in the files taken, created).

    **Everything is read before anything is written** (p.163: "If a sync fails
    at any point, the transaction is aborted and none of the files from that
    run are committed"). A file that does not parse, or whose columns differ
    from the view's, fails the run with its path named.
    """
    from anyio import to_thread

    slug = ds_service.slugify(dataset_name)
    from .sync import find_existing_sync_dataset

    existing = await find_existing_sync_dataset(conn, project_id, connection_id, slug)
    dataset_id = UUID(str(existing["id"])) if existing else uuid4()
    prefix = ds_service.storage_prefix(
        await ds_service.workspace_s3_prefix(conn, workspace_id), dataset_id)
    held = [str(r["filename"]) for r in await fetch_all(
        conn, "SELECT filename FROM dataset_files WHERE dataset_id = :did "
        "ORDER BY uploaded_at, filename", {"did": str(dataset_id)})] if existing else []
    known = await seen(conn, connection_id)
    if existing is not None and not held:
        # The dataset has versions and none of this sync's files - it was made
        # before (by a one-object sync, say). What this run writes is all it
        # holds, so it is a new view whatever the sync's type, and saying
        # APPEND would claim the rows before it are still there.
        transaction = "SNAPSHOT"
    taken_paths = [f["path"] for f, _local in taken]
    view = view_after(transaction, held, taken_paths)

    def work() -> tuple[list[engine.ColumnSchema], int, int, bytes, dict[str, bytes]]:
        with tempfile.TemporaryDirectory() as tmp:
            parts: dict[str, str] = {}
            written: dict[str, bytes] = {}
            rows_taken = 0
            for index, (f, local) in enumerate(taken):
                dest = os.path.join(tmp, f"{index}.parquet")
                try:
                    _schema, rows = engine.ingest_to_parquet(
                        local, os.path.splitext(f["path"])[1].lower(), dest)
                except engine.DatasetEngineError as exc:
                    raise FileSyncError(f"{f['path']} could not be read: {exc}") from exc
                rows_taken += rows
                parts[f["path"]] = dest
                with open(dest, "rb") as handle:
                    written[file_key(prefix, f["path"], f["size"], f.get("modified"))] = handle.read()
            for path in view:
                if path not in parts:
                    before = known[path]
                    parts[path] = storage.local_path(
                        file_key(prefix, path, before["size"], before.get("modified")))
            out = os.path.join(tmp, "data.parquet")
            try:
                schema, rows = engine.combine_parquets([(p, parts[p]) for p in view], out)
            except engine.DatasetEngineError as exc:
                raise FileSyncError(str(exc)) from exc
            with open(out, "rb") as handle:
                return schema, rows, rows_taken, handle.read(), written

    schema, view_rows, rows_taken, parquet, written = await to_thread.run_sync(work)
    for key, data in written.items():
        await to_thread.run_sync(storage.put, key, data)

    created = existing is None
    if created:
        await conn.execute(_text("""
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description, origin,
                                  connection_id, s3_location, current_version, created_by)
            VALUES (:id, :pid, :wid, :name, :slug, :descr, 'sync', :cid, :loc, 0, :by)
        """), {"id": str(dataset_id), "pid": str(project_id), "wid": str(workspace_id),
               "name": dataset_name, "slug": slug,
               "descr": f"Files synced from {folder or 'the source'}",
               "cid": str(connection_id), "loc": prefix, "by": str(requested_by)})
    row = await ds_service.add_version(
        conn, storage, dataset_id=dataset_id, workspace_id=workspace_id,
        parquet_bytes=parquet, schema=schema, row_count=view_rows,
        produced_by_kind="sync", produced_by_id=connection_id, created_by=requested_by,
        transaction_type=transaction,
    )
    version = int(row["current_version"])
    if transaction == "SNAPSHOT":
        await conn.execute(_text("DELETE FROM dataset_files WHERE dataset_id = :did"),
                           {"did": str(dataset_id)})
    for f, _local in taken:
        await ds_service.record_file(conn, dataset_id, f["path"], requested_by,
                                     version_number=version)
        await conn.execute(_text("""
            INSERT INTO sync_files (connection_id, path, size, modified)
            VALUES (:cid, :path, :size, :modified)
            ON CONFLICT (connection_id, path) DO UPDATE
                SET size = EXCLUDED.size, modified = EXCLUDED.modified, synced_at = now()
        """), {"cid": str(connection_id), "path": f["path"], "size": int(f["size"]),
               "modified": f.get("modified")})
    await conn.execute(_text("UPDATE connections SET sync_dataset_id = :did WHERE id = :cid"),
                       {"did": str(dataset_id), "cid": str(connection_id)})
    out = await fetch_one(
        conn, "SELECT id, name, slug, row_count, current_version FROM datasets WHERE id = :id",
        {"id": str(dataset_id)})
    assert out is not None
    return dict(out), rows_taken, created
