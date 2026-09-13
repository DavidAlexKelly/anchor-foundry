"""Evaluating a set definition's link hops (§333; `ontology.md` §3).

**A pure move out of `routes/objects.py`, where this had lived since §155.**
Nothing here is new: `resolve_traversal` is `_resolve_traversal` and
`declared_types` is `_declared_types`, with the same bodies and the same
reasoning. What changed is who can reach them.

The reason is p.37's Search Arounds:

    "A Search Around would create a new set by traversing a link on every
     object in the current set. For example, `Github Issue of Current
     Employee` would take the `Employees` in the current set and create a
     resulting set of `Github Issues` linked to those `Employees`."
     (`action-types` p.37)

An action's object dropdown is now built from a set that may traverse links
(p.34: "action editors can specify filters **and Search Arounds** to limit the
objects that show up in the dropdown"), and `action_choices` cannot import a
route module. The alternative was a second hop resolver living beside the
action code, which is the two-implementations problem this file's own
docstrings spend most of their length arguing against — a set whose members a
dropdown disagreed about with the object-set editor would be the worst possible
place to discover it.

Takes the `store` as an argument rather than importing one, because that is how
it was already written: a hop is a read of the set below, and the caller
already holds the store its own reads go through.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from . import object_sets
from . import ontology as ontology_service


def _jsonb(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else value


async def declared_types(conn: Any, object_type_id: UUID) -> dict[str, str]:
    """One object type's `api_name -> data_type`, for validating a set (§221).

    The shape `object_sets.parse` wants, built where the ontology is readable —
    that module imports nothing, which is what keeps the *meaning* of a set out
    of reach of a database.
    """
    return {
        str(row["api_name"]): str(row["data_type"])
        for row in await ontology_service.list_properties(conn, object_type_id)
        if row.get("api_name") and row.get("data_type")
    }


async def resolve_traversal(
    conn: Any,
    store: Any,
    prefix: str,
    workspace_id: UUID,
    definition: "object_sets.ObjectSet",
) -> tuple[tuple[Any, ...], bool]:
    """Turn a set's `via` hop into the filters that express it.

    Returns `(filters, empty)`. **`empty` is not "no filters"** - it means the
    set below linked to nothing, so this set has no members and the caller must
    stop rather than read the type unfiltered.

    **The link decides which end is near**, read from the base set's own type
    (`links_for_type` returns a link once per end it occupies), so a definition
    cannot name the wrong direction - it does not name one at all. A link that
    does not join these two types is refused here rather than quietly
    returning nothing, because "your definition is wrong" and "there are no
    matches" look identical in an empty table.

    Recursive, bounded by `MAX_TRAVERSALS` at parse time.
    """
    if definition.via is None:
        return definition.filters, False

    base = definition.via.base
    await ontology_service.get_type(conn, workspace_id, base.object_type_id)
    base_filters, base_empty = await resolve_traversal(
        conn, store, prefix, workspace_id, base
    )
    if base_empty:
        return definition.filters, True

    links = await ontology_service.links_for_type(conn, workspace_id, base.object_type_id)
    link = next(
        (row for row in links if str(row["id"]) == str(definition.via.link_type_id)), None
    )
    if link is None:
        raise ValueError(
            "that link type does not connect the set being traversed from - a link "
            "joins two named object types, and this one does not touch that type"
        )
    if str(link["far_type_id"]) != str(definition.object_type_id):
        raise ValueError(
            "this traversal lands on a different object type than the set declares - "
            f"following that link from there reaches {link['far_type_display_name']!r}"
        )

    # The near side's join values. Read at the cap plus one, so "too many" is a
    # refusal with a number rather than a page silently missing its tail.
    members, _ = await store.evaluate_object_set(
        search_prefix=prefix,
        object_type_id=base.object_type_id,
        filters=base_filters,
        limit=object_sets.MAX_JOIN_VALUES + 1,
        offset=0,
        sort="key_asc",
    )
    near = str(link["near_property"])
    values = [
        row["primary_key"]
        if near == ontology_service.PRIMARY_KEY_REF
        else _jsonb(row["properties"]).get(near)
        for row in members
    ]
    joined = object_sets.join_filter(far_property=str(link["far_property"]), values=values)
    if joined is None:
        return definition.filters, True
    return (joined, *definition.filters), False
