"""What was edited last (§317; db 0075; `ontology-manager` p.30).

    "Hovering over the Back home button will also bring up quick links to
     recently edited object types, link types, and action types, as well as
     all resources that are related to the one you are currently viewing."
     (p.30)

**The three kinds p.30 names, and no more.** Shared properties, value types,
groups and interfaces are all findable by name in the search this sits beside
(§146, §165, §168, §172, §252), and p.30's list stops at three. Adding a fourth
would be inventing a specification and then claiming parity against it.

**One query, not three lists merged here.** Taking the five most recent of a
kind by fetching every row of it is exactly the shape §209 measured at seven
seconds — this build's development workspace holds over thirteen hundred object
types, and five of them are wanted. The `UNION ALL` lets Postgres sort and
truncate, and the whole answer is `limit` rows wide however large the ontology
gets.

**No index on `updated_at`, and that is measured rather than assumed.** The
sort is over every row of the three tables in one workspace, which is the
largest development workspace's 1,979 — 23ms, against a `LIMIT 8`. An index
per table would be three write costs on every ontology edit to save twenty
milliseconds on a panel nobody blocks on. Worth revisiting at a scale nothing
here is near; §209's lesson was about a *loop* issuing queries, not about
sorting two thousand rows.

**`updated_at`, not a history table.** `object_type_versions` (db 0028) records
who changed a type and when, and nothing equivalent exists for link types or
action types — so a per-person "edited by you" would be answerable for one of
p.30's three kinds and quietly workspace-wide for the other two. p.30 asks for
"recently edited", not "recently edited by you", and a list that silently means
different things for different rows is worse than one that means one thing.

What counts as an edit is whatever moves the row: a definition change, a status
change, a title property (`ontology.py` has the three writers). No sync path
writes `object_types`, so a nightly load does not push a type nobody has
touched to the top of this list — which was worth checking before relying on
it, because a "recently edited" list dominated by machine writes is a list
people stop opening.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all

#: How many quick links p.30's hover is worth.
#:
#: **A hover, not a listing.** p.30 calls these "quick links", and the screen
#: they appear on already has a search across the whole ontology and a paged
#: table of every type. A list long enough to scroll would be a third way of
#: looking at the same rows and a worse one than either — so this is short
#: enough to read at a glance and be wrong about cheaply.
DEFAULT_LIMIT = 8

#: The ceiling on what a caller may ask for. Not a security bound — the value
#: is a bind parameter — but a "quick links" endpoint asked for a thousand rows
#: is a listing endpoint under a name that promises it is cheap.
MAX_LIMIT = 50


async def recent(
    conn: AsyncConnection, workspace_id: UUID, *, limit: int = DEFAULT_LIMIT
) -> list[dict[str, Any]]:
    """The most recently edited object types, link types and action types.

    Each row carries the same `kind`/`id`/`api_name`/`display_name` shape a
    search hit does (`ontology_search.search`), plus `updated_at` and the
    object type the thing belongs to — deliberately, so one renderer can draw
    both. Two lists of links to the same things, differing only in how they
    were found, would be two places for a destination to go wrong.

    A link type belongs to *both* its ends; the `from` end is reported, which
    is the same choice `ontology_search` makes and for the same reason — a link
    has to be listed under one type or be listed twice.
    """
    if limit < 1:
        raise ValueError(f"limit must be at least 1 (given {limit})")
    if limit > MAX_LIMIT:
        raise ValueError(f"limit is at most {MAX_LIMIT} (given {limit})")
    rows = await fetch_all(
        conn,
        """
        SELECT kind, id, api_name, display_name, updated_at,
               object_type_id, object_type_name
          FROM (
            SELECT 'object_type' AS kind, ot.id, ot.api_name, ot.display_name,
                   ot.updated_at, ot.id AS object_type_id,
                   ot.display_name AS object_type_name
              FROM object_types ot
             WHERE ot.workspace_id = :wid
            UNION ALL
            -- Joined to the `from` end rather than left-joined: db 0003 makes
            -- both ends NOT NULL with foreign keys, so a link type without an
            -- end is not a row this schema can hold.
            SELECT 'link_type', lt.id, lt.api_name, lt.display_name,
                   lt.updated_at, lt.from_object_type_id, f.display_name
              FROM link_types lt
              JOIN object_types f ON f.id = lt.from_object_type_id
             WHERE lt.workspace_id = :wid
            UNION ALL
            SELECT 'action_type', act.id, act.api_name, act.display_name,
                   act.updated_at, act.object_type_id, o.display_name
              FROM action_types act
              JOIN object_types o ON o.id = act.object_type_id
             WHERE act.workspace_id = :wid
          ) AS edited
         -- `id` breaks the tie, so two things saved in the same transaction
         -- come back in a stable order. Without it the page can reorder
         -- between two reads that returned the same rows, which reads as the
         -- list changing while nobody edited anything.
         ORDER BY updated_at DESC, id
         LIMIT :limit
        """,
        {"wid": str(workspace_id), "limit": limit},
    )
    return [dict(r) for r in rows]
