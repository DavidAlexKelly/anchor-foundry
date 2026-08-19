"""Shared properties (Foundry ``object-link-types`` p.178-191).

> "A shared property is a property that can be used on multiple object types in
> your ontology… While property metadata is shared across objects, the
> underlying object data is not." (p.178)

**One definition, several object types, and no data of its own.** p.178's
example is `start date` on both `Employee` and `Contractor`, so that the
metadata can be updated "in one place instead of on each object type". This
module owns that definition and the rules for attaching a property to it;
`services/ontology` owns the object type that does the attaching.

The three rules worth stating up front, because each is a refusal
--------------------------------------------------------------

* **The base types must match.** p.181: "Base types are related to the
  underlying column type and must match the column type in order to be applied
  on an object type." A `date` shared property on a `string` column is a
  formatter that never fires and a widget that never appears, discovered on a
  screen rather than on a save.

* **Inherited metadata cannot be edited locally.** p.188: "While associated
  with a shared property, direct edits to property metadata that is inherited
  from the shared property will be disabled." Disabled in a form is a refusal
  on the wire - otherwise the one client that does not draw the form gets to
  desynchronise every other object type's idea of what the property is.

* **The property keeps its own id and api_name.** p.188 again: they "will
  remain unchanged so as to not break existing downstream workflows that
  leverage them". So `INHERITED` deliberately does not contain `api_name`, and
  attaching never renames anything.

What is *not* inherited, and why
--------------------------------
`required`, `edit_only`, `conditional_format` and `derivation` stay local.
p.181, p.184 and p.190 give the same list of shared metadata three times and
none of them appears on it - which reads right rather than merely literal.
`required` is a statement about one object type's data quality (p.116);
`edit_only` is about one object type's backing datasets (p.113); `derivation`
is about one object type's links (p.143); and a conditional format may compare
against *another property of the same object type* (p.105), so it cannot be
defined anywhere but on the type that has both.

Two divergences, named rather than hidden
-----------------------------------------
* Foundry lists **type classes** and **render hints** among shared metadata.
  Neither exists in this platform - there is no application here reading a type
  class, and reindex tuning is not a thing this instance store exposes - so
  they are absent rather than stubbed. `docs/parity/ontology.md` says so.
* **A shared property in use cannot change its base type.** Foundry's edit page
  lists base type as editable and does not say what happens to the object types
  using it. Cascading would retype every attached property silently, which is
  the precise change `ontology.type_impact` exists to make somebody
  acknowledge; so this refuses instead and names the object types in the way.
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
from . import value_format

_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")

#: The fields an attached property takes from its shared property (p.181,
#: p.184 and p.190 - the same list each time). Not `api_name`: p.188 keeps that
#: local so downstream consumers holding it keep working.
INHERITED = ("display_name", "description", "visibility", "value_format")


class SharedPropertyError(ValueError):
    """A shared property, or an attachment to one, that cannot be saved."""


async def list_shared(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    """Every shared property in the workspace, with p.191's Usage count.

    The count is here rather than in a second endpoint because it is the one
    fact that changes what somebody does next: a shared property used by four
    object types is not a thing to delete on a hunch.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT sp.id, sp.api_name, sp.display_name, sp.description,
               sp.data_type, sp.visibility, sp.value_format,
               sp.value_type_id,
               sp.created_at, sp.updated_at,
               (SELECT count(*) FROM object_type_properties p
                 WHERE p.shared_property_id = sp.id) AS usage_count
          FROM shared_properties sp
         WHERE sp.workspace_id = :wid
         ORDER BY sp.api_name
        """,
        {"wid": str(workspace_id)},
    )
    return [_out(r) for r in rows]


async def get_shared(
    conn: AsyncConnection, workspace_id: UUID, shared_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT sp.id, sp.api_name, sp.display_name, sp.description,
               sp.data_type, sp.visibility, sp.value_format,
               sp.value_type_id,
               sp.created_at, sp.updated_at,
               (SELECT count(*) FROM object_type_properties p
                 WHERE p.shared_property_id = sp.id) AS usage_count
          FROM shared_properties sp
         WHERE sp.id = :sid AND sp.workspace_id = :wid
        """,
        {"sid": str(shared_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("shared property")
    return _out(row)


async def usage(
    conn: AsyncConnection, workspace_id: UUID, shared_id: UUID
) -> list[dict[str, Any]]:
    """p.191's Usage: "The object types on which a shared property is used."

    Returns the object type *and* the property's own api_name, because p.188
    lets those differ - `start_date` on Employee and `began_on` on Contractor
    can be the same shared property, and a usage list that hid that would be
    answering a different question.
    """
    await get_shared(conn, workspace_id, shared_id)
    rows = await fetch_all(
        conn,
        """
        SELECT ot.id AS object_type_id, ot.api_name AS object_type_api_name,
               ot.display_name AS object_type_display_name,
               p.api_name AS property_api_name
          FROM object_type_properties p
          JOIN object_types ot ON ot.id = p.object_type_id
         WHERE p.shared_property_id = :sid AND ot.workspace_id = :wid
         ORDER BY ot.api_name, p.api_name
        """,
        {"sid": str(shared_id), "wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def create_shared(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    data_type: str,
    visibility: str,
    value_format_raw: Any,
    value_type_id: UUID | None,
    created_by: UUID,
) -> dict[str, Any]:
    _check_definition(
        api_name=api_name, data_type=data_type, visibility=visibility
    )
    fmt = value_format.parse(
        value_format_raw, data_type=data_type, property_name=api_name
    )
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM shared_properties WHERE workspace_id=:wid AND api_name=:api",
        {"wid": str(workspace_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"a shared property named {api_name!r} already exists")
    row = await fetch_one(
        conn,
        """
        INSERT INTO shared_properties (workspace_id, api_name, display_name,
                                       description, data_type, visibility,
                                       value_format, value_type_id, created_by)
        VALUES (:wid, :api, :name, :descr, CAST(:dtype AS property_data_type),
                CAST(:vis AS property_visibility), CAST(:vfmt AS jsonb),
                :valuetype, :by)
        RETURNING id, api_name, display_name, description, data_type,
                  visibility, value_format, value_type_id,
                  created_at, updated_at
        """,
        {
            "wid": str(workspace_id),
            "api": api_name,
            "name": display_name,
            "descr": description,
            "dtype": data_type,
            "vis": visibility,
            "vfmt": json.dumps(fmt) if fmt is not None else None,
            # p.227's other attachment point: a value type may sit on the
            # shared property, so every property using it inherits the
            # constraint without choosing one itself.
            "valuetype": str(value_type_id) if value_type_id else None,
            "by": str(created_by),
        },
    )
    assert row is not None
    return _out({**dict(row), "usage_count": 0})


async def update_shared(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    shared_id: UUID,
    display_name: str,
    description: str,
    data_type: str,
    visibility: str,
    value_format_raw: Any,
    value_type_id: UUID | None,
) -> dict[str, Any]:
    """Edit the definition. Every object type using it sees the change on its
    next read, which is p.178's "update … in one place".

    `api_name` is not a parameter, for `object_types.api_name`'s reason (0003):
    it is the stable machine name a consumer holds, and renaming it here would
    break them with no warning that could reach them.
    """
    current = await get_shared(conn, workspace_id, shared_id)
    _check_definition(
        api_name=str(current["api_name"]),
        data_type=data_type,
        visibility=visibility,
    )
    if data_type != current["data_type"]:
        users = await usage(conn, workspace_id, shared_id)
        if users:
            raise SharedPropertyError(
                f"{current['api_name']}: cannot change base type from "
                f"{current['data_type']} to {data_type} while "
                + ", ".join(sorted({str(u["object_type_api_name"]) for u in users}))
                + " use it - detach them first"
            )
    fmt = value_format.parse(
        value_format_raw,
        data_type=data_type,
        property_name=str(current["api_name"]),
    )
    await conn.execute(
        text(
            """
            UPDATE shared_properties
               SET display_name = :name, description = :descr,
                   data_type = CAST(:dtype AS property_data_type),
                   visibility = CAST(:vis AS property_visibility),
                   value_format = CAST(:vfmt AS jsonb),
                   value_type_id = :valuetype
             WHERE id = :sid
            """
        ),
        {
            "name": display_name,
            "descr": description,
            "dtype": data_type,
            "vis": visibility,
            "vfmt": json.dumps(fmt) if fmt is not None else None,
            "valuetype": str(value_type_id) if value_type_id else None,
            "sid": str(shared_id),
        },
    )
    return await get_shared(conn, workspace_id, shared_id)


async def delete_shared(
    conn: AsyncConnection, workspace_id: UUID, shared_id: UUID
) -> None:
    """p.185: "When a shared property is deleted, all object types using this
    shared property will revert to regular properties."

    **Not refused when in use**, which is the opposite of how most deletes in
    this codebase behave, and deliberately: p.185 documents the revert as the
    normal outcome. The properties keep their last inherited metadata because
    the columns were written at save time - see db 0053 - so what reverts is
    the *link*, not the configuration somebody had.
    """
    await get_shared(conn, workspace_id, shared_id)
    await conn.execute(
        text("DELETE FROM shared_properties WHERE id = :sid"),
        {"sid": str(shared_id)},
    )


# ---- attaching a property to one (p.187-188) --------------------------------
def resolve(
    prop: dict[str, Any], shared: dict[str, Any] | None
) -> dict[str, Any]:
    """Overlay a shared property's metadata onto an attached property.

    Called on the way *out* so that editing a shared property shows through
    everywhere immediately (p.178), and on the way *in* so that what gets
    stored is what was resolved. Both directions, one function, because two
    would be two chances to inherit a different set of fields.

    A property with no shared property comes back untouched, so this is safe to
    call over a whole type's list without asking first.
    """
    if shared is None:
        return prop
    merged = dict(prop)
    for field in INHERITED:
        merged[field] = shared[field]
    # Not inherited, but guaranteed equal by `check_attachment` - copied so a
    # row written before the shared property's type was corrected cannot claim
    # a type its own formatter disagrees with.
    merged["data_type"] = shared["data_type"]
    return merged


def check_base_type(prop: dict[str, Any], shared: dict[str, Any]) -> None:
    """p.181: "Base types … must match the column type in order to be applied
    on an object type."

    Separate from `check_attachment` because it applies at *both* moments a
    property meets a shared property - the attach and every later save - while
    the inherited-metadata refusal only applies to the later ones.
    """
    if str(prop["data_type"]) != str(shared["data_type"]):
        raise SharedPropertyError(
            f"{prop['api_name']}: shared property {shared['api_name']!r} has "
            f"base type {shared['data_type']}, and this property is "
            f"{prop['data_type']} - p.181 requires them to match"
        )


def check_attachment(prop: dict[str, Any], shared: dict[str, Any]) -> None:
    """Refuse an edit to an *already attached* property (p.181, p.188).

    The refusal that matters is the second one: a client may not submit
    inherited metadata that disagrees with the shared property. p.188 says
    those fields are "disabled" while attached; on the wire that has to be a
    refusal, because a value silently discarded is a person's edit
    disappearing with no error to explain it.

    A payload carrying the *resolved* values is accepted unchanged - which is
    what the object type editor sends back after a read, and what keeps this
    from being an API that cannot accept its own output.
    """
    api = str(prop["api_name"])
    check_base_type(prop, shared)
    for field in INHERITED:
        if field not in prop:
            continue
        submitted = prop[field]
        if field == "description" and not submitted:
            # A blank description is what a client that never had one sends,
            # and it is indistinguishable from "leave it alone". Every other
            # inherited field has a value that cannot be confused with absence.
            continue
        if submitted != shared[field]:
            raise SharedPropertyError(
                f"{api}: {field} is inherited from shared property "
                f"{shared['api_name']!r} and cannot be set here - detach first"
            )


async def by_id(
    conn: AsyncConnection, workspace_id: UUID, ids: set[UUID]
) -> dict[str, dict[str, Any]]:
    """The named shared properties, keyed by string id.

    One query for a whole object type's worth of properties: a per-property
    lookup would be a query per row on every save of a type, and the caller
    needs them all before it can validate any of them anyway.
    """
    if not ids:
        return {}
    rows = await fetch_all(
        conn,
        """
        SELECT id, api_name, display_name, description, data_type,
               visibility, value_format, value_type_id
          FROM shared_properties
         WHERE workspace_id = :wid AND id = ANY(CAST(:ids AS uuid[]))
        """,
        {"wid": str(workspace_id), "ids": "{" + ",".join(str(i) for i in ids) + "}"},
    )
    return {str(r["id"]): _out(r) for r in rows}


def _check_definition(*, api_name: str, data_type: str, visibility: str) -> None:
    # Imported here rather than at module scope: `ontology` imports this module
    # for `resolve`, and the two lists are its to own.
    from . import ontology

    if not _API_RE.match(api_name):
        raise SharedPropertyError(f"invalid shared property api_name {api_name!r}")
    if data_type not in ontology.PROPERTY_TYPES:
        raise SharedPropertyError(f"invalid property type {data_type!r}")
    if visibility not in ontology.PROPERTY_VISIBILITIES:
        raise SharedPropertyError(
            f"invalid visibility {visibility!r}; expected one of "
            + ", ".join(ontology.PROPERTY_VISIBILITIES)
        )


def _out(row: Any) -> dict[str, Any]:
    out = dict(row)
    fmt = out.get("value_format")
    out["value_format"] = json.loads(fmt) if isinstance(fmt, str) else fmt
    if "usage_count" in out:
        out["usage_count"] = int(out["usage_count"])
    return out
