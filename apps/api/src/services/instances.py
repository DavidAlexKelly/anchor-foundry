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
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from . import object_sets
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


def missing_required(
    rows: list[tuple[str, dict[str, Any]]], required: set[str]
) -> dict[str, int]:
    """How many synced rows leave a required property empty (p.116).

    > "Validation happens when data is being indexed into the object: The check
    > for null values happens as backing datasources are indexed into Object
    > Storage. This means that the ontology modification itself will succeed if
    > the column backing a required property contains null values."

    **Counted, not refused**, and that is the sentence above rather than a
    softening of it. Data that is already wrong is a fact about the data; a
    sync that refused to index it would leave somebody with an object type that
    will not load and no way to see why - and no way to fix it either, since
    the fix is upstream in the dataset.

    A property that is required and **not mapped at all** counts every row:
    it is absent from all of them, which is the most complete failure there is
    and the easiest one to miss, because nothing about the rows looks wrong.

    Properties with no failures are absent from the result rather than present
    as zero, so a caller can ask "is anything wrong" by asking whether the
    answer is empty.
    """
    from . import ontology as ontology_service

    counts: dict[str, int] = {}
    for _, properties in rows:
        for api_name in required:
            if ontology_service.is_missing(properties.get(api_name)):
                counts[api_name] = counts.get(api_name, 0) + 1
    return counts


