"""Usage metrics per object type (§320; db 0077; `ontology-manager` p.32-34).

    "Reads: A read is recorded when an application loads objects for a
     specified object type… **one read represents one load request**… Many
     objects loaded or aggregated at once will only be recorded as a single
     read. Also note that any object type or link type usage happening in
     Ontology Manager is not included." (p.32)

    "Interactions: The total number of reads and writes on objects of this type
     over the last 30 days." (p.32)

    "Active users: The number of unique user IDs that triggered the reads and
     writes recorded over the last 30 days." (p.32)

**p.33 says what these are for**, and it decides what to build: "enabling
Ontology users to quickly understand the implications of making a breaking
change to this resource". Not analytics — a number somebody reads *before*
renaming a property. That is why the four figures live beside the type rather
than on a dashboard, and why `active_users` matters more than it looks: reads
tell you something is used, and thirty people using it is a different change
from one person using it thirty times.

**Counting is best-effort and never fails a request.** A read that returned the
objects and then raised because a metrics row could not be written would have
turned a working feature into an outage for a number nobody is waiting on. Each
recorder swallows its own errors and says so.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: p.32's window, in both the sentence and the query. Named because it appears
#: in four places and a 30 written four times is a 30 that becomes a 31 in one
#: of them.
WINDOW_DAYS = 30

#: The applications this platform has, as p.33's "in which Foundry
#: applications". Free text in the column (db 0077 says why), checked here so a
#: typo at a call site is a refusal rather than a row nobody can group.
APPLICATIONS = (
    "explorer",
    "object_view",
    "workshop",
    "action",
    "api",
)

#: **The one p.32 excludes by name**: "any object type or link type usage
#: happening in Ontology Manager is not included."
#:
#: Kept as a value rather than left out of `APPLICATIONS`, because the same
#: endpoints serve the Ontology Manager and the Object Explorer — so the
#: exclusion has to be a thing the recorder *recognises and drops*, not a
#: caller that happens never to call. A caller that omitted the label entirely
#: would be indistinguishable from one that forgot to pass it.
ONTOLOGY_MANAGER = "ontology_manager"


#: What a counter is kept for, and where (§620). db 0077 counted object types;
#: db 0129 is the same shape for link types, which p.32 names in the same
#: breath ("any object type or link type usage"), so one service answers both
#: and the two cannot come to count differently.
_TABLES = {
    "object_type": ("object_type_usage", "object_type_id"),
    "link_type": ("link_type_usage", "link_type_id"),
}


def _target(object_type_id: UUID | None, link_type_id: UUID | None) -> tuple[str, str, str]:
    """The table, its key column and the key, for exactly one of the two."""
    if (object_type_id is None) == (link_type_id is None):
        raise ValueError("usage is counted for one object type or one link type")
    kind, rid = (("object_type", object_type_id) if object_type_id is not None
                 else ("link_type", link_type_id))
    table, column = _TABLES[kind]
    return table, column, str(rid)


def counts(application: str) -> bool:
    """Whether usage from this application is included (p.32).

    An unknown application counts: a new screen that forgot to add itself to
    `APPLICATIONS` is a mislabelled row, and dropping its usage would make the
    numbers quietly wrong in the direction nobody checks. Only the Ontology
    Manager is excluded, because p.32 excludes it by name.
    """
    return application != ONTOLOGY_MANAGER


async def record(
    conn: AsyncConnection,
    *,
    object_type_id: UUID | None = None,
    link_type_id: UUID | None = None,
    user_id: UUID | None,
    application: str,
    reads: int = 0,
    writes: int = 0,
) -> bool:
    """Count one request. Returns whether anything was written.

    **One request, not one object** — p.32's rule: "Many objects loaded or
    aggregated at once will only be recorded as a single read." So `reads` is
    1 for a page of five hundred, and a caller passing `len(rows)` is making
    the number mean something else.

    Best-effort: a failure here is swallowed by the caller, because a metric is
    not worth failing a read for.
    """
    if not counts(application):
        return False
    if reads == 0 and writes == 0:
        return False
    table, column, rid = _target(object_type_id, link_type_id)
    uid = str(user_id) if user_id else None
    params: dict[str, Any] = {
        "tid": rid,
        "day": date.today(),
        "app": application[:50],
        "reads": reads,
        "writes": writes,
    }
    if uid is not None:
        params["uid"] = uid
    # **In a savepoint**, because the caller's `except` cannot undo what a
    # failed statement does to a transaction: PostgreSQL refuses everything
    # after it and rolls the whole request back. Without this, a counter row
    # the database refused (RLS refused hundreds in CI) took the request with
    # it - an action's edit included. Now a failure loses only the count.
    async with conn.begin_nested():
        await conn.execute(_upsert(table, column, anonymous=uid is None), params)
    return True


# **Two statements, because the table has two partial unique indexes.**
# `user_id` is nullable — a background job's read has no person behind it — so
# it cannot be part of a primary key, and db 0077 covers the two cases with two
# partial indexes instead. An `ON CONFLICT` target has to name one of them.
def _upsert(table: str, column: str, *, anonymous: bool) -> Any:
    """The counter's upsert, for one table and one of its two partial unique
    indexes (db 0077's reasons, which db 0129 copies). `table` and `column`
    come from `_TABLES` and nowhere else, so nothing a caller sends reaches
    the statement's text."""
    if anonymous:
        return text(f"""
            INSERT INTO {table} ({column}, user_id, day, application, reads, writes)
            VALUES (:tid, NULL, :day, :app, :reads, :writes)
            ON CONFLICT ({column}, day, application) WHERE user_id IS NULL
            DO UPDATE
               SET reads  = {table}.reads  + EXCLUDED.reads,
                   writes = {table}.writes + EXCLUDED.writes
        """)
    return text(f"""
        INSERT INTO {table} ({column}, user_id, day, application, reads, writes)
        VALUES (:tid, :uid, :day, :app, :reads, :writes)
        ON CONFLICT ({column}, user_id, day, application) WHERE user_id IS NOT NULL
        DO UPDATE
           SET reads  = {table}.reads  + EXCLUDED.reads,
               writes = {table}.writes + EXCLUDED.writes
    """)


async def summary(
    conn: AsyncConnection, object_type_id: UUID | None = None,
    *, link_type_id: UUID | None = None,
) -> dict[str, int]:
    """p.32's four numbers over p.32's window.

    **`interactions` is computed, not stored.** p.32 defines it as "the total
    number of reads and writes", so a stored total would be a third number free
    to disagree with the two it came from — §191's mirrored copies, in the
    shape where nothing can notice.
    """
    table, column, rid = _target(object_type_id, link_type_id)
    row = await fetch_one(
        conn,
        f"""
        SELECT COALESCE(sum(reads), 0)  AS reads,
               COALESCE(sum(writes), 0) AS writes,
               count(DISTINCT user_id)  AS active_users
          FROM {table}
         WHERE {column} = :tid AND day >= :since
        """,
        {"tid": rid, "since": date.today() - timedelta(days=WINDOW_DAYS)},
    )
    assert row is not None
    reads, writes = int(row["reads"]), int(row["writes"])
    return {
        "reads": reads,
        "writes": writes,
        "interactions": reads + writes,
        # `count(DISTINCT user_id)` does not count NULL, which is the right
        # answer rather than a convenient one: p.32 counts "unique user IDs",
        # and a service account has none.
        "active_users": int(row["active_users"]),
        "window_days": WINDOW_DAYS,
    }


async def by_application(
    conn: AsyncConnection, object_type_id: UUID | None = None,
    *, link_type_id: UUID | None = None,
) -> list[dict[str, Any]]:
    """p.33's "in which Foundry applications", over the same window.

    Ordered by how much each application did, because the question this answers
    is "who would notice if I changed this" and the biggest user is the answer.
    """
    table, column, rid = _target(object_type_id, link_type_id)
    rows = await fetch_all(
        conn,
        f"""
        SELECT application,
               COALESCE(sum(reads), 0)  AS reads,
               COALESCE(sum(writes), 0) AS writes,
               count(DISTINCT user_id)  AS active_users
          FROM {table}
         WHERE {column} = :tid AND day >= :since
         GROUP BY application
         ORDER BY sum(reads) + sum(writes) DESC, application
        """,
        {"tid": rid, "since": date.today() - timedelta(days=WINDOW_DAYS)},
    )
    return [
        {
            "application": r["application"],
            "reads": int(r["reads"]),
            "writes": int(r["writes"]),
            "interactions": int(r["reads"]) + int(r["writes"]),
            "active_users": int(r["active_users"]),
        }
        for r in rows
    ]


async def daily(
    conn: AsyncConnection, object_type_id: UUID
) -> list[dict[str, Any]]:
    """p.33's "when", as one row per day the type was used.

    **Days with no usage are absent rather than zero.** The caller drawing
    p.33's graph knows the window and can fill it; a query that manufactured
    thirty rows would be inventing data to make a chart easier, and every other
    reader would then have to know which rows were real.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT day,
               COALESCE(sum(reads), 0)  AS reads,
               COALESCE(sum(writes), 0) AS writes
          FROM object_type_usage
         WHERE object_type_id = :tid AND day >= :since
         GROUP BY day
         ORDER BY day
        """,
        {"tid": str(object_type_id), "since": date.today() - timedelta(days=WINDOW_DAYS)},
    )
    return [
        {
            "day": r["day"],
            "reads": int(r["reads"]),
            "writes": int(r["writes"]),
            "interactions": int(r["reads"]) + int(r["writes"]),
        }
        for r in rows
    ]
