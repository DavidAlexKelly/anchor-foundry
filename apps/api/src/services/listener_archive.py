"""A listener's events, archived into a backing dataset (§519; db 0108;
`data-connection` p.264).

    "Every few minutes, the listener event stream will archive into a backing
     dataset. This dataset can be used like any other dataset in the platform,
     allowing you to build data pipelines and back your ontology." (p.264)

**Here for "Archive now"; the worker's `jobs/listener_archives.py` does the
same every five minutes.** The block between the SHARED markers is the same
text in both files, and `test_listener_archive.py` holds it to that: the two
packages cannot import each other, and two archivers that disagreed about a
column would write two shapes into one dataset.

Each run appends the events after `archived_through`, at most ARCHIVE_EVENTS
of them and about ARCHIVE_BYTES, to a new version holding everything archived
so far. A listener with a steady stream catches up over several runs rather
than in one enormous version.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import timezone
from typing import Any
from uuid import UUID, uuid4

from anyio import to_thread
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from . import datasets as ds_service
from .dataset_engine import ColumnSchema
from .storage import StorageGateway

# ---- SHARED with apps/worker/src/anchor_worker/jobs/listener_archives.py ----
#: The dataset's columns. The body is text: a stream row is a string, and a
#: body that is not UTF-8 keeps its bytes as replacement characters rather
#: than failing the whole archive.
COLUMNS = (
    ("event_id", "BIGINT"),
    ("received_at", "TIMESTAMP"),
    ("content_type", "VARCHAR"),
    ("size_bytes", "INTEGER"),
    ("body", "VARCHAR"),
    ("headers", "JSON"),
)

#: One run's ceiling. p.264's "every few minutes" is the cadence; these keep a
#: backlog from becoming one version too big to write.
ARCHIVE_EVENTS = 5000
ARCHIVE_BYTES = 50_000_000

#: Events after `start`, oldest first, up to the ceiling. The first event is
#: always taken, however big, so one large event cannot stall the archive.
EVENTS_SQL = """
    SELECT id, received_at, content_type, size_bytes, body, headers FROM (
        SELECT id, received_at, content_type, size_bytes, body, headers,
               sum(size_bytes) OVER (ORDER BY id) AS running,
               row_number() OVER (ORDER BY id) AS n
          FROM listener_events WHERE listener_id = %(lid)s AND id > %(start)s
    ) ranked
     WHERE n <= %(max_events)s AND (running <= %(max_bytes)s OR n = 1)
     ORDER BY id
"""


def dataset_name(listener_name: str) -> str:
    return f"{listener_name} events"[:200]


def archive_file(previous: str | None, events: list[tuple], dest: str) -> tuple[list[tuple[str, str]], int]:
    """Write `previous`'s rows and these events to `dest` as Parquet; returns
    the schema as (name, type) pairs and the row count."""
    import duckdb

    con = duckdb.connect()
    try:
        con.execute("CREATE TABLE archive (" + ", ".join(f"{n} {t}" for n, t in COLUMNS) + ")")
        if previous is not None:
            con.execute("INSERT INTO archive SELECT * FROM read_parquet(?)", [previous])
        con.executemany(
            "INSERT INTO archive VALUES (?, ?, ?, ?, ?, ?)",
            [(event_id, received.astimezone(timezone.utc).replace(tzinfo=None), content_type,
              size, bytes(body).decode("utf-8", "replace"),
              headers if isinstance(headers, str) else json.dumps(headers))
             for event_id, received, content_type, size, body, headers in events])
        con.execute(f"COPY archive TO '{dest}' (FORMAT parquet)")
        schema = [(r[0], r[1]) for r in con.execute("DESCRIBE archive").fetchall()]
        rows = int(con.execute("SELECT count(*) FROM archive").fetchone()[0])
        return schema, rows
    finally:
        con.close()
# ---- end SHARED ---------------------------------------------------------------


def _sql(shared: str) -> str:
    """The shared query in SQLAlchemy's parameter style."""
    for name in ("lid", "start", "max_events", "max_bytes"):
        shared = shared.replace(f"%({name})s", f":{name}")
    return shared


