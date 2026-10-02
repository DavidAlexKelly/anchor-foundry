"""Following a link through its backing object type (§666; db 0132;
`object-link-types` p.197, p.199).

    "Object-backed link types expand on many-to-one cardinality link types,
     providing first class support for object types as a link type storage
     solution." (p.199)

A backed link is p.199's three prerequisites put together: the two end types,
a backing type whose every object is one link, and a many-to-one link from the
backing type to each end. So it is followed as a join table is (§552) - the
near objects' values, through the pairs, to the far objects' values - where
the pairs are the backing objects: each holds the near end's value in one
property and the far end's in another, as its two links say.

**The two links are read when the link is**, not copied into it (db 0132's
reason): a backing link whose properties change moves the backed link with
it, and one that no longer joins the backing type to its end leaves the
backed link unmapped rather than following the wrong properties.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from . import object_sets
from .instance_store import join_key

PRIMARY_KEY_REF = "$primary_key"


def side(link: dict[str, Any], *, end_type_id: Any, backing_type_id: Any) -> tuple[str, str] | None:
    """How a backing link joins its end: the end's property and the backing
    type's that is compared with it. None for a link that does not join those
    two types, or does not do it by a pair of properties - a join table's or
    another backing type's link has no one property on the backing object to
    read."""
    # db 0027 keeps a pair both-or-neither, so one side answers for both (a
    # check of the other survived the sweep as equivalent).
    if not link.get("from_property"):
        return None
    ends = (str(link["from_object_type_id"]), str(link["to_object_type_id"]))
    if ends == (str(backing_type_id), str(end_type_id)):
        return str(link["to_property"]), str(link["from_property"])
    if ends == (str(end_type_id), str(backing_type_id)):
        return str(link["from_property"]), str(link["to_property"])
    return None


def oriented(link: dict[str, Any], ends: dict[str, str], *, workspace_id: Any,
             outbound: bool) -> dict[str, Any]:
    """A backed link's pairs from one end, in the shape a join table's are
    (`link_join_tables.oriented`): the backing property holding the values in
    hand, and the one holding the values to arrive at."""
    near, far = ends["from_backing"], ends["to_backing"]
    return {
        "backing_type_id": str(link["backing_type_id"]),
        "workspace_id": str(workspace_id),
        "near_column": near if outbound else far,
        "far_column": far if outbound else near,
    }


async def _backing_objects(conn: Any, join: dict[str, Any], wanted: list[str], limit: int) -> list[dict[str, Any]]:
    """The backing objects whose near property is one of these values, at most
    `limit` of them."""
    from . import instance_store
    from . import instances as instances_service

    joined = object_sets.join_filter(far_property=join["near_column"], values=wanted)
    if joined is None:
        return []
    prefix = await instances_service.workspace_search_prefix(conn, UUID(join["workspace_id"]))
    rows, _ = await instance_store.store_for(conn).evaluate_object_set(
        search_prefix=prefix, object_type_id=UUID(join["backing_type_id"]), filters=(joined,),
        limit=limit, offset=0, sort="key_asc",
    )
    return rows


def _read(row: dict[str, Any], prop: str) -> Any:
    if prop == PRIMARY_KEY_REF:
        return row["primary_key"]
    props = row["properties"]
    if isinstance(props, str):
        import json

        props = json.loads(props)
    return props.get(prop)


async def follow(conn: Any, join: dict[str, Any], keys: list[Any]) -> list[str]:
    """The far values the backing objects pair with these near ones.

    **The backing objects read are bounded, not only the values** - each is
    one link, so a thousand links from one object are a thousand objects - and
    past `MAX_JOIN_VALUES` the traversal is refused with the number rather
    than following some of them."""
    wanted = sorted({join_key(k) for k in keys if k is not None})
    if len(wanted) > object_sets.MAX_JOIN_VALUES:
        raise ValueError(
            f"this traversal starts from {len(wanted)} objects and the limit is "
            f"{object_sets.MAX_JOIN_VALUES} - narrow the set it traverses from first"
        )
    rows = await _backing_objects(conn, join, wanted, object_sets.MAX_JOIN_VALUES + 1)
    if len(rows) > object_sets.MAX_JOIN_VALUES:
        raise ValueError(
            f"these objects are linked by more than {object_sets.MAX_JOIN_VALUES} backing "
            "objects - narrow the set it traverses from first"
        )
    far = {join_key(_read(r, join["far_column"])) for r in rows}
    return sorted(v for v in far if v is not None)


async def follow_pairs(conn: Any, join: dict[str, Any], keys: list[Any], limit: int) -> dict[str, list[str]]:
    """`follow` for many near objects at once, keyed by the near value (§604's
    shape): at most `limit` backing objects, one more being the caller's
    signal to refuse."""
    wanted = sorted({join_key(k) for k in keys if k is not None})
    out: dict[str, list[str]] = {}
    for row in await _backing_objects(conn, join, wanted, limit):
        # Each row matched a wanted near value, so its near value is one; a
        # blank far value is kept and dropped by `join_filter` downstream (a
        # guard for it here survived the sweep as equivalent).
        near = join_key(_read(row, join["near_column"]))
        out.setdefault(str(near), []).append(join_key(_read(row, join["far_column"])))
    return out
