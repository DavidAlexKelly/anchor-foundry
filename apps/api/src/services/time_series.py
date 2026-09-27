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

import re
from collections.abc import Sequence
from datetime import datetime, timezone
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
    "key_column", "timestamp_column", "value_column",
    # §427's position column (db 0097). Exactly one of `value_column` and this
    # is set on any row, which the table's own CHECK keeps true.
    "point_column",
    "created_at", "updated_at",
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


#: Which kind of point each series property holds (§427).
#:
#: **A mapping rather than a pair of booleans**, so the refusal below can name
#: the column a property actually wants: a `time_series` pointed at a position
#: column and a `geotemporal_series` pointed at a numeric one are different
#: mistakes and a shared "wrong column" would explain neither.
SERIES_KINDS = {"time_series": "value", "geotemporal_series": "point"}


async def set_series(
    conn: AsyncConnection,
    object_type_source_id: UUID,
    *,
    property_api_name: str,
    dataset_id: UUID,
    key_column: str,
    timestamp_column: str,
    value_column: str | None = None,
    point_column: str | None = None,
    columns: set[str],
    property_types: dict[str, str],
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Say where one property's points live, refusing anything that could not read.

    Four refusals, and each is a chart or a map somebody would otherwise open
    to find empty:

      * the property is not a series property at all - points behind a string
        property are points nothing would ever draw;
      * the kind of point does not match the kind of property (§427). A
        `time_series` holds numbers and a `geotemporal_series` holds positions
        (`object-link-types` p.127), so each names its own column and naming
        the other one is a mapping that reads the wrong thing rather than
        nothing at all - which is the worse failure, because it *works*;
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
    wants = SERIES_KINDS.get(declared)
    if wants is None:
        raise ValueError(
            f"{property_api_name!r} is a {declared} property - only a "
            f"{' or a '.join(sorted(SERIES_KINDS))} property can have points "
            "behind it"
        )
    given = {"value": value_column, "point": point_column}
    other = "point" if wants == "value" else "value"
    owner = next(k for k, v in SERIES_KINDS.items() if v == other)
    if given[wants] is None:
        # **The wrong column is named when one was given**, not only the
        # missing one. "needs a value column" is true either way, and on its
        # own it reads as a field somebody forgot — where what actually
        # happened is that they filled in the field for the other kind of
        # series, which is a different mistake with a different fix.
        raise ValueError(
            f"{property_api_name!r} is a {declared} property, so its points "
            f"need a {wants} column"
            + (f" — the {other} column is a {owner} property's"
               if given[other] is not None else "")
        )
    if given[other] is not None:
        raise ValueError(
            f"{property_api_name!r} is a {declared} property, so it takes a "
            f"{wants} column and not a {other} column"
        )

    named = {"key": key_column, "timestamp": timestamp_column, wants: given[wants]}
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
            f"the key, timestamp and {wants} columns must be three different columns"
        )

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO object_type_series
            (object_type_source_id, property_api_name, dataset_id,
             key_column, timestamp_column, value_column, point_column, created_by)
        VALUES (:sid, :prop, :did, :key, :ts, :val, :point, :by)
        ON CONFLICT (object_type_source_id, property_api_name) DO UPDATE
            SET dataset_id = EXCLUDED.dataset_id,
                key_column = EXCLUDED.key_column,
                timestamp_column = EXCLUDED.timestamp_column,
                value_column = EXCLUDED.value_column,
                -- **Both columns on the update, not just the one being
                -- set.** The case that reaches this is a track re-mapped to a
                -- *different* position column: keeping the old one would make
                -- the save silently do nothing, and the mapping screen would
                -- then show the new column beside points read from the old.
                --
                -- Retyping a property *between* the two series kinds would be
                -- the sharper case, and it cannot happen: `PATCH
                -- /object-types` refuses a retype while a dataset mapping
                -- names the property. Written down because the first version
                -- of this comment claimed that case, and a test for it turned
                -- out to be a test of the impact check instead.
                point_column = EXCLUDED.point_column
        RETURNING {_COLUMNS}
        """,
        {
            "sid": str(object_type_source_id), "prop": property_api_name,
            "did": str(dataset_id), "key": key_column, "ts": timestamp_column,
            "val": value_column, "point": point_column,
            "by": str(created_by) if created_by else None,
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


async def series_for_type(
    conn: AsyncConnection, object_type_id: UUID, property_api_name: str
) -> list[dict[str, Any]]:
    """Every mapping of one property, across all of a type's sources.

    **A type can be fed by several sources and each maps its own dataset**
    (db 0047 keys the mapping on `object_type_source_id`). A reader that has a
    page of *objects* rather than a page of sources cannot say which source
    each row came from - `evaluate_object_set` does not carry it - so it asks
    for all of them and reads each. A series id belonging to one source's
    dataset simply matches nothing in another's, which makes merging the
    results safe rather than merely convenient.

    Usually one row, and then this is one query and one read.
    """
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_S_COLUMNS}, d.name AS dataset_name, d.s3_location, d.project_id
          FROM object_type_series s
          JOIN object_type_sources src ON src.id = s.object_type_source_id
          JOIN datasets d ON d.id = s.dataset_id
         WHERE src.object_type_id = :tid AND s.property_api_name = :prop
         ORDER BY s.created_at
        """,
        {"tid": str(object_type_id), "prop": property_api_name},
    )
    return [dict(r) for r in rows]


