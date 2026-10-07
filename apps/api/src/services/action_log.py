"""The action log: every submission of an action type, as an object (§554;
db 0116; `action-types` p.167-168).

    "The action log models all action submissions as object types to be
     analyzed and displayed in object-aware Foundry tooling." (p.167)

    "Action log object types map one-to-one with action types. Submitting an
     action generates a single new object of the corresponding action log
     object type. This newly-created object is automatically linked to all
     edited objects." (p.167)

**Built from the platform's own parts**, which is p.167's point: a `[LOG]`
object type over a dataset, mapped by an ordinary source, and linked to the
action's object type through §552's join table. Once a submission is an object
it can be filtered, charted and linked like any other, and nothing that reads
objects has to know it is a log. Turning a log on makes those four things with
the same calls a person would; each submission then appends one row to the log
dataset and one pair per edited object to the join table, **in the action's
own commit** (decision 0008), so a submission and its log entry cannot
disagree.

p.168's schema, and what is not here:

    Action RID, Action type RID, Action type version, Timestamp, UserId,
    Edited objects (primary keys), [Optional] Parameter values

are all stored, and so, as of §586, are p.168's two other optional ones:

    [Optional] Summary: A customizable string to describe the action
    [Optional] Property values of object reference parameters (this is not
    supported for object reference parameters if allow multiple values is
    enabled)

The summary is a template in p.92's triple handlebars, the notification's own
language, so `{{{alert.priority}}}` means the same in a log as in an inbox. It
is rendered, and the properties are read, from the objects **as they were
before the action's edits**: p.167's "state of the world (as represented by the
Ontology) at the time of action submission". The summary column is always
made, so its template can be written or changed later; the properties are
chosen when the log is turned on, since each is a column.

A parameter added after the log was turned on gets its column when the
action's definition is saved (§792, `extend`): a property on the `[LOG]` type,
a column in its dataset and the mapping between them, so the next submission
stores its value and the entries before it read as empty.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_one
from ..lib.errors import ConflictError
from . import datasets as ds_service
from .storage import StorageGateway

#: The key column: p.168's "Action RID: Unique identifier for a single action
#: submission" - the run's id.
KEY_COLUMN = "action_rid"

#: p.168's default schema besides the key, as (property, data type, column type).
SCHEMA = (
    ("action_type_rid", "string", "VARCHAR"),
    ("action_type_version", "integer", "BIGINT"),
    ("timestamp", "timestamp", "TIMESTAMP"),
    ("user_id", "string", "VARCHAR"),
    # p.168: "Primary key values of all objects edited by the action." A JSON
    # list: a submission can edit objects of several types, and only the
    # action's own type has a link to follow.
    ("edited_objects", "string", "VARCHAR"),
)

#: A parameter's value is stored under this prefix, so a parameter called
#: `timestamp` cannot collide with p.168's own column.
PARAMETER_PREFIX = "param_"

#: p.168's "[Optional] Summary" (§586), rendered from the log's template.
SUMMARY_COLUMN = "summary"
#: A summary is text a person reads in a list, so it is kept to a line or two
#: rather than refused: p.95's truncation rule for a notification's subject.
MAX_SUMMARY = 1000
#: p.168's "[Optional] Property values of object reference parameters", one
#: column per (parameter, property), under this prefix and a double
#: underscore between the two names.
REFERENCE_PREFIX = "ref_"
#: More than this is a copy of the object rather than a record of a decision.
MAX_REFERENCES = 20


def reference_column(parameter: str, prop: str) -> str:
    return f"{REFERENCE_PREFIX}{parameter}__{prop}"


def check_summary(
    template: Any,
    *,
    parameters: list[dict[str, Any]],
    object_types: dict[str, str],
    properties_by_type: dict[str, dict[str, str]],
) -> str | None:
    """A summary template, refused when it names something the action does not
    have - the notification's check (p.92), for the same reason: a gap in a
    log entry is what a reader sees rather than what an author does."""
    from . import templates

    if template is None or str(template).strip() == "":
        return None
    if not isinstance(template, str):
        raise ValueError("an action log summary is text")
    if len(template) > MAX_SUMMARY:
        raise ValueError(f"an action log summary template is at most {MAX_SUMMARY} characters")
    names = {str(p["api_name"]) for p in parameters}
    for ref in templates.references(template):
        head, _, tail = ref.partition(".")
        if head == "current_user":
            continue
        if head not in names:
            raise ValueError(
                f"the summary references {ref!r}, which is neither a parameter of "
                "this action nor current_user"
            )
        declared = properties_by_type.get(str(object_types.get(head)))
        if tail and declared is not None and tail not in declared:
            raise ValueError(f"the summary references {ref!r}, and {head!r} has no {tail!r} property")
    return template


def check_references(
    raw: Any,
    *,
    parameters: list[dict[str, Any]],
    object_types: dict[str, str],
    properties_by_type: dict[str, dict[str, str]],
) -> dict[str, list[str]]:
    """`{object parameter: [property]}` whose values the log keeps, refused by
    name when it could not be kept. p.168: "not supported for object reference
    parameters if allow multiple values is enabled" - so a list of objects is
    refused, as is a parameter that is not an object or whose type is unknown."""
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("reference properties are {object parameter: [property]}")
    kinds = {str(p["api_name"]): str(p.get("data_type")) for p in parameters}
    out: dict[str, list[str]] = {}
    columns: set[str] = set()
    for name, props in raw.items():
        if name not in kinds:
            raise ValueError(f"{name!r} is not a parameter of this action")
        if kinds[name] != "object":
            raise ValueError(
                f"{name!r} is not a single object reference; p.168 keeps properties "
                "of those only, and not of a parameter that allows multiple values"
            )
        declared = properties_by_type.get(str(object_types.get(name)))
        if declared is None:
            raise ValueError(f"{name!r} does not say which object type it holds")
        if not isinstance(props, list) or not props:
            raise ValueError(f"name at least one property of {name!r} to keep")
        kept: list[str] = []
        for prop in props:
            prop = str(prop)
            if prop not in declared:
                raise ValueError(f"{name!r} has no {prop!r} property")
            column = reference_column(name, prop)
            if column in columns:
                continue
            columns.add(column)
            kept.append(prop)
        out[name] = kept
    if len(columns) > MAX_REFERENCES:
        raise ValueError(f"an action log keeps at most {MAX_REFERENCES} reference properties")
    return out


def extra_columns(
    *,
    summary: str | None,
    references: dict[str, list[str]],
    values: dict[str, Any],
    objects: dict[str, dict[str, Any]],
    actor: dict[str, Any] | None,
) -> dict[str, Any]:
    """The summary and the reference properties for one submission, from the
    objects as they were before its edits (p.167)."""
    from .notifications import render, truncate

    out: dict[str, Any] = {
        SUMMARY_COLUMN: truncate(
            render(summary, values=values, objects=objects, actor=actor), MAX_SUMMARY
        ) if summary else None,
    }
    for name, props in references.items():
        held = objects.get(name) or {}
        for prop in props:
            out[reference_column(name, prop)] = _text(held.get(prop))
    return out


#: The join table's two columns: the log object's key and an edited object's.
EDITS_COLUMNS = (("action_rid", "VARCHAR"), ("object", "VARCHAR"))


def logged_parameters(parameters: list[dict[str, Any]]) -> list[str]:
    """The parameters whose values the log stores: every one except an object
    reference, whose value is an instance id (p.168's "property values of
    object reference parameters" is ○ here)."""
    return [str(p["api_name"]) for p in parameters if p.get("data_type") != "object"]


def _text(value: Any) -> str | None:
    """A parameter's value as its column holds it: text, JSON for anything
    that is not already a string."""
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, default=str, sort_keys=True)


