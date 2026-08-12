"""Searching the ontology (parity `docs/parity/ontology.md` §6; Foundry
`ontology-manager` p.28).

> "Use the search bar in the header … to search across object types,
> properties, link types, action types, shared properties, interfaces, and
> functions." (p.28)

Four of those seven exist here; shared properties, interfaces and functions are
`○` in §1.2/§1.3 and are absent from this search for the same reason they are
absent from the Ontology Manager - there is nothing to find. Named rather than
silently skipped, because "search found nothing" and "search does not look
there" read identically to whoever typed the query.

**One query per kind, matched in Python.** The four tables are small - an
ontology is tens of types, not millions of rows - and the alternative is four
`ILIKE` clauses that would each need their own opinion about accent folding and
none of which could report *which field matched*. p.28 requires that report:
"the search results highlight the specific field that matched your query", and
a database `LIKE` that returns rows tells you a row matched, not why.

**Which field matched is the interesting part of the answer**, so it is a field
of the result rather than something the browser re-derives. A browser that
re-derived it would be a second matcher, free to disagree with the one that
decided the row belonged in the list at all - and the disagreement would look
like a highlight landing on the wrong word.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

MAX_RESULTS = 50

#: The fields searched per kind, in the order a match is reported. Order is
#: the answer to "which one matched" when a query matches more than one: the
#: name somebody would recognise beats the description they would not.
_FIELDS = ("api_name", "display_name", "description")


def _matched_field(row: dict[str, Any], needle: str, fields: tuple[str, ...] = _FIELDS) -> str | None:
    """The first of `fields` containing `needle`, case-insensitively.

    Returns the field *name*, not a boolean, because p.28's requirement is to
    say which one - and a caller that only wanted "did it match" can ask
    whether this is None.
    """
    for field in fields:
        value = row.get(field)
        if value is not None and needle in str(value).casefold():
            return field
    return None


async def search(
    conn: AsyncConnection, workspace_id: UUID, query: str, *, limit: int = MAX_RESULTS
) -> list[dict[str, Any]]:
    """Everything in this workspace's ontology matching `query`.

    Results carry `kind`, the thing's own id and names, **which field matched**,
    and - for a property - the object type it belongs to, because "status" on
    its own is not a place anybody can navigate to.

    A blank query returns nothing rather than everything: a search box whose
    empty state is the whole ontology is a list, and the Ontology Manager
    already has one of those.
    """
    from . import actions as actions_service
    from . import ontology as ontology_service

    needle = query.strip().casefold()
    if not needle:
        return []

    results: list[dict[str, Any]] = []
    types = await ontology_service.list_types(conn, workspace_id)
    by_id = {str(t["id"]): t for t in types}

    for row in types:
        field = _matched_field(row, needle)
        if field:
            results.append({
                "kind": "object_type",
                "id": str(row["id"]),
                "api_name": row["api_name"],
                "display_name": row["display_name"],
                "object_type_id": str(row["id"]),
                "object_type_name": row["display_name"],
                "matched_field": field,
                "matched_value": str(row[field] or ""),
            })

    for type_id, owner in by_id.items():
        for row in await ontology_service.list_properties(conn, UUID(type_id)):
            field = _matched_field(row, needle)
            if not field:
                continue
            results.append({
                "kind": "property",
                "id": str(row["id"]),
                "api_name": row["api_name"],
                "display_name": row["display_name"],
                "object_type_id": type_id,
                "object_type_name": owner["display_name"],
                "matched_field": field,
                "matched_value": str(row[field] or ""),
            })

    for row in await ontology_service.list_link_types(conn, workspace_id):
        # A link's two **side names** are searchable too: they are what the
        # relationship is called from each end (`object-link-types` p.192), so
        # somebody looking for "Direct reports" is looking for a side rather
        # than for the link's own name. Not `from_display_name`, which is the
        # *object type's* name at that end and is already findable as an
        # object type - searching it here would report the same word twice
        # under two kinds.
        field = _matched_field(
            row, needle, _FIELDS + ("from_side_name", "to_side_name")
        )
        if not field:
            continue
        results.append({
            "kind": "link_type",
            "id": str(row["id"]),
            "api_name": row["api_name"],
            "display_name": row["display_name"],
            "object_type_id": str(row["from_object_type_id"]),
            "object_type_name": by_id.get(
                str(row["from_object_type_id"]), {}
            ).get("display_name", ""),
            "matched_field": field,
            "matched_value": str(row[field] or ""),
        })

    for row in await actions_service.list_action_types(conn, workspace_id):
        field = _matched_field(row, needle)
        if not field:
            continue
        results.append({
            "kind": "action_type",
            "id": str(row["id"]),
            "api_name": row["api_name"],
            "display_name": row["display_name"],
            "object_type_id": str(row["object_type_id"]),
            "object_type_name": row["object_type_name"],
            "matched_field": field,
            "matched_value": str(row[field] or ""),
        })

    # **Sorted by how well the match reads, not by table.** An exact api_name
    # is what somebody typing a machine name wants first; a description match
    # is the weakest signal and goes last. Within a rank, by display name, so
    # the order is stable across calls rather than dependent on which query
    # returned first.
    def rank(result: dict[str, Any]) -> tuple[int, str]:
        value = result["matched_value"].casefold()
        if value == needle:
            return (0, str(result["display_name"]).casefold())
        if result["matched_field"] == "description":
            return (3, str(result["display_name"]).casefold())
        if value.startswith(needle):
            return (1, str(result["display_name"]).casefold())
        return (2, str(result["display_name"]).casefold())

    results.sort(key=rank)
    return results[:limit]