def _quote(name: str) -> str:
    """A column name as a SQL identifier.

    Column names come from the *schema* by the time they reach here - `set_series`
    refused any that were not - but they are still customer strings inside a
    query, so they are quoted rather than interpolated bare.
    """
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


#: How many points one series contributes to a *sparkline*, as against a chart.
#:
#: `MAX_POINTS` is the ceiling for one series somebody is looking at; a column
#: draws a page of them at a thumbnail size, so the same ceiling would be a
#: page of 25 rows asking for 125,000 points to draw a line a centimetre wide.
#: The cap is per series and it is the *latest* points, because a sparkline's
#: job is the recent shape (`workshop` p.583: "a sparkline showing the history
#: of the time series").
SPARK_POINTS = 100

#: A ceiling on how many series one batch may ask for, which is a page of rows
#: rather than a set. A caller wanting every object's series wants an export.
MAX_SERIES = 200


def points_for_many_sql(
    *,
    key_column: str,
    timestamp_column: str,
    value_column: str,
    series_ids: "Sequence[str]",
    interval: str,
    aggregate: str,
    per_series: int = SPARK_POINTS,
    transforms: list[dict[str, Any]] | None = None,
) -> str:
    """The same read, for a page of series at once (`workshop` p.583).

    **One query rather than one per row**, and that is the whole reason this
    exists beside `points_sql`: an Object Table column of sparklines asks for
    every visible row's series, and 25 round trips into the dataset engine to
    draw 25 thumbnails is the version that makes the column not worth having.

    **The cap is per series, applied with a window rather than a LIMIT.** A
    single `LIMIT` over the union would spend its whole budget on whichever
    series sorted first and hand back nothing for the rest - a column where
    the top row draws and the others are empty, which reads as missing data
    rather than as a cap. `row_number()` partitioned by the key gives each
    series its own allowance.

    **And it takes the latest points, then re-orders them.** `DESC` inside the
    window is what makes the allowance the *recent* history; the outer
    `ORDER BY` puts each series back into time order, because a line drawn
    from rows in descending order is a line drawn backwards.
    """
    if interval not in INTERVALS:
        raise ValueError(
            f"unknown interval {interval!r} (supported: {', '.join(INTERVALS)})"
        )
    if aggregate not in AGGREGATES:
        raise ValueError(
            f"unknown aggregate {aggregate!r} (supported: {', '.join(AGGREGATES)})"
        )
    if not series_ids:
        raise ValueError("no series to read")
    if len(series_ids) > MAX_SERIES:
        raise ValueError(f"too many series: {len(series_ids)} (max {MAX_SERIES})")
    key, ts, val = _quote(key_column), _quote(timestamp_column), _quote(value_column)
    # Deduplicated, because two objects may legitimately share a series id and
    # a repeated literal would widen the IN list for nothing.
    wanted = ", ".join(_literal(s) for s in dict.fromkeys(series_ids))
    series_key = f"CAST({key} AS VARCHAR)"
    capped = max(1, min(per_series, MAX_POINTS))

    if transforms:
        # p.583's transforms on a table's series (§555): every series through
        # the chain on its own - the windows partitioned by it - over every
        # point, and the allowance taken last, for §524's reason: a running
        # total over the latest hundred readings is a different series.
        clause = f"{series_key} IN ({wanted})"
        if interval == "none":
            base = f"SELECT {series_key} AS series, {ts} AS at, {val} AS value FROM dataset WHERE {clause}"
        else:
            expression = (
                f"arg_max({val}, {ts})" if aggregate == "last"
                else "count(*)" if aggregate == "count"
                else f"{aggregate}({val})"
            )
            base = (
                f"SELECT {series_key} AS series, date_trunc({_literal(interval)}, {ts}) AS at, "
                f"{expression} AS value FROM dataset WHERE {clause} GROUP BY series, at"
            )
        ctes = [f"t0 AS ({base})"] + [
            f"t{n} AS ({_transform_sql(t, f't{n - 1}', per_series=True)})"
            for n, t in enumerate(transforms, start=1)
        ]
        return (
            f"WITH {', '.join(ctes)} SELECT series, at, value FROM (SELECT series, at, value, "
            f"row_number() OVER (PARTITION BY series ORDER BY at DESC) AS rn FROM t{len(transforms)}) "
            f"WHERE rn <= {capped} ORDER BY series, at"
        )
    if interval == "none":
        inner = (
            f"SELECT {series_key} AS series, {ts} AS at, {val} AS value, "
            f"row_number() OVER (PARTITION BY {series_key} ORDER BY {ts} DESC) AS rn "
            f"FROM dataset WHERE {series_key} IN ({wanted})"
        )
    else:
        expression = (
            f"arg_max({val}, {ts})" if aggregate == "last"
            else "count(*)" if aggregate == "count"
            else f"{aggregate}({val})"
        )
        bucketed = (
            f"SELECT {series_key} AS series, date_trunc({_literal(interval)}, {ts}) AS at, "
            f"{expression} AS value FROM dataset WHERE {series_key} IN ({wanted}) "
            f"GROUP BY series, at"
        )
        inner = (
            "SELECT series, at, value, "
            "row_number() OVER (PARTITION BY series ORDER BY at DESC) AS rn "
            f"FROM ({bucketed})"
        )
    return (
        f"SELECT series, at, value FROM ({inner}) WHERE rn <= {capped} "
        "ORDER BY series, at"
    )


