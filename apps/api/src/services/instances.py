"""Object instance materialisation and browsing (spec: "object instances are
stored and indexed in OpenSearch").

Architecturally significant, flagged for review: this slice stores instances
in Postgres (object_instances, migration 0012) rather than OpenSearch. That
is not a drop-in gateway swap like storage (S3 vs local disk) or secrets
(Secrets Manager vs in-memory) — Postgres RLS gives free, per-row workspace
isolation that a search index does not enforce on its own. The production
OpenSearch-backed store now exists (services/instance_store.py:
OpenSearchInstanceStore, index-per-workspace via the same search_prefix
isolation anchor S3/pg_schema already use, object_type_id filtered within
it) but is not wired in here yet — the cutover replaces the Postgres-
connection-shaped functions below with calls through that gateway, which is
deliberately left as its own follow-up so it can be reviewed independently;
see that module's docstring for the full design and why it isn't a one-line
swap.

Sync (project-scoped, triggered per object_type_source): reads the mapped
dataset's current Parquet file through the same DuckDB path datasets/models
already use, extracts the primary key + mapped columns, and upserts one row
per source row keyed on (source_id, primary_key). A resync also removes any
previously-synced instance whose primary key no longer appears in the
current data — the store should not lag behind deletes upstream.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from .dataset_engine import DatasetEngineError, json_safe

MAX_INSTANCE_SYNC_ROWS = 20_000  # flag: worker/OpenSearch bulk path beyond this
INSTANCE_PAGE_SIZE = 50


def _quote_source_column(name: str) -> str:
    """Dataset column names come from uploaded file headers, not a fixed
    identifier grammar — quote-and-escape rather than assume they're safe
    unquoted SQL identifiers."""
    return '"' + name.replace('"', '""') + '"'


def extract_rows(
    parquet_path: str, primary_key_column: str, column_mappings: dict[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    """Reads the primary key + mapped columns for every row. Returns
    (primary_key_as_text, {property_api_name: value}) tuples; rows with a
    null primary key are skipped — they can't identify an instance."""
    import duckdb

    source_columns = [primary_key_column] + list(column_mappings.keys())
    property_names = list(column_mappings.values())
    select_list = ", ".join(_quote_source_column(c) for c in source_columns)

    con = duckdb.connect()
    try:
        try:
            cursor = con.execute(
                f"SELECT {select_list} FROM read_parquet({parquet_path!r}) "
                f"LIMIT {MAX_INSTANCE_SYNC_ROWS + 1}"
            )
            rows = cursor.fetchall()
        except duckdb.Error as exc:
            text_ = str(exc).strip()
            raise DatasetEngineError((text_.splitlines()[0] if text_ else "sync failed")[:500]) from exc
    finally:
        con.close()

    if len(rows) > MAX_INSTANCE_SYNC_ROWS:
        raise DatasetEngineError(
            f"dataset exceeds the {MAX_INSTANCE_SYNC_ROWS:,} row interactive sync limit — "
            "scheduled worker syncs handle larger tables"
        )

    out: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        pk = row[0]
        if pk is None:
            continue
        properties = {property_names[i]: json_safe(row[i + 1]) for i in range(len(property_names))}
        out.append((str(pk), properties))
    return out


async def upsert_instances(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    source_id: UUID,
    rows: list[tuple[str, dict[str, Any]]],
    synced_at: datetime,
) -> int:
    for primary_key, properties in rows:
        await conn.execute(
            text(
                """
                INSERT INTO object_instances
                    (object_type_id, source_id, primary_key, properties, updated_at)
                VALUES (:tid, :sid, :pk, CAST(:props AS jsonb), :ts)
                ON CONFLICT (source_id, primary_key)
                DO UPDATE SET properties = EXCLUDED.properties, updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "tid": str(object_type_id),
                "sid": str(source_id),
                "pk": primary_key,
                "props": json.dumps(properties),
                "ts": synced_at,
            },
        )
    return len(rows)


async def delete_stale_instances(
    conn: AsyncConnection, *, source_id: UUID, synced_before: datetime
) -> int:
    result = await conn.execute(
        text("DELETE FROM object_instances WHERE source_id = :sid AND updated_at < :ts"),
        {"sid": str(source_id), "ts": synced_before},
    )
    return result.rowcount or 0


async def list_for_type(
    conn: AsyncConnection, object_type_id: UUID, *, limit: int, offset: int
) -> tuple[list[dict[str, Any]], int]:
    limit = max(1, min(limit, INSTANCE_PAGE_SIZE))
    rows = await fetch_all(
        conn,
        """
        SELECT id, primary_key, properties, updated_at
          FROM object_instances
         WHERE object_type_id = :tid
         ORDER BY updated_at DESC
         LIMIT :limit OFFSET :offset
        """,
        {"tid": str(object_type_id), "limit": limit, "offset": max(0, offset)},
    )
    total_row = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM object_instances WHERE object_type_id = :tid",
        {"tid": str(object_type_id)},
    )
    total = int(total_row["n"]) if total_row else 0
    return [dict(r) for r in rows], total


async def get(conn: AsyncConnection, object_type_id: UUID, instance_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT id, source_id, primary_key, properties, updated_at
          FROM object_instances
         WHERE id = :iid AND object_type_id = :tid
        """,
        {"iid": str(instance_id), "tid": str(object_type_id)},
    )
    if row is None:
        raise NotFoundError("object instance")
    return dict(row)


async def update_properties(
    conn: AsyncConnection, instance_id: UUID, properties: dict[str, Any]
) -> None:
    """Merge new property values into an instance after a successful
    write-back (services/actions.py)."""
    await conn.execute(
        text(
            "UPDATE object_instances SET properties = properties || CAST(:props AS jsonb), "
            "updated_at = now() WHERE id = :iid"
        ),
        {"props": json.dumps(properties), "iid": str(instance_id)},
    )