async def upsert_instances(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    source_id: UUID,
    rows: list[tuple[str, dict[str, Any]]],
    synced_at: datetime,
) -> int:
    """Write a sync's rows, **merging over the values a dataset cannot hold**.

    `properties` here is what the backing dataset says: `extract_rows` builds
    it from `column_mappings` alone, so an **edit-only** property (Foundry
    `object-link-types` p.113) is never in it. The upsert used to be
    ``properties = EXCLUDED.properties``, which meant every sync silently
    deleted values that had no column to come back from - the values whose
    whole point is that they live only here.

    **The two stores disagreed about this, and neither raised.** OpenSearch's
    update takes a partial ``doc`` and merges it, so the same sync preserved
    those keys there and destroyed them on Postgres. That is the exact class of
    fault ``OPERATORS`` refuses ordered comparisons to avoid - one answer per
    store, no error - and it was already in the write path. Postgres now merges
    too, and a test asserts both stores agree rather than asserting each
    separately, so the next divergence fails rather than hides.

    The dataset's values are layered **on top**: anything mapped is the
    dataset's to say, which keeps a sync authoritative over exactly what it
    owns and no more.
    """
    for primary_key, properties in rows:
        await conn.execute(
            text(
                """
                INSERT INTO object_instances
                    (object_type_id, source_id, primary_key, properties, updated_at)
                VALUES (:tid, :sid, :pk, CAST(:props AS jsonb), :ts)
                ON CONFLICT (source_id, primary_key)
                DO UPDATE SET
                    properties = object_instances.properties || EXCLUDED.properties,
                    updated_at = EXCLUDED.updated_at
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


async def delete_instances(
    conn: AsyncConnection, *, source_id: UUID, primary_keys: list[str]
) -> int:
    """Remove named instances of one source (§138).

    By `(source_id, primary_key)` rather than by key alone, because that pair
    *is* instance identity here - two sources feeding one object type can each
    hold a "1".
    """
    if not primary_keys:
        return 0
    result = await conn.execute(
        text(
            "DELETE FROM object_instances WHERE source_id = :sid "
            "AND primary_key = ANY(CAST(:keys AS text[]))"
        ),
        {"sid": str(source_id), "keys": [str(k) for k in primary_keys]},
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
    sort: str = "recent",
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
         ORDER BY {_order_by(sort)}
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


def _order_by(sort: str) -> str:
    """One of `object_sets.SORTS`, as SQL.

    Interpolated into the statement rather than bound, which is safe only
    because the value is looked up in a fixed table here - it never reaches SQL
    unless it matched one of four literals. An unknown sort falls back to the
    default rather than raising: the route validates first, so reaching this
    with anything else means something bypassed it, and ordering by the default
    is a better answer than a 500 for a difference nobody can see.

    Every one of them ties on `primary_key`, so rows sharing an `updated_at` -
    routine after a bulk sync, which writes them in one instant - page
    consistently, and identically to the OpenSearch store.
    """
    from . import object_sets

    clauses = {
        "key": "i.primary_key ASC",
        "-key": "i.primary_key DESC",
        "oldest": "i.updated_at ASC, i.primary_key ASC",
        "recent": "i.updated_at DESC, i.primary_key ASC",
    }
    return clauses.get(sort, clauses[object_sets.DEFAULT_SORT])


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
        # The primary key is a column, not a property - and a traversal that
        # lands on the far side's key needs to filter on it (`object_sets`
        # PRIMARY_KEY_FILTER). Addressed by name rather than by adding a second
        # filter kind, so every operator keeps working on it.
        extract = (
            "i.primary_key"
            if f.property == object_sets.PRIMARY_KEY_FILTER
            else f"jsonb_extract_path_text(i.properties, :{prop})"
        )
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


async def time_series_object_set(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    filters: tuple[Any, ...],
    interval: str,
) -> list[tuple[datetime, int]]:
    """How many objects last changed in each time bucket, Postgres edition
    (roadmap 1.5, what a Time Series plots).

    **UTC is stated, not inherited.** `updated_at` is a `timestamptz`, so
    `date_trunc` on it would otherwise bucket by the session's TimeZone - and
    OpenSearch's date histogram defaults to UTC. Two deployments with different
    server time zones would draw the same data with the day boundaries in
    different places, which is the invisible kind of disagreement this module
    exists to prevent. `AT TIME ZONE 'UTC'` pins one answer.

    Only the buckets that have rows. The gaps are filled once, in
    `object_sets.fill_time_buckets`, so the two stores cannot fill differently.
    """
    if interval not in object_sets.TIME_INTERVALS:  # pragma: no cover - parsed upstream
        raise ValueError(f"unknown interval {interval!r}")
    predicate, params = _set_predicate(object_type_id, filters)
    rows = await fetch_all(
        conn,
        f"""
        SELECT date_trunc('{interval}', i.updated_at AT TIME ZONE 'UTC') AS bucket,
               count(*) AS n
          FROM object_instances i
         WHERE {predicate}
         GROUP BY 1
         ORDER BY 1
        """,
        params,
    )
    return [
        (row["bucket"].replace(tzinfo=timezone.utc), int(row["n"])) for row in rows
    ]


async def cross_tab_object_set(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    filters: tuple[Any, ...],
    row_property: str,
    column_property: str,
    row_values: tuple[str, ...],
    column_values: tuple[str, ...],
) -> dict[tuple[str, str], int]:
    """The cells of a cross-tab, Postgres edition (roadmap 1.5, Pivot Table).

    Cells only. The row and column axes - their order, their totals and how
    many distinct values each has - come from `group_object_set`, which is what
    makes a pivot's row totals the same numbers a bar chart over the same
    property draws. Computing them here as well would be a second copy of a
    fact, and the two would disagree the first time either changed.

    The axis values are passed in for the same reason: OpenSearch's nested
    terms aggregation truncates the inner buckets *per outer bucket*, so
    letting each store pick its own columns would give a grid whose columns
    differ from row to row. Both stores are told the axes and answer only
    "how many are in this cell".

    Empty axes mean an empty grid, and that is asked for rather than assumed:
    `= ANY('{}')` is false for every row, so the query would be a scan that
    could only return nothing.
    """
    if not row_values or not column_values:
        return {}
    predicate, params = _set_predicate(object_type_id, filters)
    params["rowprop"] = row_property
    params["colprop"] = column_property
    params["rowvals"] = list(row_values)
    params["colvals"] = list(column_values)
    row_extract = "jsonb_extract_path_text(i.properties, :rowprop)"
    col_extract = "jsonb_extract_path_text(i.properties, :colprop)"
    rows = await fetch_all(
        conn,
        f"""
        SELECT {row_extract} AS rv, {col_extract} AS cv, count(*) AS n
          FROM object_instances i
         WHERE {predicate}
           AND {row_extract} = ANY(:rowvals)
           AND {col_extract} = ANY(:colvals)
         GROUP BY 1, 2
        """,
        params,
    )
    return {(str(r["rv"]), str(r["cv"])): int(r["n"]) for r in rows}


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
