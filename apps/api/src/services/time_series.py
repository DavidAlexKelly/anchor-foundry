"""Time series properties (decision 0009 part 1; parity
`docs/parity/ontology.md` §1.1 and §4.1).

> "Stores a history of timestamped values." (`object-link-types` p.127)

**The property holds a series id; the points stay in the dataset they arrived
in** (migration 0047). This module is the two halves of that: declaring where a
type's series live, and reading points back out through the dataset engine.

**Nothing here copies points anywhere.** That is the decision, and the reason
is worth restating at the top of the file that would be the place to break it:
a `time_series_points` table would be a second copy of data the dataset
subsystem already versions, retains and traces, with its own backfill path and
its own answer to "what did this look like last Tuesday".
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError

#: Bucket widths a caller may ask for, plus `none` for the raw points.
#:
#: Decision 0009 left this open deliberately - "decided against a real widget
#: rather than in advance". The widget is §4.1's chart on the standard Object
#: View, and this is the answer: the same three `object_sets.TIME_INTERVALS`
#: already uses, plus `hour`, because a sensor reading every minute is
#: unreadable at daily resolution and that is the shape of data this exists
#: for. Sharing the names with `object_sets` is the point - two vocabularies
#: for "how wide is a bucket" would be two things to keep in step.
INTERVALS = ("none", "hour", "day", "week", "month")

#: What to do with the points inside a bucket. `last` is here because a series
#: of readings is often a *level* rather than a rate, and averaging a level
#: across a day answers a question nobody asked.
AGGREGATES = ("avg", "min", "max", "sum", "count", "last")

#: A hard ceiling on points returned, whatever the window. A chart cannot draw
#: more than this and a browser should not be asked to hold them; a caller
#: wanting the whole history has the dataset itself, which is the honest way to
#: get it.
MAX_POINTS = 5000

_FIELDS = (
    "id", "object_type_source_id", "property_api_name", "dataset_id",
    "key_column", "timestamp_column", "value_column", "created_at", "updated_at",
)
_COLUMNS = ", ".join(_FIELDS)
_S_COLUMNS = ", ".join(f"s.{f}" for f in _FIELDS)


async def list_series(
    conn: AsyncConnection, object_type_source_id: UUID
) -> list[dict[str, Any]]:
    """Every series declared on one mapping, with the dataset's name."""
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_S_COLUMNS}, d.name AS dataset_name
          FROM object_type_series s
          JOIN datasets d ON d.id = s.dataset_id
         WHERE s.object_type_source_id = :sid
         ORDER BY s.property_api_name
        """,
        {"sid": str(object_type_source_id)},
    )
    return [dict(r) for r in rows]


async def get_series(
    conn: AsyncConnection, object_type_source_id: UUID, property_api_name: str
) -> dict[str, Any] | None:
    """One series, or None.

    None rather than a 404: "does this property have points behind it" is a
    question every render of a time series property asks, and "no" is an
    ordinary answer - the property is declared, nobody has said where its
    points live yet.
    """
    for row in await list_series(conn, object_type_source_id):
        if str(row["property_api_name"]) == property_api_name:
            return row
    return None


async def set_series(
    conn: AsyncConnection,
    object_type_source_id: UUID,
    *,
    property_api_name: str,
    dataset_id: UUID,
    key_column: str,
    timestamp_column: str,
    value_column: str,
    columns: set[str],
    property_types: dict[str, str],
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Say where one property's points live, refusing anything that could not read.

    Three refusals, and each is a chart somebody would otherwise open to find
    empty:

      * the property is not declared `time_series` on this object type - a
        series behind a string property is points nothing would ever draw;
      * a named column is not in the dataset. `columns` is the dataset's own
        schema, resolved by the caller, because this module does not read
        Parquet - the engine does;
      * the three columns are not distinct. A series whose timestamp and value
        are the same column is a straight line, and saying so now beats
        discovering it from a graph.
    """
    declared = property_types.get(property_api_name)
    if declared is None:
        raise ValueError(
            f"{property_api_name!r} is not a property of this object type"
        )
    if declared != "time_series":
        raise ValueError(
            f"{property_api_name!r} is a {declared} property - only a time_series "
            "property can have points behind it"
        )
    named = {"key": key_column, "timestamp": timestamp_column, "value": value_column}
    missing = sorted(
        f"{role} column {column!r}" for role, column in named.items() if column not in columns
    )
    if missing:
        raise ValueError(
            f"the points dataset has no {', or '.join(missing)} "
            f"(it has: {', '.join(sorted(columns)) or 'no columns'})"
        )
    if len(set(named.values())) != 3:
        raise ValueError(
            "the key, timestamp and value columns must be three different columns"
        )

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO object_type_series
            (object_type_source_id, property_api_name, dataset_id,
             key_column, timestamp_column, value_column, created_by)
        VALUES (:sid, :prop, :did, :key, :ts, :val, :by)
        ON CONFLICT (object_type_source_id, property_api_name) DO UPDATE
            SET dataset_id = EXCLUDED.dataset_id,
                key_column = EXCLUDED.key_column,
                timestamp_column = EXCLUDED.timestamp_column,
                value_column = EXCLUDED.value_column
        RETURNING {_COLUMNS}
        """,
        {
            "sid": str(object_type_source_id), "prop": property_api_name,
            "did": str(dataset_id), "key": key_column, "ts": timestamp_column,
            "val": value_column, "by": str(created_by) if created_by else None,
        },
    )
    assert row is not None
    return dict(row)


async def clear_series(
    conn: AsyncConnection, object_type_source_id: UUID, property_api_name: str
) -> None:
    """Stop pointing a property at a dataset. The dataset is untouched."""
    result = await conn.execute(
        text(
            """
            DELETE FROM object_type_series
             WHERE object_type_source_id = :sid AND property_api_name = :prop
            """
        ),
        {"sid": str(object_type_source_id), "prop": property_api_name},
    )
    if result.rowcount == 0:
        raise NotFoundError("time series")


async def series_for_source(
    conn: AsyncConnection, object_type_source_id: UUID, property_api_name: str
) -> dict[str, Any] | None:
    """One series, resolved all the way to the bytes that hold its points.

    Carries the points dataset's `s3_location` and its `project_id` so a
    **workspace-scoped** reader - the Object Explorer and the standard Object
    View are both workspace-wide - can get to the file without first knowing
    which project the dataset lives in. The project is the dataset's own, read
    here, rather than anything the caller supplied.
    """
    row = await fetch_one(
        conn,
        f"""
        SELECT {_S_COLUMNS}, d.name AS dataset_name, d.s3_location, d.project_id
          FROM object_type_series s
          JOIN datasets d ON d.id = s.dataset_id
         WHERE s.object_type_source_id = :sid AND s.property_api_name = :prop
        """,
        {"sid": str(object_type_source_id), "prop": property_api_name},
    )
    return dict(row) if row else None


def _quote(name: str) -> str:
    """A column name as a SQL identifier.

    Column names come from the *schema* by the time they reach here - `set_series`
    refused any that were not - but they are still customer strings inside a
    query, so they are quoted rather than interpolated bare.
    """
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def points_sql(
    *,
    key_column: str,
    timestamp_column: str,
    value_column: str,
    series_id: str,
    interval: str,
    aggregate: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = MAX_POINTS,
) -> str:
    """The query that reads one series out of its dataset.

    A separate, pure function because it is the part worth testing without a
    Parquet file: the shape of the SQL is where a wrong bucket, an unfiltered
    key or a missing cap would live, and none of those need a dataset to see.

    `dataset` is the table the engine exposes (`dataset_engine.query`).

    **Ordered by time, ascending, always.** A chart drawn from rows in whatever
    order the file happened to hold them is not a chart, and DuckDB makes no
    promise without an ORDER BY.
    """
    if interval not in INTERVALS:
        raise ValueError(
            f"unknown interval {interval!r} (supported: {', '.join(INTERVALS)})"
        )
    if aggregate not in AGGREGATES:
        raise ValueError(
            f"unknown aggregate {aggregate!r} (supported: {', '.join(AGGREGATES)})"
        )
    key, ts, val = _quote(key_column), _quote(timestamp_column), _quote(value_column)
    where = [f"CAST({key} AS VARCHAR) = {_literal(series_id)}"]
    if start is not None:
        where.append(f"{ts} >= TIMESTAMP {_literal(start.isoformat())}")
    if end is not None:
        where.append(f"{ts} <= TIMESTAMP {_literal(end.isoformat())}")
    clause = " AND ".join(where)
    capped = max(1, min(limit, MAX_POINTS))

    if interval == "none":
        # The raw points. Still capped and still ordered - "no bucketing" is
        # not "no limit", and a series with a decade of readings would
        # otherwise decide how much memory the API uses.
        return (
            f"SELECT {ts} AS at, {val} AS value FROM dataset "
            f"WHERE {clause} ORDER BY at LIMIT {capped}"
        )
    # `last` is the value at the greatest timestamp in the bucket, which is not
    # an aggregate DuckDB spells `last(...)` reliably across versions - the
    # arg_max form says exactly what is meant and needs no ordering guarantee.
    expression = (
        f"arg_max({val}, {ts})" if aggregate == "last"
        else "count(*)" if aggregate == "count"
        else f"{aggregate}({val})"
    )
    return (
        f"SELECT date_trunc({_literal(interval)}, {ts}) AS at, "
        f"{expression} AS value FROM dataset "
        f"WHERE {clause} GROUP BY at ORDER BY at LIMIT {capped}"
    )
