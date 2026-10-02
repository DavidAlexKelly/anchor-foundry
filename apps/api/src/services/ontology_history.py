"""The Ontology's saved changes, across the workspace (§683; `ontology-manager`
p.8).

> "Select the History tab in the homepage sidebar to view a list of all saved
> Ontology changes with details on when the changes were made and the user who
> applied them. By default, the list of changes are collapsed." (p.8)

**Read from the audit log rather than kept a second time.** Every ontology
write already records who made it, when and to what (`audit.record`), and a
history table beside it would be a second account of the same saves, free to
disagree with the first. What this adds is the reading: the ontology's actions
only, in this workspace, newest first, each named by what it changed.

**An action's run is not an ontology change.** `action.execute` is somebody
using an action type, not editing one, so the filter is by the action's own
prefix - `action_type.*` is in, `action.*` is out - rather than by the resource
it was recorded against.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all

#: The audit prefixes that are edits to the ontology's definition.
PREFIXES = (
    "object_type", "link_type", "action_type", "interface", "shared_property",
    "value_type", "object_type_group", "object_view", "ontology",
)

#: Where each kind of resource is named now.
_TABLES = {
    "object_type": "object_types",
    "link_type": "link_types",
    "action_type": "action_types",
    "interface": "interfaces",
    "shared_property": "shared_properties",
    "value_type": "value_types",
    "object_type_group": "object_type_groups",
}

MAX_LIMIT = 200


async def history(
    conn: AsyncConnection,
    workspace_id: UUID,
    *,
    resource_id: UUID | None = None,
    limit: int = 50,
    before: int | None = None,
) -> list[dict[str, Any]]:
    """Saved changes, newest first; one resource's when `resource_id` is set
    (p.8's History tab on a resource's own page), and older than the entry
    `before` for the next page."""
    rows = await fetch_all(
        conn,
        """
        SELECT a.id, a.action, a.resource_type, a.resource_id, a.metadata,
               a.created_at, a.user_id, u.display_name AS user_name, u.email AS user_email
          FROM audit_log a
          LEFT JOIN users u ON u.id = a.user_id
         WHERE a.workspace_id = :wid
           AND split_part(a.action, '.', 1) = ANY(CAST(:prefixes AS text[]))
           AND (CAST(:rid AS uuid) IS NULL OR a.resource_id = CAST(:rid AS uuid))
           AND (CAST(:before AS bigint) IS NULL OR a.id < CAST(:before AS bigint))
         ORDER BY a.id DESC
         LIMIT :limit
        """,
        {
            "wid": str(workspace_id),
            "prefixes": "{" + ",".join(PREFIXES) + "}",
            "rid": str(resource_id) if resource_id else None,
            "before": before,
            "limit": max(1, min(limit, MAX_LIMIT)),
        },
    )
    out = [_entry(dict(r)) for r in rows]
    names = await _names(conn, workspace_id, out)
    for entry in out:
        entry["resource_name"] = names.get(str(entry["resource_id"])) or _named_in(entry)
    return out


def _entry(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("metadata")
    row["metadata"] = (json.loads(raw) if isinstance(raw, str) else raw) or {}
    row["user_name"] = row.get("user_name") or row.pop("user_email", None) or None
    row.pop("user_email", None)
    return row


def _named_in(entry: dict[str, Any]) -> str | None:
    """What the record itself called the resource, for one that has since
    gone: a history of a deleted type is still a history of *something*."""
    meta = entry["metadata"]
    for key in ("display_name", "api_name", "name"):
        if isinstance(meta.get(key), str) and meta[key]:
            return meta[key]
    return None


async def _names(
    conn: AsyncConnection, workspace_id: UUID, entries: list[dict[str, Any]]
) -> dict[str, str]:
    """Each resource's current display name, one query per kind present."""
    wanted: dict[str, set[str]] = {}
    for entry in entries:
        table = _TABLES.get(str(entry["resource_type"]))
        if table and entry["resource_id"]:
            wanted.setdefault(table, set()).add(str(entry["resource_id"]))
    out: dict[str, str] = {}
    for table, ids in wanted.items():
        rows = await fetch_all(
            conn,
            f"SELECT id, display_name FROM {table}"
            " WHERE workspace_id = :wid AND id = ANY(CAST(:ids AS uuid[]))",
            {"wid": str(workspace_id), "ids": "{" + ",".join(sorted(ids)) + "}"},
        )
        out.update({str(r["id"]): str(r["display_name"]) for r in rows})
    return out
