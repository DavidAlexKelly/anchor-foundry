"""Asking for a repository's unit tests to be run, and reading what happened
(§294; db 0071; `code-repositories.md` §8, p.13-14).

**The API never runs them, and that is the whole shape of this module.**
Running a repository's unit tests is running customer Python, which decision
0004 confines to a process holding no platform credentials. §286's Problems
panel could be a plain request because it parses and reads names; this cannot.
The route next door already refuses to preview a Python transform for the same
reason and says so: *"they run in an isolated task rather than in the API,
which takes long enough to need a job you can watch rather than a request that
waits."*

So `request` writes a queued row and returns immediately, the worker picks it
up, and `get` is what the Tests panel watches. Nothing here imports the sandbox.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: How much of an author's working set a single run may carry. **A limit rather
#: than a truncation**: the files are the thing under test, and a run over a
#: silently-shortened set would report on code nobody wrote. Generous enough
#: that no ordinary repository meets it, and present so that one which does is
#: told rather than surprised.
MAX_FILES_BYTES = 4 * 1024 * 1024

#: Queued runs one repository may have waiting at once. A panel with a
#: press-and-press-again button is the ordinary way this table fills up, and
#: every extra queued run over the same working set produces the same answer
#: more slowly.
MAX_QUEUED_PER_REPO = 3


async def request(
    conn: AsyncConnection,
    *,
    repo_id: UUID,
    branch: str,
    files: dict[str, str],
    requested_by: UUID,
) -> dict[str, Any]:
    """Queue a run over this working set. Returns the row.

    The files are stored rather than referenced. There is nowhere else an
    uncommitted buffer exists, and a run that re-read the branch would report on
    code that is not the code it ran — which is worse than not running, because
    it looks like an answer.
    """
    if not files:
        # `ValueError`, so the route answers 422: a request naming no files is
        # malformed rather than in conflict with anything. The same shape
        # `transform_adoption.adopt_many` takes for an empty batch, and the
        # route does not repeat the rule (§213).
        raise ValueError("there are no files to run tests over")

    payload = json.dumps(files)
    if len(payload.encode()) > MAX_FILES_BYTES:
        raise ValueError(
            f"this working set is larger than the {MAX_FILES_BYTES // (1024 * 1024)}MB "
            "a single test run may carry"
        )

    waiting = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM code_test_runs "
        " WHERE repo_id = :rid AND status = 'queued'",
        {"rid": str(repo_id)},
    )
    if waiting is not None and int(waiting["n"]) >= MAX_QUEUED_PER_REPO:
        raise ConflictError(
            f"{MAX_QUEUED_PER_REPO} test runs are already waiting on this repository - "
            "wait for one to finish rather than queueing another over the same files"
        )

    row = await fetch_one(
        conn,
        """
        INSERT INTO code_test_runs (repo_id, branch, files, requested_by)
        VALUES (:rid, :branch, CAST(:files AS jsonb), :by)
        RETURNING id, repo_id, branch, status, outcomes, error,
                  queued_at, started_at, finished_at
        """,
        {"rid": str(repo_id), "branch": branch, "files": payload,
         "by": str(requested_by)},
    )
    assert row is not None
    return dict(row)


async def get(conn: AsyncConnection, *, repo_id: UUID, run_id: UUID) -> dict[str, Any]:
    """One run, by id.

    **Scoped to the repository as well as the id**, so a run id from another
    repository reads as absent rather than as somebody else's answer — the same
    three-legged check `code._assert_commit_belongs` makes, for the same reason.
    """
    row = await fetch_one(
        conn,
        """
        SELECT id, repo_id, branch, status, outcomes, error,
               queued_at, started_at, finished_at
          FROM code_test_runs
         WHERE id = :id AND repo_id = :rid
        """,
        {"id": str(run_id), "rid": str(repo_id)},
    )
    if row is None:
        raise NotFoundError("this test run")
    return dict(row)


async def latest(
    conn: AsyncConnection, *, repo_id: UUID, branch: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """This repository's recent runs, newest first.

    Newest first because the panel opens on "what happened last time", which is
    the question somebody has before they have any other.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT id, repo_id, branch, status, outcomes, error,
               queued_at, started_at, finished_at
          FROM code_test_runs
         WHERE repo_id = :rid
           -- Cast, because Postgres cannot infer a bare parameter's type
           -- from `IS NULL` alone and answers `AmbiguousParameter`. Found
           -- by the test for the unfiltered listing, which is the only
           -- caller that passes NULL.
           AND (CAST(:branch AS text) IS NULL OR branch = CAST(:branch AS text))
         ORDER BY queued_at DESC
         LIMIT :limit
        """,
        {"rid": str(repo_id), "branch": branch, "limit": limit},
    )
    return [dict(r) for r in rows]
