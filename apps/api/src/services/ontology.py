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

import json
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
from . import conditional_format, derived_properties, shared_properties, value_format
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
    # A **series id**, not a history (decision 0009, migration 0047). The value
    # stored on the instance is a small scalar - usually the instance's own
    # primary key - and `object_type_series` says which dataset, key column,
    # timestamp column and value column hold the points behind it.
    "time_series",
}

# How prominently an application should show a property (Foundry
# `object-link-types` p.111). **A display hint, never a permission**: a hidden
# property is still stored, still synced, and still returned by this API to
# anybody who may read the object type at all. Foundry's own wording is "an
# indication to user applications", and treating it as access control would be
# worse than not having it, because somebody would rely on it as one.
PROPERTY_VISIBILITIES = ("normal", "prominent", "hidden")
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
               ot.colour, ot.title_property_id, ot.resource_id,
               ot.created_at, ot.updated_at,
               (SELECT count(*) FROM object_type_sources s
                 WHERE s.object_type_id = ot.id) AS source_count,
               -- Just the hidden ones, not every property. A browser listing
               -- types needs to know which columns not to draw
               -- (`object-link-types` p.111) and nothing else about them, and
               -- shipping every property of every type to answer that would
               -- make a list endpoint pay for a detail one.
               COALESCE((SELECT array_agg(p.api_name ORDER BY p.sort_order)
                           FROM object_type_properties p
                          WHERE p.object_type_id = ot.id
                            AND p.visibility = 'hidden'), '{}') AS hidden_properties
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
    """The type's properties, with any shared metadata already applied.

    The join is here rather than at the call sites because *every* reader of a
    property wants the resolved answer: p.178's whole point is that editing a
    shared property updates the object types using it, and a reader that saw
    the stored row would see the value from the last time the type was saved.
    `shared_property_api_name` comes back too, so an application can draw
    p.178's globe without a second query.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT p.id, p.api_name, p.display_name, p.data_type, p.required,
               p.description, p.sort_order, p.visibility, p.value_format,
               p.conditional_format, p.edit_only, p.derivation,
               p.shared_property_id,
               sp.api_name AS shared_property_api_name,
               sp.display_name AS sp_display_name,
               sp.description AS sp_description,
               sp.data_type AS sp_data_type,
               sp.visibility AS sp_visibility,
               sp.value_format AS sp_value_format
          FROM object_type_properties p
          LEFT JOIN shared_properties sp ON sp.id = p.shared_property_id
         WHERE p.object_type_id = :tid ORDER BY p.sort_order, p.api_name
        """,
        {"tid": str(type_id)},
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        full = dict(row)
        shared = (
            {
                "api_name": full["shared_property_api_name"],
                "display_name": full["sp_display_name"],
                "description": full["sp_description"],
                "data_type": full["sp_data_type"],
                "visibility": full["sp_visibility"],
                "value_format": full["sp_value_format"],
            }
            if full["shared_property_id"] is not None
            else None
        )
        prop = {k: v for k, v in full.items() if not k.startswith("sp_")}
        out.append(shared_properties.resolve(prop, shared))
    return out


def derived_property_names(properties: list[dict[str, Any]]) -> set[str]:
    """The api_names calculated from linked objects rather than stored (p.143).

    Read wherever "which properties does this object actually have a value
    for" is the question: the sync (which never produces one), the action
    write-back (which must refuse to write one - p.143 calls them read-only),
    and the instance read (which fills them in).
    """
    return {str(p["api_name"]) for p in properties if p.get("derivation")}


def edit_only_properties(properties: list[dict[str, Any]]) -> set[str]:
    """The api_names with no column in any backing dataset (p.113).

    Read by three callers that would otherwise each decide it: the sync (which
    must not overwrite them, and must not report them as missing), the action
    write-back (which writes them to the instance and not to the dataset), and
    the source editor (which must not offer them a column).
    """
    return {str(p["api_name"]) for p in properties if p.get("edit_only")}


def required_properties(properties: list[dict[str, Any]]) -> set[str]:
    """The api names a value is compulsory for (`object-link-types` p.116)."""
    return {str(p["api_name"]) for p in properties if p.get("required")}


