"""Multi-file repositories: blobs, commits, branches.

Decided in `docs/decisions/0003-repository-storage.md` and stored by migration
0033. Read the decision first - the *why* lives there.

The shape in one paragraph: file contents are content-addressed blobs,
deduplicated per workspace; a commit carries a flat `{path: sha}` manifest of
the whole snapshot rather than a tree; branches are mutable pointers that only
ever move forward. A diff is a dict comparison, a checkout is one join, and a
commit can be verified by reading it - which matters for the part of the system
that decides what code ran.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

# A single file. Generous for source, and low enough that a paste of something
# that is not source fails at the door rather than in the editor.
MAX_FILE_BYTES = 1 * 1024 * 1024
MAX_FILES = 500

# Paths are repository-relative and normalised. No leading slash, no "..", no
# backslashes: the same rule storage keys follow (services/storage.py), and for
# the same reason - a path is used to build things, so a path that can escape
# is a path that will.
_MAX_PATH = 400


def blob_sha(content: str) -> str:
    """Content address. UTF-8 of the text, so the same file committed from two
    machines with different line endings is *not* the same blob - that is a
    real difference in the file, and hiding it would make a diff lie."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def normalise_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("a file needs a path")
    cleaned = path.strip().replace("\\", "/").lstrip("/")
    if len(cleaned) > _MAX_PATH:
        raise ValueError(f"path is longer than {_MAX_PATH} characters")
    parts = [p for p in cleaned.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise ValueError(f"{path!r} escapes the repository")
    if not parts:
        raise ValueError(f"{path!r} is not a file path")
    return "/".join(parts)


async def write_blob(
    conn: AsyncConnection, *, workspace_id: UUID, content: str
) -> str:
    """Store content if it is not already stored, and return its address.

    `ON CONFLICT DO NOTHING` rather than a read-then-write: two commits landing
    the same new file at the same moment is ordinary, and the check-then-insert
    version of this is a race with a unique violation at the end of it.
    """
    if len(content.encode("utf-8")) > MAX_FILE_BYTES:
        raise ValueError(
            f"file is larger than the {MAX_FILE_BYTES // 1024} KB limit for source files"
        )
    sha = blob_sha(content)
    await conn.exec_driver_sql(
        "INSERT INTO code_blobs (workspace_id, sha256, content, size_bytes) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (str(workspace_id), sha, content, len(content.encode("utf-8"))),
    )
    return sha


async def read_blobs(
    conn: AsyncConnection, *, workspace_id: UUID, shas: list[str]
) -> dict[str, str]:
    if not shas:
        return {}
    rows = await fetch_all(
        conn,
        "SELECT sha256, content FROM code_blobs "
        "WHERE workspace_id = :wid AND sha256 = ANY(:shas)",
        {"wid": str(workspace_id), "shas": list(set(shas))},
    )
    return {r["sha256"]: r["content"] for r in rows}


async def commit(
    conn: AsyncConnection,
    *,
    repo_id: UUID,
    workspace_id: UUID,
    branch: str,
    files: dict[str, str],
    message: str,
    created_by: UUID | None,
) -> dict[str, Any]:
    """Write a whole snapshot and move a branch to it.

    `files` is the complete tree, not a patch. That is what a flat manifest
    means, and it is deliberate: a caller that sends a patch has to be trusted
    to have read the parent correctly, and this way the commit *is* the answer
    to "what did the repository look like".
    """
    if len(files) > MAX_FILES:
        raise ValueError(f"a repository may hold at most {MAX_FILES} files")

    manifest: dict[str, str] = {}
    for raw_path, content in files.items():
        path = normalise_path(raw_path)
        if path in manifest:
            raise ValueError(f"{path!r} appears twice in this commit")
        manifest[path] = await write_blob(conn, workspace_id=workspace_id, content=content)

    head = await branch_head(conn, repo_id=repo_id, name=branch)
    row = await fetch_one(
        conn,
        """
        INSERT INTO code_commits (repo_id, parent_id, manifest, message, created_by)
        VALUES (:repo, :parent, CAST(:manifest AS jsonb), :message, :author)
        RETURNING id, repo_id, parent_id, manifest, message, created_by, created_at
        """,
        {
            "repo": str(repo_id),
            "parent": str(head["head_commit_id"]) if head and head["head_commit_id"] else None,
            "manifest": json.dumps(manifest),
            "message": message[:4000],
            "author": str(created_by) if created_by else None,
        },
    )
    assert row is not None
    commit_id = row["id"]

    if head is None:
        await conn.exec_driver_sql(
            "INSERT INTO code_branches (repo_id, name, head_commit_id, created_by) "
            "VALUES (%s, %s, %s, %s)",
            (str(repo_id), branch, str(commit_id), str(created_by) if created_by else None),
        )
    else:
        await conn.exec_driver_sql(
            "UPDATE code_branches SET head_commit_id = %s WHERE repo_id = %s AND name = %s",
            (str(commit_id), str(repo_id), branch),
        )
    return dict(row)


async def branch_head(
    conn: AsyncConnection, *, repo_id: UUID, name: str
) -> dict[str, Any] | None:
    row = await fetch_one(
        conn,
        "SELECT id, name, head_commit_id FROM code_branches "
        "WHERE repo_id = :repo AND name = :name",
        {"repo": str(repo_id), "name": name},
    )
    return dict(row) if row else None


async def get_commit(conn: AsyncConnection, commit_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        "SELECT id, repo_id, parent_id, manifest, message, created_by, created_at "
        "FROM code_commits WHERE id = :cid",
        {"cid": str(commit_id)},
    )
    if row is None:
        raise NotFoundError("commit not found")
    data = dict(row)
    if isinstance(data["manifest"], str):
        data["manifest"] = json.loads(data["manifest"])
    return data


async def read_tree(
    conn: AsyncConnection, *, workspace_id: UUID, commit_id: UUID
) -> dict[str, str]:
    """Every file at a commit, path → content. One join, by design."""
    snapshot = await get_commit(conn, commit_id)
    manifest: dict[str, str] = snapshot["manifest"]
    contents = await read_blobs(conn, workspace_id=workspace_id, shas=list(manifest.values()))
    return {path: contents.get(sha, "") for path, sha in sorted(manifest.items())}


async def ancestors(conn: AsyncConnection, commit_id: UUID) -> list[UUID]:
    """The commit and everything behind it, newest first.

    Recursive CTE rather than a loop of queries: the fast-forward check runs on
    every branch move, and a walk that costs one round trip per commit is a
    walk that gets slower every day the repository is used.
    """
    rows = await fetch_all(
        conn,
        """
        WITH RECURSIVE walk AS (
            SELECT id, parent_id FROM code_commits WHERE id = :cid
            UNION ALL
            SELECT c.id, c.parent_id
              FROM code_commits c JOIN walk w ON c.id = w.parent_id
        )
        SELECT id FROM walk
        """,
        {"cid": str(commit_id)},
    )
    return [r["id"] for r in rows]


def diff(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    """Three sets, from two manifests.

    Compares *addresses*, not contents, so a file with identical content is
    unchanged however it got there - which is the answer a reviewer wants, and
    the one a line-by-line comparison of every file would spend real time
    reaching.
    """
    before_paths, after_paths = set(before), set(after)
    return {
        "added": sorted(after_paths - before_paths),
        "deleted": sorted(before_paths - after_paths),
        "modified": sorted(
            p for p in before_paths & after_paths if before[p] != after[p]
        ),
    }


async def move_branch(
    conn: AsyncConnection, *, repo_id: UUID, name: str, to_commit: UUID
) -> None:
    """Fast-forward only.

    A non-fast-forward move is refused rather than accepted, because accepting
    it discards commits - silently, and permanently for anything not published.
    The refusal names the branch and its head so whoever hit it can see what
    they would have lost.
    """
    head = await branch_head(conn, repo_id=repo_id, name=name)
    if head is None:
        raise NotFoundError(f"branch {name!r} does not exist")
    current = head["head_commit_id"]
    if current is not None and UUID(str(current)) not in {
        UUID(str(a)) for a in await ancestors(conn, to_commit)
    }:
        raise ConflictError(
            f"branch {name!r} cannot fast-forward: its head ({current}) is not an "
            "ancestor of the commit you are moving it to, so the move would discard "
            "commits. Rebase onto the branch instead."
        )
    await conn.exec_driver_sql(
        "UPDATE code_branches SET head_commit_id = %s WHERE repo_id = %s AND name = %s",
        (str(to_commit), str(repo_id), name),
    )


async def create_branch(
    conn: AsyncConnection,
    *,
    repo_id: UUID,
    name: str,
    from_commit: UUID | None,
    created_by: UUID | None,
) -> dict[str, Any]:
    existing = await branch_head(conn, repo_id=repo_id, name=name)
    if existing is not None:
        raise ConflictError(f"branch {name!r} already exists")
    row = await fetch_one(
        conn,
        "INSERT INTO code_branches (repo_id, name, head_commit_id, created_by) "
        "VALUES (:repo, :name, :head, :author) RETURNING id, name, head_commit_id",
        {
            "repo": str(repo_id),
            "name": name,
            "head": str(from_commit) if from_commit else None,
            "author": str(created_by) if created_by else None,
        },
    )
    assert row is not None
    return dict(row)


async def list_branches(conn: AsyncConnection, repo_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        "SELECT id, name, head_commit_id, created_at, updated_at FROM code_branches "
        "WHERE repo_id = :repo ORDER BY name",
        {"repo": str(repo_id)},
    )
    return [dict(r) for r in rows]


async def delete_branch(conn: AsyncConnection, *, repo_id: UUID, name: str) -> None:
    """Deletes the pointer, never the commits.

    They are still referenced by anything published from them, and a version
    whose commit vanished would be a record that changed after the fact.
    Unreferenced commits are garbage, not errors (decision 0003).
    """
    await conn.exec_driver_sql(
        "DELETE FROM code_branches WHERE repo_id = %s AND name = %s",
        (str(repo_id), name),
    )
