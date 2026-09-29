"""The readings of a union of object sets that a Filter List needs (§687;
`workshop` p.450).

> "You can use a variable to store a union of multiple object sets of
> different object types and pass it to the Filter List widget. The Filter
> List will allow the following filtering options: Common property … Single
> property" (p.450)

A union is `{"union": [definition, ...]}` (§686), each part a set over one
type. **Every reading here asks each part the question the route already asks
of one set, and adds the answers up**, so nothing about how a set is counted,
bucketed or narrowed has a second implementation. The store does the work,
once per part.

**A part whose type does not declare the property has no values for it**,
which is p.450's Single property read from the other side: its objects are in
the union and in no bar. They are counted in a distribution's or a timeline's
`total`, so `missing` says how many members have no value, as it does for one
set.

**Only counts.** A count adds up across parts; an average or a distinct count
does not, and a chart over a union is not something p.450 describes. So a
grouping that asks for any other aggregation is refused.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from . import instance_store
from . import instances as instances_service
from . import object_set_eval, object_sets
from . import ontology as ontology_service


@dataclass(frozen=True)
class Part:
    definition: object_sets.ObjectSet
    #: The part's membership, with any traversal resolved (§544).
    members: tuple[object_sets.Filter, ...]
    #: `{api_name: data_type}` for the part's type.
    declared: dict[str, str]


def parts_of(definition: dict[str, Any]) -> list[dict[str, Any]]:
    """Each part, unparsed. One that is not an object is refused by
    `object_type_id_of`, in the sentence a lone set gets."""
    raw = definition[object_sets.UNION]
    if not isinstance(raw, list) or not raw:
        raise ValueError("a union of object sets holds at least one set")
    return raw


async def _parts(conn: Any, store: Any, prefix: str, workspace_id: UUID,
                 definition: dict[str, Any]) -> list[Part]:
    out: list[Part] = []
    for raw in parts_of(definition):
        type_id = object_sets.object_type_id_of(raw)
        await ontology_service.get_type(conn, workspace_id, type_id)
        declared = await object_set_eval.declared_types(conn, type_id)
        parsed = object_sets.parse(raw, property_types=declared)
        members = await object_set_eval.members_filters(conn, store, prefix, workspace_id, parsed)
        out.append(Part(parsed, tuple(members), declared))
    return out


async def _store(conn: Any, workspace_id: UUID) -> tuple[Any, str]:
    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    return instance_store.store_for(conn), prefix


async def _count(store: Any, prefix: str, part: Part, *extra: object_sets.Filter) -> int:
    n = await store.aggregate_object_set(
        search_prefix=prefix, object_type_id=part.definition.object_type_id,
        filters=(*part.members, *extra), aggregation="count", property_name=None)
    return int(n or 0)


# ---- grouping: a histogram's or a dropdown's values ------------------------
def merge_groups(
    answers: list[tuple[list[tuple[str, int]], int]], limit: int,
) -> tuple[list[tuple[str, int]], int, bool]:
    """Each part's `(buckets, distinct_total)`, as one list of the `limit`
    commonest values: count descending, then value ascending, the order the
    route gives one set.

    `distinct_total` is exact when no part was cut short, since then every
    value of every part is here. When one was, a value past its cut is not, so
    the total is the most that can be said - at least this many - and the
    answer says it was truncated."""
    counts: dict[str, int] = {}
    cut = False
    for buckets, distinct in answers:
        cut = cut or distinct > len(buckets)
        for value, count in buckets:
            counts[value] = counts.get(value, 0) + count
    ordered = sorted(counts.items(), key=lambda vc: (-vc[1], vc[0]))
    distinct_total = max([len(ordered), *(d for _, d in answers)])
    return ordered[:limit], distinct_total, cut or len(ordered) > limit


async def group(conn: Any, workspace_id: UUID, definition: dict[str, Any], property_name: str,
                limit: int, aggregation: str) -> tuple[list[tuple[str, int]], int, bool]:
    """p.450's options for one property, with how many objects of the whole
    union have each value.

    **A count is exact for every value shown.** A part whose own list was cut
    short may hold a value that made the combined list without making its own,
    so that part is asked for each such value directly rather than counted as
    having none of it."""
    if aggregation != "count":
        raise ValueError(
            "a union of object sets is grouped by count; aggregate one of the sets it "
            "joins for anything else")
    store, prefix = await _store(conn, workspace_id)
    parts = [p for p in await _parts(conn, store, prefix, workspace_id, definition)
             if property_name in p.declared]
    answers: list[tuple[list[tuple[str, int]], int]] = []
    for part in parts:
        buckets, distinct = await store.group_object_set(
            search_prefix=prefix, object_type_id=part.definition.object_type_id,
            filters=part.members, property_name=property_name, limit=limit,
            aggregation=object_sets.parse_aggregation("count", None),
        )
        answers.append(([(value, count) for value, count, _ in buckets], distinct))
    shown, distinct_total, truncated = merge_groups(answers, limit)
    extra: dict[str, int] = {}
    for part, (buckets, distinct) in zip(parts, answers):
        if distinct <= len(buckets):
            continue
        have = {value for value, _ in buckets}
        for value, _ in shown:
            if value not in have:
                extra[value] = extra.get(value, 0) + await _count(
                    store, prefix, part, object_sets.Filter(property_name, "in", [value]))
    if extra:
        recounted = [(value, count + extra.get(value, 0)) for value, count in shown]
        shown = sorted(recounted, key=lambda vc: (-vc[1], vc[0]))
    return shown, distinct_total, truncated


# ---- distribution: a numeric property's bars --------------------------------
@dataclass(frozen=True)
class Distribution:
    buckets: list[tuple[object_sets.Bucket, int]]
    integer: bool
    total: int


async def distribution(conn: Any, workspace_id: UUID, definition: dict[str, Any],
                       property_name: str, buckets: int) -> Distribution:
    """p.449's distribution chart over every part that has the number, on one
    range: the smallest and largest value in the whole union, so a bar means
    the same range for every type it counts."""
    store, prefix = await _store(conn, workspace_id)
    parts = await _parts(conn, store, prefix, workspace_id, definition)
    total = 0
    numbered: list[tuple[Part, str]] = []
    for part in parts:
        total += await _count(store, prefix, part)
        if property_name in part.declared:
            numbered.append((part, object_sets.distributable_type(property_name, part.declared)))
    lows: list[float] = []
    highs: list[float] = []
    for part, _ in numbered:
        for name, into in (("min", lows), ("max", highs)):
            value = await store.aggregate_object_set(
                search_prefix=prefix, object_type_id=part.definition.object_type_id,
                filters=part.members,
                aggregation=object_sets.parse_aggregation(
                    name, property_name, property_types=part.declared))
            if value is not None:
                into.append(float(value))
    # Whole numbers only when every part's are: one decimal makes the bars
    # ranges of decimals for all of them.
    integer = bool(numbered) and all(t == "integer" for _, t in numbered)
    ranges = [] if not lows else object_sets.distribution_buckets(
        min(lows), max(highs), buckets, integer=integer)
    counted = []
    for bucket in ranges:
        n = 0
        for part, data_type in numbered:
            n += await _count(store, prefix, part,
                              *object_sets.bucket_filters(property_name, data_type, bucket))
        counted.append((bucket, n))
    return Distribution(counted, integer, total)


# ---- time series: a timeline's dates ----------------------------------------
def merge_times(answers: list[list[tuple[datetime, int]]]) -> list[tuple[datetime, int]]:
    """Each part's buckets, added up by start. One interval for every part, so
    a start means the same bucket in each."""
    counts: dict[datetime, int] = {}
    for buckets in answers:
        for start, count in buckets:
            counts[start] = counts.get(start, 0) + count
    return sorted(counts.items())


async def time_series(conn: Any, workspace_id: UUID, definition: dict[str, Any],
                      property_name: str | None, interval: str
                      ) -> tuple[list[tuple[datetime, int]], str, int]:
    """p.449's timeline, or when the union's objects last changed: each part's
    buckets at one interval, added up, then filled as one series. `auto` picks
    the finest interval that fits the whole union, as it does one set."""
    store, prefix = await _store(conn, workspace_id)
    parts = await _parts(conn, store, prefix, workspace_id, definition)
    total = 0
    dated: list[tuple[Part, tuple[str, str] | None]] = []
    for part in parts:
        total += await _count(store, prefix, part)
        if property_name is None:
            dated.append((part, None))
        elif property_name in part.declared:
            dated.append((part, (property_name,
                                 object_sets.datable_type(property_name, part.declared))))
    candidates = (object_sets.TIME_INTERVALS if interval == object_sets.AUTO_INTERVAL
                  else (interval,))
    filled: list[tuple[datetime, int]] = []
    for candidate in candidates:
        answers = [await store.time_series_object_set(
            search_prefix=prefix, object_type_id=part.definition.object_type_id,
            filters=part.members, interval=candidate, date_property=date_property,
        ) for part, date_property in dated]
        try:
            filled = object_sets.fill_time_buckets(merge_times(answers), candidate)
        except ValueError:
            if candidate != candidates[-1]:
                continue
            raise
        if len(filled) <= object_sets.MAX_AUTO_POINTS or candidate == candidates[-1]:
            break
    return filled, candidate, total
