"""How a dataset's current version was made (§506; `dataset-preview` p.3).

    "About: Information including the time the dataset was created and
     updated, the users who created and last updated the dataset, the size of
     the table, any tools and input datasets used to create the data, tags,
     and more." (p.3)

"Tools and input datasets" was ◑, answered only by the Lineage tab. Every
version already records what produced it (`produced_by_kind` and
`produced_by_id`), and this turns that into names a reader can follow. The
**tool** is the transform, connection or action that wrote the version, and
the **inputs** are the datasets it read.

For a transform, the inputs are the ones **the run that wrote this version**
read (db 0024's model version), not the transform's inputs today. When no
recorded run wrote it, the transform's current inputs stand in, and the
answer says so.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError


async def _datasets(conn: AsyncConnection, ids: list[str]) -> list[dict[str, Any]]:
    """Datasets by id, named and linkable, in name order. A dataset deleted
    since, or one the reader cannot see, is left out rather than guessed at."""
    return await fetch_all(conn, """
        SELECT name, resource_id FROM datasets WHERE id = ANY(CAST(:ids AS uuid[]))
         ORDER BY name
    """, {"ids": ids})


async def current_origin(conn: AsyncConnection, dataset_id: UUID) -> dict[str, Any]:
    version = await fetch_one(conn, """
        SELECT v.id, v.version_number, v.produced_by_kind AS kind, v.produced_by_id AS pid,
               v.created_at, d.original_filename, d.forked_from_version
          FROM datasets d
          JOIN dataset_versions v ON v.dataset_id = d.id AND v.version_number = d.current_version
         WHERE d.id = :id
    """, {"id": dataset_id})
    if version is None:
        raise NotFoundError("dataset")
    kind = version["kind"] or "upload"
    pid = str(version["pid"]) if version["pid"] else None
    tool: dict[str, Any] | None = None
    inputs: list[dict[str, Any]] = []
    note: str | None = None

    # A NULL producer finds nothing, which is the answer "gone" gives - except
    # for a transform, whose fallback would name today's inputs, and a fork,
    # whose note would name a version that is not there.
    if kind == "model" and pid:
        model = await fetch_one(conn, "SELECT name, resource_id FROM models WHERE id = :id",
                                {"id": pid})
        if model is not None:
            tool = {"kind": "transform", "name": model["name"], "resource_id": model["resource_id"]}
        run_inputs = await fetch_one(conn, """
            SELECT mv.inputs FROM model_runs r JOIN model_versions mv ON mv.id = r.model_version
             WHERE r.output_version = :vid
        """, {"vid": version["id"]})
        if run_inputs is not None:
            ids = [str(i["dataset_id"]) for i in run_inputs["inputs"]]
        else:
            note = "the inputs are the transform's today; no recorded run wrote this version"
            ids = [str(r["dataset_id"]) for r in await fetch_all(
                conn, "SELECT dataset_id FROM model_inputs WHERE model_id = :id", {"id": pid})]
        inputs = await _datasets(conn, ids)
    elif kind == "sync":
        found = await fetch_one(conn, "SELECT name, resource_id FROM connections WHERE id = :id",
                                {"id": pid})
        if found is not None:
            tool = {"kind": "sync", "name": found["name"], "resource_id": found["resource_id"]}
    elif kind in ("action", "action_batch"):
        column = "batch_id" if kind == "action_batch" else "id"
        found = await fetch_one(conn, f"""
            SELECT t.display_name FROM action_runs r JOIN action_types t ON t.id = r.action_type_id
             WHERE r.{column} = :id LIMIT 1
        """, {"id": pid})
        if found is not None:
            tool = {"kind": "action", "name": found["display_name"], "resource_id": None}
    elif kind == "fork" and pid:
        inputs = await _datasets(conn, [pid])
        note = f"branched from version {version['forked_from_version']}"
    elif kind == "rollback":
        source = await fetch_one(conn, "SELECT version_number FROM dataset_versions WHERE id = :id",
                                 {"id": pid})
        note = f"rolled back to version {source['version_number']}" if source else "rolled back"
    elif kind in ("upload", "reparse"):
        filename = version["original_filename"]
        verb = "re-parsed from" if kind == "reparse" else "uploaded as"
        note = f"{verb} {filename}" if filename else None

    return {
        "version_number": version["version_number"],
        "kind": kind,
        "made_at": version["created_at"],
        "tool": tool,
        "inputs": inputs,
        "note": note,
    }
