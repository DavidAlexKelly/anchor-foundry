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

are all stored. p.168's optional Summary and the property values of object
reference parameters are not, and nor is a parameter added after the log was
turned on - the dataset's columns are fixed when it is made, and a column the
source does not map would be a value written nowhere.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import duckdb
from anyio import to_thread
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_one
from ..lib.errors import ConflictError
from . import datasets as ds_service
from .dataset_engine import ColumnSchema
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


def _empty_parquet(columns: list[tuple[str, str]], dest: str) -> None:
    con = duckdb.connect()
    try:
        definition = ", ".join(f'"{name}" {kind}' for name, kind in columns)
        con.execute(f"CREATE TABLE t ({definition})")
        con.execute(f"COPY t TO '{dest}' (FORMAT parquet)")
    finally:
        con.close()


async def _free_name(conn: AsyncConnection, project_id: UUID, wanted: str) -> str:
    for n in range(1, 100):
        name = wanted if n == 1 else f"{wanted} {n}"
        taken = await fetch_one(
            conn, "SELECT 1 AS x FROM datasets WHERE project_id = :pid AND slug = :s",
            {"pid": str(project_id), "s": ds_service.slugify(name)},
        )
        if taken is None:
            return name
    raise ValueError("no free name for the action log's dataset")


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
    """A dataset with these columns and no rows, at version 1 - what a source
    can map before the first submission has happened."""
    def build() -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "data.parquet")
            _empty_parquet(columns, dest)
            with open(dest, "rb") as handle:
                return handle.read()

    parquet = await to_thread.run_sync(build)
    dataset_id = uuid4()
    name = await _free_name(conn, project_id, name)
    prefix = await ds_service.workspace_s3_prefix(conn, workspace_id)
    await conn.execute(text("""
        INSERT INTO datasets (id, project_id, workspace_id, name, slug, description, origin,
                              s3_location, current_version, created_by)
        VALUES (:id, :pid, :wid, :name, :slug, :descr, 'action_log', :loc, 0, :by)
    """), {"id": str(dataset_id), "pid": str(project_id), "wid": str(workspace_id),
           "name": name, "slug": ds_service.slugify(name), "descr": description,
           "loc": ds_service.storage_prefix(prefix, dataset_id), "by": str(by)})
    await ds_service.add_version(
        conn, storage, dataset_id=dataset_id, workspace_id=workspace_id,
        parquet_bytes=parquet, schema=[ColumnSchema(name=n, data_type=t) for n, t in columns],
        row_count=0, produced_by_kind="action_log", produced_by_id=action_type_id,
        created_by=by,
    )
    return dataset_id


async def enable(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    action_type: dict[str, Any],
    by: UUID,
) -> dict[str, Any]:
    """Turn an action type's log on: its dataset and `[LOG]` object type, the
    source between them, and the link to the objects it edits.

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
    display = str(action_type["display_name"])
    parameters = logged_parameters(list(action_type.get("parameters") or []))
    columns = [(KEY_COLUMN, "VARCHAR"), *((c, kind) for c, _t, kind in SCHEMA),
               *((PARAMETER_PREFIX + p, "VARCHAR") for p in parameters)]
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
        UPDATE action_types SET log_object_type_id = :tid, log_link_type_id = :lid
         WHERE id = :aid
    """), {"tid": str(log_type["id"]), "lid": str(link["id"]), "aid": str(action_type["id"])})
    return {"log_object_type_id": log_type["id"], "log_link_type_id": link["id"]}
