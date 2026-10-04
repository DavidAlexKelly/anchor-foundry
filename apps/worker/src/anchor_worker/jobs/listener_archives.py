"""A listener's events, archived into a backing dataset every five minutes
(§519; db 0108; `data-connection` p.264).

    "Every few minutes, the listener event stream will archive into a backing
     dataset." (p.264)

The API's `services/listener_archive.py` does the same run for "Archive now".
**The block between the SHARED markers is the same text in both files**, and
`apps/api/tests/test_listener_archive.py` holds it to that: two archivers that
disagreed about a column would write two shapes into one dataset.

Discovery is `list_listeners_to_archive()` (db 0108), the SECURITY DEFINER
shape db 0014 set. Each listener is then archived through a connection
scoped to its workspace, in its own `try`, so one failure does not stop the
others.

Note: deliberately no `from __future__ import annotations` here - see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
import os
import tempfile
from datetime import timezone
from uuid import uuid4

from dagster import OpExecutionContext, job, op

from ..resources import PlatformDatabase
from ..storage import gateway_from_env, slugify, storage_prefix

# ---- SHARED with apps/api/src/services/listener_archive.py ----
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


def _free_name(cur, project_id, wanted: str) -> str:
    for n in range(1, 100):
        name = wanted if n == 1 else f"{wanted} {n}"
        cur.execute("SELECT 1 FROM datasets WHERE project_id = %s AND slug = %s",
                    (str(project_id), slugify(name)))
        if cur.fetchone() is None:
            return name
    raise ValueError("no free name for the archive dataset")


def archive_one(platform_db: PlatformDatabase, storage, listener_id, workspace_id) -> int:
    """One listener's run, in one transaction. Returns how many events it
    wrote."""
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT l.project_id, l.display_name, l.archive_dataset_id, l.archived_through,
                       w.s3_prefix
                  FROM listeners l JOIN workspaces w ON w.id = l.workspace_id
                 WHERE l.id = %s FOR UPDATE OF l
            """, (str(listener_id),))
            found = cur.fetchone()
            if found is None:
                return 0
            project_id, display_name, dataset_id, archived_through, ws_prefix = found
            start = archived_through if dataset_id else 0
            cur.execute(EVENTS_SQL, {"lid": str(listener_id), "start": start,
                                     "max_events": ARCHIVE_EVENTS, "max_bytes": ARCHIVE_BYTES})
            events = cur.fetchall()
            if not events:
                return 0
            previous = None
            version = 1
            if dataset_id:
                cur.execute("SELECT s3_location, current_version FROM datasets WHERE id = %s",
                            (str(dataset_id),))
                location, current = cur.fetchone()
                previous = storage.local_path(location)
                version = int(current) + 1
            with tempfile.TemporaryDirectory() as tmp:
                dest = os.path.join(tmp, "data.parquet")
                schema, count = archive_file(previous, events, dest)
                with open(dest, "rb") as handle:
                    parquet = handle.read()
            if dataset_id is None:
                dataset_id = uuid4()
                name = _free_name(cur, project_id, dataset_name(display_name))
                cur.execute("""
                    INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                                          origin, s3_location, current_version)
                    VALUES (%s, %s, %s, %s, %s, %s, 'listener', %s, 0)
                """, (str(dataset_id), str(project_id), str(workspace_id), name, slugify(name),
                      f"Events received by the listener {display_name}",
                      storage_prefix(ws_prefix, dataset_id)))
            key = f"{storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
            storage.put(key, parquet)
            schema_json = json.dumps([{"name": n, "data_type": t} for n, t in schema])
            cur.execute("""
                UPDATE datasets SET s3_location = %s, table_schema = %s, row_count = %s,
                                    current_version = %s
                 WHERE id = %s
            """, (key, schema_json, count, version, str(dataset_id)))
            cur.execute("""
                INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                              table_schema, row_count, produced_by_kind,
                                              produced_by_id, transaction_type)
                VALUES (%s, %s, %s, %s, %s, 'listener', %s, 'APPEND')
            """, (str(dataset_id), version, key, schema_json, count, str(listener_id)))
            cur.execute("""
                UPDATE listeners SET archive_dataset_id = %s, archived_through = %s,
                                     archived_at = now()
                 WHERE id = %s
            """, (str(dataset_id), events[-1][0], str(listener_id)))
        conn.commit()
    return len(events)


@op
def archive_listener_events(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    storage = gateway_from_env()
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT listener_id, workspace_id FROM list_listeners_to_archive()")
            candidates = cur.fetchall()
    archived = 0
    for listener_id, workspace_id in candidates:
        try:
            archived += archive_one(platform_db, storage, listener_id, workspace_id)
        except Exception as exc:  # noqa: BLE001 - one listener must not stop the rest
            context.log.error(f"listener {listener_id}: archive failed: {exc}")
    return archived


@job
def scheduled_listener_archives() -> None:
    archive_listener_events()
