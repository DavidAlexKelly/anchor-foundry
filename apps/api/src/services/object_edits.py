"""Per-object edit history (§470; `workshop` p.402–403, db 0104).

> "The Edit History widget displays the list of user edits made to an object's
> properties after Track user edit history has been enabled for the object type
> within Ontology Manager." (p.402)

**Recorded by the three action paths and read by one route.** The single
execute, the batch submission and the undo each call `record` once per object
they changed, after the write succeeded and only then - a failed run changed
nothing, and a history entry beside a failure would describe an edit that did
not happen. A sync never calls it, which is p.402's "edits completed by a
pipeline … will not be reflected" by construction.

**Whether to record is read here, at write time**, from the type's
`edit_history_since`: tracking off means nothing is written, so switching it on
later cannot make earlier edits appear - p.402's "Edits completed prior to
enabling Edit History … will not be reflected".
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: The most edits one read returns. A history is read a screen at a time, and
#: an object edited by an automation every minute for a year has half a million.
MAX_EDITS = 500

ORDERS = ("newest", "oldest")


def diff(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """The properties whose value changed, in name order, with both values.

    **Compared as JSON**, so `1` and `1.0` differ only where JSON says they
    do, and a property that went from a value to absent reads as `None` on its
    new side rather than vanishing from the record.
    """
    changed = []
    for name in sorted(set(before) | set(after)):
        old, new = before.get(name), after.get(name)
        if json.dumps(old, sort_keys=True, default=str) != json.dumps(new, sort_keys=True, default=str):
            changed.append((name, old, new))
    return changed


async def tracking_since(conn: AsyncConnection, object_type_id: UUID) -> datetime | None:
    row = await fetch_one(
        conn,
        "SELECT edit_history_since FROM object_types WHERE id = :tid",
        {"tid": str(object_type_id)},
    )
    return row["edit_history_since"] if row else None


async def set_tracking(
    conn: AsyncConnection, workspace_id: UUID, object_type_id: UUID, enabled: bool,
) -> datetime | None:
    """p.402's "Track user edit history". Enabling keeps an existing start
    rather than moving it, so saving the setting twice does not hide the edits
    recorded between the two saves; disabling clears it."""
    row = await fetch_one(
        conn,
        """
        UPDATE object_types
           SET edit_history_since = CASE
                 WHEN :on THEN COALESCE(edit_history_since, now())
                 ELSE NULL END
         WHERE id = :tid AND workspace_id = :wid
        RETURNING edit_history_since
        """,
        {"on": enabled, "tid": str(object_type_id), "wid": str(workspace_id)},
    )
    return row["edit_history_since"] if row else None


async def record(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    object_type_id: UUID,
    primary_key: str,
    action_run_id: UUID | None,
    edited_by: UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> int:
    """Record one object's change: a create (no `before`), a delete (no
    `after`), or a row per property that differs. Returns how many rows were
    written, which is none when the type is not tracked or nothing changed."""
    if await tracking_since(conn, object_type_id) is None:
        return 0
    if before is None and after is None:
        return 0
    if before is None:
        rows = [("create", None, None, after)]
    elif after is None:
        rows = [("delete", None, before, None)]
    else:
        rows = [("modify", name, old, new) for name, old, new in diff(before, after)]
    for kind, prop, old, new in rows:
        await fetch_one(
            conn,
            """
            INSERT INTO object_edits
                (workspace_id, object_type_id, primary_key, action_run_id, edited_by,
                 kind, property, before_value, after_value)
            VALUES (:wid, :tid, :pk, :run, :who, :kind, :prop,
                    CAST(:old AS jsonb), CAST(:new AS jsonb))
            RETURNING id
            """,
            {
                "wid": str(workspace_id), "tid": str(object_type_id), "pk": primary_key,
                "run": str(action_run_id) if action_run_id else None,
                "who": str(edited_by), "kind": kind, "prop": prop,
                "old": None if old is None else json.dumps(old, default=str),
                "new": None if new is None else json.dumps(new, default=str),
            },
        )
    return len(rows)


class EditRecorder:
    """`record` with one run's constants bound, for a path that changes
    several objects in one submission."""

    def __init__(
        self, conn: AsyncConnection, *, workspace_id: UUID, action_run_id: UUID | None,
        edited_by: UUID,
    ) -> None:
        self._conn = conn
        self._common = {
            "workspace_id": workspace_id, "action_run_id": action_run_id,
            "edited_by": edited_by,
        }

    async def record(
        self, object_type_id: UUID, primary_key: str,
        before: dict[str, Any] | None, after: dict[str, Any] | None,
    ) -> int:
        return await record(
            self._conn, object_type_id=object_type_id, primary_key=primary_key,
            before=before, after=after, **self._common,
        )


async def history(
    conn: AsyncConnection,
    *,
    object_type_id: UUID,
    primary_key: str,
    order: str = "newest",
    properties: list[str] | None = None,
    limit: int = MAX_EDITS,
) -> tuple[list[dict[str, Any]], bool]:
    """One object's edits, and whether there were more than `limit`.

    `properties` narrows to p.403's "Property configuration"; **a create or a
    delete is kept whatever it names**, because it is not about one property and
    a history that dropped them would show an object's edits with no start.
    """
    direction = "DESC" if order == "newest" else "ASC"
    rows = await fetch_all(
        conn,
        f"""
        SELECT e.id, e.kind, e.property,
               -- As text, decoded once by the caller: a jsonb string comes back
               -- from the driver already decoded, so decoding "whatever came
               -- back" would parse an email address as JSON.
               e.before_value::text AS before_value, e.after_value::text AS after_value,
               e.edited_at,
               e.action_run_id, e.edited_by, u.display_name AS editor_name,
               u.email AS editor_email
          FROM object_edits e
          LEFT JOIN users u ON u.id = e.edited_by
         WHERE e.object_type_id = :tid AND e.primary_key = :pk
           AND (CAST(:props AS text[]) IS NULL OR e.property IS NULL
                OR e.property = ANY(CAST(:props AS text[])))
         ORDER BY e.edited_at {direction}, e.seq {direction}
         LIMIT :lim
        """,
        {
            "tid": str(object_type_id), "pk": primary_key,
            "props": properties, "lim": limit + 1,
        },
    )
    out = [dict(r) for r in rows]
    return out[:limit], len(out) > limit
