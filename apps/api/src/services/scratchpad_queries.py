"""The Scratchpad's history and favourites (§306; db 0073; p.15).

    "To view queries marked as favorites, go to the [star] tab. To view a
     history of queries ran in the SQL helper, go to the [clock] tab." (p.15)

**Two tabs, one table** — the argument is in db 0073 and it is the design.
A favourite is a history entry somebody starred, so `listing` takes a filter
rather than there being two functions that would drift.

What lives here that the schema cannot: the **retention rule**. A history
that grows for ever is a table nobody prunes and a tab nobody can read.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError

#: How many un-starred queries a person keeps per repository.
#:
#: **Favourites are not counted and never evicted.** A star is the one signal
#: somebody has given that a query is worth keeping, and a cap that ignored it
#: would delete precisely the queries they asked to keep — which is worse than
#: no cap at all, because it would happen quietly and only to the people who
#: used the feature most.
#:
#: Fifty rather than a round ten: a scratchpad session is a dozen near-identical
#: attempts at one query, so a small cap would throw away this morning's work by
#: lunchtime. And rather than a thousand: this is a list somebody scrolls.
MAX_HISTORY = 50


async def record(
    conn: AsyncConnection, *, repo_id: UUID, author_id: UUID, sql: str
) -> dict[str, Any]:
    """Note that this query was run, and prune what fell off the end.

    **The same text is the same row** (db 0073's UNIQUE), so running a query
    twice moves it to the top of the history rather than adding a second entry.
    A history that repeats one query twenty times is a log, and what somebody
    opens this tab for is the query they wrote.

    `first_ran_at` is deliberately not touched on a re-run: "I wrote this on
    Tuesday and I am still running it" is a different fact from when it last
    ran, and the second overwriting the first would lose it.
    """
    row = await fetch_one(
        conn,
        """
        INSERT INTO scratchpad_queries (repo_id, author_id, sql)
        VALUES (:rid, :aid, :sql)
        ON CONFLICT (repo_id, author_id, sql) DO UPDATE
           SET run_count = scratchpad_queries.run_count + 1,
               last_ran_at = now()
        RETURNING id, repo_id, sql, favourite, run_count, first_ran_at, last_ran_at
        """,
        {"rid": str(repo_id), "aid": str(author_id), "sql": sql},
    )
    assert row is not None
    await _prune(conn, repo_id=repo_id, author_id=author_id)
    return dict(row)


async def _prune(conn: AsyncConnection, *, repo_id: UUID, author_id: UUID) -> None:
    """Drop the oldest un-starred queries past the cap.

    Done on write rather than on a schedule: there is no job that would run it,
    and a cap enforced only by a job that does not exist is not a cap. The cost
    is one small delete on the row that just went in, which is the moment the
    table is already being written to.
    """
    await conn.exec_driver_sql(
        """
        DELETE FROM scratchpad_queries
         WHERE id IN (
               SELECT id FROM scratchpad_queries
                WHERE repo_id = %s AND author_id = %s AND NOT favourite
                ORDER BY last_ran_at DESC
               OFFSET %s
         )
        """,
        (str(repo_id), str(author_id), MAX_HISTORY),
    )


async def listing(
    conn: AsyncConnection, *, repo_id: UUID, author_id: UUID, favourites_only: bool
) -> list[dict[str, Any]]:
    """p.15's two tabs, as one query with one filter.

    Most recently run first, in both. A history is read to find what you were
    just doing; a favourites list is short enough that the order matters less
    than it costing nothing to be consistent — and two orders would be two
    things to explain.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT id, repo_id, sql, favourite, run_count, first_ran_at, last_ran_at
          FROM scratchpad_queries
         WHERE repo_id = :rid
           AND author_id = :aid
           AND (NOT :only OR favourite)
         ORDER BY last_ran_at DESC
        """,
        {"rid": str(repo_id), "aid": str(author_id), "only": favourites_only},
    )
    return [dict(r) for r in rows]


async def set_favourite(
    conn: AsyncConnection,
    *,
    repo_id: UUID,
    author_id: UUID,
    query_id: UUID,
    favourite: bool,
) -> dict[str, Any]:
    """Star or unstar one query.

    `author_id` is in the WHERE clause as well as in db 0073's policy. Not
    belt-and-braces: the policy makes another author's row invisible, so this
    would return no row and raise `NotFoundError` either way — saying it here
    means the intent is legible to somebody reading the service without the
    schema open, and it is the sentence that stays true if the policy is ever
    relaxed for an admin.
    """
    row = await fetch_one(
        conn,
        """
        UPDATE scratchpad_queries
           SET favourite = :fav
         WHERE id = :id AND repo_id = :rid AND author_id = :aid
        RETURNING id, repo_id, sql, favourite, run_count, first_ran_at, last_ran_at
        """,
        {"id": str(query_id), "rid": str(repo_id), "aid": str(author_id),
         "fav": favourite},
    )
    if row is None:
        raise NotFoundError("this query")
    return dict(row)


async def remove(
    conn: AsyncConnection, *, repo_id: UUID, author_id: UUID, query_id: UUID
) -> None:
    """Forget a query.

    A scratchpad accumulates mistakes, and a history you cannot clear is one
    people stop opening.
    """
    row = await fetch_one(
        conn,
        """
        DELETE FROM scratchpad_queries
         WHERE id = :id AND repo_id = :rid AND author_id = :aid
        RETURNING id
        """,
        {"id": str(query_id), "rid": str(repo_id), "aid": str(author_id)},
    )
    if row is None:
        raise NotFoundError("this query")
