"""Favourite objects (§312; db 0074; `getting-started` p.34).

    "When you navigate to an individual object view, you can select the star
     next to its title to save it as a favorite. This will add the object to
     your sidebar… Think of favorites as shortcuts that you can add and remove
     to keep frequently used resources close at hand." (p.34)

**Whose favourites they are never travels in a request.** db 0074's policy pins
every read and write to the caller, so there is no parameter here that could be
pointed at somebody else's shortcuts — which is the same division
`scratchpad_queries` arrived at the expensive way in §306, where two service
clauses turned out to be doing nothing the policy was not already doing.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError

#: How many objects one person may star in one workspace.
#:
#: **A refusal rather than an eviction**, which is the opposite of §306's
#: scratchpad history and for the opposite reason. A history is a record of
#: what you did and dropping its oldest entry loses nothing anybody chose; a
#: favourite *is* the choice, so silently dropping the least recent would
#: delete a decision. p.34 calls these "frequently used resources close at
#: hand", and a list long enough to need scrolling has stopped being that.
MAX_FAVOURITES = 100


class TooManyFavourites(Exception):
    """The list is full, and the message says what to do about it."""


async def add(
    conn: AsyncConnection,
    *,
    user_id: UUID,
    workspace_id: UUID,
    object_type_id: UUID,
    instance_id: UUID,
    label: str,
) -> dict[str, Any]:
    """Star one object.

    **Starring twice is the same star** (db 0074's UNIQUE), so this is safe to
    call from a button whose state arrived a moment ago. The label is refreshed
    on the way through: the object may have been renamed since, and the moment
    somebody stars it again is the one moment we are holding the current name.
    """
    existing = await fetch_one(
        conn,
        """
        SELECT id FROM object_favourites
         WHERE object_type_id = :tid AND instance_id = :iid
        """,
        {"tid": str(object_type_id), "iid": str(instance_id)},
    )
    if existing is None:
        # Counted only when a row is about to be added, so re-starring
        # something already in a full list is not refused for being full.
        count = await fetch_one(
            conn,
            "SELECT count(*) AS n FROM object_favourites WHERE workspace_id = :wid",
            {"wid": str(workspace_id)},
        )
        assert count is not None
        if int(count["n"]) >= MAX_FAVOURITES:
            raise TooManyFavourites(
                f"You have {MAX_FAVOURITES} favourites in this workspace, which "
                "is as many as this list holds. Remove one you have finished "
                "with — favourites are shortcuts to what you are working on now."
            )

    row = await fetch_one(
        conn,
        """
        INSERT INTO object_favourites
               (user_id, workspace_id, object_type_id, instance_id, label)
        VALUES (:uid, :wid, :tid, :iid, :label)
        ON CONFLICT (user_id, object_type_id, instance_id) DO UPDATE
           SET label = EXCLUDED.label
        RETURNING id, object_type_id, instance_id, label, created_at
        """,
        {"uid": str(user_id), "wid": str(workspace_id),
         "tid": str(object_type_id), "iid": str(instance_id), "label": label[:500]},
    )
    assert row is not None
    return dict(row)


async def remove(
    conn: AsyncConnection, *, object_type_id: UUID, instance_id: UUID
) -> None:
    """Unstar one object.

    Addressed by *what it points at* rather than by the favourite's own id,
    because that is what the caller has: the star sits on an object view, which
    knows the object and has never been told the row's id.
    """
    row = await fetch_one(
        conn,
        """
        DELETE FROM object_favourites
         WHERE object_type_id = :tid AND instance_id = :iid
        RETURNING id
        """,
        {"tid": str(object_type_id), "iid": str(instance_id)},
    )
    if row is None:
        raise NotFoundError("this favourite")


async def listing(
    conn: AsyncConnection, *, workspace_id: UUID
) -> list[dict[str, Any]]:
    """This person's favourites in this workspace, newest first.

    **Newest first, not alphabetical.** p.34's shortcuts are "frequently used
    resources close at hand", and what somebody starred most recently is what
    they are working on now. A list sorted by a label the reader did not choose
    would bury today's work under a name beginning with A.

    The type's display name is joined so a row can say what kind of thing it
    is; the object's own label is stored (db 0074) so ten shortcuts do not cost
    ten reads against the instance store.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT f.id, f.object_type_id, f.instance_id, f.label, f.created_at,
               t.display_name AS object_type_name
          FROM object_favourites f
          JOIN object_types t ON t.id = f.object_type_id
         WHERE f.workspace_id = :wid
         ORDER BY f.created_at DESC
        """,
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def starred(
    conn: AsyncConnection, *, object_type_id: UUID, instance_id: UUID
) -> bool:
    """Whether this object is one of the caller's favourites.

    Its own read rather than a scan of `listing`, because the star is drawn on
    an object view that has no reason to have fetched the whole list — and a
    view that fetched a hundred favourites to decide the state of one button
    would be paying the sidebar's cost on a screen that has no sidebar.
    """
    row = await fetch_one(
        conn,
        """
        SELECT 1 AS yes FROM object_favourites
         WHERE object_type_id = :tid AND instance_id = :iid
        """,
        {"tid": str(object_type_id), "iid": str(instance_id)},
    )
    return row is not None
