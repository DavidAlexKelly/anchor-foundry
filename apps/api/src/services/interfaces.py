"""Interfaces: a shape several object types implement (Foundry
``object-link-types`` p.4, p.53; ``ontology`` p.60-62; db 0065).

> "An interface is an Ontology type that describes the shape of an object type
> and its capabilities. Interfaces provide object type polymorphism, allowing
> for consistent modeling of and interaction with object types that share a
> common shape." (`object-link-types` p.4)

**What an interface is *for*, in one example**, because the model reads as
bookkeeping without it. `ontology` p.61 puts three object types side by side -
Vehicle, Equipment, Facility - each with its own `lastInspectionDate` and
`inspectionStatus` and its own duplicate "Schedule inspection" action. The
interface version has one `Inspectable`, one shared action, and three
implementing types. p.62: "Target interfaces in workflows: build actions,
functions, and applications against interfaces where possible."

**Properties only.** p.60 says an interface shares properties, links *and*
actions. A link has two ends and an action has parameters and rules, so each
raises its own question about what "the implementing type must supply" means;
properties are the half p.61's worked example is entirely about, and the other
two are ○ on the row rather than half-built here.

**The rules that are worth reading twice**

*Extension is a graph, not a chain.* p.53: "interfaces may extend any number of
other interfaces." So the effective shape of an interface is its own properties
plus every ancestor's, and two ancestors can declare the same name - which is
either agreement (same base type, fine) or a contradiction that has to be
refused before anything tries to implement it.

*Implementation is a mapping, not a name match.* p.66 maps a shared property
type onto the implementing type's own, and p.60's argument requires it: three
types satisfy one interface **while differing in everything else**, and that
includes what they call things. A Vehicle whose column is `last_checked` is
still Inspectable.

*A base type must match.* The same rule p.181 applies to shared properties, one
resource over, and for the same reason: an interface that promised a date and
got a string would be a promise nothing enforced, which is worse than no
promise. Refused with both types named, because a refusal that says only "does
not match" makes somebody go and look.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from . import ontology_status

#: An interface is "an Ontology type" (p.4), so it is named like one - the same
#: rule `object_types.api_name` has, which is what makes `Inspectable` and
#: `SchedulableResource` (p.60) legal and reads alike in the one place the two
#: appear together: a type's implements list.
_INTERFACE_API_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")

#: A property of an interface is named like a property (0003).
_PROPERTY_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")

MAX_PROPERTIES = 100
MAX_EXTENDS = 10


class InterfaceError(ValueError):
    """An interface, extension or implementation that cannot be stored."""


# ---- the pure half ----------------------------------------------------------
def effective_properties(
    interface_id: str,
    *,
    own: dict[str, list[dict[str, Any]]],
    extends: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Every property an implementation of this interface must supply.

    Its own, plus every ancestor's, **depth-first through the extension graph
    in declaration order** - so a property inherited from the first-named
    parent comes before one from the second, and an interface's own properties
    come first. The order is not decoration: it is what the panel draws and the
    order a mapping is checked in, so leaving it to a set would make the same
    interface read differently on two screens.

    **A name declared twice is agreement or a contradiction, never a silent
    winner.** Two ancestors can both say `status`; if they agree on the base
    type there is one property and nothing to decide, and if they do not, no
    implementation could satisfy both - so it is refused here rather than at
    the moment somebody tries, which would be one screen too late.

    Pure: the caller does the reading, so the whole of p.53's "any number of
    other interfaces" is checkable without a database.
    """
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    _walk(interface_id, own=own, extends=extends, seen=seen, order=order, path=[])
    return [seen[name] for name in order]


