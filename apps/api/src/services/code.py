"""The Code pillar's repository surface (ROADMAP Code item 2).

`docs/decisions/0001-where-code-lives.md` decided that this pillar is a
*view* over data Models already writes, not a second store: a run is pinned to
the exact definition that produced it (`model_runs.model_version`, migration
0024), and a git ref cannot promise that. So there is no repository object
here, no working copy and no checkout - a project's transforms *are* the
repository, `model_versions` *is* the history, and this module renders both in
the shape somebody expects from one.

Two things are genuinely new, and only two:

* **The change set** (migration 0030) - one edit spanning several transforms,
  which nothing could express before. `apply_change_set` writes it by calling
  the same `models.update` the inline editor calls, in one transaction, so
  Code cannot drift from Models' validation (cycle refusal, input checks) or
  from the build path an edit triggers. That is `ROADMAP.md` Code item 3
  answered by construction rather than by a round trip.
* **Paths.** A repository has files, and a model has a name. `file_path`
  derives one from the other deterministically, including for names that
  collide once punctuation is stripped, because a path that changes between
  two reads is not a path.

Diffs are computed, never stored: two versions' code is all a diff needs, and
a stored rendering is a second copy that can disagree with what it describes.
"""
from __future__ import annotations

import difflib
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from . import models as model_service

_EXTENSIONS = {"sql": "sql", "python": "py"}
_UNSAFE = re.compile(r"[^a-z0-9]+")


def _stem(name: str) -> str:
    stem = _UNSAFE.sub("_", name.strip().lower()).strip("_")
    return stem or "model"


def file_path(name: str, language: str, model_id: UUID | str, *, disambiguate: bool) -> str:
    """The path a model appears at. Two models can legitimately be called
    "Daily orders" and "Daily Orders!", which collapse to the same stem, so a
    colliding path takes a short id suffix - and *both* sides of a collision
    take it, since a path that depends on which model was created first would
    move under an unrelated model's rename."""
    stem = _stem(name)
    if disambiguate:
        stem = f"{stem}_{str(model_id)[:8]}"
    return f"models/{stem}.{_EXTENSIONS.get(language, 'txt')}"


