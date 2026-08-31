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


def constraint_violation_counts(
    rows: list[tuple[str, dict[str, Any]]],
    constrained: dict[str, tuple[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """How many rows break each value type constraint, and one example why.

    **Counts and reports rather than refusing the sync**, which is where this
    diverges from Foundry and does so deliberately. p.227 says an object type
    with failing values "will fail to index" - taking the whole type off every
    screen because one row is wrong. This platform already made the opposite
    choice for required properties (§154, p.116's own split: sync reports,
    actions refuse), and applying it here keeps one rule instead of two: a bad
    row is reported, the good rows still index, and the report says which
    property and gives a reason somebody can act on.

    The example matters more than the count. "412 rows failed `email`" sends
    somebody to look at 412 rows; "412 rows failed `email`, e.g. 'n/a' does not
    match ...@..." tells them what the pipeline is putting there.
    """
    from . import value_constraints

    out: dict[str, dict[str, Any]] = {}
    for _, properties in rows:
        for api_name, (base_type, constraint) in constrained.items():
            why = value_constraints.violation(
                constraint, base_type, properties.get(api_name)
            )
            if why is None:
                continue
            seen = out.setdefault(api_name, {"count": 0, "example": why})
            seen["count"] += 1
    return out


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

    Equality-shaped comparison is text-to-text, matching ``object_sets.matches``
    and the OpenSearch store. **Ordered operators compare in the declared
    property type's own ordering** (§221) — see ``_comparable_sql`` for the two
    rules that keeps identical across the stores.

    This paragraph described ordered operators for months while
    ``object_sets.parse`` refused every one of them: it was written for the
    first implementation, which was withdrawn when the cross-store test caught
    the two stores disagreeing, and the prose stayed. It also described the
    wrong thing — "cast both sides to double precision" is not what a date
    needs. §217's lesson in the other direction: a comment can outlive the code
    it describes, and the only tell is that nothing exercises what it claims.
    """
    predicate, params = _set_predicate(object_type_id, filters)
    # **On its own line, and its binds kept separate from the predicate's.** A
    # property sort binds the property name, so `_order_by` has parameters of
    # its own - and computing it inside the f-string below would have it mutate
    # a dict that is read by the argument after it, which works only because of
    # Python's evaluation order and would break silently on a reformat. The
    # count query does not order, so it does not get those binds either.
    order_params: dict[str, Any] = {}
    order = _order_by(sort, order_params)
    rows = await fetch_all(
        conn,
        f"""
        SELECT i.id, i.object_type_id, i.primary_key, i.properties, i.updated_at
          FROM object_instances i
         WHERE {predicate}
         ORDER BY {order}
         LIMIT :limit OFFSET :offset
        """,
        {**params, **order_params,
         "limit": max(1, min(limit, INSTANCE_PAGE_SIZE)), "offset": max(0, offset)},
    )
    total_row = await fetch_one(
        conn,
        f"SELECT count(*) AS n FROM object_instances i WHERE {predicate}",
        params,
    )
    return [dict(r) for r in rows], int(total_row["n"]) if total_row else 0


# The SQL type each declared type compares in (§221; decision 0006 §2).
#
# `double precision` covers `integer` too: the comparison is an ordering, not
# an identity, and a bigint that does not fit a double exactly still orders
# correctly against the bounds a filter carries. `timestamptz` covers `date`
# for the same reason `instance_mapping` maps both to one field - a date is a
# timestamp at midnight, and giving them two orderings would make a filter
# spanning both properties incoherent.
#
# Interpolated into SQL rather than bound, which is safe **only** because the
# key comes from `object_sets.ORDERABLE_TYPES` and the value from this literal
# table: a declared type never reaches SQL, only one of two constants does.
_CAST_FOR = {
    "integer": "double precision",
    "float": "double precision",
    "date": "timestamptz",
    "timestamp": "timestamptz",
}

_SQL_COMPARISON = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}

# A timestamp text that already says which offset it is in. db 0029 keeps one
# "when the source has one", so this separates the two cases the ontology
# actually stores rather than guessing at a format.
_HAS_OFFSET = r"(Z|[+-][0-9]{2}:?[0-9]{2})$"


def _comparable_sql(extract: str, data_type: str | None) -> str:
    """A stored property, as a value its declared type can be ordered by.

    Two rules, and both exist because the alternative is a disagreement nobody
    can see.

    **`pg_input_is_valid` rather than a regex or a bare cast.** A bare cast
    raises on the first unparseable row, so one `"n/a"` in a `capacity` column
    fails a whole page rather than narrowing it. A regex guard is a second,
    weaker copy of Postgres's own parser - it would accept `2026-13-45` and
    then throw anyway, on the row it was written to protect. This asks the
    parser. A value that will not cast becomes NULL, which does not match in
    either direction and sorts last, exactly as `object_sets._compares` says
    and as OpenSearch treats a field that failed to index.

    **A timestamp with no offset is UTC, stated rather than left to the
    server.** `'2026-01-05'::timestamptz` uses the session's `TimeZone`, so the
    same data would land on a different instant on a deployment configured to
    anything but UTC - a cross-store divergence hiding in a server setting,
    which is the exact shape decision 0006 exists to remove. `AT TIME ZONE
    'UTC'` says it, and matches `object_sets._instant`, which the reference
    semantics and the OpenSearch bound both go through.
    """
    cast = _CAST_FOR[data_type]
    if cast != "timestamptz":
        return f"(CASE WHEN pg_input_is_valid({extract}, '{cast}') THEN {extract}::{cast} END)"
    return (
        f"(CASE WHEN NOT pg_input_is_valid({extract}, 'timestamptz') THEN NULL"
        f" WHEN {extract} ~ '{_HAS_OFFSET}' THEN {extract}::timestamptz"
        f" ELSE {extract}::timestamp AT TIME ZONE 'UTC' END)"
    )


def _order_by(sort: "Any", params: dict[str, Any]) -> str:
    """An `object_sets.Sort`, as SQL.

    Interpolated into the statement rather than bound, which is safe only
    because every part of it comes from a fixed table: one of four literal
    clauses, or a cast looked up by `ORDERABLE_TYPES` key. **The property name
    is bound**, never concatenated — a sort is written by whoever builds an
    app, so it is user input, exactly like a filter's property name.

    An unknown sort falls back to the default rather than raising: the route
    validates first, so reaching this with anything else means something
    bypassed it, and ordering by the default is a better answer than a 500 for
    a difference nobody can see.

    **Every ordering ties on `primary_key`**, so rows sharing a value — routine
    after a bulk sync, which writes them in one instant — page consistently and
    identically to the OpenSearch store. That matters more for a property sort
    than for the four fixed ones: `status` has five distinct values over a
    million rows, so without the tie-break almost every page boundary falls
    inside a group of equals.
    """
    from . import object_sets

    clauses = {
        "key": "i.primary_key ASC",
        "-key": "i.primary_key DESC",
        "oldest": "i.updated_at ASC, i.primary_key ASC",
        "recent": "i.updated_at DESC, i.primary_key ASC",
    }
    key = sort if isinstance(sort, str) else sort.key
    if key in clauses:
        return clauses[key]
    if isinstance(sort, str) or sort.property is None:
        return clauses[object_sets.DEFAULT_SORT]

    params["sortprop"] = sort.property
    direction = "DESC" if sort.descending else "ASC"
    # **NULLS LAST in both directions**, which Postgres does not do by default:
    # it sorts NULLs last ascending and first descending, so a descending sort
    # would open with every row whose value would not cast. OpenSearch puts
    # missing values last either way, and a page that starts with the unusable
    # rows on one store and the largest on the other is the invisible kind of
    # wrong this file exists to prevent.
    value = _comparable_sql(
        "jsonb_extract_path_text(i.properties, :sortprop)", sort.data_type
    )
    return f"{value} {direction} NULLS LAST, i.primary_key ASC"


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
        elif f.op in object_sets.ORDERED_OPERATORS:
            comparison = _SQL_COMPARISON[f.op]
            bound = object_sets.comparable(f.value, f.data_type)
            if bound is None:
                # A bound that does not fit its own declared type. Nothing
                # matches, which is what the reference says - written as a
                # literal false rather than a comparison against NULL, because
                # `x > NULL` is NULL and `WHERE NULL` is *also* no rows only by
                # coincidence of three-valued logic.
                where.append("false")
                continue
            where.append(
                f"({_comparable_sql(extract, f.data_type)} {comparison} "
                f"CAST(:{val} AS {_CAST_FOR[f.data_type]}))"
            )
            params[val] = bound.isoformat() if hasattr(bound, "isoformat") else bound
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