def is_missing(value: Any) -> bool:
    """Whether a value fails a required property (p.116).

    > "You can use this object type property to validate that there are no
    > objects that have a null value for this property, **or an empty array if
    > it is an array property**." … "Array properties cannot be empty: Setting
    > an array property to required ensures the presence of at least one item."

    Three things count as absent and the third is ours: `None`, an empty list,
    and the **empty string**. A form posts `""` for a box somebody cleared, and
    treating that as a value would let the one path a person actually uses walk
    straight past the rule - which would make the whole feature a decoration on
    everything except a hand-written API call.

    `0` and `false` are values. They are the classic false-negative in a check
    written with `if not value`, and a required numeric property whose only
    legal reading is zero is an ordinary thing.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _validate_properties(properties: list[dict[str, Any]]) -> None:
    # Built first, because a conditional formatting rule may compare against a
    # *different* property (`object-link-types` p.105) - so validating one
    # property needs the base type of every property on the type.
    types_by_property = {
        str(p["api_name"]): str(p["data_type"]) for p in properties
    }
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
        visibility = str(prop.get("visibility") or "normal")
        if visibility not in PROPERTY_VISIBILITIES:
            raise ValueError(
                f"invalid visibility {visibility!r} for {api!r}; expected one of "
                + ", ".join(PROPERTY_VISIBILITIES)
            )
        # Normalised in place, so what is stored is what was checked. A
        # formatter validated and then written from the untouched input would
        # be two things that only look like one.
        prop["value_format"] = value_format.parse(
            prop.get("value_format"),
            data_type=str(prop["data_type"]),
            property_name=api,
        )
        prop["conditional_format"] = conditional_format.parse(
            prop.get("conditional_format"),
            property_name=api,
            types_by_property=types_by_property,
        )
        if prop.get("derivation") is not None:
            # p.148's own list, checked here because each item is a fact about
            # the *property* rather than about the chain.
            derived_properties.check_compatible(prop, property_name=api)


async def _apply_shared(
    conn: AsyncConnection,
    workspace_id: UUID,
    properties: list[dict[str, Any]],
    *,
    already_attached: dict[str, str],
) -> None:
    """Check every attachment to a shared property, then resolve it in place.

    Runs after `_validate_properties`, which is not an ordering detail: that
    function normalises `value_format`, and comparing a raw formatter against a
    stored normalised one would refuse a payload that means exactly the same
    thing.

    Resolving *before* the write is what keeps `object_type_versions` (db 0028)
    honest - a snapshot has to record what the type was, and "whatever the
    shared property says today" is not a record of anything.

    **Attaching adopts; editing an attached property refuses.** p.187 and p.188
    are two different moments and this is the line between them. Choosing a
    shared property *is* choosing its metadata, so a fresh attach takes the
    inherited fields whatever the request said about them - otherwise a client
    would have to read the shared property back and echo it just to point at
    it. Once attached, p.188 disables those fields, and a contradicting value
    is refused rather than discarded: silently dropping somebody's edit is the
    failure this repo keeps having to fix (§157, §160, §163).

    `already_attached` maps api_name to the shared property id the stored row
    carries, so "already attached to *this* shared property" is the question
    being asked - swapping one shared property for another is an attach.
    """
    ids = {
        UUID(str(p["shared_property_id"]))
        for p in properties
        if p.get("shared_property_id")
    }
    known = await shared_properties.by_id(conn, workspace_id, ids)
    for prop in properties:
        raw = prop.get("shared_property_id")
        if not raw:
            prop["shared_property_id"] = None
            continue
        shared = known.get(str(raw))
        if shared is None:
            raise shared_properties.SharedPropertyError(
                f"{prop['api_name']}: no shared property {raw} in this workspace"
            )
        if already_attached.get(str(prop["api_name"])) == str(raw):
            shared_properties.check_attachment(prop, shared)
        else:
            # A fresh attach still has to satisfy p.181's base type rule; only
            # the inherited-metadata refusal is what the moment excuses.
            shared_properties.check_base_type(prop, shared)
        prop.update(shared_properties.resolve(prop, shared))


async def _attached_shared_ids(
    conn: AsyncConnection, type_id: UUID
) -> dict[str, str]:
    """Which of the type's stored properties already point at which shared
    property, keyed by api_name - the one identifier that survives an edit
    (p.188, and 0028's note that property ids do not)."""
    rows = await fetch_all(
        conn,
        """
        SELECT api_name, shared_property_id FROM object_type_properties
         WHERE object_type_id = :tid AND shared_property_id IS NOT NULL
        """,
        {"tid": str(type_id)},
    )
    return {str(r["api_name"]): str(r["shared_property_id"]) for r in rows}


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
    # Nothing is stored yet, so every attachment here is a fresh one.
    await _apply_shared(conn, workspace_id, properties, already_attached={})
    for prop in properties:
        if prop.get("derivation") is not None:
            # Not a limitation so much as a consequence: a derived property
            # follows link types *from this object type*, and a link type can
            # only be created against types that already exist. At create time
            # there are none, so no chain named here could be a legal one.
            raise ValueError(
                f"{prop['api_name']}: add a derived property after the object "
                "type exists - its links have to exist first"
            )
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
                                                data_type, required, description, sort_order,
                                                visibility, value_format,
                                                conditional_format, edit_only,
                                                derivation, shared_property_id)
            VALUES (:tid, :api, :name, CAST(:dtype AS property_data_type),
                    :required, :descr, :sort, CAST(:vis AS property_visibility),
                    CAST(:vfmt AS jsonb), CAST(:cfmt AS jsonb), :editonly,
                    CAST(:deriv AS jsonb), :shared)
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
                "vis": str(prop.get("visibility") or "normal"),
                "vfmt": (
                    json.dumps(prop["value_format"])
                    if prop.get("value_format") is not None
                    else None
                ),
                "cfmt": (
                    json.dumps(prop["conditional_format"])
                    if prop.get("conditional_format") is not None
                    else None
                ),
                "editonly": bool(prop.get("edit_only", False)),
                "deriv": (
                    json.dumps(prop["derivation"])
                    if prop.get("derivation") is not None
                    else None
                ),
                # p.187: attaching is part of saving the object type, so the
                # reference is written with the rest of the property rather
                # than by a separate call somebody could forget to make.
                "shared": (
                    str(prop["shared_property_id"])
                    if prop.get("shared_property_id")
                    else None
                ),
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

    **Every configurable field of a property, because a restore is meant to be
    a restore.** For a long time this recorded six of them, and the five that
    were missing - `visibility`, `value_format`, `conditional_format`,
    `edit_only`, `derivation` - were each added by a later unit that did not
    notice the snapshot existed. The consequence was silent and one-directional:
    rolling back to any earlier version *erased* them, with no error and
    nothing in the history to say it had happened. Found while adding
    `shared_property_id` (§164), which would have been the sixth.

    The rule this file now follows: **a new column on `object_type_properties`
    is a new key here**, or a restore quietly deletes it. No general test can
    catch the omission - the failure is a missing key, and only a test that
    names the key can see it missing - which is why `test_version_restore.py`
    has one test per field.

    Versions written before this change still hold six keys, and restoring one
    still clears the other six. That is not fixable: the data was never
    captured. Recorded rather than papered over.
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
                               'sort_order', p.sort_order,
                               'visibility', p.visibility,
                               'value_format', p.value_format,
                               'conditional_format', p.conditional_format,
                               'edit_only', p.edit_only,
                               'derivation', p.derivation,
                               'shared_property_id', p.shared_property_id)
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

    # One row per property an action writes, which after migration 0044 is a
    # `modify_object` rule rather than a name in a jsonb column. Read here
    # rather than through `actions_service` to keep the impact report one
    # query - it already runs several, and this is the same question asked of
    # a different table.
    actions = await fetch_all(
        conn,
        """
        SELECT at.id, at.display_name, r.config->>'property' AS property
          FROM action_types at
          JOIN action_rules r ON r.action_type_id = at.id AND r.kind = 'modify_object'
         WHERE at.object_type_id = :tid
        """,
        {"tid": str(type_id)},
    )
    for action in actions:
        for prop in [action["property"]] if action["property"] else []:
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
    await _apply_shared(
        conn,
        workspace_id,
        properties,
        already_attached=await _attached_shared_ids(conn, type_id),
    )
    # The chain is checked against the ontology rather than against itself:
    # whether the links join up, and whether any hop can reach more than one
    # object, are facts only the workspace's link types can answer.
    links_by_id = {
        str(link["id"]): link for link in await list_link_types(conn, workspace_id)
    }
    for prop in properties:
        prop["derivation"] = derived_properties.parse(
            prop.get("derivation"),
            property_name=str(prop["api_name"]),
            link_types=links_by_id,
            object_type_id=str(type_id),
        )
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