def _with_paths(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stems: dict[str, int] = {}
    for row in rows:
        stems[_stem(str(row["name"]))] = stems.get(_stem(str(row["name"])), 0) + 1
    out = []
    for row in rows:
        stem = _stem(str(row["name"]))
        out.append({
            **row,
            "path": file_path(
                str(row["name"]), str(row["language"]), row["id"],
                disambiguate=stems[stem] > 1,
            ),
        })
    return out


async def tree(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    """Every transform in the project as a file listing. Ordered by path so
    the tree is stable between reads - a repository whose files reshuffle on
    refresh is unreadable."""
    rows = await fetch_all(
        conn,
        """
        SELECT m.id, m.name, m.language, m.description, m.updated_at,
               length(m.code) AS size_bytes,
               (SELECT max(version_number) FROM model_versions v
                 WHERE v.model_id = m.id) AS current_version
          FROM models m
         WHERE m.project_id = :pid
         ORDER BY m.name
        """,
        {"pid": str(project_id)},
    )
    return sorted(_with_paths([dict(r) for r in rows]), key=lambda r: r["path"])


async def file(
    conn: AsyncConnection, project_id: UUID, model_id: UUID, version_number: int | None
) -> dict[str, Any]:
    """One file's source, at head or at a version. Reading an old version
    returns the code *and* the inputs it was saved with, because a transform
    that says `FROM orders` means nothing without knowing what `orders` was
    bound to at the time (migration 0024's reason for snapshotting both)."""
    model = await model_service.get(conn, project_id, model_id)
    entry = next((e for e in await tree(conn, project_id) if str(e["id"]) == str(model_id)), None)
    assert entry is not None  # get() above would have raised
    if version_number is None:
        return {
            **entry,
            "code": model["code"],
            "version_number": entry["current_version"],
            "inputs": await model_service.list_inputs(conn, model_id),
        }
    row = await fetch_one(
        conn,
        """
        SELECT version_number, code, inputs, restored_from, change_set_id, created_at,
               (SELECT u.email FROM users u WHERE u.id = model_versions.created_by)
                   AS created_by_email
          FROM model_versions WHERE model_id = :mid AND version_number = :n
        """,
        {"mid": str(model_id), "n": version_number},
    )
    if row is None:
        raise NotFoundError("model version")
    return {**entry, **dict(row)}


async def diff(
    conn: AsyncConnection,
    project_id: UUID,
    model_id: UUID,
    from_version: int | None,
    to_version: int | None,
) -> dict[str, Any]:
    """A unified diff between two versions, computed here and stored nowhere.

    `from_version=None` means "the state before version 1", i.e. the file
    being added, which is a real thing to want to see and not the same as
    diffing v1 against itself.
    """
    to = await file(conn, project_id, model_id, to_version)
    before = "" if from_version is None else str(
        (await file(conn, project_id, model_id, from_version))["code"]
    )
    after = str(to["code"])
    # `splitlines()` without keepends, and `lineterm=""`: a transform's source
    # usually has no trailing newline, and with keepends that makes the last
    # "-" line and the first "+" line run together into one line downstream.
    # Every entry here is exactly one line, and the caller joins them.
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{to['path']} (v{from_version})" if from_version else "/dev/null",
            tofile=f"{to['path']} (v{to['version_number']})",
            n=3,
            lineterm="",
        )
    )
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {
        "path": to["path"],
        "model_id": model_id,
        "from_version": from_version,
        "to_version": to["version_number"],
        "diff": "\n".join(lines),
        "added": added,
        "removed": removed,
    }


async def history(
    conn: AsyncConnection, project_id: UUID, limit: int = 50
) -> list[dict[str, Any]]:
    """The project's commit log: change sets and standalone saves in one
    timeline.

    Two kinds of entry rather than one, because that is the truth about how
    this codebase gets edited - the inline Models editor writes a version with
    no change set, and inventing a synthetic one for it would claim an
    intention nobody expressed (0030). A standalone entry is still a real
    edit and belongs in the log; it just has no message.
    """
    change_sets = await fetch_all(
        conn,
        """
        SELECT c.id, c.summary, c.description, c.created_at,
               (SELECT u.email FROM users u WHERE u.id = c.created_by) AS created_by_email,
               (SELECT count(*) FROM model_versions v WHERE v.change_set_id = c.id)
                   AS model_count
          FROM code_change_sets c
         WHERE c.project_id = :pid
         ORDER BY c.created_at DESC
         LIMIT :lim
        """,
        {"pid": str(project_id), "lim": limit},
    )
    standalone = await fetch_all(
        conn,
        """
        SELECT v.id, v.model_id, v.version_number, v.restored_from, v.created_at,
               m.name AS model_name, m.language,
               (SELECT u.email FROM users u WHERE u.id = v.created_by) AS created_by_email
          FROM model_versions v
          JOIN models m ON m.id = v.model_id
         WHERE m.project_id = :pid AND v.change_set_id IS NULL
         ORDER BY v.created_at DESC
         LIMIT :lim
        """,
        {"pid": str(project_id), "lim": limit},
    )
    paths = {str(e["id"]): e["path"] for e in await tree(conn, project_id)}
    entries: list[dict[str, Any]] = [
        {
            "kind": "change_set",
            "id": r["id"],
            "summary": r["summary"],
            "description": r["description"],
            "created_at": r["created_at"],
            "created_by_email": r["created_by_email"],
            "model_count": r["model_count"],
        }
        for r in change_sets
    ]
    entries += [
        {
            "kind": "version",
            "id": r["id"],
            "summary": (
                f"Reverted {r['model_name']} to v{r['restored_from']}"
                if r["restored_from"]
                else f"Edited {r['model_name']}"
            ),
            "description": "",
            "created_at": r["created_at"],
            "created_by_email": r["created_by_email"],
            "model_count": 1,
            "model_id": r["model_id"],
            "version_number": r["version_number"],
            "path": paths.get(str(r["model_id"])),
        }
        for r in standalone
    ]
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return entries[:limit]


