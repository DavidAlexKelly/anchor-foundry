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
from . import ontology_status, value_constraints

_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class ValueTypeError(ValueError):
    """A value type that cannot be saved, or an attachment that cannot hold."""


def _out(row: Any, names: dict[str, str] | None = None) -> dict[str, Any]:
    out = dict(row)
    raw = out.get("constraint_json")
    out["constraint"] = json.loads(raw) if isinstance(raw, str) else raw
    out.pop("constraint_json", None)
    out["constraint_summary"] = value_constraints.describe(out["constraint"], names)
    for key in ("version_number", "usage_count"):
        if key in out and out[key] is not None:
            out[key] = int(out[key])
    return out


_SELECT = """
    SELECT vt.id, vt.api_name, vt.display_name, vt.description,
           vt.example_value, vt.status, vt.deprecation,
           vt.created_at, vt.updated_at,
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
    names = {str(r["id"]): str(r["api_name"]) for r in rows}
    return [_out(r, names) for r in rows]


async def _names(conn: AsyncConnection, workspace_id: UUID) -> dict[str, str]:
    """Every value type's api_name by id, for describing a reference (§681)."""
    rows = await fetch_all(
        conn, "SELECT id, api_name FROM value_types WHERE workspace_id = :wid",
        {"wid": str(workspace_id)},
    )
    return {str(r["id"]): str(r["api_name"]) for r in rows}


async def current_rules(
    conn: AsyncConnection, ids: set[str]
) -> dict[str, dict[str, Any]]:
    """`{id: {"base_type", "constraint"}}` for each value type as it is now
    (p.230), which is what a nested or elements reference applies (§681).

    Not filtered by workspace: row-level security already limits it to the
    value types this reader may see, and every reference was checked against
    its own workspace when it was saved."""
    if not ids:
        return {}
    rows = await fetch_all(
        conn,
        _SELECT + " WHERE vt.id = ANY(CAST(:ids AS uuid[]))",
        {"ids": "{" + ",".join(sorted(ids)) + "}"},
    )
    return {
        str(r["id"]): {"base_type": str(r["base_type"]), "constraint": _out(r)["constraint"]}
        for r in rows
    }


async def resolve_constraints(
    conn: AsyncConnection, constraints: list[dict[str, Any] | None]
) -> list[dict[str, Any] | None]:
    """Each constraint with its references' current rules beside it, in one
    query for all of them (`value_constraints.resolve`)."""
    ids = {ref for c in constraints for ref in value_constraints.references(c)}
    found = await current_rules(conn, ids)
    return [value_constraints.resolve(c, found) for c in constraints]


