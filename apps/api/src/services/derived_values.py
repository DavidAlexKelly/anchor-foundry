"""A page of derived property values, one read per hop (§604;
`object-link-types` p.143-147).

`_derive_property` answers one object: its chain is an object set rooted at
that object, and each hop is a read. A table of twenty-five rows asking the
same way is twenty-five chains - a read per row per hop, which is why
`_with_derived` has always been single-reads-only and why a derived property
was an empty column everywhere a list is drawn (`ontology.md`'s row for
p.143, `workshop.md`'s for p.169).

**This is the chain pushed into the set read**, the shape that row named and
§402 used for a page of time series: each hop reads the far objects of *every*
row at once, with the same `in` filter a single chain compiles to, and then
hands each row back the objects its own join values reach. Three hops for a
page is three reads, whatever the page size.

**The answer is the single read's answer**, and `test_derived_values.py`
holds the two to it row by row:

- the same link lookup, refused in the same sentences;
- the same text comparison for a join (`instance_store.join_key`, which both
  stores use), and the same `MAX_JOIN_VALUES` refusal from `join_filter`;
- the same key order for a collection, because the far objects are read with
  the same `key_asc` sort and each row keeps them in that order;
- and the arithmetic in `object_sets.comparable`, the reference semantics the
  stores are tested against (Postgres casts both numeric types to double
  precision, which is what that function does in Python), with
  `instances._number`'s rule for what an aggregate returns.

**One difference, and it is a bound rather than a meaning.** A single chain
may reach `MAX_JOIN_VALUES` objects per hop; a page's hop may reach
`MAX_REACHED` in total across its rows, and past that the property is
refused for the page with a sentence rather than answered for some rows.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from . import derived_properties, link_join_tables, object_sets
from . import ontology as ontology_service
from .instance_store import join_key
from .instances import _number

#: How many far objects one hop may reach for a whole page. Twenty-five rows
#: of a department's employees is well inside it; a page whose rows each
#: reach a thousand things is a page of derived values nobody can read.
MAX_REACHED = 5000


def _jsonb(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _value(row: dict[str, Any], name: str) -> Any:
    """What a hop or an aggregation reads off an object: its key, or one of its
    properties - `$primary_key` is the one name that is not a property."""
    if name == ontology_service.PRIMARY_KEY_REF:
        return row["primary_key"]
    return _jsonb(row["properties"]).get(name)


def empty_for(aggregate: str | None) -> Any:
    """What a chain that reached nothing answers (`_empty_for`'s rule)."""
    if aggregate in ("count", "exact_cardinality"):
        return 0
    if aggregate in ("collect_list", "collect_set"):
        return []
    return None


async def derive_for_rows(
    conn: Any,
    store: Any,
    prefix: str,
    workspace_id: UUID,
    *,
    start_type_id: UUID,
    rows: list[dict[str, Any]],
    derivation: dict[str, Any],
) -> dict[str, Any]:
    """One derived property for every row, keyed by the row's primary key.

    Raises `ValueError` with the sentence the single read would give, or with
    `MAX_REACHED`'s when the page as a whole reaches too far.
    """
    # Each row's objects at the current hop, keyed by primary key so an object
    # reached twice (two employees on one project) is one object - a chain is
    # a *set*, which is what the single read's `in` filter gives it too.
    reached: dict[str, dict[str, dict[str, Any]]] = {
        str(r["primary_key"]): {str(r["primary_key"]): r} for r in rows
    }
    order: dict[str, int] = {}
    type_id = start_type_id
    for hop in derivation["links"]:
        # **Only the refusal a saved chain can still meet.** `resolve_traversal`
        # also re-checks that each type is visible and that a link lands where
        # the set says, because it answers sets a caller wrote. A derivation was
        # checked against both when it was saved, a link's two types cannot be
        # changed afterwards, and every hop is in this workspace - so §604's
        # sweep found neither check could fire here, and they went. A link
        # *deleted* under a derivation is still possible, and refused below.
        links = await ontology_service.links_for_type(conn, workspace_id, type_id)
        link = next((row for row in links if str(row["id"]) == str(hop["link_type_id"])), None)
        if link is None:
            raise ValueError(
                "that link type does not connect the set being traversed from - a link "
                "joins two named object types, and this one does not touch that type"
            )
        far_type = UUID(str(hop["far_type_id"]))

        near = str(link["near_property"])
        here = {pk: obj for level in reached.values() for pk, obj in level.items()}
        # Each object's join key on the far side: its own value, or - through
        # p.197's join table - the far keys the table pairs it with. An empty
        # value (`None`) is kept rather than skipped: `join_filter` and
        # `follow_pairs` both drop it, so it reaches nothing either way.
        targets: dict[str, list[Any]] = {
            pk: [join_key(_value(obj, near))] for pk, obj in here.items()
        }
        if link.get("join"):
            pairs = await link_join_tables.follow_pairs(
                conn, link["join"], [t for ts in targets.values() for t in ts], MAX_REACHED + 1,
            )
            if sum(len(v) for v in pairs.values()) > MAX_REACHED:
                raise ValueError(_too_far(MAX_REACHED))
            targets = {pk: pairs.get(ts[0], []) for pk, ts in targets.items()}

        joined = object_sets.join_filter(
            far_property=str(link["far_property"]),
            values=[t for ts in targets.values() for t in ts],
        )
        far_rows: list[dict[str, Any]] = []
        if joined is not None:
            far_rows, _ = await store.evaluate_object_set(
                search_prefix=prefix,
                object_type_id=far_type,
                filters=(joined,),
                limit=MAX_REACHED + 1,
                offset=0,
                sort="key_asc",
            )
            if len(far_rows) > MAX_REACHED:
                raise ValueError(_too_far(MAX_REACHED))
        by_key: dict[str, list[dict[str, Any]]] = {}
        for far in far_rows:
            key = join_key(_value(far, str(link["far_property"])))
            if key is not None:
                by_key.setdefault(key, []).append(far)
        order = {str(far["primary_key"]): i for i, far in enumerate(far_rows)}
        reached = {
            start: {
                str(far["primary_key"]): far
                for pk in level
                for key in targets.get(pk, [])
                for far in by_key.get(key, [])
            }
            for start, level in reached.items()
        }
        type_id = far_type

    aggregate = derivation.get("aggregate")
    numeric = None
    if aggregate in derived_properties.NUMERIC_AGGREGATES:
        # The far type's declaration, read now rather than carried on the
        # derivation - `_derive_property`'s reason, and its refusals.
        far = await ontology_service.list_properties(conn, type_id)
        numeric = object_sets.parse_aggregation(
            str(aggregate),
            str(derivation.get("property") or ""),
            property_types={str(p["api_name"]): str(p["data_type"]) for p in far},
        )
    return {
        start: _aggregate(
            sorted(level.values(), key=lambda o: order[str(o["primary_key"])]),
            derivation,
            numeric,
        )
        for start, level in reached.items()
    }


def _too_far(limit: int) -> str:
    return (
        f"this page's rows reach more than {limit} objects along the chain, so the "
        "column is not filled in - it is still answered on each object's own view"
    )


def _aggregate(objs: list[dict[str, Any]], derivation: dict[str, Any], numeric: Any) -> Any:
    """One row's answer from the objects its chain reached, in key order."""
    aggregate = derivation.get("aggregate")
    if not objs:
        return empty_for(aggregate)
    name = str(derivation.get("property") or "")
    if aggregate == "count":
        return len(objs)
    if aggregate == "exact_cardinality":
        # Distinct *text*, nulls left out: `count(DISTINCT
        # jsonb_extract_path_text(...))`, which is the store's answer.
        return len({k for k in (join_key(_jsonb(o["properties"]).get(name)) for o in objs)
                    if k is not None})
    if numeric is not None:
        values = [
            v for v in (object_sets.comparable(_jsonb(o["properties"]).get(name), numeric.data_type)
                        for o in objs)
            if v is not None
        ]
        if not values:
            return None
        if numeric.name == "sum":
            total = sum(values)
        elif numeric.name == "avg":
            total = sum(values) / len(values)
        elif numeric.name == "min":
            total = min(values)
        else:
            total = max(values)
        return _number(total, numeric)
    limit = int(derivation.get("limit") or 1)
    values = [_value(o, name) for o in objs[:limit]]
    if aggregate == "collect_set":
        return sorted({v for v in values if v is not None}, key=lambda v: str(v))
    if aggregate == "collect_list":
        return values
    return values[0]
