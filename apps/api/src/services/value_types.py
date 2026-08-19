"""Value types (Foundry ``object-link-types`` p.222-234).

> "Value types are semantic wrappers around a field type that include metadata
> and constraints that can enhance type safety, improve expressiveness, and
> provide additional context." (p.222)

**The sibling of ``shared_properties``, and the difference is the point.** A
shared property shares *metadata* - what a property is called and how it is
shown. A value type shares a *constraint* - what a value is allowed to be. They
attach independently and compose; p.227 names both places a value type can go
("Assigning a value type to an object type property", "Assigning a value type
to a shared property").

Half of a value type is immutable, and that shapes everything here
-----------------------------------------------------------------
> "The metadata values for name, description, and apiName can be changed
> whenever necessary. The base type metadata and the constraints that define
> the validation rules for the type are immutable. If you choose to update the
> constraints of a value type, a new version of the value type is created."
> (p.229)

So editing the metadata is an `UPDATE`, and editing the constraint is an
`INSERT` of a new version. `current_version` always means the highest-numbered
one, per p.230's "automatically propagate … all uses of the value type across
the Ontology are updated to the latest version" - a property references the
value type, never a version, so there is exactly one answer to "what is being
enforced" at any moment.

Where a constraint is *enforced* is not here
--------------------------------------------
This module stores and versions; ``value_constraints`` evaluates. p.227 puts
enforcement at indexing time - "If you apply a value type to an object property
that contains property values that fail validation, that object type will fail
to index" - and this platform makes the same split §154 made for required
properties (p.116): **the sync reports, the action refuses.** Refusing to index
would take an object type off every screen because one row is wrong, which is a
worse outcome than a report saying which row.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from . import value_constraints

_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class ValueTypeError(ValueError):
    """A value type that cannot be saved, or an attachment that cannot hold."""


def _out(row: Any) -> dict[str, Any]:
    out = dict(row)
    raw = out.get("constraint_json")
    out["constraint"] = json.loads(raw) if isinstance(raw, str) else raw
    out.pop("constraint_json", None)
    out["constraint_summary"] = value_constraints.describe(out["constraint"])
    for key in ("version_number", "usage_count"):
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    return out


_SELECT = """
    SELECT vt.id, vt.api_name, vt.display_name, vt.description,
           vt.example_value, vt.created_at, vt.updated_at,
           v.version_number, v.base_type, v.constraint_json,
           (SELECT count(*) FROM object_type_properties p
             WHERE p.value_type_id = vt.id)
         + (SELECT count(*) FROM shared_properties sp
             WHERE sp.value_type_id = vt.id) AS usage_count
      FROM value_types vt
      -- The current version is the highest-numbered one (p.230). A LATERAL
      -- join rather than a pointer column on `value_types`: a pointer would be
      -- a second place for "which version applies" to live, and a chance for
      -- the two to disagree after an interrupted write.
      JOIN LATERAL (
          SELECT version_number, base_type, constraint_json
            FROM value_type_versions
           WHERE value_type_id = vt.id
           ORDER BY version_number DESC
           LIMIT 1
      ) v ON true