# ---- transforms (§524; `workshop` p.583-586) ----------------------------------
#: "A time series transform performs a mathematical operation on input time
#: series data to yield a new output time series. These input time series can
#: be time series properties or the outputs from other transforms, which allows
#: multiple transforms to be chained together." (p.583)
TRANSFORM_KINDS = (
    "cumulative", "periodic", "rolling", "derivative", "integral", "shift", "range", "formula",
)
#: What a cumulative or rolling window aggregates with: p.586's summarizer
#: vocabulary, as far as a window over points can use it.
WINDOW_AGGREGATES = ("sum", "avg", "min", "max", "count", "stddev")
#: The units a window, a rate or a shift is measured in, in seconds.
TIME_UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400, "week": 604800}
MAX_TRANSFORMS = 10
#: p.584's periodic window types: "Start means that each output point
#: represents the beginning of a time interval … End means that each output
#: point represents the end of a time interval".
WINDOW_TYPES = ("start", "end")
#: p.585's integration methods: "linear, which uses the average value between
#: two time points; left hand sum, which uses the value at the earlier time
#: point; and right hand sum, which uses the value at the later time point".
INTEGRATION_METHODS = ("linear", "left", "right")
#: Where periodic windows line up when no alignment timestamp is given.
EPOCH = "1970-01-01T00:00:00"
#: Ours: a window or shift of more than this many units is a typo.
MAX_SPAN = 100_000


def _span(raw: Any, what: str, *, signed: bool = False) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{what} must be a whole number")
    if signed:
        if raw == 0 or abs(raw) > MAX_SPAN:
            raise ValueError(f"{what} must be non-zero and at most {MAX_SPAN} either way")
    elif not 1 <= raw <= MAX_SPAN:
        raise ValueError(f"{what} must be from 1 to {MAX_SPAN}")
    return raw


def _unit(raw: Any) -> str:
    if raw not in TIME_UNITS:
        raise ValueError(f"the unit must be one of {', '.join(TIME_UNITS)}")
    return str(raw)


def _instant(raw: Any, what: str) -> str | None:
    if raw is None or raw == "":
        return None
    try:
        return datetime.fromisoformat(str(raw)).isoformat()
    except ValueError:
        raise ValueError(f"the {what} {raw!r} is not a date and time") from None