def _walk(
    interface_id: str,
    *,
    own: dict[str, list[dict[str, Any]]],
    extends: dict[str, list[str]],
    seen: dict[str, dict[str, Any]],
    order: list[str],
    path: list[str],
) -> None:
    if interface_id in path:
        # p.53 allows any number of parents and says nothing about cycles,
        # because a cycle is not an abstraction - `A extends B extends A` has
        # no shape at all, and the walk that resolves it would not terminate.
        # Named in the order they were followed, which is what makes it fixable.
        raise InterfaceError(
            "interfaces cannot extend each other in a circle: "
            + " → ".join(path[path.index(interface_id):] + [interface_id])
        )
    for prop in own.get(interface_id, []):
        name = str(prop["api_name"])
        existing = seen.get(name)
        if existing is None:
            seen[name] = prop
            order.append(name)
        elif str(existing["data_type"]) != str(prop["data_type"]):
            raise InterfaceError(
                f"two interfaces in this hierarchy declare {name!r} with "
                f"different base types ({existing['data_type']} and "
                f"{prop['data_type']}) - no object type could implement both"
            )
    for parent in extends.get(interface_id, []):
        _walk(parent, own=own, extends=extends, seen=seen, order=order,
              path=[*path, interface_id])


def check_implementation(
    *,
    interface_name: str,
    required: list[dict[str, Any]],
    property_types: dict[str, str],
    mapping: dict[str, str],
) -> None:
    """Whether this object type can claim to implement this interface.

    `required` is the interface's effective properties, `property_types` is
    `{api_name: data_type}` for the object type, and `mapping` is
    `{interface property: the type's property}`.

    Three refusals, and each is a promise that would otherwise be unenforced:

    * a **required property with nothing mapped to it** - the interface says
      every implementation has one, and this one would not;
    * a mapping that names a property the object type **does not have**, which
      is the shape of a rename that happened somewhere else;
    * a mapping whose **base types differ**, which is p.181's rule about shared
      properties applied one resource over - a promise of a date answered with
      a string is a promise nothing enforced.

    An *optional* property left unmapped is fine and is the reason `required`
    exists: p.62's "design interfaces around capabilities" needs a capability
    with one mandatory field and two optional ones, which is an ordinary thing.
    """
    declared = {str(p["api_name"]): str(p["data_type"]) for p in required}
    unknown = sorted(set(mapping) - set(declared))
    if unknown:
        raise InterfaceError(
            f"{interface_name} does not declare " + ", ".join(unknown)
        )
    for prop in required:
        name = str(prop["api_name"])
        target = mapping.get(name)
        if not target:
            if prop.get("required", True):
                raise InterfaceError(
                    f"{interface_name} requires {name!r} ({prop['data_type']}) "
                    "and this object type maps nothing to it"
                )
            continue
        if target not in property_types:
            raise InterfaceError(
                f"{name!r} is mapped to {target!r}, which this object type "
                "does not have"
            )
        if property_types[target] != str(prop["data_type"]):
            raise InterfaceError(
                f"{interface_name} declares {name!r} as {prop['data_type']} "
                f"and {target!r} is {property_types[target]} - an interface's "
                "base types must match the properties implementing them"
            )


def parse_properties(raw: Any) -> list[dict[str, Any]]:
    """Normalise and check an interface's own property list.

    Normalised rather than passed through for `value_format.parse`'s reason:
    what is stored has to be what was checked, or the two are only accidentally
    the same.
    """
    from . import ontology as ontology_service

    if not isinstance(raw, list):
        raise InterfaceError("an interface's properties must be a list")
    if len(raw) > MAX_PROPERTIES:
        raise InterfaceError(
            f"an interface may declare at most {MAX_PROPERTIES} properties"
        )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise InterfaceError(f"property {index + 1} is not an object")
        api = str(item.get("api_name") or "")
        if not _PROPERTY_API_RE.match(api):
            raise InterfaceError(f"invalid interface property name {api!r}")
        if api in seen:
            raise InterfaceError(f"duplicate interface property {api!r}")
        seen.add(api)
        data_type = str(item.get("data_type") or "")
        if data_type not in ontology_service.PROPERTY_TYPES:
            raise InterfaceError(
                f"interface property {api!r} has type {data_type!r}; expected "
                "one of " + ", ".join(sorted(ontology_service.PROPERTY_TYPES))
            )
        out.append(
            {
                "api_name": api,
                "display_name": str(item.get("display_name") or api),
                "description": str(item.get("description") or ""),
                "data_type": data_type,
                # **Defaults to required**, which is the direction that cannot
                # silently weaken a promise: a client that has never heard of
                # this flag declares a property every implementation must have,
                # which is what p.61's worked example describes.
                "required": bool(item.get("required", True)),
            }
        )
    return out


