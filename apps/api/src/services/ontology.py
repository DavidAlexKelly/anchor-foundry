"""Ontology service (spec §"Objects - The Semantic Layer", §16 object_types /
object_type_properties / link_types / object_type_sources).

Object types and link types live at the workspace level; object type sources
live at the project level and map a project dataset's columns onto the
workspace type's properties. This slice is the definition layer - build the
ontology, map data to it, and get auto-suggestions from dataset schemas.

Instance materialisation ("object instances are stored and indexed in
OpenSearch") is the next slice: it needs the instance-store gateway
(OpenSearch in production, Postgres locally) and the sync pipeline. Sources
created here carry sync_status='never_synced' until that ships - the status
column is telling the truth, not faking progress. Actions (write-back) follow
with Canvas.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import BreakingChangeError, ConflictError, NotFoundError
# Re-exported so callers keep saying ontology.coerce_property_value; the
# definitions live in their own module because the worker needs a verbatim
# copy of them (see that module's docstring).
from .property_values import (  # noqa: F401
    ATTACHMENT_FIELDS,
    PropertyValueError,
    coerce_property_value,
    coerce_rows,
    column_value,
)

PROPERTY_TYPES = {
    "string", "integer", "float", "boolean", "date", "timestamp", "geopoint",
    "json", "attachment",
}
CARDINALITIES = {"one_to_one", "one_to_many", "many_to_many"}

_TYPE_API_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
_PROP_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")

# DuckDB inferred type → property type, for auto-suggestion.
_DUCK_TO_PROPERTY = [
    ("BOOLEAN", "boolean"),
    ("TINYINT", "integer"), ("SMALLINT", "integer"), ("INTEGER", "integer"),
    ("BIGINT", "integer"), ("HUGEINT", "integer"),
    ("DOUBLE", "float"), ("FLOAT", "float"), ("DECIMAL", "float"),
    ("TIMESTAMP", "timestamp"), ("DATE", "date"),
    ("STRUCT", "json"), ("LIST", "json"), ("MAP", "json"), ("JSON", "json"),
]


def property_type_for(duck_type: str) -> str:
    upper = duck_type.upper()
    for needle, prop in _DUCK_TO_PROPERTY:
        if needle in upper:
            return prop
    return "string"


def to_api_name(display: str, *, type_case: bool) -> str:
    words = re.findall(r"[A-Za-z0-9]+", display)
    if not words:
        raise ValueError(f"cannot derive an API name from {display!r}")
    if type_case:
        candidate = "".join(w.capitalize() for w in words)[:100]
        if not _TYPE_API_RE.match(candidate):
            raise ValueError(f"cannot derive an API name from {display!r}")
    else:
        candidate = "_".join(w.lower() for w in words)[:100]
        if not _PROP_API_RE.match(candidate):
            raise ValueError(f"cannot derive an API name from {display!r}")
    return candidate


# ---- object types -----------------------------------------------------------
async def list_types(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        """
        SELECT ot.id, ot.api_name, ot.display_name, ot.description, ot.icon,
               ot.colour, ot.title_property_id, ot.created_at, ot.updated_at,
               (SELECT count(*) FROM object_type_sources s
                 WHERE s.object_type_id = ot.id) AS source_count
          FROM object_types ot
         WHERE ot.workspace_id = :wid
         ORDER BY ot.display_name
        """,
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def get_type(conn: AsyncConnection, workspace_id: UUID, type_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT id, api_name, display_name, description, icon, colour,
               title_property_id, created_at, updated_at
          FROM object_types WHERE id = :tid AND workspace_id = :wid
        """,
        {"tid": str(type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("object type")
    return dict(row)


async def list_properties(conn: AsyncConnection, type_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        """
        SELECT id, api_name, display_name, data_type, required, description, sort_order
          FROM object_type_properties
         WHERE object_type_id = :tid ORDER BY sort_order, api_name
        """,
        {"tid": str(type_id)},
    )
    return [dict(r) for r in rows]


def _validate_properties(properties: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for prop in properties:
        api = str(prop["api_name"])
        if not _PROP_API_RE.match(api):
            raise ValueError(f"invalid property api_name {api!r}")
        if api in seen:
            raise ValueError(f"duplicate property {api!r}")
        seen.add(api)
        if str(prop["data_type"]) not in PROPERTY_TYPES:
            raise ValueError(f"invalid property type {prop['data_type']!r}")


async def create_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    icon: str,
    colour: str,
    properties: list[dict[str, Any]],
    title_property: str | None,
    created_by: UUID,
) -> dict[str, Any]:
    if not _TYPE_API_RE.match(api_name):
        raise ValueError(f"invalid object type api_name {api_name!r}")
    _validate_properties(properties)
    if title_property is not None and title_property not in {
        str(p["api_name"]) for p in properties
    }:
        raise ValueError("title_property must be one of the defined properties")
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM object_types WHERE workspace_id=:wid AND api_name=:api",
        {"wid": str(workspace_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"an object type named {api_name!r} already exists")

    row = await fetch_one(
        conn,
        """
        INSERT INTO object_types (workspace_id, api_name, display_name, description,
                                  icon, colour, created_by)
        VALUES (:wid, :api, :name, :descr, :icon, :colour, :by)
        RETURNING id, api_name, display_name, description, icon, colour,
                  title_property_id, created_at, updated_at
        """,
        {
            "wid": str(workspace_id),
            "api": api_name,
            "name": display_name,
            "descr": description,
            "icon": icon,
            "colour": colour,
            "by": str(created_by),
        },
    )
    assert row is not None
    type_id = UUID(str(row["id"]))
    title_id = await _write_property_rows(conn, type_id, properties, title_property)
    if title_id is not None:
        row = dict(row)
        row["title_property_id"] = title_id
    await _snapshot_version(conn, type_id, created_by=created_by)
    return dict(row)


async def _write_property_rows(
    conn: AsyncConnection,
    type_id: UUID,
    properties: list[dict[str, Any]],
    title_property: str | None,
) -> UUID | None:
    """Insert the property rows in the given order and point the type's
    title_property_id at the named one. Shared by create and update so the
    two cannot drift on sort ordering or title resolution."""
    title_id: UUID | None = None
    for index, prop in enumerate(properties):
        prow = await fetch_one(
            conn,
            """
            INSERT INTO object_type_properties (object_type_id, api_name, display_name,
                                                data_type, required, description, sort_order)
            VALUES (:tid, :api, :name, CAST(:dtype AS property_data_type),
                    :required, :descr, :sort)
            RETURNING id
            """,
            {
                "tid": str(type_id),
                "api": str(prop["api_name"]),
                "name": str(prop.get("display_name") or prop["api_name"]),
                "dtype": str(prop["data_type"]),
                "required": bool(prop.get("required", False)),
                "descr": str(prop.get("description", "")),
                "sort": index,
            },
        )
        assert prow is not None
        if title_property == str(prop["api_name"]):
            title_id = UUID(str(prow["id"]))
    await conn.execute(
        text("UPDATE object_types SET title_property_id = :pid WHERE id = :tid"),
        {"pid": str(title_id) if title_id else None, "tid": str(type_id)},
    )
    return title_id


async def delete_type(conn: AsyncConnection, workspace_id: UUID, type_id: UUID) -> None:
    await get_type(conn, workspace_id, type_id)
    await fetch_one(
        conn, "DELETE FROM object_types WHERE id = :tid RETURNING id", {"tid": str(type_id)}
    )


# ---- object type definition history (db 0028) -------------------------------
async def _snapshot_version(
    conn: AsyncConnection,
    type_id: UUID,
    *,
    created_by: UUID,
    restored_from: int | None = None,
) -> int:
    """Append the type's *current* state as the next version.

    Reads the live rows rather than taking the caller's proposed values, so a
    version can never record something the database does not actually hold -
    the snapshot is a statement about what the type became, not about what
    somebody asked for.
    """
    row = await fetch_one(
        conn,
        """
        INSERT INTO object_type_versions (
            object_type_id, version_number, display_name, description, icon, colour,
            properties, title_property, restored_from, created_by)
        SELECT ot.id,
               COALESCE((SELECT max(v.version_number) + 1 FROM object_type_versions v
                          WHERE v.object_type_id = ot.id), 1),
               ot.display_name, ot.description, ot.icon, ot.colour,
               COALESCE(
                   (SELECT jsonb_agg(jsonb_build_object(
                               'api_name', p.api_name,
                               'display_name', p.display_name,
                               'data_type', p.data_type,
                               'required', p.required,
                               'description', p.description,
                               'sort_order', p.sort_order)
                           ORDER BY p.sort_order, p.api_name)
                      FROM object_type_properties p WHERE p.object_type_id = ot.id),
                   '[]'::jsonb),
               (SELECT p.api_name FROM object_type_properties p
                 WHERE p.id = ot.title_property_id),
               :restored, :by
          FROM object_types ot
         WHERE ot.id = :tid
        RETURNING version_number
        """,
        {"tid": str(type_id), "restored": restored_from, "by": str(created_by)},
    )
    assert row is not None
    return int(row["version_number"])


async def list_type_versions(
    conn: AsyncConnection, workspace_id: UUID, type_id: UUID
) -> list[dict[str, Any]]:
    await get_type(conn, workspace_id, type_id)  # 404 if invisible
    rows = await fetch_all(
        conn,
        """
        SELECT v.id, v.version_number, v.display_name, v.description, v.icon, v.colour,
               v.properties, v.title_property, v.restored_from, v.created_at,
               u.email AS created_by_email
          FROM object_type_versions v
          LEFT JOIN users u ON u.id = v.created_by
         WHERE v.object_type_id = :tid
         ORDER BY v.version_number DESC
        """,
        {"tid": str(type_id)},
    )
    return [dict(r) for r in rows]


# ---- what an edit would break ------------------------------------------------
#
# Removing or retyping a property does not raise anything anywhere: every
# consumer degrades quietly, which is exactly why this analysis exists rather
# than a try/except somewhere downstream.
#
#   * a dataset mapping keeps writing the property on every sync
#     (instances.extract_rows works from column_mappings alone and never
#     consults the type), while the browse UI iterates the type's *declared*
#     properties - so the data keeps arriving and stops being visible;
#   * an action's value check falls back to `property_types.get(prop,
#     "string")` (actions.validate_submitted_values), so a removed integer
#     property silently starts accepting any string;
#   * a link join whose property is gone traverses to nothing, forever, and
#     the panel says "nothing matches" - indistinguishable from data that
#     genuinely has no matches.
#
# None of those is an error a user would ever be shown, which is the whole
# argument for refusing the change until somebody says they mean it.
BREAKING_CHANGES = {"removed", "retyped"}


def _diff_properties(
    current: list[dict[str, Any]], proposed: list[dict[str, Any]]
) -> dict[str, str]:
    """{api_name: 'removed' | 'retyped'} for the properties an edit disturbs.

    Properties are matched by api_name, so a *rename* is a removal plus an
    addition and is reported as such. That is not a shortcut: nothing in the
    schema distinguishes "renamed a property" from "deleted one and added
    another", every consumer that names the old api_name breaks either way,
    and offering rename-with-migration would mean rewriting mappings, action
    lists, link joins and stored instance keys - a much larger feature than
    this item, and one that should not be implied by a text field.

    Additions and changes to display_name/description/required are absent:
    nothing downstream reads them, so nothing downstream can break on them.
    """
    before = {str(p["api_name"]): str(p["data_type"]) for p in current}
    after = {str(p["api_name"]): str(p["data_type"]) for p in proposed}
    changes: dict[str, str] = {}
    for api_name, data_type in before.items():
        if api_name not in after:
            changes[api_name] = "removed"
        elif after[api_name] != data_type:
            changes[api_name] = "retyped"
    return changes


async def type_impact(
    conn: AsyncConnection,
    workspace_id: UUID,
    type_id: UUID,
    proposed_properties: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Every consumer a proposed property change would disturb, named.

    Returned as a list rather than a boolean because a warning that cannot
    say *which* dataset mapping or *which* action it is about is a warning
    nobody can act on.
    """
    await get_type(conn, workspace_id, type_id)
    current = await list_properties(conn, type_id)
    changes = _diff_properties(current, proposed_properties)
    if not changes:
        return []

    import json

    impacts: list[dict[str, Any]] = []

    sources = await fetch_all(
        conn,
        """
        SELECT s.id, s.column_mappings, d.name AS dataset_name
          FROM object_type_sources s
          JOIN datasets d ON d.id = s.dataset_id
         WHERE s.object_type_id = :tid
        """,
        {"tid": str(type_id)},
    )
    for source in sources:
        mappings = source["column_mappings"]
        if isinstance(mappings, str):
            mappings = json.loads(mappings)
        for column, prop in mappings.items():
            change = changes.get(str(prop))
            if change is None:
                continue
            impacts.append({
                "property": str(prop),
                "change": change,
                "consumer_kind": "dataset_mapping",
                "consumer_id": source["id"],
                "consumer_name": str(source["dataset_name"]),
                "detail": f"column {column!r} is mapped to it",
                "blocking": True,
            })

    actions = await fetch_all(
        conn,
        "SELECT id, display_name, editable_properties FROM action_types "
        "WHERE object_type_id = :tid",
        {"tid": str(type_id)},
    )
    for action in actions:
        editable = action["editable_properties"]
        if isinstance(editable, str):
            editable = json.loads(editable)
        for prop in editable or []:
            change = changes.get(str(prop))
            if change is None:
                continue
            impacts.append({
                "property": str(prop),
                "change": change,
                "consumer_kind": "action",
                "consumer_id": action["id"],
                "consumer_name": str(action["display_name"]),
                "detail": "the action writes it",
                "blocking": True,
            })

    links = await fetch_all(
        conn,
        """
        SELECT id, display_name, from_object_type_id, to_object_type_id,
               from_property, to_property
          FROM link_types
         WHERE workspace_id = :wid
           AND from_property IS NOT NULL
           AND (from_object_type_id = :tid OR to_object_type_id = :tid)
        """,
        {"wid": str(workspace_id), "tid": str(type_id)},
    )
    for link in links:
        for end, column in (("from", "from_property"), ("to", "to_property")):
            if str(link[f"{end}_object_type_id"]) != str(type_id):
                continue
            prop = str(link[column])
            change = changes.get(prop)
            if change is None:
                continue
            # A retype is harmless to a link: the join compares the *text*
            # form of both values (instance_store.join_key), so an integer
            # that becomes a string still matches what it matched before.
            # Only a removal actually breaks a traversal.
            impacts.append({
                "property": prop,
                "change": change,
                "consumer_kind": "link",
                "consumer_id": link["id"],
                "consumer_name": str(link["display_name"]),
                "detail": f"the link joins on it ({end} end)",
                "blocking": change == "removed",
            })

    return impacts


def impact_summary(impacts: list[dict[str, Any]]) -> str:
    blocking = [i for i in impacts if i["blocking"]]
    parts = [
        f"{i['consumer_kind'].replace('_', ' ')} {i['consumer_name']!r} "
        f"({i['detail']}, property {i['change']})"
        for i in blocking
    ]
    return "; ".join(parts)


async def update_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    type_id: UUID,
    display_name: str,
    description: str,
    icon: str,
    colour: str,
    properties: list[dict[str, Any]],
    title_property: str | None,
    updated_by: UUID,
    acknowledge_breaking: bool = False,
) -> dict[str, Any]:
    """Edit a type's definition, recording the result as a new version.

    A **whole-definition** replacement rather than a set of granular
    operations (add_property / drop_property / retype). Two reasons: the edit
    form already holds the whole definition, so a granular API would make the
    client compute a diff the service has to recompute anyway to judge
    impact; and impact is a property of the *whole* change - dropping `a`
    while adding `b` is one edit a reviewer should see together, not two
    warnings arriving in sequence with the type briefly invalid in between.

    `api_name` is not a parameter: 0003 calls it the stable machine name used
    by exports, and no in-product warning reaches an external consumer
    holding it.

    Property rows are deleted and re-inserted rather than diffed and patched.
    Property ids are not referenced by anything except `title_property_id`,
    which this function rewrites in the same statement - so a rebuild is
    simpler than a diff with nothing to lose, and it is what keeps sort_order
    honestly equal to the order the caller sent.
    """
    await get_type(conn, workspace_id, type_id)
    _validate_properties(properties)
    if not properties:
        raise ValueError("an object type needs at least one property")
    if title_property is not None and title_property not in {
        str(p["api_name"]) for p in properties
    }:
        raise ValueError("title_property must be one of the defined properties")

    impacts = await type_impact(conn, workspace_id, type_id, properties)
    if any(i["blocking"] for i in impacts) and not acknowledge_breaking:
        raise BreakingChangeError(
            "this change breaks existing consumers: " + impact_summary(impacts),
            impacts=impacts,
        )

    await conn.execute(
        text(
            """
            UPDATE object_types
               SET display_name = :name, description = :descr, icon = :icon,
                   colour = :colour, title_property_id = NULL
             WHERE id = :tid
            """
        ),
        {"name": display_name, "descr": description, "icon": icon,
         "colour": colour, "tid": str(type_id)},
    )
    # title_property_id is cleared above so the delete below cannot trip a
    # dangling reference before the new rows exist.
    await conn.execute(
        text("DELETE FROM object_type_properties WHERE object_type_id = :tid"),
        {"tid": str(type_id)},
    )
    await _write_property_rows(conn, type_id, properties, title_property)
    await _snapshot_version(conn, type_id, created_by=updated_by)
    return await get_type(conn, workspace_id, type_id)


async def restore_type_version(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    type_id: UUID,
    version_number: int,
    updated_by: UUID,
    acknowledge_breaking: bool = False,
) -> dict[str, Any]:
    """Roll the definition back by appending a new version equal to an old one.

    A restore goes through the same impact check as any other edit, and that
    is the point rather than an oversight: reverting to a definition from
    before a property existed removes that property *now*, from consumers
    built since. "It used to be like this" is not evidence that going back is
    safe.
    """
    version = await fetch_one(
        conn,
        """
        SELECT display_name, description, icon, colour, properties, title_property
          FROM object_type_versions
         WHERE object_type_id = :tid AND version_number = :n
        """,
        {"tid": str(type_id), "n": version_number},
    )
    if version is None:
        await get_type(conn, workspace_id, type_id)  # 404 shape for a bad type too
        raise NotFoundError("object type version")

    import json

    properties = version["properties"]
    if isinstance(properties, str):
        properties = json.loads(properties)

    updated = await update_type(
        conn,
        workspace_id=workspace_id,
        type_id=type_id,
        display_name=str(version["display_name"]),
        description=str(version["description"]),
        icon=str(version["icon"]),
        colour=str(version["colour"]),
        properties=list(properties),
        title_property=version["title_property"],
        updated_by=updated_by,
        acknowledge_breaking=acknowledge_breaking,
    )
    # update_type appended a version already; mark it as the revert it is, so
    # the history reads "reverted to v2" rather than showing an unexplained
    # reappearance of an old definition.
    await conn.execute(
        text(
            """
            UPDATE object_type_versions SET restored_from = :from
             WHERE object_type_id = :tid
               AND version_number = (SELECT max(version_number)
                                       FROM object_type_versions
                                      WHERE object_type_id = :tid)
            """
        ),
        {"from": version_number, "tid": str(type_id)},
    )
    return updated


# ---- link types -------------------------------------------------------------
# Reserved reference to an instance's primary key rather than one of its
# mapped properties (db 0027). Needed because the far end of a foreign key is
# nearly always the referenced row's key, and the primary key is a field on
# the instance, not an entry in its properties JSON. The '$' prefix cannot
# collide with a property api_name (_PROP_API_RE requires a leading lowercase
# letter), so a property can never be shadowed by the sentinel.
PRIMARY_KEY_REF = "$primary_key"


async def _validate_join_property(
    conn: AsyncConnection, type_id: UUID, value: str, *, end: str
) -> None:
    """A join property must be the primary-key sentinel or a property the type
    actually declares. Checked here rather than left to produce zero matches
    at traversal time: "this link finds nothing" and "this link names a
    property that does not exist" look identical in the UI, and only one of
    them is the user's data being wrong."""
    if value == PRIMARY_KEY_REF:
        return
    if not _PROP_API_RE.match(value):
        raise ValueError(f"invalid {end} property {value!r}")
    known = {str(p["api_name"]) for p in await list_properties(conn, type_id)}
    if value not in known:
        raise ValueError(
            f"{end} property {value!r} is not a property of that object type "
            f"(known: {', '.join(sorted(known)) or 'none'}, or {PRIMARY_KEY_REF!r})"
        )


def _normalise_join(
    from_property: str | None, to_property: str | None
) -> tuple[str | None, str | None]:
    """Empty strings arrive from HTML selects that mean "not set"; treat them
    as unset rather than letting them fail the column's shape CHECK."""
    a = (from_property or "").strip() or None
    b = (to_property or "").strip() or None
    if (a is None) != (b is None):
        raise ValueError(
            "a link's join needs a property on both ends - half a join is not a "
            "weaker join, it is an unanswerable question"
        )
    return a, b


_LINK_SELECT = """
        SELECT lt.id, lt.api_name, lt.display_name, lt.cardinality, lt.created_at,
               lt.from_property, lt.to_property,
               lt.from_object_type_id, f.display_name AS from_display_name,
               lt.to_object_type_id, t.display_name AS to_display_name
          FROM link_types lt
          JOIN object_types f ON f.id = lt.from_object_type_id
          JOIN object_types t ON t.id = lt.to_object_type_id
"""


async def list_link_types(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        _LINK_SELECT + " WHERE lt.workspace_id = :wid ORDER BY lt.display_name",
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def get_link_type(
    conn: AsyncConnection, workspace_id: UUID, link_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        _LINK_SELECT + " WHERE lt.id = :lid AND lt.workspace_id = :wid",
        {"lid": str(link_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("link type")
    return dict(row)


async def links_for_type(
    conn: AsyncConnection, workspace_id: UUID, type_id: UUID
) -> list[dict[str, Any]]:
    """Every traversable link type touching this object type, from that type's
    point of view.

    A link type is returned once per end it occupies, with ``direction`` and
    the pair reordered so the caller never has to work out which side it is
    on: ``near_property`` is the property to read off the instance in hand,
    ``far_property`` is the one to match against on the other type. A
    self-link (both ends the same type) is returned **twice** on purpose -
    outbound and inbound are genuinely different questions when a Person
    links to a Person by manager: one is "my manager", the other is "my
    reports".

    Only mapped links come back (db 0027: the pair is both-or-neither, so
    ``from_property IS NOT NULL`` is the whole test). A link type without a
    join is still a valid ontology statement; it just cannot answer an
    instance-level question yet.
    """
    await get_type(conn, workspace_id, type_id)  # 404 if invisible
    rows = await fetch_all(
        conn,
        _LINK_SELECT
        + """
         WHERE lt.workspace_id = :wid
           AND lt.from_property IS NOT NULL
           AND (lt.from_object_type_id = :tid OR lt.to_object_type_id = :tid)
         ORDER BY lt.display_name
        """,
        {"wid": str(workspace_id), "tid": str(type_id)},
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        link = dict(row)
        if str(link["from_object_type_id"]) == str(type_id):
            out.append({
                **link,
                "direction": "outbound",
                "near_property": link["from_property"],
                "far_property": link["to_property"],
                "far_type_id": link["to_object_type_id"],
                "far_type_display_name": link["to_display_name"],
            })
        if str(link["to_object_type_id"]) == str(type_id):
            out.append({
                **link,
                "direction": "inbound",
                "near_property": link["to_property"],
                "far_property": link["from_property"],
                "far_type_id": link["from_object_type_id"],
                "far_type_display_name": link["from_display_name"],
            })
    return out


async def create_link_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    api_name: str,
    display_name: str,
    from_type_id: UUID,
    to_type_id: UUID,
    cardinality: str,
    created_by: UUID,
    from_property: str | None = None,
    to_property: str | None = None,
) -> dict[str, Any]:
    if not _PROP_API_RE.match(api_name):
        raise ValueError(f"invalid link api_name {api_name!r}")
    if cardinality not in CARDINALITIES:
        raise ValueError(f"invalid cardinality {cardinality!r}")
    # Both endpoints must be this workspace's types (404 shape otherwise).
    await get_type(conn, workspace_id, from_type_id)
    await get_type(conn, workspace_id, to_type_id)
    from_property, to_property = _normalise_join(from_property, to_property)
    if from_property is not None:
        await _validate_join_property(conn, from_type_id, from_property, end="from")
        assert to_property is not None
        await _validate_join_property(conn, to_type_id, to_property, end="to")
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM link_types WHERE workspace_id=:wid AND api_name=:api",
        {"wid": str(workspace_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"a link type named {api_name!r} already exists")
    row = await fetch_one(
        conn,
        """
        INSERT INTO link_types (workspace_id, api_name, display_name,
                                from_object_type_id, to_object_type_id,
                                cardinality, created_by, from_property, to_property)
        VALUES (:wid, :api, :name, :from, :to, CAST(:card AS link_cardinality), :by,
                :fprop, :tprop)
        RETURNING id, api_name, display_name, from_object_type_id,
                  to_object_type_id, cardinality, created_at,
                  from_property, to_property
        """,
        {
            "wid": str(workspace_id),
            "api": api_name,
            "name": display_name,
            "from": str(from_type_id),
            "to": str(to_type_id),
            "card": cardinality,
            "by": str(created_by),
            "fprop": from_property,
            "tprop": to_property,
        },
    )
    assert row is not None
    return dict(row)


async def set_link_join(
    conn: AsyncConnection,
    workspace_id: UUID,
    link_id: UUID,
    *,
    from_property: str | None,
    to_property: str | None,
) -> dict[str, Any]:
    """Map (or unmap) the properties a link joins on, in place.

    Only the join is mutable. Changing an endpoint or the cardinality would
    make it a different relationship wearing the same name - delete and
    recreate for that. The join, by contrast, is the one part that is a
    statement about *how the data expresses* the relationship rather than
    about the ontology, and it has to be editable: every link type defined
    before db 0027 exists without one, and delete-and-recreate as the only
    route to adding it would break every reference to a link people already
    built their ontology around.
    """
    link = await get_link_type(conn, workspace_id, link_id)
    from_property, to_property = _normalise_join(from_property, to_property)
    if from_property is not None:
        await _validate_join_property(
            conn, UUID(str(link["from_object_type_id"])), from_property, end="from"
        )
        assert to_property is not None
        await _validate_join_property(
            conn, UUID(str(link["to_object_type_id"])), to_property, end="to"
        )
    await conn.execute(
        text(
            "UPDATE link_types SET from_property = :fprop, to_property = :tprop "
            "WHERE id = :lid AND workspace_id = :wid"
        ),
        {"fprop": from_property, "tprop": to_property,
         "lid": str(link_id), "wid": str(workspace_id)},
    )
    return await get_link_type(conn, workspace_id, link_id)


async def delete_link_type(conn: AsyncConnection, workspace_id: UUID, link_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM link_types WHERE id=:lid AND workspace_id=:wid RETURNING id",
        {"lid": str(link_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("link type")


# ---- object type sources (project-level mapping) ----------------------------
async def list_sources(
    conn: AsyncConnection, project_id: UUID, workspace_id: UUID
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        """
        SELECT s.id, s.object_type_id, ot.display_name AS object_type_name,
               s.dataset_id, d.name AS dataset_name, s.primary_key_column,
               s.column_mappings, s.sync_status, s.last_synced_at, s.last_error,
               s.created_at
          FROM object_type_sources s
          JOIN datasets d ON d.id = s.dataset_id
          JOIN object_types ot ON ot.id = s.object_type_id
         WHERE d.project_id = :pid AND ot.workspace_id = :wid
         ORDER BY ot.display_name, d.name
        """,
        {"pid": str(project_id), "wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def create_source(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    project_id: UUID,
    object_type_id: UUID,
    dataset_id: UUID,
    primary_key_column: str,
    column_mappings: dict[str, str],
    created_by: UUID,
) -> dict[str, Any]:
    """Map dataset columns → object properties. Every referenced column must
    exist in the dataset's schema and every property on the type - a mapping
    that silently drops columns would corrupt instances at sync time."""
    await get_type(conn, workspace_id, object_type_id)
    ds = await fetch_one(
        conn,
        "SELECT table_schema FROM datasets WHERE id=:did AND project_id=:pid",
        {"did": str(dataset_id), "pid": str(project_id)},
    )
    if ds is None:
        raise NotFoundError("dataset")

    import json

    schema = ds["table_schema"]
    if isinstance(schema, str):
        schema = json.loads(schema)
    dataset_columns = {c["name"] for c in schema}
    properties = {str(p["api_name"]) for p in await list_properties(conn, object_type_id)}

    if primary_key_column not in dataset_columns:
        raise ValueError(f"primary key column {primary_key_column!r} is not in the dataset")
    if not column_mappings:
        raise ValueError("map at least one column to a property")
    for column, prop in column_mappings.items():
        if column not in dataset_columns:
            raise ValueError(f"column {column!r} is not in the dataset")
        if prop not in properties:
            raise ValueError(f"property {prop!r} is not defined on the object type")

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM object_type_sources WHERE object_type_id=:tid AND dataset_id=:did",
        {"tid": str(object_type_id), "did": str(dataset_id)},
    )
    if existing is not None:
        raise ConflictError("this dataset already feeds that object type")

    row = await fetch_one(
        conn,
        """
        INSERT INTO object_type_sources (object_type_id, dataset_id, primary_key_column,
                                         column_mappings, created_by)
        VALUES (:tid, :did, :pk, CAST(:mappings AS jsonb), :by)
        RETURNING id, object_type_id, dataset_id, primary_key_column,
                  column_mappings, sync_status, last_synced_at, last_error, created_at
        """,
        {
            "tid": str(object_type_id),
            "did": str(dataset_id),
            "pk": primary_key_column,
            "mappings": json.dumps(column_mappings),
            "by": str(created_by),
        },
    )
    assert row is not None
    return dict(row)


async def get_source(
    conn: AsyncConnection, project_id: UUID, source_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT s.id, s.object_type_id, ot.display_name AS object_type_name,
               s.dataset_id, d.name AS dataset_name, d.s3_location,
               s.primary_key_column, s.column_mappings, s.sync_status,
               s.last_synced_at, s.last_error, s.created_at
          FROM object_type_sources s
          JOIN datasets d ON d.id = s.dataset_id
          JOIN object_types ot ON ot.id = s.object_type_id
         WHERE s.id = :sid AND d.project_id = :pid
        """,
        {"sid": str(source_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("object type source")
    return dict(row)


async def mark_source_synced(
    conn: AsyncConnection, source_id: UUID, *, ok: bool, error: str | None
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        UPDATE object_type_sources
           SET sync_status = CAST(:status AS object_sync_status),
               last_synced_at = CASE WHEN :ok THEN now() ELSE last_synced_at END,
               last_error = :error
         WHERE id = :sid
        RETURNING id, object_type_id, dataset_id, primary_key_column,
                  column_mappings, sync_status, last_synced_at, last_error, created_at
        """,
        {"status": "ok" if ok else "error", "ok": ok, "error": error, "sid": str(source_id)},
    )
    assert row is not None
    return dict(row)


_SCHEDULE_COLUMNS = "id, sync_schedule, sync_next_run_at"


async def get_source_schedule(
    conn: AsyncConnection, project_id: UUID, source_id: UUID
) -> dict[str, Any]:
    await get_source(conn, project_id, source_id)  # 404 if invisible
    row = await fetch_one(
        conn,
        f"""
        SELECT s.{_SCHEDULE_COLUMNS} FROM object_type_sources s
          JOIN datasets d ON d.id = s.dataset_id
         WHERE s.id = :sid AND d.project_id = :pid
        """,
        {"sid": str(source_id), "pid": str(project_id)},
    )
    assert row is not None
    return dict(row)


async def set_source_schedule(
    conn: AsyncConnection, project_id: UUID, source_id: UUID, *, cron_schedule: str, next_run_at
) -> dict[str, Any]:
    await get_source(conn, project_id, source_id)
    row = await fetch_one(
        conn,
        f"""
        UPDATE object_type_sources s SET sync_schedule = :cron, sync_next_run_at = :next_run
          FROM datasets d
         WHERE s.id = :sid AND d.id = s.dataset_id AND d.project_id = :pid
        RETURNING s.{_SCHEDULE_COLUMNS}
        """,
        {"cron": cron_schedule, "next_run": next_run_at, "sid": str(source_id), "pid": str(project_id)},
    )
    assert row is not None
    return dict(row)


async def clear_source_schedule(
    conn: AsyncConnection, project_id: UUID, source_id: UUID
) -> dict[str, Any]:
    await get_source(conn, project_id, source_id)
    row = await fetch_one(
        conn,
        f"""
        UPDATE object_type_sources s SET sync_schedule = NULL, sync_next_run_at = NULL
          FROM datasets d
         WHERE s.id = :sid AND d.id = s.dataset_id AND d.project_id = :pid
        RETURNING s.{_SCHEDULE_COLUMNS}
        """,
        {"sid": str(source_id), "pid": str(project_id)},
    )
    assert row is not None
    return dict(row)


async def delete_source(conn: AsyncConnection, project_id: UUID, source_id: UUID) -> None:
    row = await fetch_one(
        conn,
        """
        DELETE FROM object_type_sources s
         USING datasets d
         WHERE s.id = :sid AND d.id = s.dataset_id AND d.project_id = :pid
        RETURNING s.id
        """,
        {"sid": str(source_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("object type source")


# ---- auto-suggestion (spec: "Your customers table looks like a Customer") ---
async def suggest_from_dataset(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID
) -> dict[str, Any]:
    ds = await fetch_one(
        conn,
        "SELECT name, table_schema FROM datasets WHERE id=:did AND project_id=:pid",
        {"did": str(dataset_id), "pid": str(project_id)},
    )
    if ds is None:
        raise NotFoundError("dataset")
    import json

    schema = ds["table_schema"]
    if isinstance(schema, str):
        schema = json.loads(schema)

    # Singularise a trailing plural: "customers" suggests "Customer".
    base = str(ds["name"]).strip()
    singular = re.sub(r"ies$", "y", base)
    if singular == base:
        singular = re.sub(r"s$", "", base) or base

    properties: list[dict[str, Any]] = []
    pk_guess: str | None = None
    title_guess: str | None = None
    for column in schema:
        col_name = str(column["name"])
        prop_api = to_api_name(col_name, type_case=False)
        prop_type = property_type_for(str(column["data_type"]))
        properties.append(
            {
                "api_name": prop_api,
                "display_name": col_name.replace("_", " ").title(),
                "data_type": prop_type,
                "required": False,
                "source_column": col_name,
            }
        )
        lowered = col_name.lower()
        if pk_guess is None and (lowered == "id" or lowered.endswith("_id")):
            pk_guess = col_name
        if title_guess is None and any(
            hint in lowered for hint in ("name", "title", "email", "label")
        ):
            title_guess = prop_api
    return {
        "dataset_name": ds["name"],
        "suggested_api_name": to_api_name(singular, type_case=True),
        "suggested_display_name": singular.replace("_", " ").replace("-", " ").title(),
        "suggested_primary_key": pk_guess or (str(schema[0]["name"]) if schema else None),
        "suggested_title_property": title_guess,
        "properties": properties,
    }
