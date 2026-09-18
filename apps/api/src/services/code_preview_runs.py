"""Asking for a Python transform to be previewed, and reading what came back
(§390; db 0092; `code-repositories.md` §2.2 and §2.4, p.13-14).

**The API never runs it, which is why this exists at all.** A preview executes
the author's transform, and for Python that is customer code, which decision
0004 confines to a process holding no platform credentials. SQL previews stay
a plain request — `dataset_engine.preview_transform` runs them in the API's own
sandbox with external access off — and that asymmetry is the feature rather
than an inconsistency: the two languages are previewed by the same button and
answered by different machinery, because only one of them can be run where the
answer is wanted.

So `request` writes a queued row and returns, the worker picks it up, and `get`
is what the panel watches. Nothing here imports the sandbox.

**The shape is `code_test_runs`' shape**, deliberately and almost line for
line: db 0071's header quotes the very refusal this closes, so the precedent
was written with this case in mind. Where the two differ is what travels — a
test run carries the whole working set because pytest collects across a
repository, and a preview carries one file because a transform declares its
own inputs.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: How much editor buffer a single preview may carry. A transform file that
#: exceeds this is not a transform file; the limit is here so that one which
#: does is told rather than surprised, which is `code_test_runs`' reasoning
#: for `MAX_FILES_BYTES` at a size one file rather than a repository.
MAX_CONTENT_BYTES = 512 * 1024

#: Queued previews one repository may have waiting at once. **Lower than the
#: test runs' three**, because a preview is over a *buffer somebody is still
#: typing in*: the second press is nearly always meant to replace the first
#: rather than to join it, and three of them in a queue means watching two
#: answers to questions already out of date.
MAX_QUEUED_PER_REPO = 2


async def request(
    conn: AsyncConnection,
    *,
    repo_id: UUID,
    branch: str,
    path: str,
    content: str,
    input_datasets: dict[str, str],
    requested_by: UUID,
) -> dict[str, Any]:
    """Queue a preview of this file. Returns the row.

    The buffer is stored rather than referenced, for `code_test_runs.request`'s
    reason: an uncommitted edit exists nowhere else, and a run that re-read the
    branch would answer about code that is not the code it was asked about.
    """
    if not content.strip():
        # `ValueError`, so the route answers 422 — an empty buffer is a
        # malformed request rather than a conflict with anything.
        raise ValueError("there is nothing in this file to preview")

    if not input_datasets:
        # A transform with no inputs has nothing to preview *against*, and the
        # sample — the whole point of a preview — would be a sample of
        # nothing. The declaration parser already rejects a file that declares
        # no transform; this is the narrower case of one that declares a
        # transform reading nothing.
        raise ValueError("this transform reads no datasets, so there is nothing to preview")

    if len(content.encode()) > MAX_CONTENT_BYTES:
        raise ValueError(
            f"this file is larger than the {MAX_CONTENT_BYTES // 1024}KB a single "
            "preview may carry"
        )

    waiting = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM code_preview_runs "
        " WHERE repo_id = :rid AND status = 'queued'",
        {"rid": str(repo_id)},
    )
    if waiting is not None and int(waiting["n"]) >= MAX_QUEUED_PER_REPO:
        raise ConflictError(
            f"{MAX_QUEUED_PER_REPO} previews are already waiting on this repository - "
            "wait for one to finish rather than queueing another over a buffer that "
            "has moved on"
        )

    row = await fetch_one(
        conn,
        """
        INSERT INTO code_preview_runs
               (repo_id, branch, path, content, input_datasets, requested_by)
        VALUES (:rid, :branch, :path, :content, CAST(:inputs AS jsonb), :by)
        RETURNING id, repo_id, branch, path, status, result, inputs, error,
                  queued_at, started_at, finished_at
        """,
        {"rid": str(repo_id), "branch": branch, "path": path,
         "content": content, "inputs": json.dumps(input_datasets),
         "by": str(requested_by)},
    )
    assert row is not None
    return dict(row)


async def get(conn: AsyncConnection, *, repo_id: UUID, run_id: UUID) -> dict[str, Any]:
    """One preview, by id.

    Scoped to the repository as well as the id, so a run id from another
    repository reads as absent rather than as somebody else's rows.
    """
    row = await fetch_one(
        conn,
        """
        SELECT id, repo_id, branch, path, status, result, inputs, error,
               queued_at, started_at, finished_at
          FROM code_preview_runs
         WHERE id = :id AND repo_id = :rid
        """,
        {"id": str(run_id), "rid": str(repo_id)},
    )
    if row is None:
        raise NotFoundError("this preview")
    return dict(row)


async def latest(
    conn: AsyncConnection, *, repo_id: UUID, path: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """This repository's recent previews, newest first.

    Filtered by `path` rather than by branch, which is `code_test_runs.latest`'s
    one real divergence: a preview is about a *file*, so "what did this file do
    last time" is the question the panel opens with.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT id, repo_id, branch, path, status, result, inputs, error,
               queued_at, started_at, finished_at
          FROM code_preview_runs
         WHERE repo_id = :rid
           -- Cast for the reason `code_test_runs.latest` records: Postgres
           -- cannot infer a bare parameter's type from `IS NULL` alone.
           AND (CAST(:path AS text) IS NULL OR path = CAST(:path AS text))
         ORDER BY queued_at DESC
         LIMIT :limit
        """,
        {"rid": str(repo_id), "path": path, "limit": limit},
    )
    return [dict(r) for r in rows]