# ---- reading ----------------------------------------------------------------
async def list_interfaces(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    """Every interface in the workspace, with the counts a listing needs.

    The two counts are one query each over the whole workspace rather than one
    per row - §169's N+1 is recent enough to still be the first thing to check
    when a listing wants a number.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT i.id, i.api_name, i.display_name, i.description, i.status,
               i.deprecation, i.created_at, i.updated_at,
               (SELECT count(*) FROM interface_properties p
                 WHERE p.interface_id = i.id) AS property_count,
               (SELECT count(*) FROM object_type_interfaces oti
                 WHERE oti.interface_id = i.id) AS implementation_count
          FROM interfaces i
         WHERE i.workspace_id = :wid
         ORDER BY i.display_name
        """,
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def _graph(
    conn: AsyncConnection, workspace_id: UUID
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """Every interface's own properties and parents, in two reads.

    The whole workspace rather than one interface's ancestors, because
    resolving *any* interface may walk *any* path through the graph and a
    per-node fetch would be the N+1 the listing above already avoids. A
    workspace's interfaces are a handful of rows by construction - they
    describe shapes, and there are not many shapes.
    """
    props = await fetch_all(
        conn,
        """
        SELECT p.interface_id, p.api_name, p.display_name, p.description,
               p.data_type, p.required, p.sort_order
          FROM interface_properties p
          JOIN interfaces i ON i.id = p.interface_id
         WHERE i.workspace_id = :wid
         ORDER BY p.sort_order, p.api_name
        """,
        {"wid": str(workspace_id)},
    )
    edges = await fetch_all(
        conn,
        """
        SELECT e.interface_id, e.extends_id
          FROM interface_extends e
          JOIN interfaces i ON i.id = e.interface_id
         WHERE i.workspace_id = :wid
        """,
        {"wid": str(workspace_id)},
    )
    own: dict[str, list[dict[str, Any]]] = {}
    for row in props:
        own.setdefault(str(row["interface_id"]), []).append(
            {k: row[k] for k in
             ("api_name", "display_name", "description", "data_type", "required")}
        )
    extends: dict[str, list[str]] = {}
    for row in edges:
        extends.setdefault(str(row["interface_id"]), []).append(str(row["extends_id"]))
    return own, extends


async def get_interface(
    conn: AsyncConnection, workspace_id: UUID, interface_id: UUID
) -> dict[str, Any]:
    """One interface, its own properties, its parents, and its **effective**
    shape - which is the one an implementation is checked against."""
    row = await fetch_one(
        conn,
        """
        SELECT id, api_name, display_name, description, status, deprecation,
               created_at, updated_at
          FROM interfaces WHERE id = :iid AND workspace_id = :wid
        """,
        {"iid": str(interface_id), "wid": str(workspace_id)},
    )
    if row is None:
        # **`NotFoundError`, which is what every other service here raises**
        # (`actions`, `canvas`), and what §9 asks for: an id that is not in this
        # workspace is 404 rather than 403, so the answer does not say whether
        # it exists somewhere else. §251 raised a bare `LookupError` and nothing
        # caught it, which made every read of a missing interface a 500 - found
        # by §254's first scope test, because that is the first test that ever
        # asked for one.
        raise NotFoundError("interface")
    own, extends = await _graph(conn, workspace_id)
    out = dict(row)
    out["properties"] = own.get(str(interface_id), [])
    out["extends"] = extends.get(str(interface_id), [])
    out["effective_properties"] = effective_properties(
        str(interface_id), own=own, extends=extends
    )
    return out


async def implementations_of(
    conn: AsyncConnection, workspace_id: UUID, interface_id: UUID
) -> list[dict[str, Any]]:
    """`[{object_type_id, api_name, display_name, property_mapping}]` for one
    interface - the other direction from `implementations_by_type`.

    Its own query rather than a filter over that one, because the two answer
    different questions at different scales: that one draws a column on a
    listing of every type, this one is the membership of an interface set
    (§254) and reads one interface's rows. Filtering the workspace-wide answer
    would read every implementation in the workspace to find a handful, which
    is §248's defect written on purpose.

    Ordered by the object type's name so a set's fan-out is the same shape on
    every read - the merge below it is stable, and a caller enumerating the
    members should see them in an order that does not move.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT oti.object_type_id, oti.property_mapping,
               ot.api_name, ot.display_name
          FROM object_type_interfaces oti
          JOIN object_types ot ON ot.id = oti.object_type_id
          JOIN interfaces i ON i.id = oti.interface_id
         WHERE oti.interface_id = :iid AND i.workspace_id = :wid
         ORDER BY ot.display_name, ot.id
        """,
        {"iid": str(interface_id), "wid": str(workspace_id)},
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        mapping = row["property_mapping"]
        out.append(
            {
                "object_type_id": str(row["object_type_id"]),
                "api_name": row["api_name"],
                "display_name": row["display_name"],
                "property_mapping": (
                    json.loads(mapping) if isinstance(mapping, str) else mapping
                ) or {},
            }
        )
    return out


async def implementations_by_type(
    conn: AsyncConnection, workspace_id: UUID
) -> dict[str, list[dict[str, Any]]]:
    """`{object type id: [{interface_id, api_name, display_name, mapping}]}`.

    One query for the whole workspace, for `list_interfaces`' reason: the
    object types listing draws this per row.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT oti.object_type_id, oti.interface_id, oti.property_mapping,
               i.api_name, i.display_name
          FROM object_type_interfaces oti
          JOIN interfaces i ON i.id = oti.interface_id
         WHERE i.workspace_id = :wid
         ORDER BY i.display_name
        """,
        {"wid": str(workspace_id)},
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        mapping = row["property_mapping"]
        out.setdefault(str(row["object_type_id"]), []).append(
            {
                "interface_id": str(row["interface_id"]),
                "api_name": row["api_name"],
                "display_name": row["display_name"],
                "property_mapping": (
                    json.loads(mapping) if isinstance(mapping, str) else mapping
                ) or {},
            }
        )
    return out


# ---- writing ----------------------------------------------------------------
async def create_interface(
    conn: AsyncConnection,
    workspace_id: UUID,
    *,
    api_name: str,
    display_name: str,
    description: str = "",
    properties: Any = None,
    extends: list[UUID] | None = None,
    status: str = ontology_status.DEFAULT_STATUS,
    deprecation: Any = None,
    created_by: UUID,
) -> dict[str, Any]:
    """Declare a shape (p.4).

    **An interface with no properties is allowed**, which is worth saying
    because the neighbouring type refuses the same thing: p.149 requires a
    struct to have at least one field, and nothing here says an interface must.
    The reason they differ is what each one *is* - a struct with no fields is a
    value with no content, while an interface with none is a **taxonomy**, and
    p.62 names that use explicitly ("taxonomic interfaces may include
    `MilitaryAsset` or `MedicalDevice`"). A marker interface is a real thing to
    declare.
    """
    if not _INTERFACE_API_RE.match(api_name):
        raise InterfaceError(f"invalid interface api_name {api_name!r}")
    if not display_name.strip():
        raise InterfaceError("an interface needs a display name")
    parsed = parse_properties(properties or [])
    status = ontology_status.check_status(status, kind="interface")
    note = ontology_status.parse_deprecation(deprecation, status)

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM interfaces WHERE workspace_id = :wid AND api_name = :api",
        {"wid": str(workspace_id), "api": api_name},
    )
    if existing is not None:
        raise InterfaceError(f"an interface named {api_name!r} already exists")

    row = await fetch_one(
        conn,
        """
        INSERT INTO interfaces (workspace_id, api_name, display_name, description,
                                status, deprecation, created_by)
        VALUES (:wid, :api, :name, :descr, CAST(:status AS ontology_status),
                CAST(:depr AS jsonb), :by)
        RETURNING id
        """,
        {"wid": str(workspace_id), "api": api_name, "name": display_name,
         "descr": description, "status": status,
         "depr": json.dumps(note) if note is not None else None,
         "by": str(created_by)},
    )
    assert row is not None
    interface_id = UUID(str(row["id"]))
    await _write_shape(conn, workspace_id, interface_id, parsed, extends or [])
    return await get_interface(conn, workspace_id, interface_id)


async def update_interface(
    conn: AsyncConnection,
    workspace_id: UUID,
    interface_id: UUID,
    *,
    display_name: str,
    description: str = "",
    properties: Any = None,
    extends: list[UUID] | None = None,
    status: str | None = None,
    deprecation: Any = None,
) -> dict[str, Any]:
    """Replace the shape as one document, `set_definition`'s shape and its
    reason: the properties and the extension list constrain each other, so a
    per-row API would have an ordering in which some sequence of individually
    valid edits passes through an invalid state.

    `api_name` is absent because it is immutable, for `object_types.api_name`'s
    reason (db 0003): it is the stable machine name a consumer holds, and an
    interface is a promise other resources point at.

    **What this does not do is re-check the implementations.** An edit that
    adds a required property leaves every existing implementation short of it,
    and that is a refusal `set_implementations` will make the next time one is
    saved rather than a cascade this call performs. Rewriting somebody else's
    object type to keep your edit valid is the thing §129's action refusal
    declines to do, one resource over.
    """
    current = await get_interface(conn, workspace_id, interface_id)
    if not display_name.strip():
        raise InterfaceError("an interface needs a display name")
    parsed = parse_properties(properties or [])
    next_status = ontology_status.check_status(
        str(status or current["status"]), kind="interface"
    )
    note = ontology_status.parse_deprecation(deprecation, next_status)
    await conn.execute(
        text(
            """
            UPDATE interfaces
               SET display_name = :name, description = :descr,
                   status = CAST(:status AS ontology_status),
                   deprecation = CAST(:depr AS jsonb)
             WHERE id = :iid
            """
        ),
        {"name": display_name, "descr": description, "iid": str(interface_id),
         "status": next_status,
         "depr": json.dumps(note) if note is not None else None},
    )
    await _write_shape(conn, workspace_id, interface_id, parsed, extends or [])
    return await get_interface(conn, workspace_id, interface_id)


async def _write_shape(
    conn: AsyncConnection,
    workspace_id: UUID,
    interface_id: UUID,
    properties: list[dict[str, Any]],
    extends: list[UUID],
) -> None:
    """The properties and the parents, written whole and then checked together.

    **Nothing here re-resolves the graph, and a mutant is why.** This function
    used to end by calling `effective_properties` to prove the new shape
    resolved - a cycle, a contradiction - and a mutant removing that call
    survived every test. It had to: both callers end with `get_interface`,
    which resolves the graph to build its answer, and a refusal there rolls the
    same transaction back. The check was real and it was the *second* one, so
    it is gone rather than covered by a test that could not fail (§213).

    What still holds, and where: the write is inside the caller's transaction,
    so a shape that does not resolve is never visible to anybody.
    """
    if len(extends) > MAX_EXTENDS:
        raise InterfaceError(
            f"an interface may extend at most {MAX_EXTENDS} others"
        )
    for table in ("interface_properties", "interface_extends"):
        await conn.execute(
            text(f"DELETE FROM {table} WHERE interface_id = :iid"),
            {"iid": str(interface_id)},
        )
    for order, prop in enumerate(properties):
        await conn.execute(
            text(
                """
                INSERT INTO interface_properties
                    (interface_id, api_name, display_name, description,
                     data_type, required, sort_order)
                VALUES (:iid, :api, :name, :descr,
                        CAST(:dtype AS property_data_type), :req, :ord)
                """
            ),
            {"iid": str(interface_id), "api": prop["api_name"],
             "name": prop["display_name"], "descr": prop["description"],
             "dtype": prop["data_type"], "req": prop["required"], "ord": order},
        )
    for parent in dict.fromkeys(extends):
        if str(parent) == str(interface_id):
            raise InterfaceError("an interface cannot extend itself")
        await conn.execute(
            text(
                "INSERT INTO interface_extends (interface_id, extends_id) "
                "VALUES (:iid, :pid)"
            ),
            {"iid": str(interface_id), "pid": str(parent)},
        )


async def delete_interface(
    conn: AsyncConnection, workspace_id: UUID, interface_id: UUID
) -> None:
    """Two refusals: p.256's status gate, then anything that depends on it.

    **p.256 applies here like everywhere else** - "a resource's status must be
    `experimental` or `deprecated` before it can be deleted". An interface has
    a status for the reason every ontology resource does (0055), and a status
    nothing consults is a label rather than a state. Checked *first* because it
    is about this resource rather than about others, which is the order
    `ontology.delete_type` and `actions.delete_action_type` already use.

    **Then: refused while anything implements it or extends it.** p.185's
    shared property reverts its users to ordinary properties when it is
    deleted, and this deliberately does not: a shared property gives an object
    type *metadata* it can live without, and an interface is a claim other
    resources are written against ("target the interface directly", p.61).
    Silently un-implementing three object types is a change to three object
    types, and it should be typed by whoever wants it.
    """
    row = await get_interface(conn, workspace_id, interface_id)
    ontology_status.check_deletable(
        str(row["status"]), kind="interface", name=str(row["api_name"])
    )
    users = await fetch_all(
        conn,
        """
        SELECT ot.display_name AS name FROM object_type_interfaces oti
          JOIN object_types ot ON ot.id = oti.object_type_id
         WHERE oti.interface_id = :iid
         UNION ALL
        SELECT i.display_name FROM interface_extends e
          JOIN interfaces i ON i.id = e.interface_id
         WHERE e.extends_id = :iid
        """,
        {"iid": str(interface_id)},
    )
    if users:
        raise InterfaceError(
            "this interface is implemented or extended by "
            + ", ".join(sorted(str(r["name"]) for r in users))
            + " - change those first"
        )
    await conn.execute(
        text("DELETE FROM interfaces WHERE id = :iid"), {"iid": str(interface_id)}
    )


async def set_implementations(
    conn: AsyncConnection,
    workspace_id: UUID,
    object_type_id: UUID,
    entries: list[dict[str, Any]],
    *,
    created_by: UUID,
) -> list[dict[str, Any]]:
    """Which interfaces this object type implements, and how (p.53, p.66).

    **The whole list, replacing what was there**, which is `set_definition`'s
    shape for `set_definition`'s reason - and one more here: an implementation
    is checked against the object type's *current* properties, so a per-entry
    API would let two of them disagree about which properties exist.

    Every entry is checked before any is written - and **the transaction is
    what makes that safe, not the ordering**. A mutant that moved the delete
    above the checks survived, because the refusal rolls the request back
    either way; the order is here because a function that validates and then
    writes is one anybody can read in a sitting, which is a different kind of
    good from a guarantee. Recorded rather than covered by a test that could
    not fail.
    """
    from . import ontology as ontology_service

    declared = await ontology_service.list_properties(conn, object_type_id)
    property_types = {str(p["api_name"]): str(p["data_type"]) for p in declared}
    own, graph = await _graph(conn, workspace_id)

    checked: list[tuple[UUID, dict[str, str]]] = []
    seen: set[str] = set()
    for entry in entries:
        interface_id = UUID(str(entry["interface_id"]))
        if str(interface_id) in seen:
            raise InterfaceError("the same interface is implemented twice")
        seen.add(str(interface_id))
        interface = await fetch_one(
            conn,
            "SELECT id, api_name, display_name FROM interfaces "
            "WHERE id = :iid AND workspace_id = :wid",
            {"iid": str(interface_id), "wid": str(workspace_id)},
        )
        if interface is None:
            raise InterfaceError("this workspace has no such interface")
        raw = entry.get("property_mapping") or {}
        if not isinstance(raw, dict):
            raise InterfaceError("a property mapping must be an object")
        mapping = {str(k): str(v) for k, v in raw.items() if v}
        check_implementation(
            interface_name=str(interface["display_name"]),
            required=effective_properties(str(interface_id), own=own, extends=graph),
            property_types=property_types,
            mapping=mapping,
        )
        checked.append((interface_id, mapping))

    await conn.execute(
        text("DELETE FROM object_type_interfaces WHERE object_type_id = :tid"),
        {"tid": str(object_type_id)},
    )
    for interface_id, mapping in checked:
        await conn.execute(
            text(
                """
                INSERT INTO object_type_interfaces
                    (object_type_id, interface_id, property_mapping, created_by)
                VALUES (:tid, :iid, CAST(:map AS jsonb), :by)
                """
            ),
            {"tid": str(object_type_id), "iid": str(interface_id),
             "map": json.dumps(mapping), "by": str(created_by)},
        )
    by_type = await implementations_by_type(conn, workspace_id)
    return by_type.get(str(object_type_id), [])
