"""p.65's Interface action control (§763).

> "Submission criteria apply uniformly across all object types that implement
> the interface, so you cannot configure different permissions per object type
> within a single interface action. To restrict access, disable interface
> actions for specific object types in Ontology Manager by selecting its
> Interfaces tab and establishing control over actions inherited from an
> interface in the Interface action control section." (action-types p.65)

An object type may switch off any action on an interface it implements, for
its own objects. Switched off, the action is not among the type's actions
(p.64's merge in `actions.list_action_types`) and is refused when submitted
against one of its objects (`refusal`), which is what makes this a control
rather than a label.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one


class ControlError(ValueError):
    """A control that cannot be stored."""


async def inherited(
    conn: AsyncConnection, workspace_id: UUID, object_type_id: UUID
) -> list[dict[str, Any]]:
    """Every action on an interface this type implements, and whether this
    type has it switched on."""
    rows = await fetch_all(
        conn,
        """
        SELECT at.id AS action_type_id, at.api_name, at.display_name,
               i.id AS interface_id, i.display_name AS interface_name,
               NOT EXISTS (SELECT 1 FROM interface_action_controls c
                            WHERE c.object_type_id = :tid AND c.action_type_id = at.id)
                   AS enabled
          FROM action_types at
          JOIN interfaces i ON i.id = at.interface_id
          JOIN object_type_interfaces oti
            ON oti.interface_id = at.interface_id AND oti.object_type_id = :tid
         WHERE at.workspace_id = :wid
         ORDER BY i.display_name, at.display_name, at.api_name
        """,
        {"tid": str(object_type_id), "wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def set_disabled(
    conn: AsyncConnection,
    workspace_id: UUID,
    object_type_id: UUID,
    disabled: list[UUID],
    *,
    created_by: UUID,
) -> list[dict[str, Any]]:
    """Which inherited actions this type switches off, the whole list. Each
    must be an action this type inherits: switching off anything else would
    be a row nothing reads."""
    offered = {str(r["action_type_id"]) for r in await inherited(conn, workspace_id, object_type_id)}
    wanted = list(dict.fromkeys(str(d) for d in disabled))
    stray = [d for d in wanted if d not in offered]
    if stray:
        raise ControlError(
            "only an action on an interface this object type implements can be switched "
            "off for it (action-types p.65)")
    await conn.execute(
        text("DELETE FROM interface_action_controls WHERE object_type_id = :tid"),
        {"tid": str(object_type_id)},
    )
    for action_id in wanted:
        await conn.execute(
            text(
                "INSERT INTO interface_action_controls (object_type_id, action_type_id, created_by) "
                "VALUES (:tid, :aid, :by)"
            ),
            {"tid": str(object_type_id), "aid": action_id, "by": str(created_by)},
        )
    return await inherited(conn, workspace_id, object_type_id)


async def refusal(
    conn: AsyncConnection, object_type_id: UUID, action_type_id: UUID, *, type_name: str
) -> str | None:
    """Why this interface action may not run against this type's objects,
    or None."""
    row = await fetch_one(
        conn,
        "SELECT 1 AS x FROM interface_action_controls "
        "WHERE object_type_id = :tid AND action_type_id = :aid",
        {"tid": str(object_type_id), "aid": str(action_type_id)},
    )
    if row is None:
        return None
    return (f"this action is switched off for {type_name} objects, in its Interface action "
            "control (action-types p.65)")