def log_row(
    *,
    run_id: UUID,
    action_type: dict[str, Any],
    user_id: UUID,
    at: datetime,
    edited: list[str],
    bound: dict[str, Any],
    columns: set[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One submission's row in the log dataset, keyed by column. A parameter
    with no column - added after the log was made - is left out rather than
    written to a column that is not there."""
    row: dict[str, Any] = {
        KEY_COLUMN: str(run_id),
        "action_type_rid": str(action_type["id"]),
        "action_type_version": int(action_type.get("version") or 1),
        "timestamp": at,
        "user_id": str(user_id),
        "edited_objects": json.dumps(edited),
    }
    for name, value in bound.items():
        column = PARAMETER_PREFIX + name
        if column in columns:
            row[column] = _text(value)
    # §586's summary and reference properties, each only where the log has
    # its column: a log made before §586 has neither.
    for column, value in (extra or {}).items():
        if column in columns:
            row[column] = value
    return row


def edited_objects(
    *, subject: tuple[Any, str] | None, others: list[tuple[Any, str]],
) -> list[tuple[str, str]]:
    """p.168's "Primary key values of all objects edited by the action", as
    (object type, key) in the order written, each once: the subject if the
    action wrote it, then every object it changed, created or deleted."""
    out: list[tuple[str, str]] = []
    for type_id, key in ([subject] if subject else []) + list(others):
        pair = (str(type_id), str(key))
        if pair not in out:
            out.append(pair)
    return out


def properties_of(row: dict[str, Any]) -> dict[str, Any]:
    """The same row as the log object's properties, for the index: everything
    but the key, with the timestamp in the form a stored instance holds."""
    return {
        column: value.isoformat() if isinstance(value, datetime) else value
        for column, value in row.items()
        if column != KEY_COLUMN
    }


async def _free_api_name(conn: AsyncConnection, workspace_id: UUID, table: str, wanted: str) -> str:
    wanted = wanted[:95]
    for n in range(1, 100):
        name = wanted if n == 1 else f"{wanted}_{n}"
        taken = await fetch_one(
            conn, f"SELECT 1 AS x FROM {table} WHERE workspace_id = :wid AND api_name = :api",
            {"wid": str(workspace_id), "api": name},
        )
        if taken is None:
            return name
    raise ValueError("no free api name for the action log")


async def _empty_dataset(
    conn: AsyncConnection, storage: StorageGateway, *, workspace_id: UUID, project_id: UUID,
    name: str, description: str, columns: list[tuple[str, str]], action_type_id: UUID,
    by: UUID,
) -> UUID:
    return await ds_service.create_empty(
        conn, storage, workspace_id=workspace_id, project_id=project_id, name=name,
        description=description, columns=columns, origin="action_log",
        produced_by_kind="action_log", produced_by_id=action_type_id, by=by,
    )


async def enable(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    action_type: dict[str, Any],
    by: UUID,
    summary: str | None = None,
    references: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Turn an action type's log on: its dataset and `[LOG]` object type, the
    source between them, and the link to the objects it edits.

    With p.168's optional Summary template and the properties of object
    reference parameters to keep (§586), both checked here against the action
    before anything is made.

    p.167: "all action log object types are prefaced with [LOG]". The link is
    to the action's own object type - p.167's "automatically linked to all
    edited objects" - through a join table, because one submission edits many
    objects and one object is edited by many submissions.
    """
    from . import ontology as ontology_service

    if action_type.get("log_object_type_id"):
        raise ConflictError("this action type already has an action log")
    subject_type = action_type.get("object_type_id")
    if subject_type is None:
        # An interface action's objects are of whichever types implement it,
        # so there is no one type for the log to link to.
        raise ValueError("an action on an interface has no one object type for its log to link to")
    from . import actions as actions_service

    declared = list(action_type.get("parameters") or [])
    object_types = actions_service.object_parameter_types(
        list(action_type.get("rules") or []), default_object_type_id=subject_type,
        parameters=declared,
    )
    properties_by_type = await actions_service.properties_by_type(conn, workspace_id)
    summary = check_summary(
        summary, parameters=declared, object_types=object_types,
        properties_by_type=properties_by_type,
    )
    references = check_references(
        references, parameters=declared, object_types=object_types,
        properties_by_type=properties_by_type,
    )
    display = str(action_type["display_name"])
    parameters = logged_parameters(declared)
    kept = [reference_column(name, prop) for name, props in references.items() for prop in props]
    columns = [(KEY_COLUMN, "VARCHAR"), *((c, kind) for c, _t, kind in SCHEMA),
               *((PARAMETER_PREFIX + p, "VARCHAR") for p in parameters),
               (SUMMARY_COLUMN, "VARCHAR"), *((c, "VARCHAR") for c in kept)]
    log_dataset = await _empty_dataset(
        conn, storage, workspace_id=workspace_id, project_id=project_id,
        name=f"[LOG] {display}", description=f"Every submission of the action {display}",
        columns=columns, action_type_id=UUID(str(action_type["id"])), by=by,
    )
    properties = [
        {"api_name": c, "display_name": c.replace("_", " ").capitalize(), "data_type": t}
        for c, t, _k in SCHEMA
    ] + [
        {"api_name": PARAMETER_PREFIX + p, "display_name": p, "data_type": "string"}
        for p in parameters
    ] + [
        {"api_name": SUMMARY_COLUMN, "display_name": "Summary", "data_type": "string"},
    ] + [
        {"api_name": reference_column(name, prop), "display_name": f"{name} {prop}",
         "data_type": "string"}
        for name, props in references.items() for prop in props
    ]
    log_type = await ontology_service.create_type(
        conn, workspace_id=workspace_id,
        api_name=await _free_api_name(
            conn, workspace_id, "object_types", f"log_{action_type['api_name']}"),
        display_name=f"[LOG] {display}",
        description=f"Every submission of the action {display} (action-types p.167).",
        icon="cube", colour="#6b7280", properties=properties,
        title_property="timestamp", created_by=by,
    )
    await ontology_service.create_source(
        conn, workspace_id=workspace_id, project_id=project_id,
        object_type_id=UUID(str(log_type["id"])), dataset_id=log_dataset,
        primary_key_column=KEY_COLUMN,
        column_mappings={p["api_name"]: p["api_name"] for p in properties},
        created_by=by,
    )
    edits_dataset = await _empty_dataset(
        conn, storage, workspace_id=workspace_id, project_id=project_id,
        name=f"[LOG] {display} edits",
        description=f"Which objects each submission of {display} edited",
        columns=list(EDITS_COLUMNS), action_type_id=UUID(str(action_type["id"])), by=by,
    )
    link = await ontology_service.create_link_type(
        conn, workspace_id=workspace_id,
        api_name=await _free_api_name(
            conn, workspace_id, "link_types", f"log_{action_type['api_name']}_edited"),
        display_name=f"[LOG] {display} edited",
        from_type_id=UUID(str(log_type["id"])), to_type_id=UUID(str(subject_type)),
        cardinality="many_to_many", created_by=by,
        from_side_name="Edited objects", to_side_name=f"[LOG] {display}",
        join_dataset_id=edits_dataset, join_from_column="action_rid",
        join_to_column="object",
    )
    await conn.execute(text("""
        UPDATE action_types SET log_object_type_id = :tid, log_link_type_id = :lid,
               log_summary = :summary,
               log_reference_properties = CAST(:refs AS jsonb)
         WHERE id = :aid
    """), {"tid": str(log_type["id"]), "lid": str(link["id"]), "aid": str(action_type["id"]),
           "summary": summary, "refs": json.dumps(references)})
    return {"log_object_type_id": log_type["id"], "log_link_type_id": link["id"],
            "log_summary": summary, "log_reference_properties": references}


async def extend(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    workspace_id: UUID,
    action_type: dict[str, Any],
    by: UUID,
) -> list[str]:
    """Give the log a column for each parameter it has none for (§792): p.168's
    "[Optional] Parameter values" for a parameter added after the log was
    turned on. The `[LOG]` type gains the property, its dataset the column (a
    new version, every earlier entry empty in it) and its source the mapping.
    Returns the columns added; none when the action has no log, or every
    parameter already has one."""
    import os
    import tempfile

    from anyio import to_thread

    from . import dataset_engine
    from . import ontology as ontology_service

    log_type_id = action_type.get("log_object_type_id")
    if not log_type_id:
        return []
    source = await fetch_one(conn, """
        SELECT s.id, s.dataset_id, s.column_mappings, d.s3_location
          FROM object_type_sources s JOIN datasets d ON d.id = s.dataset_id
         WHERE s.object_type_id = :tid
         ORDER BY s.created_at LIMIT 1
    """, {"tid": str(log_type_id)})
    if source is None:
        return []
    mappings = source["column_mappings"]
    if isinstance(mappings, str):
        mappings = json.loads(mappings)
    mapped = set(mappings.values())
    names = [p for p in logged_parameters(list(action_type.get("parameters") or []))
             if PARAMETER_PREFIX + p not in mapped]
    if not names:
        return []
    columns = [PARAMETER_PREFIX + p for p in names]
    path = await to_thread.run_sync(storage.local_path, str(source["s3_location"]))
    with tempfile.TemporaryDirectory() as tmp:
        dest = os.path.join(tmp, "out.parquet")
        schema, rows = await to_thread.run_sync(
            dataset_engine.add_columns, path, columns, dest)
        await ds_service.add_version(
            conn, storage, dataset_id=UUID(str(source["dataset_id"])), workspace_id=workspace_id,
            parquet_path=dest, schema=schema, row_count=rows, produced_by_kind="action_log",
            produced_by_id=UUID(str(action_type["id"])), created_by=by,
            transaction_type="SNAPSHOT",
        )
    # The property, after the log's own: a plain text one, as `enable` makes
    # each parameter's. The `[LOG]` type is the log's, so it is written here
    # rather than through a whole-definition edit of somebody's type.
    await ontology_service.get_type(conn, workspace_id, UUID(str(log_type_id)))
    for p in names:
        await conn.execute(text("""
            INSERT INTO object_type_properties
                   (object_type_id, api_name, display_name, data_type, required,
                    description, sort_order)
            VALUES (:tid, :api, :name, 'string', false, '',
                    (SELECT coalesce(max(sort_order), -1) + 1 FROM object_type_properties
                      WHERE object_type_id = :tid))
        """), {"tid": str(log_type_id), "api": PARAMETER_PREFIX + p, "name": p})
    await conn.execute(text(
        "UPDATE object_type_sources SET column_mappings = CAST(:m AS jsonb) WHERE id = :sid"),
        {"m": json.dumps({**mappings, **{c: c for c in columns}}), "sid": str(source["id"])})
    return columns


async def set_summary(
    conn: AsyncConnection, *, workspace_id: UUID, action_type: dict[str, Any],
    summary: str | None,
) -> str | None:
    """Write or change the log's Summary template (p.168's "customizable
    string", §586). Every log has the column, so this changes only what later
    submissions write; an entry already made keeps the summary it was given."""
    from . import actions as actions_service

    if not action_type.get("log_object_type_id"):
        raise ValueError("this action type has no action log to summarise")
    declared = list(action_type.get("parameters") or [])
    summary = check_summary(
        summary, parameters=declared,
        object_types=actions_service.object_parameter_types(
            list(action_type.get("rules") or []),
            default_object_type_id=action_type.get("object_type_id"), parameters=declared,
        ),
        properties_by_type=await actions_service.properties_by_type(conn, workspace_id),
    )
    await conn.execute(text("UPDATE action_types SET log_summary = :s WHERE id = :aid"),
                       {"s": summary, "aid": str(action_type["id"])})
    return summary