async def get_change_set(
    conn: AsyncConnection, project_id: UUID, change_set_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT id, project_id, summary, description, created_at,
               (SELECT u.email FROM users u WHERE u.id = code_change_sets.created_by)
                   AS created_by_email
          FROM code_change_sets WHERE id = :cid AND project_id = :pid
        """,
        {"cid": str(change_set_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("change set")
    members = await fetch_all(
        conn,
        """
        SELECT v.model_id, v.version_number, m.name AS model_name, m.language,
               (SELECT max(p.version_number) FROM model_versions p
                 WHERE p.model_id = v.model_id AND p.version_number < v.version_number)
                   AS previous_version
          FROM model_versions v JOIN models m ON m.id = v.model_id
         WHERE v.change_set_id = :cid
         ORDER BY m.name
        """,
        {"cid": str(change_set_id)},
    )
    paths = {str(e["id"]): e["path"] for e in await tree(conn, project_id)}
    return {
        **dict(row),
        "models": [
            {**dict(m), "path": paths.get(str(m["model_id"]))} for m in members
        ],
    }


async def apply_change_set(
    conn: AsyncConnection,
    project_id: UUID,
    *,
    summary: str,
    description: str,
    changes: list[dict[str, Any]],
    created_by: UUID,
) -> dict[str, Any]:
    """Save several transforms as one edit.

    Every write goes through `models.update`, so a change set cannot bypass a
    check the inline editor enforces - cycle refusal, input validation, the
    upstream-trigger rule. It also means the versions this writes are the same
    rows a run resolves against, which is the whole point of the decision this
    item was blocked on.

    **A change with no change is refused rather than recorded.** `update`
    already declines to write a version when the code and inputs are
    unchanged, so a change set built entirely from no-ops would be a commit
    message attached to nothing - a lie about history rather than an empty
    one. The whole thing rolls back; the caller's transaction is the unit.
    """
    if not changes:
        raise ValueError("a change set needs at least one file")
    seen: set[str] = set()
    for change in changes:
        key = str(change["model_id"])
        if key in seen:
            raise ValueError("the same model appears twice in one change set")
        seen.add(key)

    row = await fetch_one(
        conn,
        """
        INSERT INTO code_change_sets (project_id, summary, description, created_by)
        VALUES (:pid, :summary, :descr, :by)
        RETURNING id, project_id, summary, description, created_at
        """,
        {
            "pid": str(project_id), "summary": summary,
            "descr": description, "by": str(created_by),
        },
    )
    assert row is not None
    change_set_id = UUID(str(row["id"]))

    written: list[dict[str, Any]] = []
    for change in changes:
        model_id = UUID(str(change["model_id"]))
        before = await model_service.get(conn, project_id, model_id)
        await model_service.update(
            conn, project_id, model_id,
            name=None, description=None,
            code=change.get("code"),
            inputs=change.get("inputs"),
            updated_by=created_by,
            change_set_id=change_set_id,
        )
        after = await model_service.get(conn, project_id, model_id)
        if str(after["code"]) != str(before["code"]) or change.get("inputs") is not None:
            written.append({"model_id": model_id})

    members = await fetch_all(
        conn,
        "SELECT count(*) AS n FROM model_versions WHERE change_set_id = :cid",
        {"cid": str(change_set_id)},
    )
    if not members or int(members[0]["n"]) == 0:
        raise ValueError(
            "nothing in this change set changed anything - "
            "every file matches what is already saved"
        )
    return await get_change_set(conn, project_id, change_set_id)
