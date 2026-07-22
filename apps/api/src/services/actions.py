"""Actions — write-back (spec: "Canvas buttons/forms writing back to object
instances → source datasets").

Scope, flagged for review: write-back targets this platform's own Parquet
copy of the mapped dataset (the same dataset the object type source points
at), not the customer's original external system reached through a
connection. Connectors in this build only support test/discover, not
write — true write-through to a live external table needs its own connector
capability and is out of scope here. Every write-back still creates a new
dataset_versions row (produced_by_kind='action'), exactly like
uploads/syncs/model runs — nothing is silently overwritten.

An action_type names a subset of an object type's properties as writable
("editable_properties"), validated against that type's real properties the
same way object_type_sources.column_mappings is validated against a
dataset's schema. Executing one (routes/actions.py orchestrates; this
module holds the DB-only primitives) requires the instance's mapped
property to also appear in its source's column_mappings — only properties
with a known dataset column can be written back.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_API_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


def _validate_value(data_type: str, value: Any) -> None:
    if value is None:
        return
    if data_type == "integer" and not isinstance(value, int):
        raise ValueError(f"expected an integer, got {value!r}")
    if data_type == "float" and not isinstance(value, (int, float)):
        raise ValueError(f"expected a number, got {value!r}")
    if data_type == "boolean" and not isinstance(value, bool):
        raise ValueError(f"expected a boolean, got {value!r}")
    if data_type == "string" and not isinstance(value, str):
        raise ValueError(f"expected a string, got {value!r}")


def validate_submitted_values(
    values: dict[str, Any],
    *,
    editable_properties: list[str],
    property_types: dict[str, str],
    mapped_properties: set[str],
) -> None:
    """A submitted value is only writable if it's (a) on the action type's
    editable list, (b) type-consistent with the property's declared type,
    and (c) actually mapped to a dataset column on this instance's source —
    properties the source never populated have no write-back target."""
    if not values:
        raise ValueError("submit at least one value to write")
    editable = set(editable_properties)
    for prop, value in values.items():
        if prop not in editable:
            raise ValueError(f"{prop!r} is not editable by this action")
        if prop not in mapped_properties:
            raise ValueError(
                f"{prop!r} has no dataset column mapped on this instance's source"
            )
        _validate_value(property_types.get(prop, "string"), value)


# ---- action types (workspace-scoped) ----------------------------------------
async def list_action_types(
    conn: AsyncConnection, workspace_id: UUID, *, object_type_id: UUID | None = None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"wid": str(workspace_id)}
    where = "at.workspace_id = :wid"
    if object_type_id is not None:
        where += " AND at.object_type_id = :tid"
        params["tid"] = str(object_type_id)
    rows = await fetch_all(
        conn,
        f"""
        SELECT at.id, at.object_type_id, ot.display_name AS object_type_name,
               at.api_name, at.display_name, at.description,
               at.editable_properties, at.created_at, at.updated_at
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE {where}
         ORDER BY at.display_name
        """,
        params,
    )
    return [dict(r) for r in rows]


async def get_action_type(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT at.id, at.object_type_id, ot.display_name AS object_type_name,
               at.api_name, at.display_name, at.description,
               at.editable_properties, at.created_at, at.updated_at
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE at.id = :aid AND at.workspace_id = :wid
        """,
        {"aid": str(action_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("action type")
    return dict(row)


async def create_action_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    object_type_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    editable_properties: list[str],
    created_by: UUID,
) -> dict[str, Any]:
    if not _API_NAME_RE.match(api_name):
        raise ValueError(f"invalid action api_name {api_name!r}")
    if not editable_properties:
        raise ValueError("an action must make at least one property editable")

    from . import ontology as ontology_service

    await ontology_service.get_type(conn, workspace_id, object_type_id)  # 404 if invisible
    known = {p["api_name"] for p in await ontology_service.list_properties(conn, object_type_id)}
    unknown = [p for p in editable_properties if p not in known]
    if unknown:
        raise ValueError(f"not properties of this object type: {', '.join(unknown)}")

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM action_types WHERE object_type_id=:tid AND api_name=:api",
        {"tid": str(object_type_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"an action named {api_name!r} already exists on this object type")

    import json

    row = await fetch_one(
        conn,
        """
        INSERT INTO action_types (workspace_id, object_type_id, api_name, display_name,
                                  description, editable_properties, created_by)
        VALUES (:wid, :tid, :api, :name, :descr, CAST(:props AS jsonb), :by)
        RETURNING id, object_type_id, api_name, display_name, description,
                  editable_properties, created_at, updated_at
        """,
        {
            "wid": str(workspace_id), "tid": str(object_type_id), "api": api_name,
            "name": display_name, "descr": description,
            "props": json.dumps(editable_properties), "by": str(created_by),
        },
    )
    assert row is not None
    object_type = await ontology_service.get_type(conn, workspace_id, object_type_id)
    return {**dict(row), "object_type_name": object_type["display_name"]}


async def delete_action_type(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM action_types WHERE id=:aid AND workspace_id=:wid RETURNING id",
        {"aid": str(action_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("action type")


# ---- action_runs bookkeeping --------------------------------------------------
async def open_run(
    conn: AsyncConnection,
    *,
    action_type_id: UUID,
    instance_id: UUID,
    dataset_id: UUID,
    requested_by: UUID,
    submitted_values: dict[str, Any],
) -> UUID:
    import json

    row = await fetch_one(
        conn,
        """
        INSERT INTO action_runs (action_type_id, instance_id, dataset_id,
                                 requested_by, submitted_values)
        VALUES (:atid, :iid, :did, :by, CAST(:vals AS jsonb))
        RETURNING id
        """,
        {
            "atid": str(action_type_id), "iid": str(instance_id), "did": str(dataset_id),
            "by": str(requested_by), "vals": json.dumps(submitted_values),
        },
    )
    assert row is not None
    return UUID(str(row["id"]))


async def close_run(
    conn: AsyncConnection,
    run_id: UUID,
    *,
    ok: bool,
    dataset_version: int | None,
    error: str | None,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE action_runs
               SET status = :status, dataset_version = :version,
                   error = :error, finished_at = now()
             WHERE id = :id
            """
        ),
        {
            "status": "succeeded" if ok else "failed",
            "version": dataset_version,
            "error": error,
            "id": str(run_id),
        },
    )


async def list_runs(conn: AsyncConnection, action_type_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT id, instance_id, dataset_id, dataset_version, submitted_values,
               status, error, started_at, finished_at
          FROM action_runs
         WHERE action_type_id = :atid
         ORDER BY started_at DESC
         LIMIT 50
        """,
        {"atid": str(action_type_id)},
    )