"""


async def list_types(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn, _SELECT + " WHERE vt.workspace_id = :wid ORDER BY vt.api_name",
        {"wid": str(workspace_id)},
    )
    return [_out(r) for r in rows]


async def get_type(
    conn: AsyncConnection, workspace_id: UUID, value_type_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn, _SELECT + " WHERE vt.id = :vid AND vt.workspace_id = :wid",
        {"vid": str(value_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("value type")
    return _out(row)


async def by_id(
    conn: AsyncConnection, workspace_id: UUID, ids: set[UUID]
) -> dict[str, dict[str, Any]]:
    """The named value types with their current versions, keyed by string id.

    One query for a whole object type's worth of properties, for
    `shared_properties.by_id`'s reason: the caller needs them all before it can
    validate any of them.
    """
    if not ids:
        return {}
    rows = await fetch_all(
        conn,
        _SELECT + " WHERE vt.workspace_id = :wid AND vt.id = ANY(CAST(:ids AS uuid[]))",
        {"wid": str(workspace_id), "ids": "{" + ",".join(str(i) for i in ids) + "}"},
    )
    return {str(r["id"]): _out(r) for r in rows}


async def list_versions(
    conn: AsyncConnection, workspace_id: UUID, value_type_id: UUID
) -> list[dict[str, Any]]:
    """Every version, newest first. p.229 makes the constraint immutable and a
    change an append, so this is the record of what was being enforced when -
    the question somebody asks after finding data that was rejected."""
    await get_type(conn, workspace_id, value_type_id)
    rows = await fetch_all(
        conn,
        """
        SELECT id, version_number, base_type, constraint_json, created_at
          FROM value_type_versions
         WHERE value_type_id = :vid
         ORDER BY version_number DESC
        """,
        {"vid": str(value_type_id)},
    )
    return [_out(r) for r in rows]


async def create(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    example_value: str,
    base_type: str,
    constraint_raw: Any,
    created_by: UUID,
) -> dict[str, Any]:
    from . import ontology

    if not _API_RE.match(api_name):
        raise ValueTypeError(f"invalid value type api_name {api_name!r}")
    if base_type not in ontology.PROPERTY_TYPES:
        raise ValueTypeError(f"invalid base type {base_type!r}")
    parsed = value_constraints.parse(constraint_raw, base_type=base_type)

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM value_types WHERE workspace_id=:wid AND api_name=:api",
        {"wid": str(workspace_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"a value type named {api_name!r} already exists")

    row = await fetch_one(
        conn,
        """
        INSERT INTO value_types (workspace_id, api_name, display_name,
                                 description, example_value, created_by)
        VALUES (:wid, :api, :name, :descr, :example, :by)
        RETURNING id
        """,
        {
            "wid": str(workspace_id), "api": api_name, "name": display_name,
            "descr": description, "example": example_value, "by": str(created_by),
        },
    )
    assert row is not None
    await _append_version(
        conn, UUID(str(row["id"])), base_type=base_type,
        constraint=parsed, created_by=created_by,
    )
    return await get_type(conn, workspace_id, UUID(str(row["id"])))


async def update_metadata(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    value_type_id: UUID,
    display_name: str,
    description: str,
    example_value: str,
) -> dict[str, Any]:
    """p.229's mutable half: "name, description, and apiName can be changed
    whenever necessary".

    `api_name` is not a parameter here, unlike Foundry, for
    `object_types.api_name`'s reason (db 0003): it is the stable machine name a
    consumer holds, and renaming it would break them with no warning that could
    reach them. Recorded as a divergence in `docs/parity/ontology.md`.
    """
    await get_type(conn, workspace_id, value_type_id)
    await conn.execute(
        text(
            """
            UPDATE value_types
               SET display_name = :name, description = :descr,
                   example_value = :example
             WHERE id = :vid
            """
        ),
        {"name": display_name, "descr": description,
         "example": example_value, "vid": str(value_type_id)},
    )
    return await get_type(conn, workspace_id, value_type_id)


async def add_version(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    value_type_id: UUID,
    constraint_raw: Any,
    created_by: UUID,
) -> dict[str, Any]:
    """p.229's immutable half: changing the constraint appends a version.

    **The base type is not a parameter.** p.229 calls it immutable in the same
    breath as the constraints, and it is the stronger of the two claims: a
    value type whose base type changed would be attached to properties it can
    no longer describe, and every one of them would start failing at once. The
    new version inherits the base type of the current one.
    """
    current = await get_type(conn, workspace_id, value_type_id)
    parsed = value_constraints.parse(
        constraint_raw, base_type=str(current["base_type"])
    )
    if parsed == current["constraint"]:
        # An append that changes nothing would be a version somebody has to
        # read to discover it says the same thing.
        raise ValueTypeError(
            "that is the constraint this value type already has - a version "
            "records a change"
        )
    await _append_version(
        conn, value_type_id, base_type=str(current["base_type"]),
        constraint=parsed, created_by=created_by,
    )
    return await get_type(conn, workspace_id, value_type_id)


async def delete(
    conn: AsyncConnection, workspace_id: UUID, value_type_id: UUID
) -> None:
    """Deleting a value type unbinds the properties using it (db 0054's
    `ON DELETE SET NULL`), exactly as deleting a shared property does (p.185).

    Foundry recommends *deprecating* rather than deleting a value type with
    consumers (p.229). There is no status here yet - that is `ontology.md`
    §1.3's own ○ row - so this deletes and unbinds, and the audit record says
    how many properties stopped being constrained.
    """
    await get_type(conn, workspace_id, value_type_id)
    await conn.execute(
        text("DELETE FROM value_types WHERE id = :vid"), {"vid": str(value_type_id)}
    )


async def usage(
    conn: AsyncConnection, workspace_id: UUID, value_type_id: UUID
) -> list[dict[str, Any]]:
    """Where it is used - both of p.227's places, in one list, each row saying
    which kind it is so "email on Customer" and "the email shared property" are
    tellable apart."""
    await get_type(conn, workspace_id, value_type_id)
    rows = await fetch_all(
        conn,
        """
        SELECT 'object_type_property' AS kind,
               ot.display_name AS owner_name, p.api_name AS property_api_name,
               ot.id AS object_type_id
          FROM object_type_properties p
          JOIN object_types ot ON ot.id = p.object_type_id
         WHERE p.value_type_id = :vid AND ot.workspace_id = :wid
        UNION ALL
        SELECT 'shared_property', '', sp.api_name, NULL
          FROM shared_properties sp
         WHERE sp.value_type_id = :vid AND sp.workspace_id = :wid
        ORDER BY 1, 2, 3
        """,
        {"vid": str(value_type_id), "wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


def check_attachment(prop: dict[str, Any], value_type: dict[str, Any]) -> None:
    """Refuse a value type on a property of a different base type.

    p.222's whole proposition is that the value type *is* the type, with
    meaning attached; attaching an `email` (string) value type to an integer
    property would be a constraint that rejects every row - the failure p.227
    describes as an object type that "will fail to index", arriving on a screen
    rather than on a save.
    """
    if str(prop["data_type"]) != str(value_type["base_type"]):
        raise ValueTypeError(
            f"{prop['api_name']}: value type {value_type['api_name']!r} is a "
            f"{value_type['base_type']}, and this property is "
            f"{prop['data_type']}"
        )


async def _append_version(
    conn: AsyncConnection,
    value_type_id: UUID,
    *,
    base_type: str,
    constraint: dict[str, Any] | None,
    created_by: UUID,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO value_type_versions (value_type_id, version_number,
                                             base_type, constraint_json,
                                             created_by)
            SELECT :vid,
                   COALESCE((SELECT max(version_number) + 1
                               FROM value_type_versions
                              WHERE value_type_id = :vid), 1),
                   CAST(:btype AS property_data_type),
                   CAST(:constraint AS jsonb), :by
            """
        ),
        {
            "vid": str(value_type_id),
            "btype": base_type,
            "constraint": json.dumps(constraint) if constraint is not None else None,
            "by": str(created_by),
        },
    )