def parse_transforms(
    raw: Any, *, inputs: str = "none", _depth: int = 0,
) -> list[dict[str, Any]]:
    """The transforms a series is read through, in order, or a ValueError
    saying which one is wrong and why. Checked where they are saved (a
    variable) and again where they are read, since the read builds SQL.

    `inputs` says what a formula's other inputs (§561) may be here: `none`
    where there is nothing to name one by (a table's series column, a read by
    series id), `variables` in a variable's own definition, where each is a
    time series set variable's id, and `references` in a read, where each is
    that variable resolved - the object, the property and its own chain."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("transforms must be a list")
    if len(raw) > MAX_TRANSFORMS:
        raise ValueError(f"a series takes at most {MAX_TRANSFORMS} transforms")
    out: list[dict[str, Any]] = []
    for n, item in enumerate(raw, start=1):
        try:
            if not isinstance(item, dict):
                raise ValueError("must be an object")
            kind = item.get("kind")
            if kind not in TRANSFORM_KINDS:
                raise ValueError(f"the kind must be one of {', '.join(TRANSFORM_KINDS)}")
            if kind in ("cumulative", "rolling"):
                aggregate = item.get("aggregate")
                if aggregate not in WINDOW_AGGREGATES:
                    raise ValueError(f"the aggregate must be one of {', '.join(WINDOW_AGGREGATES)}")
                parsed: dict[str, Any] = {"kind": kind, "aggregate": aggregate}
                if kind == "rolling":
                    parsed["window"] = _span(item.get("window"), "the window")
                    parsed["unit"] = _unit(item.get("unit"))
            elif kind == "periodic":
                aggregate = item.get("aggregate")
                if aggregate not in WINDOW_AGGREGATES:
                    raise ValueError(f"the aggregate must be one of {', '.join(WINDOW_AGGREGATES)}")
                window_type = item.get("window_type", "start")
                if window_type not in WINDOW_TYPES:
                    raise ValueError(f"the window type must be one of {', '.join(WINDOW_TYPES)}")
                parsed = {"kind": kind, "aggregate": aggregate,
                          "window": _span(item.get("window"), "the window"),
                          "unit": _unit(item.get("unit")),
                          "align": _instant(item.get("align"), "alignment") or EPOCH,
                          "window_type": window_type}
            elif kind == "derivative":
                parsed = {"kind": kind, "unit": _unit(item.get("unit"))}
            elif kind == "integral":
                method = item.get("method", "linear")
                if method not in INTEGRATION_METHODS:
                    raise ValueError(f"the method must be one of {', '.join(INTEGRATION_METHODS)}")
                parsed = {"kind": kind, "unit": _unit(item.get("unit")), "method": method}
            elif kind == "shift":
                parsed = {"kind": kind, "by": _span(item.get("by"), "the shift", signed=True),
                          "unit": _unit(item.get("unit"))}
            elif kind == "formula":
                expression = item.get("expression")
                if not isinstance(expression, str) or not expression.strip():
                    raise ValueError("a formula needs an expression")
                if len(expression) > MAX_FORMULA:
                    raise ValueError(f"a formula is at most {MAX_FORMULA} characters")
                named = _formula_inputs(item.get("inputs"), inputs, _depth)
                formula_sql(expression, tuple(named))
                parsed = {"kind": kind, "expression": expression.strip()}
                if named:
                    parsed["inputs"] = named
            else:
                start = _instant(item.get("start"), "start")
                end = _instant(item.get("end"), "end")
                if start is None and end is None:
                    raise ValueError("a time range needs a start, an end or both")
                if start is not None and end is not None and start > end:
                    raise ValueError("the start is after the end")
                parsed = {"kind": kind, "start": start, "end": end}
        except ValueError as exc:
            raise ValueError(f"transform {n}: {exc}") from None
        out.append(parsed)
    return out


def _epoch_seconds(instant: str) -> float:
    """An instant as seconds since 1970, read as UTC when it names no zone,
    which is how every timestamp here is drawn."""
    moment = datetime.fromisoformat(instant)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return (moment - datetime(1970, 1, 1)).total_seconds()


#: p.586's formula: "build formulas using variable references to these
#: inputs". The series itself is `x`; p.586's example ("scales the input time
#: series by a factor of two, and adds five") is `x * 2 + 5`.
FORMULA_VARIABLE = "x"
#: p.586's **Add input** (§561): "users can add new input time series - either
#: time series properties or the outputs from other transforms - to the
#: transform". Each is named in the formula; ours caps how many and how deep
#: (an input's own chain may have a formula with inputs of its own).
MAX_FORMULA_INPUTS = 4
MAX_INPUT_DEPTH = 3
_INPUT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


def _formula_inputs(raw: Any, mode: str, depth: int) -> dict[str, Any]:
    """A formula's other inputs by name, checked for where they are written:
    see `parse_transforms`."""
    if raw is None or raw == {}:
        return {}
    if mode == "none":
        raise ValueError(
            "a formula here has only its own series - other inputs are a time "
            "series set variable's (p.586)"
        )
    if not isinstance(raw, dict):
        raise ValueError("a formula's inputs must be an object of name -> input")
    if len(raw) > MAX_FORMULA_INPUTS:
        raise ValueError(f"a formula takes at most {MAX_FORMULA_INPUTS} other inputs")
    if depth >= MAX_INPUT_DEPTH:
        raise ValueError(f"a formula's inputs nest at most {MAX_INPUT_DEPTH} deep")
    out: dict[str, Any] = {}
    for name, value in raw.items():
        if (not isinstance(name, str) or not _INPUT_NAME.match(name)
                or name == FORMULA_VARIABLE or name in FORMULA_FUNCTIONS):
            raise ValueError(
                f"{name!r} cannot name an input: a lower-case word of at most 16 "
                f"letters, digits and underscores, other than {FORMULA_VARIABLE} "
                "and the functions"
            )
        if mode == "variables":
            if not isinstance(value, str) or not value:
                raise ValueError(f"input {name} must name a time series set variable")
            out[name] = value
        else:
            out[name] = _input_reference(name, value, depth)
    return out


def _input_reference(name: str, raw: Any, depth: int) -> dict[str, Any]:
    """One input as a read carries it: the time series set it was resolved
    from, which is the same question `instance_series_points` answers."""
    if not isinstance(raw, dict):
        raise ValueError(f"input {name} must name an object's time series")
    ref: dict[str, Any] = {}
    for field in ("object_type_id", "instance_id", "property"):
        value = raw.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"input {name} needs its {field}")
        if field != "property":
            try:
                value = str(UUID(value))
            except ValueError:
                raise ValueError(f"input {name}: {value!r} is not an id") from None
        ref[field] = value
    for field, allowed, default in (("interval", INTERVALS, "day"),
                                    ("aggregate", AGGREGATES, "avg")):
        value = raw.get(field, default)
        if value not in allowed:
            raise ValueError(f"input {name}: the {field} must be one of {', '.join(allowed)}")
        ref[field] = value
    try:
        ref["transforms"] = parse_transforms(
            raw.get("transforms"), inputs="references", _depth=depth + 1)
    except ValueError as exc:
        raise ValueError(f"input {name}: {exc}") from None
    return ref
#: The functions a formula may call, each one argument. The ones with a
#: domain answer outside it with a gap rather than failing the whole read.
FORMULA_FUNCTIONS = ("abs", "sqrt", "ln", "log10", "exp", "floor", "ceil", "round")
MAX_FORMULA = 200


def formula_sql(expression: str, inputs: Sequence[str] = ()) -> str:
    """A formula over `x` as SQL over `value`, or a ValueError saying what in
    it is not arithmetic. Parsed, never interpolated: only numbers, `x`, the
    four operations, powers, brackets and FORMULA_FUNCTIONS get through.

    With other inputs (§561) the series is joined to them: `x` is `x.value`
    and each input `in_<name>.value`, as `_transform_sql` aliases them."""
    import ast

    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError:
        raise ValueError(f"{expression!r} is not a formula") from None
    columns = ({FORMULA_VARIABLE: "x.value", **{n: f"in_{n}.value" for n in inputs}}
               if inputs else {FORMULA_VARIABLE: "value"})
    return _formula_node(tree.body, columns)


def _formula_node(node: Any, columns: dict[str, str]) -> str:
    import ast

    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        number = float(node.value)
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{node.value!r} is too large a number for a formula")
        return repr(number)
    if isinstance(node, ast.Name) and node.id in columns:
        return f"CAST({columns[node.id]} AS DOUBLE)"
    if isinstance(node, ast.Name):
        raise ValueError(f"a formula knows only {', '.join(columns)}, not {node.id!r}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        sign = "-" if isinstance(node.op, ast.USub) else "+"
        return f"({sign}{_formula_node(node.operand, columns)})"
    if isinstance(node, ast.BinOp):
        left, right = _formula_node(node.left, columns), _formula_node(node.right, columns)
        if isinstance(node.op, ast.Add):
            return f"({left} + {right})"
        if isinstance(node.op, ast.Sub):
            return f"({left} - {right})"
        if isinstance(node.op, ast.Mult):
            return f"({left} * {right})"
        # A division by zero and a fractional power of a negative are left to
        # DuckDB, which answers infinity or NaN rather than failing; the
        # transform's `isfinite` turns either into a gap. A guard here would
        # be a second copy of that rule.
        if isinstance(node.op, ast.Div):
            return f"({left} / {right})"
        if isinstance(node.op, ast.Pow):
            return f"power({left}, {right})"
        raise ValueError("a formula uses only + - * / and **")
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name not in FORMULA_FUNCTIONS:
            raise ValueError(f"a formula may call only {', '.join(FORMULA_FUNCTIONS)}")
        if len(node.args) != 1 or node.keywords:
            raise ValueError(f"{name} takes one argument")
        arg = _formula_node(node.args[0], columns)
        # sqrt and the logarithms are guarded because DuckDB *raises* outside
        # their domain, which would fail the whole series for one point.
        if name == "sqrt":
            return f"(CASE WHEN {arg} < 0 THEN NULL ELSE sqrt({arg}) END)"
        if name in ("ln", "log10"):
            return f"(CASE WHEN {arg} <= 0 THEN NULL ELSE {name}({arg}) END)"
        return f"{name}({arg})"
    raise ValueError("a formula is numbers, x, + - * / **, brackets and "
                     f"{', '.join(FORMULA_FUNCTIONS)}")


def _window_call(aggregate: str) -> str:
    # Every name in WINDOW_AGGREGATES is DuckDB's own; its `stddev` is the
    # sample standard deviation, which one point does not have.
    return f"{aggregate}(value)"


def _transform_sql(
    transform: dict[str, Any], source: str, *, per_series: bool = False,
    inputs: dict[str, str] | None = None,
) -> str:
    """One transform as a query over `source`, which has `at` and `value` - and
    `series`, when `per_series` is set: a page of series at once (§555), each
    transformed on its own, the windows partitioned by it. `inputs` names the
    query each of a formula's other inputs is read from (§561)."""
    s = "series, " if per_series else ""
    part = "PARTITION BY series " if per_series else ""
    kind = transform["kind"]
    if kind == "cumulative":
        # p.584: "aggregating over all earlier points, including the input
        # point itself".
        return (f"SELECT {s}at, {_window_call(transform['aggregate'])} OVER ({part}ORDER BY at "
                f"ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS value FROM {source}")
    if kind == "periodic":
        # p.584: "equally spaced, non-overlapping time intervals … aligned
        # with a user-specified alignment timestamp". A point exactly on a
        # boundary starts a Start window and ends an End window.
        align = _epoch_seconds(transform["align"])
        size = transform["window"] * TIME_UNITS[transform["unit"]]
        edge = "floor" if transform["window_type"] == "start" else "ceil"
        return (
            f"SELECT {s}epoch_ms(CAST(({align} + {edge}((epoch_ms(CAST(at AS TIMESTAMP)) / 1000.0 "
            f"- {align}) / {size}) * {size}) * 1000 AS BIGINT)) AS at, "
            f"{_window_call(transform['aggregate'])} AS value FROM {source} "
            f"GROUP BY {'1, 2' if per_series else '1'}"
        )
    if kind == "integral":
        # p.585: "the cumulative area under the input time series", in the
        # unit chosen: a power reading integrated per hour is energy in
        # kilowatt-hours. Each gap between two points adds its width times
        # the method's height; the first point has no area before it.
        height = {"linear": f"(lag(value) OVER ({part}ORDER BY at) + value) / 2",
                  "left": f"lag(value) OVER ({part}ORDER BY at)",
                  "right": "value"}[transform["method"]]
        seconds = TIME_UNITS[transform["unit"]]
        return (
            f"SELECT {s}at, coalesce(sum(area) OVER ({part}ORDER BY at ROWS BETWEEN UNBOUNDED "
            f"PRECEDING AND CURRENT ROW), 0) AS value FROM (SELECT {s}at, "
            f"(epoch_ms(CAST(at AS TIMESTAMP)) - epoch_ms(CAST(lag(at) OVER ({part}ORDER BY at) "
            f"AS TIMESTAMP))) / 1000.0 / {seconds} * {height} AS area FROM {source}) areas"
        )
    if kind == "rolling":
        # p.584: "the points that fall in a fixed-size temporal window
        # preceding it, including the input point itself". A window of time,
        # not of points, so gaps in the readings do not stretch it.
        return (f"SELECT {s}at, {_window_call(transform['aggregate'])} OVER ({part}ORDER BY at "
                f"RANGE BETWEEN INTERVAL {transform['window']} {transform['unit'].upper()} "
                f"PRECEDING AND CURRENT ROW) AS value FROM {source}")
    if kind == "derivative":
        # p.585: the rate of change, per the unit chosen. The first point has
        # nothing before it to change from, and two readings at one instant
        # have no rate, so both are left out rather than drawn as zero.
        seconds = TIME_UNITS[transform["unit"]]
        return (
            f"SELECT {s}at, value FROM (SELECT {s}at, (value - lag(value) OVER ({part}ORDER BY at)) "
            "/ NULLIF((epoch_ms(CAST(at AS TIMESTAMP)) "
            f"- epoch_ms(CAST(lag(at) OVER ({part}ORDER BY at) AS TIMESTAMP))) / 1000.0, 0) "
            f"* {seconds} AS value FROM {source}) rates WHERE value IS NOT NULL"
        )
    if kind == "shift":
        # p.586: "identical to the input time series, but temporally shifted".
        return (f"SELECT {s}CAST(at AS TIMESTAMP) + INTERVAL ({transform['by']}) "
                f"{transform['unit'].upper()} AS at, value FROM {source}")
    if kind == "formula" and inputs:
        # §561: p.586's formula over several series. **Its points are the
        # series' own**, and each other input is read *as of* each of them -
        # its latest value at or before that instant - so a daily input
        # against hourly readings holds its day's value, and an input with no
        # reading yet leaves a gap, as a division by zero does. p.586 does not
        # say how inputs line up; this is the rule that invents no reading.
        joins = " ".join(
            f"ASOF LEFT JOIN (SELECT CAST(at AS TIMESTAMP) AS at, value FROM {query}) "
            f"in_{name} ON CAST(x.at AS TIMESTAMP) >= in_{name}.at"
            for name, query in inputs.items()
        )
        expression = formula_sql(transform["expression"], tuple(inputs))
        return (f"SELECT at, CASE WHEN isfinite(v) THEN v END AS value FROM "
                f"(SELECT x.at AS at, CAST({expression} AS DOUBLE) AS v "
                f"FROM {source} x {joins}) formula")
    if kind == "formula":
        # p.586's formula, over this series as `x`. A point whose formula has
        # no answer (a division by zero, a square root of a negative) is a
        # gap rather than an error for the whole series, and so is one that
        # overflows: infinity is not a reading.
        return (f"SELECT {s}at, CASE WHEN isfinite(v) THEN v END AS value FROM "
                f"(SELECT {s}at, CAST({formula_sql(transform['expression'])} AS DOUBLE) AS v "
                f"FROM {source}) formula")
    where = []
    if transform["start"] is not None:
        where.append(f"CAST(at AS TIMESTAMP) >= TIMESTAMP {_literal(transform['start'])}")
    if transform["end"] is not None:
        where.append(f"CAST(at AS TIMESTAMP) <= TIMESTAMP {_literal(transform['end'])}")
    return f"SELECT {s}at, value FROM {source} WHERE {' AND '.join(where)}"


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
    transforms: list[dict[str, Any]] | None = None,
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

    if transforms:
        # §524: every point goes through the transforms and the cap comes
        # last. A cumulative sum over the first five thousand readings would
        # be a different series, not a shorter one.
        ctes: list[str] = []
        last = _chain(ctes, "t", _base_sql(ts, val, clause, interval, aggregate), transforms)
        return (f"WITH {', '.join(ctes)} SELECT at, value FROM {last} "
                f"ORDER BY at LIMIT {capped}")
    return f"{_base_sql(ts, val, clause, interval, aggregate)} ORDER BY at LIMIT {capped}"


