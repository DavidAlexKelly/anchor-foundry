"""Object instance materialisation and browsing (spec: "object instances are
stored and indexed in OpenSearch").

This module is now the *SQL layer* rather than the store: the functions
below still own every statement against object_instances (migration 0012),
but callers reach them through services/instance_store.py's
``PostgresInstanceStore``, which implements the same Protocol as the
OpenSearch-backed store. Routes ask ``store_for(conn)`` which one they have
and never find out. Postgres remains the fallback and the local-dev default
- RLS gives free per-row workspace isolation that a search index cannot,
which is why this path is kept rather than deleted at cutover.

Sync (project-scoped, triggered per object_type_source): reads the mapped
dataset's current Parquet file through the same DuckDB path datasets/models
already use, extracts the primary key + mapped columns, and upserts one row
per source row keyed on (source_id, primary_key). A resync also removes any
previously-synced instance whose primary key no longer appears in the
current data - the store should not lag behind deletes upstream.
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


async def workspace_search_prefix(conn: AsyncConnection, workspace_id: UUID) -> str:
    """The workspace's immutable search namespace (db 0002), which the
    OpenSearch store uses as its index name. Resolved by the caller and
    handed to the store, the same way s3_prefix is for storage - the store
    never looks up workspaces itself."""
    row = await fetch_one(
        conn, "SELECT search_prefix FROM workspaces WHERE id = :wid",
        {"wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("workspace")
    return str(row["search_prefix"])


def _quote_source_column(name: str) -> str:
    """Dataset column names come from uploaded file headers, not a fixed
    identifier grammar - quote-and-escape rather than assume they're safe
    unquoted SQL identifiers."""
    return '"' + name.replace('"', '""') + '"'


def extract_rows(
    parquet_path: str, primary_key_column: str, column_mappings: dict[str, str]
) -> list[tuple[str, dict[str, Any]]]:
    """Reads the primary key + mapped columns for every row. Returns
    (primary_key_as_text, {property_api_name: value}) tuples; rows with a
    null primary key are skipped - they can't identify an instance."""
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
            f"dataset exceeds the {MAX_INSTANCE_SYNC_ROWS:,} row interactive sync limit - "
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


