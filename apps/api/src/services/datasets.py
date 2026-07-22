"""Datasets service (spec §16 datasets/dataset_versions, §17 "Datasets:
CRUD, upload, preview, query, profile, schema, versions, export").

Storage layout under the workspace isolation anchor:
    {ws.s3_prefix}datasets/{dataset_id}/v{version}/data.parquet
    {ws.s3_prefix}datasets/{dataset_id}/original/{safe_filename}
Uploads are converted to canonical Parquet at ingest; the original bytes are
kept verbatim beside it ("export everything" §11 includes what you gave us).

This slice covers origin='upload'. origin='sync' rows are written by the
connection-sync worker job (next slice); origin='model_output' by the models
layer.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from .dataset_engine import ColumnSchema
from .storage import StorageGateway

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9_-]{0,61}[a-z0-9])?$")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # flag: conservative day-one cap


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-_")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


def safe_filename(filename: str) -> str:
    """Original filenames become storage-key segments; strip anything that
    isn't plainly safe and keep the extension."""
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._") or "upload"
    return cleaned[:120]


def storage_prefix(ws_s3_prefix: str, dataset_id: UUID) -> str:
    return f"{ws_s3_prefix}datasets/{dataset_id}/"


_COLUMNS = """
    id, project_id, workspace_id, name, slug, description, origin,
    connection_id, s3_location, table_schema, row_count, current_version,
    created_by, created_at, updated_at
"""


async def list_for_project(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM datasets WHERE project_id = :pid ORDER BY name",
        {"pid": str(project_id)},
    )


async def get(conn: AsyncConnection, project_id: UUID, dataset_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS} FROM datasets WHERE id = :did AND project_id = :pid",
        {"did": str(dataset_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("dataset")
    return row


async def workspace_s3_prefix(conn: AsyncConnection, workspace_id: UUID) -> str:
    row = await fetch_one(
        conn, "SELECT s3_prefix FROM workspaces WHERE id = :wid", {"wid": str(workspace_id)}
    )
    if row is None:
        raise NotFoundError("workspace")
    return str(row["s3_prefix"])


async def create_from_upload(
    conn: AsyncConnection,
    *,
    dataset_id: UUID,
    workspace_id: UUID,
    project_id: UUID,
    name: str,
    description: str,
    parquet_key: str,
    schema: list[ColumnSchema],
    row_count: int,
    created_by: UUID,
) -> dict[str, Any]:
    """Insert the dataset row + version 1 after the bytes are already in
    storage (see routes: storage first, row second — an orphaned file is
    recoverable garbage; a row without its file is a broken dataset)."""
    slug = slugify(name)
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM datasets WHERE project_id = :pid AND slug = :slug",
        {"pid": str(project_id), "slug": slug},
    )
    if existing is not None:
        raise ConflictError(f"a dataset with slug '{slug}' already exists in this project")

    import json

    schema_json = json.dumps([c.as_dict() for c in schema])
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                              origin, s3_location, table_schema, row_count,
                              current_version, created_by)
        VALUES (:id, :pid, :wid, :name, :slug, :descr, 'upload', :loc,
                CAST(:schema AS jsonb), :rows, 1, :by)
        RETURNING {_COLUMNS}
        """,
        {
            "id": str(dataset_id),
            "pid": str(project_id),
            "wid": str(workspace_id),
            "name": name,
            "slug": slug,
            "descr": description,
            "loc": parquet_key,
            "schema": schema_json,
            "rows": row_count,
            "by": str(created_by),
        },
    )
    assert row is not None  # parent-checking policy: RETURNING safe
    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind, created_by)
        VALUES (:did, 1, :key, CAST(:schema AS jsonb), :rows, 'upload', :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id),
            "key": parquet_key,
            "schema": schema_json,
            "rows": row_count,
            "by": str(created_by),
        },
    )
    return row


async def update(
    conn: AsyncConnection,
    project_id: UUID,
    dataset_id: UUID,
    *,
    name: str | None,
    description: str | None,
) -> dict[str, Any]:
    await get(conn, project_id, dataset_id)  # 404 shape before update
    row = await fetch_one(
        conn,
        f"""
        UPDATE datasets
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description)
         WHERE id = :did
        RETURNING {_COLUMNS}
        """,
        {"name": name, "descr": description, "did": str(dataset_id)},
    )
    assert row is not None
    return row


async def delete(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    dataset_id: UUID,
) -> None:
    await get(conn, project_id, dataset_id)
    prefix = storage_prefix(await workspace_s3_prefix(conn, workspace_id), dataset_id)
    await fetch_one(
        conn, "DELETE FROM datasets WHERE id = :did RETURNING id", {"did": str(dataset_id)}
    )
    # Storage after the row within the same request; a crash between the two
    # leaves recoverable files, and the worker's cleanup patterns extend to
    # dataset prefixes in a later milestone.
    storage.delete_prefix(prefix)


async def list_versions(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID
) -> list[dict[str, Any]]:
    await get(conn, project_id, dataset_id)
    return await fetch_all(
        conn,
        """
        SELECT id, version_number, row_count, table_schema, produced_by_kind, created_at
          FROM dataset_versions
         WHERE dataset_id = :did
         ORDER BY version_number DESC
        """,
        {"did": str(dataset_id)},
    )


async def add_version(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    dataset_id: UUID,
    workspace_id: UUID,
    parquet_bytes: bytes,
    schema: list[ColumnSchema],
    row_count: int,
    produced_by_kind: str,
    produced_by_id: UUID | None,
    created_by: UUID,
) -> dict[str, Any]:
    """Append a new version to an already-known dataset in place — the
    simpler single-purpose case where uploads/model-outputs/syncs' own
    create-or-version-by-slug logic doesn't apply because the dataset id is
    already known (used by action write-back)."""
    import json

    ws_prefix = await workspace_s3_prefix(conn, workspace_id)
    current = await fetch_one(
        conn, "SELECT current_version FROM datasets WHERE id = :id", {"id": str(dataset_id)}
    )
    if current is None:
        raise NotFoundError("dataset")
    version = int(current["current_version"]) + 1
    parquet_key = f"{storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
    storage.put(parquet_key, parquet_bytes)
    schema_json = json.dumps([c.as_dict() for c in schema])

    updated = await fetch_one(
        conn,
        """
        UPDATE datasets
           SET s3_location = :loc, table_schema = CAST(:schema AS jsonb),
               row_count = :rows, current_version = :version
         WHERE id = :id
        RETURNING id, project_id, name, slug, row_count, current_version
        """,
        {
            "loc": parquet_key, "schema": schema_json, "rows": row_count,
            "version": version, "id": str(dataset_id),
        },
    )
    assert updated is not None
    await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind,
                                      produced_by_id, created_by)
        VALUES (:did, :version, :key, CAST(:schema AS jsonb), :rows, :kind, :pbid, :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id), "version": version, "key": parquet_key,
            "schema": schema_json, "rows": row_count, "kind": produced_by_kind,
            "pbid": str(produced_by_id) if produced_by_id else None, "by": str(created_by),
        },
    )
    return dict(updated)