def _chain(ctes: list[str], prefix: str, base: str, transforms: list[dict[str, Any]]) -> str:
    """A series and its transforms as CTEs `<prefix>0`, `<prefix>1`, …, added
    to `ctes`, with the name of the last. A formula's other inputs (§561) are
    chains of their own, read in full before it: an input capped or cut short
    would be a different series, for the cap's reason."""
    ctes.append(f"{prefix}0 AS ({base})")
    for n, transform in enumerate(transforms, start=1):
        joined = {
            name: _chain(ctes, f"{prefix}{n}_{name}_", _input_sql(name, spec),
                         spec["transforms"])
            for name, spec in (transform.get("inputs") or {}).items()
        }
        ctes.append(f"{prefix}{n} AS "
                    f"({_transform_sql(transform, f'{prefix}{n - 1}', inputs=joined)})")
    return f"{prefix}{len(transforms)}"


def _input_sql(name: str, spec: dict[str, Any]) -> str:
    """A formula input's own series, from the table the read loaded its
    dataset as (`routes/objects._resolve_formula_inputs`)."""
    if "table" not in spec:
        raise ValueError(f"input {name} was not resolved to a dataset")  # pragma: no cover
    where = f"CAST({_quote(spec['key_column'])} AS VARCHAR) = {_literal(spec['series_id'])}"
    return _base_sql(_quote(spec["timestamp_column"]), _quote(spec["value_column"]), where,
                     spec["interval"], spec["aggregate"], table=spec["table"])