async def search(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    query: str | None,
    object_type_ids: list[UUID] | None,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Workspace-wide instance search, Postgres edition (roadmap Objects
    item 2).

    **This is substring matching over the properties JSON, not search.** No
    tokenisation, no relevance, no prefix handling beyond what LIKE gives -
    "ada" finds "Ada Lovelace" and also finds a department called "Adaptive".
    That is the honest capability of the fallback store, and it is precisely
    why the roadmap sequenced the Object Explorer after the OpenSearch
    cutover: this path exists so the feature works in local dev and on a
    deployment that has not moved yet, not because Postgres is a search
    engine.
    """
    limit = max(1, min(limit, INSTANCE_PAGE_SIZE))
    offset = max(0, offset)
    where = ["t.workspace_id = :wid"]
    params: dict[str, Any] = {"wid": str(workspace_id), "limit": limit, "offset": offset}
    if object_type_ids:
        where.append("i.object_type_id = ANY(CAST(:types AS uuid[]))")
        params["types"] = [str(t) for t in object_type_ids]
    if query:
        where.append("(i.properties::text ILIKE :q OR i.primary_key ILIKE :q)")
        params["q"] = f"%{query}%"
    predicate = " AND ".join(where)

    rows = await fetch_all(
        conn,
        f"""
        SELECT i.id, i.object_type_id, i.primary_key, i.properties, i.updated_at
          FROM object_instances i
          JOIN object_types t ON t.id = i.object_type_id
         WHERE {predicate}
         ORDER BY i.updated_at DESC
         LIMIT :limit OFFSET :offset
        """,
        params,
    )
    total_row = await fetch_one(
        conn,
        f"""
        SELECT count(*) AS n FROM object_instances i
          JOIN object_types t ON t.id = i.object_type_id
         WHERE {predicate}
        """,
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    )
    return [dict(r) for r in rows], int(total_row["n"]) if total_row else 0


async def find_by_property(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    property_name: str | None,
    key: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """Exact-equality lookup, Postgres edition: the far end of a link
    traversal (roadmap Objects item 3). ``property_name=None`` means the
    primary key. ``key`` is already the text form (instance_store.join_key).

    ``jsonb_extract_path_text`` rather than ``properties ->> :prop``: the
    function form takes the property name as an ordinary bind parameter, so a
    property named by the user is never concatenated into SQL. The comparison
    is text-to-text, matching what join_key promises.
    """
    if property_name is None:
        predicate = "i.primary_key = :key"
        params: dict[str, Any] = {"key": key}
    else:
        predicate = "jsonb_extract_path_text(i.properties, :prop) = :key"
        params = {"prop": property_name, "key": key}
    params.update({"tid": str(object_type_id)})

    rows = await fetch_all(
        conn,
        f"""
        SELECT i.id, i.object_type_id, i.primary_key, i.properties, i.updated_at
          FROM object_instances i
         WHERE i.object_type_id = :tid AND {predicate}
         ORDER BY i.primary_key
         LIMIT :limit OFFSET :offset
        """,
        {**params, "limit": max(1, min(limit, INSTANCE_PAGE_SIZE)), "offset": max(0, offset)},
    )
    total_row = await fetch_one(
        conn,
        f"SELECT count(*) AS n FROM object_instances i "
        f"WHERE i.object_type_id = :tid AND {predicate}",
        params,
    )
    return [dict(r) for r in rows], int(total_row["n"]) if total_row else 0


async def evaluate_object_set(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    filters: tuple[Any, ...],
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    """A filtered set and its size, Postgres edition (roadmap 1.2).

    ``jsonb_extract_path_text`` for the same reason ``find_by_property`` uses
    it: the property name is a *bind parameter*, never concatenated into SQL.
    A set definition is written by whoever builds an app, so the property name
    is user input, and the one place this could go wrong is the one place it
    must not.

    Comparison is text-to-text, matching ``object_sets.matches`` and the
    OpenSearch store. Ordered operators cast both sides to double precision and
    fall back to no-match on a value that will not cast, so one unparseable row
    narrows the set rather than failing the query - the same choice
    ``object_sets._matches_one`` makes, made the same way in both stores.
    """
    predicate, params = _set_predicate(object_type_id, filters)
    rows = await fetch_all(
        conn,
        f"""
        SELECT i.id, i.object_type_id, i.primary_key, i.properties, i.updated_at
          FROM object_instances i
         WHERE {predicate}
         ORDER BY i.updated_at DESC, i.id
         LIMIT :limit OFFSET :offset
        """,
        {**params, "limit": max(1, min(limit, INSTANCE_PAGE_SIZE)), "offset": max(0, offset)},
    )
    total_row = await fetch_one(
        conn,
        f"SELECT count(*) AS n FROM object_instances i WHERE {predicate}",
        params,
    )
    return [dict(r) for r in rows], int(total_row["n"]) if total_row else 0


def _set_predicate(
    object_type_id: UUID, filters: tuple[Any, ...]
) -> tuple[str, dict[str, Any]]:
    """The WHERE clause for one set definition, and its bind parameters.

    Shared by paging and aggregating - see `aggregate_object_set` for why that
    matters.
    """
    where = ["i.object_type_id = :tid"]
    params: dict[str, Any] = {"tid": str(object_type_id)}

    for index, f in enumerate(filters):
        prop = f"p{index}"
        val = f"v{index}"
        params[prop] = f.property
        extract = f"jsonb_extract_path_text(i.properties, :{prop})"
        if f.op == "eq":
            where.append(f"{extract} = :{val}")
            params[val] = _filter_text(f.value)
        elif f.op == "neq":
            # NULL is not "different from x" in SQL's three-valued logic, but a
            # property that is absent *is* different from x to anybody reading
            # the app. coalesce makes the answer the one they expect.
            where.append(f"coalesce({extract}, '') <> :{val}")
            params[val] = _filter_text(f.value)
        elif f.op == "in":
            where.append(f"{extract} = ANY(:{val})")
            params[val] = [_filter_text(v) for v in f.value]
        elif f.op == "starts_with":
            # Anchored, so the index can be used and so this means the same
            # thing as OpenSearch's phrase_prefix.
            where.append(f"{extract} ILIKE :{val}")
            params[val] = f"{_escape_like(_filter_text(f.value))}%"
        else:  # pragma: no cover - object_sets.parse refuses anything else
            raise ValueError(f"unsupported object-set operator {f.op!r}")

    return " AND ".join(where), params


async def aggregate_object_set(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    filters: tuple[Any, ...],
    aggregation: str,
    property_name: str | None,
) -> int:
    """One number over a whole set, Postgres edition (roadmap 1.5).

    Reuses `_set_predicate` so the number counts exactly the rows
    `evaluate_object_set` would page through. Two predicates would be two
    definitions of the set, and the first time they drifted a Metric Card
    would count rows the table beside it does not show.
    """
    predicate, params = _set_predicate(object_type_id, filters)
    if aggregation == "count_distinct":
        # Same text extraction the filters use, so "how many distinct regions"
        # and "where region = north" agree about what a region *is*.
        params["prop"] = property_name
        row = await fetch_one(
            conn,
            f"""
            SELECT count(DISTINCT jsonb_extract_path_text(i.properties, :prop)) AS n
              FROM object_instances i
             WHERE {predicate}
            """,
            params,
        )
    else:
        row = await fetch_one(
            conn,
            f"SELECT count(*) AS n FROM object_instances i WHERE {predicate}",
            params,
        )
    return int(row["n"]) if row else 0


async def group_object_set(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    filters: tuple[Any, ...],
    property_name: str,
    limit: int,
) -> tuple[list[tuple[str, int]], int]:
    """How many in each distinct value of one property, Postgres edition
    (roadmap 1.5).

    Ordered by count descending *then value ascending*. The second key is not
    decoration: without it, ties fall to whatever order each store happens to
    produce, so two deployments would draw the same data differently and one of
    them would look wrong to somebody who knew the other.

    Rows whose property is absent are excluded rather than grouped under an
    empty label - OpenSearch's terms aggregation skips missing fields, and a
    bar labelled "" appearing on one store only is exactly the disagreement
    this whole module is arranged to avoid.
    """
    predicate, params = _set_predicate(object_type_id, filters)
    params["prop"] = property_name
    params["limit"] = max(1, limit)
    rows = await fetch_all(
        conn,
        f"""
        SELECT jsonb_extract_path_text(i.properties, :prop) AS value, count(*) AS n
          FROM object_instances i
         WHERE {predicate}
           AND jsonb_extract_path_text(i.properties, :prop) IS NOT NULL
         GROUP BY 1
         ORDER BY n DESC, value ASC
         LIMIT :limit
        """,
        params,
    )
    total_row = await fetch_one(
        conn,
        f"""
        SELECT count(DISTINCT jsonb_extract_path_text(i.properties, :prop)) AS n
          FROM object_instances i
         WHERE {predicate}
        """,
        {k: v for k, v in params.items() if k != "limit"},
    )
    return (
        [(str(r["value"]), int(r["n"])) for r in rows],
        int(total_row["n"]) if total_row else 0,
    )


def _filter_text(value: Any) -> str:
    """One definition of "the text of a value", shared with the OpenSearch
    store and with object_sets."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
