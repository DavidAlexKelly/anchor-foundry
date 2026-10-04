"""An interface set, evaluated (§254, §741; `ontology` p.61, `action-types`
p.36, p.62).

This is `POST /interfaces/{id}/evaluate`'s body, moved out of the route so the
second reader of an interface set reads the same one: §741's interface
reference dropdown, whose p.36 filters are written against the interface and
have to be rewritten onto each implementation exactly as the route's are.
`interfaces.members_page` (now removed) said it would collapse into this evaluator the day an
interface reference gained filters, rather than grow a second copy, and this
is that day.

See `interface_sets` for the rules (filters translated by name, a type that
answers nothing to a filtered property skipped rather than read unfiltered,
the merged order and its depth bound); this module only runs them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from . import (
    instance_store, instances, interface_sets, interfaces, object_set_eval, object_sets,
    ontology,
)


def _jsonb(value: Any) -> Any:
    import json

    return json.loads(value) if isinstance(value, str) else value


@dataclass
class Evaluated:
    instances: list[dict[str, Any]]
    total: int
    #: The implementing types read, and the ones skipped because a filter
    #: names an optional property they answer nothing to.
    read: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


async def declared(conn: AsyncConnection, workspace_id: UUID, interface_id: UUID) -> tuple[
    dict[str, Any], dict[str, str]
]:
    """The interface and its effective `{api_name: data_type}` - the
    vocabulary every filter on it is written in."""
    interface = await interfaces.get_interface(conn, workspace_id, interface_id)
    return interface, {
        str(p["api_name"]): str(p["data_type"]) for p in interface["effective_properties"]
    }


async def evaluate(
    conn: AsyncConnection,
    workspace_id: UUID,
    interface_id: UUID,
    *,
    filters: Any,
    sort: Any = None,
    limit: int,
    offset: int = 0,
) -> Evaluated:
    """Every object of every type that implements this interface, narrowed by
    `filters` written in the interface's own names.

    Raises `interface_sets.InterfaceSetError` for a request the interface
    cannot answer and `ValueError` for a filter one implementation's store
    refuses; the route turns both into a 422.
    """
    interface, names = await declared(conn, workspace_id, interface_id)
    members_raw = await interfaces.implementations_of(conn, workspace_id, interface_id)
    members = [
        interface_sets.Member(
            object_type_id=UUID(r["object_type_id"]), property_mapping=r["property_mapping"],
        )
        for r in members_raw
    ]
    # **The request before the resource.** Depth and sort are wrong about what
    # was asked for whatever this interface looks like, and answering "nothing
    # implements it" to somebody who asked for page nine sends them to fix the
    # wrong thing.
    interface_sets.check_depth(limit=limit, offset=offset)
    order = interface_sets.parse_sort(sort)
    interface_sets.check_fan_out(members, interface_name=str(interface["api_name"]))

    prefix = await instances.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    pages: list[list[dict[str, Any]]] = []
    read: list[str] = []
    total = 0
    for member, raw in zip(members, members_raw):
        translated = interface_sets.filters_for(
            filters, member=member, declared=names, interface_name=str(interface["api_name"]),
        )
        if translated is None:
            # This type answers nothing to a filtered property, so no object of
            # it can match. Skipped rather than read unfiltered, which would be
            # decision 0002's silent widening.
            continue
        property_types = await object_set_eval.declared_types(conn, member.object_type_id)
        # §675: each implementing property's row, for what it presents
        # (p.131's reduced element, p.170's main field).
        presenters = {str(p["api_name"]): p
                      for p in await ontology.list_properties(conn, member.object_type_id)}
        definition = object_sets.parse(
            {"object_type_id": str(member.object_type_id), "filters": translated},
            property_types=property_types,
        )
        # **The whole prefix of the merged order, from every type.** Any of
        # them could supply the entire page, so each is asked for
        # `offset + limit` from the top rather than for its own slice - which
        # is what `check_depth` bounds.
        rows, count = await store.evaluate_object_set(
            search_prefix=prefix,
            object_type_id=definition.object_type_id,
            filters=definition.filters,
            limit=offset + limit,
            offset=0,
            sort=object_sets.parse_sorts(order, property_types=property_types),
        )
        total += count
        read.append(str(raw["display_name"]))
        pages.append([
            {
                "id": r["id"],
                "primary_key": r["primary_key"],
                "object_type_id": member.object_type_id,
                "object_type_name": raw["display_name"],
                "updated_at": r["updated_at"],
                "properties": interface_sets.project(
                    _jsonb(r["properties"]) or {},
                    member=member, declared=names, presenters=presenters,
                ),
            }
            for r in rows
        ])
    return Evaluated(
        instances=interface_sets.merge(pages, sort=order, limit=limit, offset=offset),
        total=total,
        read=read,
        skipped=[str(r["display_name"]) for r in members_raw if str(r["display_name"]) not in read],
    )


async def contains(
    conn: AsyncConnection,
    workspace_id: UUID,
    interface_id: UUID,
    *,
    filters: list[dict[str, Any]],
    object_type_id: UUID,
    primary_key: Any,
) -> bool:
    """Whether one object, of one implementing type, is in the interface set
    these filters make - p.34's "the value selected is also validated", asked
    of the object rather than by reading the offer and looking for it (§331's
    lesson: an object past the dropdown's last row is still allowed).
    """
    interface, names = await declared(conn, workspace_id, interface_id)
    for raw in await interfaces.implementations_of(conn, workspace_id, interface_id):
        if UUID(str(raw["object_type_id"])) != object_type_id:
            continue
        member = interface_sets.Member(
            object_type_id=object_type_id, property_mapping=raw["property_mapping"],
        )
        translated = interface_sets.filters_for(
            filters, member=member, declared=names, interface_name=str(interface["api_name"]),
        )
        if translated is None:
            return False
        property_types = await object_set_eval.declared_types(conn, object_type_id)
        definition = object_sets.parse(
            {"object_type_id": str(object_type_id), "filters": [
                *translated,
                {"property": object_sets.PRIMARY_KEY_FILTER, "op": "eq", "value": primary_key},
            ]},
            property_types=property_types,
        )
        prefix = await instances.workspace_search_prefix(conn, workspace_id)
        _rows, count = await instance_store.store_for(conn).evaluate_object_set(
            search_prefix=prefix, object_type_id=object_type_id,
            filters=definition.filters, limit=1, offset=0,
        )
        return count > 0
    return False
