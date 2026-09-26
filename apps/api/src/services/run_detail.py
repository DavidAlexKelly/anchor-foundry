"""One job's detail: progress, specification, files and resulting schema
(§507; `dataset-preview` p.3).

    "Upon selection, a detailed Job view appears on the right showing
     detailed job information, including progress, specification, build
     logs, files and the resulting schema." (p.3)

The build log is §358's (`models.run_log`). The rest is here, and every part
of it is **the run's**, not the model's today:

- **progress** is the run's own three timestamps, as how long it waited and
  how long it ran;
- **specification** is the model version the run executed (db 0024), so a
  model edited since still shows the code this run ran. A run from before
  db 0024 has no version, and says so with null rather than borrowing
  today's;
- **output** is the dataset version the run wrote: its files, row count and
  schema. A run that wrote nothing has none.
"""
from __future__ import annotations

import posixpath
from typing import Any
from uuid import UUID

from anyio import to_thread
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from .storage import StorageGateway


def _ms(start: Any, end: Any) -> int | None:
    """Milliseconds between two timestamps, or None while one is missing."""
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() * 1000)


async def detail(
    conn: AsyncConnection, storage: StorageGateway, *, model_id: UUID, run_id: UUID,
) -> dict[str, Any]:
    run = await fetch_one(conn, """
        SELECT r.status, r.queued_at, r.started_at, r.finished_at, r.output_version,
               mv.version_number, mv.code, mv.inputs, m.language
          FROM model_runs r
          JOIN models m ON m.id = r.model_id
          LEFT JOIN model_versions mv ON mv.id = r.model_version
         WHERE r.id = :rid AND r.model_id = :mid
    """, {"rid": str(run_id), "mid": str(model_id)})
    # Checked against the model it was reached through, as `run_log` is: a
    # run id is unique across every project.
    if run is None:
        raise NotFoundError("model run")

    progress = {
        "status": str(run["status"]),
        "queued_at": run["queued_at"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "waited_ms": _ms(run["queued_at"], run["started_at"]),
        "ran_ms": _ms(run["started_at"], run["finished_at"]),
    }

    specification = None
    if run["version_number"] is not None:
        declared = run["inputs"]
        names = {str(r["id"]): r["name"] for r in await fetch_all(conn, """
            SELECT id, name FROM datasets WHERE id = ANY(CAST(:ids AS uuid[]))
        """, {"ids": [str(i["dataset_id"]) for i in declared]})}
        specification = {
            "version_number": run["version_number"],
            "language": str(run["language"]),
            "code": run["code"],
            # A deleted input keeps its alias and its id; only its name is
            # gone, and a guessed one would be worse than none.
            "inputs": [{"alias": i["input_alias"], "dataset_id": str(i["dataset_id"]),
                        "dataset_name": names.get(str(i["dataset_id"]))} for i in declared],
        }

    output = None
    if run["output_version"] is not None:
        version = await fetch_one(conn, """
            SELECT version_number, s3_manifest_key, table_schema, row_count
              FROM dataset_versions WHERE id = :vid
        """, {"vid": str(run["output_version"])})
        key = str(version["s3_manifest_key"])
        output = {
            "version_number": version["version_number"],
            "row_count": version["row_count"],
            "schema": version["table_schema"],
            # The file's name, not its key: the key is an internal path. A
            # file gone from storage keeps its name and loses its size.
            "files": [{"name": posixpath.basename(key),
                       "size_bytes": await to_thread.run_sync(storage.size, key)}],
        }

    return {"progress": progress, "specification": specification, "output": output}