async def _drop_deleted_shared_properties(
    conn: AsyncConnection,
    workspace_id: UUID,
    properties: list[dict[str, Any]],
) -> None:
    """Forget an attachment to a shared property that no longer exists.

    **The one reference a restore may drop rather than refuse**, and the
    asymmetry is deliberate. `object-link-types` p.185 already decided it -
    "all object types using this shared property will revert to regular
    properties" - so a version that recorded an attachment to a since-deleted
    one restores as a regular property. Refusing would let a delete elsewhere
    permanently block a rollback here, over a decision the delete had made.

    A **derivation** whose link types have gone is not treated this way; it is
    left to `update_type`'s refusal. Nothing documents what a derived property
    becomes when its chain stops joining up, and the honest answer is that the
    version cannot be restored: dropping it silently would put back something
    that is not the version, and keeping it would produce a column of blanks -
    the exact outcome `derived_properties.parse` exists to refuse.
    """
    ids = {
        UUID(str(p["shared_property_id"]))
        for p in properties
        if p.get("shared_property_id")
    }
    if not ids:
        return
    known = await shared_properties.by_id(conn, workspace_id, ids)
    for prop in properties:
        raw = prop.get("shared_property_id")
        if raw and str(raw) not in known:
            prop["shared_property_id"] = None


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
    properties = [dict(p) for p in properties]
    await _drop_deleted_shared_properties(conn, workspace_id, properties)

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
               lt.from_side_name, lt.to_side_name,
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
                # The name of the side you arrive at (Foundry p.192). Going
                # from -> to lands on the `to` side, so that is its name.
                # Falls back to the link's single name, which is what every
                # link type had before sides could be named separately.
                "side_name": link["to_side_name"] or link["display_name"],
            })
        if str(link["to_object_type_id"]) == str(type_id):
            out.append({
                **link,
                "direction": "inbound",
                "near_property": link["to_property"],
                "far_property": link["from_property"],
                "far_type_id": link["from_object_type_id"],
                "far_type_display_name": link["from_display_name"],
                "side_name": link["from_side_name"] or link["display_name"],
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
    from_side_name: str | None = None,
    to_side_name: str | None = None,
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
                                cardinality, created_by, from_property, to_property,
                                from_side_name, to_side_name)
        VALUES (:wid, :api, :name, :from, :to, CAST(:card AS link_cardinality), :by,
                :fprop, :tprop, :fside, :tside)
        RETURNING id, api_name, display_name, from_object_type_id,
                  to_object_type_id, cardinality, created_at,
                  from_property, to_property, from_side_name, to_side_name
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
            "fside": (from_side_name or "").strip() or None,
            "tside": (to_side_name or "").strip() or None,
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
    from_side_name: str | None = None,
    to_side_name: str | None = None,
) -> dict[str, Any]:
    """Map (or unmap) the properties a link joins on, and name its two sides.

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
            "UPDATE link_types SET from_property = :fprop, to_property = :tprop, "
            # COALESCE, so a caller that only means to change the join does not
            # blank the names by omitting them. Clearing a name is therefore not
            # expressible here, which is the right trade: an unnamed side falls
            # back to the link's own name, so nobody is stuck with a wrong one.
            "       from_side_name = COALESCE(:fside, from_side_name), "
            "       to_side_name = COALESCE(:tside, to_side_name) "
            "WHERE id = :lid AND workspace_id = :wid"
        ),
        {"fprop": from_property, "tprop": to_property,
         "fside": (from_side_name or "").strip() or None,
         "tside": (to_side_name or "").strip() or None,
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
    declared = await list_properties(conn, object_type_id)
    properties = {str(p["api_name"]) for p in declared}
    # p.113: an edit-only property is "not directly mapped to a column in the
    # backing dataset". Mapping one is refused rather than silently accepted,
    # because accepting it would make the flag a lie the sync then acts on -
    # `upsert_instances` preserves edit-only keys, so a mapped-and-edit-only
    # property would have its dataset value ignored on every sync with nothing
    # anywhere saying why. p.114 gives the intended flow: untoggle first.
    edit_only = {str(p["api_name"]) for p in declared if p.get("edit_only")}

    if primary_key_column not in dataset_columns:
        raise ValueError(f"primary key column {primary_key_column!r} is not in the dataset")
    if not column_mappings:
        raise ValueError("map at least one column to a property")
    for column, prop in column_mappings.items():
        if column not in dataset_columns:
            raise ValueError(f"column {column!r} is not in the dataset")
        if prop not in properties:
            raise ValueError(f"property {prop!r} is not defined on the object type")
        if prop in edit_only:
            raise ValueError(
                f"property {prop!r} is edit-only, so it has no column; turn "
                "off edit-only first to map it"
            )

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