async def _free_name(conn: AsyncConnection, project_id: UUID, wanted: str) -> str:
    """The dataset name, or the first "… 2", "… 3" whose slug is free: a
    project may already hold a dataset called what the archive would be."""
    for n in range(1, 100):
        name = wanted if n == 1 else f"{wanted} {n}"
        taken = await fetch_one(conn, "SELECT 1 AS x FROM datasets WHERE project_id = :pid AND slug = :s",
                                {"pid": str(project_id), "s": ds_service.slugify(name)})
        if taken is None:
            return name
    raise ValueError("no free name for the archive dataset")


async def archive(conn: AsyncConnection, storage: StorageGateway, listener_id: UUID, *,
                  by: UUID) -> dict[str, Any] | None:
    """One archive run. None when there was nothing new to archive.

    The caller has already found the listener in its project (the route's
    `listeners.get`); this locks it, so two runs cannot archive the same
    events twice."""
    listener = await fetch_one(conn, """
        SELECT l.id, l.project_id, l.workspace_id, l.display_name, l.archive_dataset_id,
               l.archived_through
          FROM listeners l WHERE l.id = :id
           FOR UPDATE OF l
    """, {"id": str(listener_id)})
    assert listener is not None
    project_id = listener["project_id"]
    dataset_id = listener["archive_dataset_id"]
    # A deleted dataset starts the archive over (db 0108).
    start = listener["archived_through"] if dataset_id else 0
    events = await fetch_all(conn, _sql(EVENTS_SQL), {
        "lid": str(listener_id), "start": start,
        "max_events": ARCHIVE_EVENTS, "max_bytes": ARCHIVE_BYTES})
    if not events:
        return None
    rows = [(e["id"], e["received_at"], e["content_type"], e["size_bytes"], e["body"], e["headers"])
            for e in events]

    previous = None
    if dataset_id:
        current = await fetch_one(conn, "SELECT s3_location FROM datasets WHERE id = :id",
                                  {"id": str(dataset_id)})
        previous = await to_thread.run_sync(storage.local_path, str(current["s3_location"]))

    def build() -> tuple[list[tuple[str, str]], int, bytes]:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "data.parquet")
            schema, count = archive_file(previous, rows, dest)
            with open(dest, "rb") as handle:
                return schema, count, handle.read()

    schema, count, parquet = await to_thread.run_sync(build)
    if dataset_id is None:
        dataset_id = uuid4()
        name = await _free_name(conn, project_id, dataset_name(listener["display_name"]))
        prefix = await ds_service.workspace_s3_prefix(conn, listener["workspace_id"])
        await conn.execute(text("""
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description, origin,
                                  s3_location, current_version, created_by)
            VALUES (:id, :pid, :wid, :name, :slug, :descr, 'listener', :loc, 0, :by)
        """), {"id": str(dataset_id), "pid": str(project_id), "wid": str(listener["workspace_id"]),
               "name": name, "slug": ds_service.slugify(name),
               "descr": f"Events received by the listener {listener['display_name']}",
               "loc": ds_service.storage_prefix(prefix, dataset_id), "by": str(by)})
    committed = await ds_service.add_version(
        conn, storage, dataset_id=dataset_id, workspace_id=listener["workspace_id"],
        parquet_bytes=parquet, schema=[ColumnSchema(name=n, data_type=t) for n, t in schema],
        row_count=count, produced_by_kind="listener", produced_by_id=listener_id, created_by=by,
        # An archive only ever adds the events since the last (§747).
        transaction_type="APPEND")
    await conn.execute(text("""
        UPDATE listeners SET archive_dataset_id = :did, archived_through = :through, archived_at = now()
         WHERE id = :id
    """), {"id": str(listener_id), "did": str(dataset_id), "through": rows[-1][0]})
    return {"dataset_id": dataset_id, "version": committed["current_version"],
            "archived": len(rows), "rows": count}

