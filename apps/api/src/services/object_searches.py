"""Saved searches for the Object Explorer (ROADMAP.md phase 2, item 4.1).

Stored in migration 0040. A saved search holds a *definition* - the explorer's
own parameters - and never results: "vessels flagged NO" is a question, and the
answer is different tomorrow.

**The interesting part of this module is `parse`, and it is interesting because
it is used twice.** The explorer route has always had a rule that a property
filter needs exactly one type, because a property api_name only means something
within a type. That rule lived in the route. If saving a search had validated
separately - or not at all - it would be possible to save a search that cannot
run, and the person who found out would not be the person who made the mistake.
So the rule moved here, and both callers use it.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

MAX_TYPE_IDS = 20


class SearchError(ValueError):
    """Refusal, phrased for whoever wrote the search."""


def parse(
    *,
    q: str | None,
    type_ids: list[UUID] | None,
    property_name: str | None,
    value: str | None,
    # Browsing everything is a reasonable thing to do in the explorer; *saving*
    # an empty search is not. The one place the two callers legitimately
    # differ, named rather than left to each of them to remember.
    require_criteria: bool = True,
) -> dict[str, Any]:
    """The explorer's parameters, checked once for everybody who runs them.

    Two rules, both of which exist because the alternative is a query that
    answers a different question from the one asked:

    * **`property` and `value` come as a pair.** One without the other is
      either "match anything" or "match a value in no particular column", and
      neither is what somebody typing half a filter meant.
    * **A property filter needs exactly one type.** `status` on an Order and
      `status` on a Shipment are unrelated columns that happen to share a name,
      so matching across both silently unions two different questions.
    """
    if (property_name is None) != (value is None):
        raise SearchError("filtering by a property needs both 'property' and 'value'")
    ids = list(type_ids or [])
    if len(ids) > MAX_TYPE_IDS:
        raise SearchError(f"a search may name at most {MAX_TYPE_IDS} object types")
    if len(set(map(str, ids))) != len(ids):
        raise SearchError("the same object type appears twice in this search")
    if property_name is not None and len(ids) != 1:
        raise SearchError(
            "filtering by a property needs exactly one type_id - a property "
            "name only means something within a type"
        )
    if require_criteria and not q and not ids and property_name is None:
        # A named question with no question in it.
        raise SearchError("a saved search needs something to search for")
    return {
        "q": q or None,
        "type_ids": [str(i) for i in ids],
        "property": property_name,
        "value": value,
    }


def _definition(row: Any) -> dict[str, Any]:
    stored = row["definition"]
    return json.loads(stored) if isinstance(stored, str) else dict(stored or {})


async def _annotate(
    conn: AsyncConnection, workspace_id: UUID, rows: list[Any]
) -> list[dict[str, Any]]:
    """Fill in the type names, and say which are gone.

    A search naming a deleted object type still opens - the filter simply
    matches nothing - but saying so beats rendering a bare uuid, and beats
    refusing to open a search somebody may want to repair.
    """
    known = {
        str(r["id"]): str(r["display_name"])
        for r in await fetch_all(
            conn,
            "SELECT id, display_name FROM object_types WHERE workspace_id = :wid",
            {"wid": str(workspace_id)},
        )
    }
    out: list[dict[str, Any]] = []
    for row in rows:
        definition = _definition(row)
        ids = [str(i) for i in definition.get("type_ids", [])]
        out.append({
            **dict(row),
            "definition": definition,
            "type_names": [known[i] for i in ids if i in known],
            "missing_types": [i for i in ids if i not in known],
        })
    return out


_COLUMNS = "id, workspace_id, name, description, definition, created_by, created_at, updated_at"


async def list_searches(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM object_searches WHERE workspace_id = :wid ORDER BY name",
        {"wid": str(workspace_id)},
    )
    return await _annotate(conn, workspace_id, list(rows))


async def get_search(
    conn: AsyncConnection, workspace_id: UUID, search_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS} FROM object_searches WHERE id = :id AND workspace_id = :wid",
        {"id": str(search_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("saved search")
    return (await _annotate(conn, workspace_id, [row]))[0]


async def create_search(
    conn: AsyncConnection,
    workspace_id: UUID,
    *,
    name: str,
    description: str,
    definition: dict[str, Any],
    created_by: UUID | None,
) -> dict[str, Any]:
    existing = await fetch_one(
        conn,
        "SELECT id FROM object_searches WHERE workspace_id = :wid AND name = :name",
        {"wid": str(workspace_id), "name": name},
    )
    if existing is not None:
        raise ConflictError(
            f"a saved search called {name!r} already exists in this workspace"
        )
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO object_searches (workspace_id, name, description, definition, created_by)
        VALUES (:wid, :name, :descr, CAST(:definition AS jsonb), :by)
        RETURNING {_COLUMNS}
        """,
        {
            "wid": str(workspace_id), "name": name, "descr": description,
            "definition": json.dumps(definition),
            "by": str(created_by) if created_by else None,
        },
    )
    assert row is not None
    return (await _annotate(conn, workspace_id, [row]))[0]


async def update_search(
    conn: AsyncConnection,
    workspace_id: UUID,
    search_id: UUID,
    *,
    name: str | None,
    description: str | None,
    definition: dict[str, Any] | None,
) -> dict[str, Any]:
    await get_search(conn, workspace_id, search_id)
    if name is not None:
        clash = await fetch_one(
            conn,
            "SELECT id FROM object_searches "
            "WHERE workspace_id = :wid AND name = :name AND id <> :id",
            {"wid": str(workspace_id), "name": name, "id": str(search_id)},
        )
        if clash is not None:
            raise ConflictError(
                f"a saved search called {name!r} already exists in this workspace"
            )
    row = await fetch_one(
        conn,
        f"""
        UPDATE object_searches
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description),
               definition = COALESCE(CAST(:definition AS jsonb), definition)
         WHERE id = :id AND workspace_id = :wid
        RETURNING {_COLUMNS}
        """,
        {
            "name": name, "descr": description,
            "definition": json.dumps(definition) if definition is not None else None,
            "id": str(search_id), "wid": str(workspace_id),
        },
    )
    assert row is not None
    return (await _annotate(conn, workspace_id, [row]))[0]


async def delete_search(
    conn: AsyncConnection, workspace_id: UUID, search_id: UUID
) -> None:
    await get_search(conn, workspace_id, search_id)
    await conn.exec_driver_sql(
        "DELETE FROM object_searches WHERE id = %s AND workspace_id = %s",
        (str(search_id), str(workspace_id)),
    )
