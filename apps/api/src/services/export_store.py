"""Exports and their history in the database (db 0069; decision 0014).

Separate from `services/exports.py`, which is what a configuration *means*: the
split every service pair here uses.

**`last_version` is the only mutable thing in this file, and it is the whole of
p.192's behaviour change.** An export that has written version 7 records 7, and
the next run comparing 7 against the dataset's current version is how "nothing
new to export" becomes a success rather than a rewrite. It moves only on a
successful write — a failed run leaves it alone, so a retry does the work the
failure did not.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: One page of an export's history. §256's number and its reason: a scheduled
#: export writes a row every run, so this list grows on a timer whether or not
#: anybody is looking at it.
PAGE = 50

_COLUMNS = """
    e.id, e.project_id, e.connection_id, e.dataset_id, e.name, e.kind,
    e.mode, e.destination, e.last_version, e.created_by, e.created_at,
    e.updated_at, e.schedule, e.next_run_at,
    c.name AS connection_name, c.source_type AS connection_source_type,
    c.exports_enabled,
    d.name AS dataset_name, d.current_version AS dataset_version
"""

_JOINS = """
      FROM exports e
      JOIN connections c ON c.id = e.connection_id
      JOIN datasets d ON d.id = e.dataset_id
"""


def _clean(row: dict[str, Any]) -> dict[str, Any]:
    """`destination` as a dict whichever way the driver returned it.

    A jsonb column comes back parsed from some drivers and as text from others,
    and `routes/connections.py` normalises at every call site for that reason.
    Done once here instead, because a caller that forgot would get
    `"{}".get("table")` — an AttributeError far from the cause.
    """
    out = dict(row)
    raw = out.get("destination")
    out["destination"] = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    return out


async def list_for_project(
    conn: AsyncConnection, project_id: UUID
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        f"SELECT {_COLUMNS} {_JOINS} WHERE e.project_id = :pid ORDER BY e.name",
        {"pid": str(project_id)},
    )
    return [_clean(row) for row in rows]


async def get(conn: AsyncConnection, project_id: UUID, export_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS} {_JOINS} WHERE e.id = :eid AND e.project_id = :pid",
        {"eid": str(export_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("export not found")
    return _clean(row)


async def connection_for(
    conn: AsyncConnection, project_id: UUID, connection_id: UUID
) -> dict[str, Any]:
    """The source an export may write to, or a refusal saying why not.

    Read through RLS rather than checked against a list, so a connection in
    another project is "does not exist" rather than "forbidden" — the answer
    db 0006 gives everywhere else, and the one that does not tell a caller what
    they cannot see. A workspace-scoped connection is usable from any project
    in its workspace, which is what that scope means.

    **Two refusals, and they are different questions.** Whether this *kind* of
    source can be a destination at all is `exports.DESTINATIONS`; whether this
    particular source has been *turned on* for exports is p.202's flag. The
    first is a fact about the connector, the second is somebody's decision, and
    collapsing them would make "your admin has not enabled this" read as "this
    is not supported".
    """
    row = await fetch_one(
        conn,
        """
        SELECT c.id, c.name, c.source_type, c.config, c.secret_arn, c.scope,
               c.workspace_id, c.project_id, c.exports_enabled
          FROM connections c
         WHERE c.id = :cid
           AND (c.scope = 'workspace' OR c.project_id = :pid)
        """,
        {"cid": str(connection_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("connection")
    if not row["exports_enabled"]:
        # p.202: "you must enable exports in the Connection settings section of
        # the source to which you are exporting". Named as the deliberate,
        # reversible thing it is - and who may reverse it, because the person
        # reading this generally cannot.
        raise ConflictError(
            f"exports are not enabled for {row['name']!r} (p.202) - a workspace "
            "admin can turn them on for this source"
        )
    return row


async def create(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    connection_id: UUID,
    dataset_id: UUID,
    config: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM exports WHERE project_id = :pid AND name = :name",
        {"pid": str(project_id), "name": config["name"]},
    )
    if existing is not None:
        # db 0069's unique constraint refuses it too; this turns that into a
        # sentence rather than a 500 quoting a constraint name — the fix §259
        # had to make once and §263 again.
        raise ConflictError(f"this project already has an export called {config['name']}")

    row = await fetch_one(
        conn,
        """
        INSERT INTO exports (project_id, connection_id, dataset_id, name, kind,
                             mode, destination, created_by)
        VALUES (:pid, :cid, :did, :name, CAST(:kind AS export_kind),
                CAST(:mode AS export_mode), CAST(:dest AS jsonb), :by)
        RETURNING id
        """,
        {
            "pid": str(project_id), "cid": str(connection_id), "did": str(dataset_id),
            "name": config["name"], "kind": config["kind"], "mode": config["mode"],
            "dest": json.dumps(config["destination"]), "by": str(created_by),
        },
    )
    assert row is not None
    return await get(conn, project_id, UUID(str(row["id"])))


async def delete(conn: AsyncConnection, project_id: UUID, export_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM exports WHERE id = :eid AND project_id = :pid RETURNING id",
        {"eid": str(export_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("export not found")


async def set_schedule(
    conn: AsyncConnection,
    project_id: UUID,
    export_id: UUID,
    *,
    schedule: str | None,
    next_run_at: Any,
) -> dict[str, Any]:
    """Set or clear an export's cron (db 0070; decision 0016; p.205).

    **Both columns move together and one of them is derived**, which is why
    this is a single statement rather than two: a `schedule` with a stale
    `next_run_at` would fire at whatever the old cron said, and a cleared
    schedule leaving a timestamp behind would leave a row that reads as due to
    anyone querying it directly. `list_due_exports()` keys on `schedule IS NOT
    NULL`, so a leftover timestamp would not actually fire — which is exactly
    the sort of thing that stops being true when somebody writes the second
    query.
    """
    row = await fetch_one(
        conn,
        """UPDATE exports
              SET schedule = :cron, next_run_at = :next
            WHERE id = :eid AND project_id = :pid
        RETURNING id""",
        {
            "cron": schedule,
            "next": next_run_at,
            "eid": str(export_id),
            "pid": str(project_id),
        },
    )
    if row is None:
        raise NotFoundError("export not found")
    return await get(conn, project_id, export_id)


async def record(
    conn: AsyncConnection,
    *,
    export_id: UUID,
    result: dict[str, Any],
    run_by: UUID | None,
) -> dict[str, Any]:
    """One run, and — when it wrote — the version it got to.

    **Both writes in one call**, because they are one fact. A run row saying it
    exported version 7 beside an export still claiming it last wrote 6 would
    make the next run redo the work and the history disagree with itself; and
    the two statements are in the caller's transaction, so either both land or
    neither does.
    """
    row = await fetch_one(
        conn,
        """
        INSERT INTO export_runs (export_id, status, skipped, dataset_version,
                                 rows_written, error, finished_at, run_by)
        VALUES (:eid, :status, :skipped, :version, :rows, :error, now(), :by)
        RETURNING id, status, skipped, dataset_version, rows_written, error,
                  started_at, finished_at
        """,
        {
            "eid": str(export_id),
            "status": "succeeded" if result["ok"] else "failed",
            "skipped": bool(result.get("skipped")),
            "version": result.get("dataset_version"),
            "rows": int(result.get("rows_written") or 0),
            "error": result.get("error"),
            "by": str(run_by) if run_by else None,
        },
    )
    assert row is not None

    # **Only on a success.** A failed run must leave the mark where it was, or
    # the retry would skip the work that failed — which would be the worst
    # outcome available: a broken export that looks fixed.
    #
    # **`GREATEST` guards a race, not a mistake.** Each run reads the dataset's
    # current version before it starts and writes the mark after it finishes,
    # so two overlapping runs can finish out of order: the one that read v5
    # commits after the one that read v6, and a plain assignment would move the
    # mark back to 5. The next run would then re-export v6 to a `mirror`
    # destination that already had it.
    #
    # §265's harness cannot kill a mutant that removes this, and that is a fact
    # about the harness rather than about the line: every test here makes one
    # request at a time, so the interleaving simply does not occur. This is the
    # time-of-check/time-of-use exception to §213 — the ordering is not
    # guaranteed by another layer, it is guaranteed by this expression.
    #
    # It is also why there is no `not skipped` clause. There was one, and the
    # harness *could* kill nothing with it either — but for the opposite
    # reason: a skip happens only when `last_version >= dataset_version`, so
    # `GREATEST` already makes that case a no-op. A line that cannot fail
    # because something else covers it gets deleted (§264); a line that cannot
    # fail because the tests cannot interleave gets a comment.
    if result["ok"] and result.get("dataset_version"):
        await conn.execute(
            text(
                "UPDATE exports SET last_version = GREATEST(COALESCE(last_version, 0), :v)"
                " WHERE id = :eid"
            ),
            {"v": int(result["dataset_version"]), "eid": str(export_id)},
        )
    return dict(row)


async def runs(
    conn: AsyncConnection, export_id: UUID, *, limit: int = PAGE, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    total = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM export_runs WHERE export_id = :eid",
        {"eid": str(export_id)},
    )
    rows = await fetch_all(
        conn,
        """
        SELECT id, status, skipped, dataset_version, rows_written, error,
               started_at, finished_at, run_by
          FROM export_runs
         WHERE export_id = :eid
         ORDER BY started_at DESC
         LIMIT :limit OFFSET :offset
        """,
        {"eid": str(export_id), "limit": max(1, min(limit, PAGE)), "offset": max(0, offset)},
    )
    return rows, int(total["n"]) if total else 0


async def uses_connection(conn: AsyncConnection, connection_id: UUID) -> list[str]:
    """The exports pointing at this source, by name.

    db 0069's `ON DELETE RESTRICT` refuses the delete on its own; this is what
    turns it into a sentence naming them. §259 built the same thing for
    webhooks and the route already reads both.
    """
    rows = await fetch_all(
        conn,
        "SELECT name FROM exports WHERE connection_id = :cid ORDER BY name",
        {"cid": str(connection_id)},
    )
    return [str(row["name"]) for row in rows]