async def get_type(
    conn: AsyncConnection, workspace_id: UUID, value_type_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn, _SELECT + " WHERE vt.id = :vid AND vt.workspace_id = :wid",
        {"vid": str(value_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("value type")
    return _out(row, await _names(conn, workspace_id))


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
    out = {str(r["id"]): _out(r) for r in rows}
    # What a nested or elements constraint names, for `check_attachment`.
    resolved = await resolve_constraints(conn, [t["constraint"] for t in out.values()])
    for held, constraint in zip(out.values(), resolved):
        held["resolved_constraint"] = constraint
    return out


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
    names = await _names(conn, workspace_id)
    return [_out(r, names) for r in rows]


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
    await _check_references(conn, workspace_id, parsed, already=set())

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


#: An argument left out, told apart from one sent as null: a deprecation note
#: left out is kept, and one sent as null is cleared.
KEEP: Any = object()


async def update_metadata(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    value_type_id: UUID,
    display_name: str,
    description: str,
    example_value: str,
    status: str | None = None,
    deprecation: Any = KEEP,
) -> dict[str, Any]:
    """p.229's mutable half: "name, description, and apiName can be changed
    whenever necessary". And the status (§764), which is not part of a version
    either: p.229 recommends *deprecating* a value type, which is a statement
    about the value type rather than a new rule.

    `api_name` is not a parameter here, unlike Foundry, for
    `object_types.api_name`'s reason (db 0003): it is the stable machine name a
    consumer holds, and renaming it would break them with no warning that could
    reach them. Recorded as a divergence in `docs/parity/ontology.md`.

    **Omitted means unchanged**, for both: a client written before §764 does
    not reset a status, or drop a note, by saving a description. A note left
    out while the value type stays deprecated is kept; moving away from
    deprecated drops it, as `parse_deprecation` does everywhere (p.254).
    """
    current = await get_type(conn, workspace_id, value_type_id)
    next_status = ontology_status.check_status(
        str(status or current["status"]), kind="value_type"
    )
    if deprecation is KEEP:
        deprecation = current["deprecation"] if next_status == "deprecated" else None
    note = ontology_status.parse_deprecation(deprecation, next_status)
    await _check_replacement(conn, workspace_id, value_type_id, note)
    await conn.execute(
        text(
            """
            UPDATE value_types
               SET display_name = :name, description = :descr,
                   example_value = :example,
                   status = CAST(:status AS ontology_status),
                   deprecation = CAST(:depr AS jsonb)
             WHERE id = :vid
            """
        ),
        {"name": display_name, "descr": description,
         "example": example_value, "vid": str(value_type_id),
         "status": next_status,
         "depr": json.dumps(note) if note is not None else None},
    )
    return await get_type(conn, workspace_id, value_type_id)


async def _check_replacement(
    conn: AsyncConnection,
    workspace_id: UUID,
    value_type_id: UUID,
    note: dict[str, Any] | None,
) -> None:
    """p.254's "the resource that is meant to replace the one that is
    deprecated", which for a value type is p.229's "creating a new one": it
    has to be another value type of this workspace, or the note points
    somebody at nothing."""
    replacement = (note or {}).get("replacement_id")
    if replacement is None:
        return
    if replacement == str(value_type_id):
        raise ValueTypeError("a value type cannot be its own replacement")
    try:
        wanted = UUID(replacement)
    except ValueError as exc:
        raise ValueTypeError(f"no value type {replacement} in this workspace") from exc
    if not await by_id(conn, workspace_id, {wanted}):
        raise ValueTypeError(f"no value type {replacement} in this workspace")


def check_not_deprecated(
    owner: str, value_type: dict[str, Any], *, already: bool
) -> None:
    """A deprecated value type takes no new attachments (§764).

    p.229 deprecates a value type so that its consumers move to a new one, and
    p.254 calls deprecated "should not be relied on". **What already uses it
    keeps it**: unbinding would be deleting the rule out from under data that
    was valid a moment ago, and p.256 leaves a deprecated resource in place
    until it is deleted. So only the *new* use is refused, and the sentence
    names the replacement when the note has one.
    """
    if already or str(value_type.get("status")) != "deprecated":
        return
    replacement = (value_type.get("deprecation") or {}).get("replacement_id")
    raise ValueTypeError(
        f"{owner}: value type {value_type['api_name']!r} is deprecated and takes "
        "no new properties (p.229)"
        + (f" - use its replacement {replacement}" if replacement else "")
    )


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
    await _check_references(
        conn, workspace_id, parsed,
        already=set(value_constraints.references(current["constraint"])),
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
    consumers (p.229), and §764 gave it the status to do that with: like any
    ontology resource, it must be experimental or deprecated to be deleted
    (p.256). What is deleted still unbinds, and the audit record says how many
    properties stopped being constrained.
    """
    current = await get_type(conn, workspace_id, value_type_id)
    # p.256, as for every ontology resource (§764): an active value type is
    # one applications rely on.
    ontology_status.check_deletable(
        str(current["status"]), kind="value_type", name=str(current["api_name"])
    )
    # A value type another one names (§681) is refused rather than unbound:
    # unbinding a property is visible on its row, and a reference inside
    # somebody else's constraint that silently stopped checking is not.
    referrers = [
        t["api_name"] for t in await list_types(conn, workspace_id)
        if str(value_type_id) in value_constraints.references(t["constraint"])
    ]
    if referrers:
        raise ConflictError(
            f"{', '.join(referrers)} applies this value type to its items or "
            f"fields; change {'that' if len(referrers) == 1 else 'those'} first"
        )
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
    # §681: what a nested or elements constraint applies has to fit what the
    # property holds, for the same reason one level down.
    resolved = value_type.get("resolved_constraint") or {}
    items = resolved.get("items") if resolved.get("kind") == "nested" else None
    if items is not None and str(prop.get("array_of")) != items["base_type"]:
        raise ValueTypeError(
            f"{prop['api_name']}: value type {value_type['api_name']!r} applies a "
            f"{items['base_type']} value type to each item, and this array holds "
            f"{prop.get('array_of')}"
        )
    if resolved.get("kind") == "elements":
        fields = {str(f.get("api_name")): str(f.get("data_type"))
                  for f in (prop.get("struct_fields") or [])}
        for field, held in sorted((resolved.get("resolved") or {}).items()):
            if fields.get(field) != held["base_type"]:
                raise ValueTypeError(
                    f"{prop['api_name']}: value type {value_type['api_name']!r} applies a "
                    f"{held['base_type']} value type to the field {field!r}, and "
                    + (f"this struct's {field!r} is {fields[field]}" if field in fields
                       else "this struct has no such field")
                )


async def check_for_shared(
    conn: AsyncConnection,
    workspace_id: UUID,
    *,
    api_name: str,
    data_type: str,
    value_type_id: UUID | None,
    already: str | None,
) -> None:
    """p.227's other attachment point, a shared property (§764).

    This workspace's, of the shared property's base type, and not deprecated
    unless the shared property already had it - the three refusals a
    property's own choice gets in `ontology._apply_value_types`."""
    if value_type_id is None:
        return
    found = (await by_id(conn, workspace_id, {value_type_id})).get(str(value_type_id))
    if found is None:
        raise ValueTypeError(f"{api_name}: no value type {value_type_id} in this workspace")
    if str(found["base_type"]) != data_type:
        raise ValueTypeError(
            f"{api_name}: value type {found['api_name']!r} is a "
            f"{found['base_type']}, and this shared property is {data_type}"
        )
    check_not_deprecated(api_name, found, already=already == str(value_type_id))


async def _check_references(
    conn: AsyncConnection,
    workspace_id: UUID,
    constraint: dict[str, Any] | None,
    *,
    already: set[str],
) -> None:
    """Each value type a nested or elements constraint names (§681) must be
    one of this workspace's, and a scalar - which also rules out naming
    itself, since only an array or struct value type names anything.

    A deprecated one is not named anew (§764), and `already` is what the
    current version names: a new version keeps those, as a property keeps
    its own."""
    refs = value_constraints.references(constraint)
    if not refs:
        return
    known = await by_id(conn, workspace_id, {UUID(r) for r in refs})
    for ref in refs:
        held = known.get(ref)
        if held is None:
            raise ValueTypeError(f"no value type {ref} in this workspace")
        if str(held["base_type"]) not in value_constraints.REFERENCE_TYPES:
            raise ValueTypeError(
                f"{held['api_name']} is a {held['base_type']} value type; items and "
                f"fields take a {', '.join(value_constraints.REFERENCE_TYPES)} one"
            )
        check_not_deprecated("items and fields", held, already=ref in already)


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