def _base_sql(ts: str, val: str, clause: str, interval: str, aggregate: str,
              table: str = "dataset") -> str:
    """The series itself, bucketed or not, unordered and uncapped."""
    if interval == "none":
        # The raw points. Still capped and still ordered by the caller - "no
        # bucketing" is not "no limit", and a series with a decade of readings
        # would otherwise decide how much memory the API uses.
        return f"SELECT {ts} AS at, {val} AS value FROM {table} WHERE {clause}"
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
        f"{expression} AS value FROM {table} "
        f"WHERE {clause} GROUP BY at"
    )


def track_sql(
    *,
    key_column: str,
    timestamp_column: str,
    point_column: str,
    series_id: str,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = MAX_POINTS,
) -> str:
    """The query that reads one geotemporal series out of its dataset (§427).

    `points_sql`'s counterpart, and a separate function rather than a branch
    in it, because **a geotemporal series has no aggregate and no interval**
    and that is the interesting part rather than an omission:

      * the mean of two positions is a place neither of them was, and on a
        track that crosses a bay it is a point in the water. `avg` is the
        default every chart uses and it is the one answer a map must not give;
      * `sum` and `count` are not positions at all;
      * `min`/`max` would need an order on positions, and there is none - the
        same objection `property_reducers.UNREDUCIBLE` makes about geopoints
        one layer down;
      * `last` alone *would* work, and a bucketed track of last-known
        positions is a real thing - but it is a different reading from the one
        p.11 asks for ("render on a Map"), and offering one operation out of
        five under a control that names five would be a control that mostly
        refuses (§214). Downsampling a track belongs with whatever asks for
        it, with its own word.

    So this returns the raw points, ordered and capped, and the cap is the
    same `MAX_POINTS` for the same reason: a decade of readings should not
    decide how much memory the API uses.

    **The point column is returned as text**, not parsed here. This module
    does not know what a position is; `property_values._coerce_geopoint` does,
    and it already reads every spelling a real column holds. A parse here
    would be a second one free to disagree with it (§191).
    """
    key, ts, point = _quote(key_column), _quote(timestamp_column), _quote(point_column)
    where = [f"CAST({key} AS VARCHAR) = {_literal(series_id)}"]
    if start is not None:
        where.append(f"{ts} >= TIMESTAMP {_literal(start.isoformat())}")
    if end is not None:
        where.append(f"{ts} <= TIMESTAMP {_literal(end.isoformat())}")
    clause = " AND ".join(where)
    capped = max(1, min(limit, MAX_POINTS))
    return (
        f"SELECT {ts} AS at, CAST({point} AS VARCHAR) AS point FROM dataset "
        f"WHERE {clause} ORDER BY at LIMIT {capped}"
    )


