"""File-based syncs (decision 0021; `data-connection` p.160-164; §749).

> "Each run will ingest all files nested in the external system's
>  subdirectory, including files ingested in previous runs, and commit a
>  SNAPSHOT transaction to the output dataset containing exactly those files."
>  (p.160)

A connection whose managed sync is of mode `files` syncs a **subfolder**: each
run lists it, takes the files p.164's filters leave, reads each into its own
Parquet, and commits the dataset's files as one version of p.160's transaction
type. The pure half (`parse_filters`, `check`, `select`, `view_after`) decides
which files and what the view becomes; `record` writes it.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from . import dataset_engine as engine
from . import datasets as ds_service
from .storage import StorageGateway

#: p.160's "Transaction type" (decision 0020).
TRANSACTIONS = ("SNAPSHOT", "APPEND", "UPDATE")

#: A regex a person typed, run against every path in a folder. Bounded so a
#: filter cannot be an essay.
MAX_PATTERN = 200


class FileSyncError(ValueError):
    """A file sync that cannot be saved or cannot run, in a sentence."""


def _when(value: str) -> datetime:
    """A date or date-time, in UTC."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _stamp(value: datetime) -> str:
    """The connector's own format for LastModified (`_s3_timestamp`), so the
    two compare as strings."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f%z")


def parse_filters(raw: Any) -> dict[str, Any]:
    """p.164's filters, checked and normalised. Absent keys are filters not
    set; unknown keys are refused rather than kept, since a stored setting
    nothing reads is a control that cannot work."""
    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise FileSyncError("filters are an object of p.164's filters")
    known = {"exclude_synced", "path_matches", "path_not_matches", "any_path_matches",
             "modified_after", "size_min", "size_max", "at_least", "limit"}
    unknown = sorted(set(raw) - known)
    if unknown:
        raise FileSyncError(f"unknown filter {', '.join(unknown)}")
    out: dict[str, Any] = {}
    excluded = raw.get("exclude_synced")
    if excluded not in (None, False):
        if excluded is True:
            excluded = {}
        if not isinstance(excluded, dict) or set(excluded) - {"by_modified", "by_size"}:
            raise FileSyncError(
                "exclude_synced is true, or {by_modified, by_size} for p.164's options")
        out["exclude_synced"] = {"by_modified": bool(excluded.get("by_modified")),
                                 "by_size": bool(excluded.get("by_size"))}
    for key in ("path_matches", "path_not_matches", "any_path_matches"):
        pattern = raw.get(key)
        if pattern in (None, ""):
            continue
        if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN:
            raise FileSyncError(f"{key} is a regular expression of up to {MAX_PATTERN} characters")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise FileSyncError(f"{key} is not a regular expression: {exc}") from exc
        out[key] = pattern
    if raw.get("modified_after") not in (None, ""):
        try:
            out["modified_after"] = _stamp(_when(str(raw["modified_after"])))
        except ValueError as exc:
            raise FileSyncError("modified_after is a date, like 2026-01-31") from exc
    for key, least in (("size_min", 0), ("size_max", 0), ("at_least", 1), ("limit", 1)):
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < least:
            raise FileSyncError(f"{key} is a whole number of at least {least}")
        out[key] = value
    if "size_min" in out and "size_max" in out and out["size_min"] > out["size_max"]:
        raise FileSyncError("size_min is larger than size_max, so no file could pass")
    return out


def check(transaction: str, filters: dict[str, Any]) -> None:
    """Refuse the settings p.160-162 call contradictory where they would make
    a run do something other than its type says (decision 0021 §2)."""
    if transaction not in TRANSACTIONS:
        raise FileSyncError(f"a file sync's transaction type is one of {', '.join(TRANSACTIONS)}")
    excluded = filters.get("exclude_synced")
    if transaction == "APPEND":
        if excluded is None:
            raise FileSyncError(
                "an APPEND file sync needs Exclude files already synced: without it every "
                "run adds every file again, and the dataset holds each row once per run"
            )
        if excluded["by_modified"] or excluded["by_size"]:
            raise FileSyncError(
                "p.161: Exclude files already synced with the modified date or size option "
                "would re-ingest a changed file in an APPEND, duplicating its rows. A file "
                "that changes needs an UPDATE file sync"
            )
    if transaction == "UPDATE" and not (excluded and (excluded["by_modified"]
                                                      or excluded["by_size"])):
        raise FileSyncError(
            "an UPDATE file sync needs Exclude files already synced with the modified date "
            "or size option, or it can never see a file change - and then it is an APPEND"
        )


def select(
    listing: list[dict[str, Any]], filters: dict[str, Any],
    seen: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The files a run takes: `listing` (as `list_folder` returns it) through
    p.164's filters, oldest first so a limited run drains a backlog in order.
    `seen` is `sync_files`: every file this sync has taken, by path."""
    files = sorted(listing, key=lambda f: (f.get("modified") or "", f["path"]))
    if "path_matches" in filters:
        files = [f for f in files if re.search(filters["path_matches"], f["path"])]
    if "path_not_matches" in filters:
        files = [f for f in files if not re.search(filters["path_not_matches"], f["path"])]
    if "modified_after" in filters:
        files = [f for f in files if (f.get("modified") or "") > filters["modified_after"]]
    if "size_min" in filters:
        files = [f for f in files if f["size"] >= filters["size_min"]]
    if "size_max" in filters:
        files = [f for f in files if f["size"] <= filters["size_max"]]
    if "any_path_matches" in filters and not any(
            re.search(filters["any_path_matches"], f["path"]) for f in files):
        # p.164: "If any file has a relative path matching the regular
        # expression, sync all files in the subfolder that are not otherwise
        # filtered" - and none does.
        return []
    excluded = filters.get("exclude_synced")
    if excluded is not None:
        def changed(f: dict[str, Any]) -> bool:
            before = seen.get(f["path"])
            if before is None:
                return True
            return ((excluded["by_modified"] and before.get("modified") != f.get("modified"))
                    or (excluded["by_size"] and int(before["size"]) != int(f["size"])))
        files = [f for f in files if changed(f)]
    if len(files) < filters.get("at_least", 0):
        return []
    if "limit" in filters:
        files = files[:filters["limit"]]
    return files


def view_after(transaction: str, held: list[str], taken: list[str]) -> list[str]:
    """The dataset's files after a run, in the order they are read: a
    SNAPSHOT is exactly what it took (p.160, p.162), an APPEND or UPDATE is
    what was held with what it took added, a path it took again replacing
    the old (p.161-162)."""
    if transaction == "SNAPSHOT":
        return list(taken)
    return [path for path in held if path not in taken] + list(taken)


def file_key(dataset_prefix: str, path: str, size: int, modified: str | None) -> str:
    """Where one synced file's rows are kept. Named by the file *as it was
    taken*, so a run that fails after writing it leaves the key the dataset's
    files still name untouched."""
    name = hashlib.sha256(f"{path}\n{size}\n{modified or ''}".encode()).hexdigest()[:32]
    return f"{dataset_prefix}files/{name}.parquet"


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
        storage.put(key, data)

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