#: How many positions a map draws per track (§557): enough for a breadcrumb
#: trail to have its shape, few enough that a page of tracks stays one read.
TRACK_POINTS = 500


def tracks_for_many_sql(
    *,
    key_column: str,
    timestamp_column: str,
    point_column: str,
    series_ids: "Sequence[str]",
    per_series: int = TRACK_POINTS,
) -> str:
    """`track_sql` for a page of tracks at once (§557; `workshop` p.303's map
    timeline over the objects on a map).

    `points_for_many_sql`'s shape, for its reasons: one query rather than one
    per object, the allowance **per track** with a window rather than a LIMIT
    over all of them, the **latest** positions kept and put back in time
    order. And `track_sql`'s: raw positions, no bucket and no aggregate, the
    point column returned as text for `_coerce_geopoint` to read.
    """
    if not series_ids:
        raise ValueError("no tracks to read")
    if len(series_ids) > MAX_SERIES:
        raise ValueError(f"too many tracks: {len(series_ids)} (max {MAX_SERIES})")
    key, ts, point = _quote(key_column), _quote(timestamp_column), _quote(point_column)
    wanted = ", ".join(_literal(s) for s in dict.fromkeys(series_ids))
    series_key = f"CAST({key} AS VARCHAR)"
    capped = max(1, min(per_series, MAX_POINTS))
    return (
        f"SELECT series, at, point FROM (SELECT {series_key} AS series, {ts} AS at, "
        f"CAST({point} AS VARCHAR) AS point, "
        f"row_number() OVER (PARTITION BY {series_key} ORDER BY {ts} DESC) AS rn "
        f"FROM dataset WHERE {series_key} IN ({wanted})) WHERE rn <= {capped} "
        "ORDER BY series, at"
    )
