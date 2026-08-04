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
from . import code_checks as check_service
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


async def requires_review(conn: AsyncConnection, project_id: UUID) -> bool:
    row = await fetch_one(
        conn,
        "SELECT require_code_review FROM projects WHERE id = :pid",
        {"pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("project")
    return bool(row["require_code_review"])


async def assert_direct_edit_allowed(conn: AsyncConnection, project_id: UUID) -> None:
    """The gate (ROADMAP Code item 4). Called by every path that would make a
    definition live without a review, which is the only place it can be
    enforced honestly - a gate on the screen is a gate on one screen."""
    if await requires_review(conn, project_id):
        raise ValueError(
            "this project requires review: open a proposal instead of "
            "editing a transform directly"
        )


async def apply_change_set(
    conn: AsyncConnection,
    project_id: UUID,
    *,
    summary: str,
    description: str,
    changes: list[dict[str, Any]],
    created_by: UUID,
    via_review: bool = False,
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
    if not via_review:
        await assert_direct_edit_allowed(conn, project_id)
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
            reviewed=via_review,
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


# ---- review-gated promotion (ROADMAP Code item 4) ---------------------------
"""A proposal is a *request* for code to become a definition.

It is deliberately not stored in `model_versions`: that table is what a run
resolves against (`model_runs.model_version`), so it must never contain code
nobody approved. Applying a proposal writes the versions - through the same
change set path an ungated save uses - and only then does the code exist as a
definition. Nothing runs a proposal, and nothing can.
"""

_PROPOSAL_COLUMNS = """
    id, project_id, summary, description, state, change_set_id,
    created_by, created_at, files_updated_at, closed_by, closed_at,
    source_repo_id, source_commit_id
"""


async def _proposal_row(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""
        SELECT {_PROPOSAL_COLUMNS},
               (SELECT u.email FROM users u WHERE u.id = code_proposals.created_by)
                   AS created_by_email
          FROM code_proposals WHERE id = :id AND project_id = :pid
        """,
        {"id": str(proposal_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("proposal")
    return dict(row)


async def _current_version(conn: AsyncConnection, model_id: UUID) -> int:
    row = await fetch_one(
        conn,
        "SELECT COALESCE(max(version_number), 0) AS n FROM model_versions WHERE model_id = :mid",
        {"mid": str(model_id)},
    )
    return int(row["n"]) if row else 0


async def _write_files(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    changes: list[dict[str, Any]],
) -> None:
    """Replace a proposal's files, recording the version each was written
    against. Every model is checked against the project first, so a proposal
    cannot smuggle in a transform from somewhere else."""
    if not changes:
        raise ValueError("a proposal needs at least one file")
    seen: set[str] = set()
    await fetch_all(
        conn, "DELETE FROM code_proposal_files WHERE proposal_id = :pid RETURNING model_id",
        {"pid": str(proposal_id)},
    )
    for change in changes:
        model_id = UUID(str(change["model_id"]))
        if str(model_id) in seen:
            raise ValueError("the same model appears twice in one proposal")
        seen.add(str(model_id))
        model = await model_service.get(conn, project_id, model_id)
        code = str(change["code"])
        if code == str(model["code"]):
            raise ValueError(
                f"{model['name']} is unchanged - a proposal cannot ask for an edit "
                "that has already happened"
            )
        await fetch_one(
            conn,
            """
            INSERT INTO code_proposal_files (proposal_id, model_id, code, base_version)
            VALUES (:pid, :mid, :code, :base) RETURNING model_id
            """,
            {
                "pid": str(proposal_id), "mid": str(model_id), "code": code,
                "base": await _current_version(conn, model_id),
            },
        )


async def create_proposal(
    conn: AsyncConnection,
    project_id: UUID,
    *,
    summary: str,
    description: str,
    changes: list[dict[str, Any]],
    created_by: UUID,
    # A proposal to *publish a commit* rather than to change named transforms
    # (db 0039). Mutually exclusive with `changes`: one describes files typed
    # into the proposal, the other describes files that already exist in a
    # repository, and a proposal that was both would have two answers to "what
    # is being reviewed".
    source_repo_id: UUID | None = None,
    source_commit_id: UUID | None = None,
) -> dict[str, Any]:
    commit_backed = source_commit_id is not None
    if commit_backed and changes:
        raise ValueError(
            "a proposal proposes a commit or a set of files, not both"
        )
    if not commit_backed and not changes:
        raise ValueError("a proposal needs at least one file")
    row = await fetch_one(
        conn,
        """
        INSERT INTO code_proposals (project_id, summary, description, created_by,
                                    source_repo_id, source_commit_id)
        VALUES (:pid, :summary, :descr, :by, :repo, :commit) RETURNING id
        """,
        {"pid": str(project_id), "summary": summary, "descr": description,
         "by": str(created_by),
         "repo": str(source_repo_id) if source_repo_id else None,
         "commit": str(source_commit_id) if source_commit_id else None},
    )
    assert row is not None
    proposal_id = UUID(str(row["id"]))
    if commit_backed:
        # Nothing is written: the files are the commit's, and the commit is
        # immutable. But the plan is run now so a commit that cannot be
        # published is refused at the door rather than becoming a proposal
        # nobody can apply.
        # `plan()` refuses a commit that declares nothing, so an empty list
        # cannot reach here - the refusal always arrives as `unpublishable`.
        _, unpublishable = await proposal_files(conn, project_id, proposal_id)
        if unpublishable:
            raise ValueError(unpublishable)
    else:
        await _write_files(conn, project_id, proposal_id, changes)
    return await get_proposal(conn, project_id, proposal_id)


async def update_proposal(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    *,
    summary: str | None,
    description: str | None,
    changes: list[dict[str, Any]] | None,
    actor_id: UUID,
) -> dict[str, Any]:
    """Only the author edits a proposal, and editing the *files* invalidates
    every approval it already had.

    Without that, approve-then-swap-the-code is a way to get arbitrary code
    past a reviewer who read something else - the reviewer's name would sit
    against a change they never saw. Editing the summary alone does not
    invalidate anything: the reviewer approved code, not prose.
    """
    proposal = await _proposal_row(conn, project_id, proposal_id)
    if proposal["state"] != "open":
        raise ValueError("this proposal is closed")
    if str(proposal["created_by"]) != str(actor_id):
        raise ValueError("only the author can edit a proposal")
    if changes is not None:
        await _write_files(conn, project_id, proposal_id, changes)
    await fetch_one(
        conn,
        """
        UPDATE code_proposals
           SET summary = COALESCE(:summary, summary),
               description = COALESCE(:descr, description),
               files_updated_at = CASE WHEN :touched THEN now() ELSE files_updated_at END
         WHERE id = :id RETURNING id
        """,
        {"summary": summary, "descr": description,
         "touched": changes is not None, "id": str(proposal_id)},
    )
    return await get_proposal(conn, project_id, proposal_id)


async def list_proposals(
    conn: AsyncConnection, project_id: UUID, state: str | None = None
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_PROPOSAL_COLUMNS},
               (SELECT u.email FROM users u WHERE u.id = code_proposals.created_by)
                   AS created_by_email,
               (SELECT count(*) FROM code_proposal_files f WHERE f.proposal_id = code_proposals.id)
                   AS file_count
          FROM code_proposals
         WHERE project_id = :pid
           -- Cast both sides to text: a bare `:state IS NULL` gives Postgres
           -- no way to infer the parameter's type and it refuses the whole
           -- statement ("could not determine data type of parameter").
           AND (CAST(:state AS text) IS NULL OR CAST(state AS text) = CAST(:state AS text))
         ORDER BY created_at DESC
        """,
        {"pid": str(project_id), "state": state},
    )
    return [dict(r) for r in rows]


def _blockers(proposal: dict[str, Any], files: list[dict[str, Any]],
              reviews: list[dict[str, Any]],
              checks: list[dict[str, Any]] | None = None) -> list[str]:
    """Every reason this proposal cannot be applied, in one list.

    A single "can't apply" boolean would leave somebody guessing which rule
    they tripped; the UI shows these verbatim.
    """
    reasons: list[str] = []
    if proposal["state"] != "open":
        reasons.append(f"this proposal is {proposal['state']}")
    # Latest verdict per reviewer, and only reviews of the code as it now
    # stands - an approval from before the last edit approved something else.
    latest: dict[str, dict[str, Any]] = {}
    for review in sorted(reviews, key=lambda r: r["created_at"]):
        if review["created_at"] < proposal["files_updated_at"]:
            continue
        latest[str(review["reviewer_id"])] = review
    if any(r["verdict"] == "request_changes" for r in latest.values()):
        reasons.append("a reviewer has asked for changes")
    if not any(r["verdict"] == "approve" for r in latest.values()):
        reasons.append("nobody has approved the current version of this proposal")
    stale = [f["path"] for f in files if f["base_version"] != f["current_version"]]
    if stale:
        reasons.append(
            "changed since this was proposed, so applying it would overwrite work "
            "nobody reviewed: " + ", ".join(sorted(stale))
        )
    # Item 2.8. A failing check is a reason in exactly the same list as every
    # other reason, so `apply` has one gate rather than two - and the surface
    # keeps showing every rule that was tripped rather than the first.
    reasons.extend(check_service.blockers(checks or []))
    return reasons


async def _version_at(conn: AsyncConnection, model_id: UUID, at: Any) -> int:
    """The model's version number as of a moment.

    What a commit-backed proposal has instead of a stored `base_version`
    (db 0039). Versions are append-only and carry their own timestamps, so
    "which version was this proposed against" is a question the data already
    answers - and one computed from the data cannot disagree with it.
    """
    row = await fetch_one(
        conn,
        "SELECT COALESCE(max(version_number), 0) AS n FROM model_versions "
        "WHERE model_id = :mid AND created_at <= :at",
        {"mid": str(model_id), "at": at},
    )
    return int(row["n"]) if row else 0


async def _files_from_commit(
    conn: AsyncConnection, project_id: UUID, proposal: dict[str, Any]
) -> list[dict[str, Any]]:
    """A commit-backed proposal's files, derived rather than stored.

    The commit is immutable, so this is the same answer every time it is asked
    - which is a stronger guarantee than 0031's stored files give, not a weaker
    one: there is no way to swap the code out from under an approval, because
    there is nothing to swap.
    """
    from . import transform_publish as publish_service

    workspace = await fetch_one(
        conn, "SELECT workspace_id FROM projects WHERE id = :pid",
        {"pid": str(project_id)},
    )
    assert workspace is not None
    try:
        steps = await publish_service.plan(
            conn,
            project_id=project_id,
            workspace_id=UUID(str(workspace["workspace_id"])),
            repo_id=UUID(str(proposal["source_repo_id"])),
            commit_id=UUID(str(proposal["source_commit_id"])),
        )
    except publish_service.PublishError as exc:
        # The commit has not changed, so this can only mean the *project* has -
        # an input dataset deleted, a name taken by something else. Surfaced as
        # a blocker rather than a 500, because it is a true statement about the
        # proposal: it cannot be applied, and this is why.
        return [{"unpublishable": str(exc)}]

    files: list[dict[str, Any]] = []
    for step in steps:
        model_id = UUID(str(step["model_id"])) if step["model_id"] else None
        live = ""
        base = current = 0
        if model_id is not None:
            row = await fetch_one(
                conn, "SELECT code FROM models WHERE id = :mid", {"mid": str(model_id)}
            )
            live = str(row["code"]) if row else ""
            base = await _version_at(conn, model_id, proposal["files_updated_at"])
            current = await _current_version(conn, model_id)
        files.append({
            "model_id": step["model_id"],
            "model_name": step["model_name"],
            "language": step["language"],
            # The repository path, not the derived `models/x.sql` one: this is
            # the file a reviewer is looking at, and it is the anchor a comment
            # on a not-yet-created transform hangs on.
            "path": step["path"],
            "code": step["code"],
            # The declared inputs, already resolved to datasets by the plan. A
            # file that would *create* a transform has no `model_inputs` rows
            # to look them up in, so carrying them here is what makes such a
            # file checkable at all.
            "inputs": step["inputs"],
            "base_version": base,
            "current_version": current,
            "diff": "\n".join(
                difflib.unified_diff(
                    live.splitlines(), str(step["code"]).splitlines(),
                    fromfile=f"{step['path']} (live, v{current})"
                    if model_id else "/dev/null",
                    tofile=f"{step['path']} (proposed)", n=3, lineterm="",
                )
            ),
            "rows": side_by_side(live, str(step["code"])),
        })
    return files


async def proposal_files(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID,
    proposal: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """A proposal's files, however they are held, plus a reason there are none.

    The one place that knows a proposal has two shapes (db 0039). Everything
    downstream - the review surface, the comment anchors, the checks - reads
    this rather than either table, so a second kind of proposal cannot be half
    supported.
    """
    proposal = proposal or await _proposal_row(conn, project_id, proposal_id)
    if not proposal["source_commit_id"]:
        return await _files_from_rows(conn, project_id, proposal_id), None
    files = await _files_from_commit(conn, project_id, proposal)
    if files and "unpublishable" in files[0]:
        return [], str(files[0]["unpublishable"])
    return files, None


async def get_proposal(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID
) -> dict[str, Any]:
    proposal = await _proposal_row(conn, project_id, proposal_id)
    files, unpublishable = await proposal_files(
        conn, project_id, proposal_id, proposal
    )
    return await _assemble_proposal(
        conn, project_id, proposal_id, proposal, files, unpublishable
    )


async def _files_from_rows(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID
) -> list[dict[str, Any]]:
    paths = {str(e["id"]): e for e in await tree(conn, project_id)}
    file_rows = await fetch_all(
        conn,
        """
        SELECT f.model_id, f.code, f.base_version, m.name AS model_name, m.language,
               m.code AS current_code
          FROM code_proposal_files f JOIN models m ON m.id = f.model_id
         WHERE f.proposal_id = :pid
         ORDER BY m.name
        """,
        {"pid": str(proposal_id)},
    )
    files: list[dict[str, Any]] = []
    for row in file_rows:
        entry = paths.get(str(row["model_id"]), {})
        current = await _current_version(conn, UUID(str(row["model_id"])))
        # The diff a reviewer reads is proposed-vs-*live*, not
        # proposed-vs-base: what matters is what applying this would do now.
        diff_lines = list(
            difflib.unified_diff(
                str(row["current_code"]).splitlines(),
                str(row["code"]).splitlines(),
                fromfile=f"{entry.get('path', '')} (live, v{current})",
                tofile=f"{entry.get('path', '')} (proposed)",
                n=3,
                lineterm="",
            )
        )
        files.append({
            "model_id": row["model_id"],
            "model_name": row["model_name"],
            "language": row["language"],
            "path": entry.get("path"),
            "code": row["code"],
            "base_version": row["base_version"],
            "current_version": current,
            "diff": "\n".join(diff_lines),
            # The same comparison as `diff`, aligned into rows with both sides'
            # line numbers (item 2.7). Both are returned: the unified string is
            # what an existing caller reads, and re-deriving one from the other
            # in the browser would be a second implementation of the diff.
            "rows": side_by_side(str(row["current_code"]), str(row["code"])),
        })
    return files


async def _assemble_proposal(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    proposal: dict[str, Any],
    files: list[dict[str, Any]],
    unpublishable: str | None,
) -> dict[str, Any]:
    reviews = [dict(r) for r in await fetch_all(
        conn,
        """
        SELECT id, reviewer_id, verdict, comment, created_at,
               (SELECT u.email FROM users u WHERE u.id = code_proposal_reviews.reviewer_id)
                   AS reviewer_email
          FROM code_proposal_reviews WHERE proposal_id = :pid
         ORDER BY created_at DESC
        """,
        {"pid": str(proposal_id)},
    )]
    comments = await _comments(conn, proposal_id, proposal["files_updated_at"])
    marks = await _file_marks(conn, proposal_id, proposal["files_updated_at"])
    checks = await check_service.list_checks(
        conn, proposal_id, proposal["files_updated_at"]
    )
    for f in files:
        key = anchor_key(f["model_id"], f.get("path"))
        f["comments"] = [c for c in comments if _anchor_of(c) == key]
        f["read_by"] = marks.get(key, [])
        f["checks"] = [c for c in checks if _anchor_of(c) == key]
    blockers = _blockers(proposal, files, reviews, checks)
    if unpublishable:
        # Not an error: the commit is fine and has not moved. Something in the
        # project has, and this says which - the same shape every other blocker
        # takes, so the surface renders it without knowing it is special.
        blockers.insert(0, unpublishable)
    return {
        **proposal,
        "files": files,
        "reviews": reviews,
        # File-less comments cannot exist (every comment names a file the
        # proposal changes), so this is the whole conversation in one place for
        # a caller that wants a timeline rather than a per-file view.
        "comments": comments,
        # Including the ones with no file, and the stale ones - a check that
        # went stale is information, and hiding it would read as "no checks
        # have run" when in fact they have and the code moved.
        "checks": checks,
        "blockers": blockers,
    }


async def review_proposal(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    *,
    verdict: str,
    comment: str,
    reviewer_id: UUID,
) -> dict[str, Any]:
    """Record a verdict. Nobody reviews their own proposal - a review somebody
    gave themselves is not a review, and letting it count would make the gate
    a formality anyone in a hurry can perform on themselves."""
    proposal = await _proposal_row(conn, project_id, proposal_id)
    if proposal["state"] != "open":
        raise ValueError("this proposal is closed")
    if str(proposal["created_by"]) == str(reviewer_id):
        raise ValueError("you cannot review your own proposal")
    await fetch_one(
        conn,
        """
        INSERT INTO code_proposal_reviews (proposal_id, reviewer_id, verdict, comment)
        VALUES (:pid, :by, CAST(:verdict AS code_review_verdict), :comment)
        RETURNING id
        """,
        {"pid": str(proposal_id), "by": str(reviewer_id),
         "verdict": verdict, "comment": comment},
    )
    return await get_proposal(conn, project_id, proposal_id)


async def apply_proposal(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID, *, actor_id: UUID
) -> dict[str, Any]:
    """Turn an approved proposal into definitions.

    The staleness re-check is the point of `base_version`: an approval is an
    approval of a diff against a particular state, and applying it after
    somebody else edited the same file would overwrite work no reviewer ever
    saw. The check happens *here*, at apply time, rather than only when the
    review was given - the gap between the two is exactly where the race
    lives.
    """
    detail = await get_proposal(conn, project_id, proposal_id)
    if detail["blockers"]:
        raise ValueError("; ".join(detail["blockers"]))
    if detail["source_commit_id"]:
        return await _apply_publish(conn, project_id, proposal_id, detail, actor_id)
    change_set = await apply_change_set(
        conn,
        project_id,
        summary=detail["summary"],
        description=detail["description"],
        changes=[{"model_id": f["model_id"], "code": f["code"]} for f in detail["files"]],
        created_by=actor_id,
        via_review=True,
    )
    await fetch_one(
        conn,
        """
        UPDATE code_proposals
           SET state = 'applied', change_set_id = :cid, closed_by = :by, closed_at = now()
         WHERE id = :id RETURNING id
        """,
        {"cid": str(change_set["id"]), "by": str(actor_id), "id": str(proposal_id)},
    )
    return await get_proposal(conn, project_id, proposal_id)


async def _apply_publish(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    detail: dict[str, Any],
    actor_id: UUID,
) -> dict[str, Any]:
    """Apply a commit-backed proposal by publishing its commit.

    A change set is created around it so a publish of four files reads as one
    entry in the project's history rather than four, and so `code_proposals`'
    own constraint - applied implies a change set - keeps meaning what it says.
    """
    from . import transform_publish as publish_service

    workspace = await fetch_one(
        conn, "SELECT workspace_id FROM projects WHERE id = :pid",
        {"pid": str(project_id)},
    )
    assert workspace is not None
    row = await fetch_one(
        conn,
        """
        INSERT INTO code_change_sets (project_id, summary, description, created_by)
        VALUES (:pid, :summary, :descr, :by)
        RETURNING id
        """,
        {"pid": str(project_id), "summary": detail["summary"],
         "descr": detail["description"], "by": str(actor_id)},
    )
    assert row is not None
    change_set_id = UUID(str(row["id"]))
    try:
        await publish_service.publish(
            conn,
            project_id=project_id,
            workspace_id=UUID(str(workspace["workspace_id"])),
            repo_id=UUID(str(detail["source_repo_id"])),
            commit_id=UUID(str(detail["source_commit_id"])),
            actor_id=actor_id,
            # The review is what applying a proposal *is*. This lifts the gate
            # that refuses a direct publish, and nothing else.
            reviewed=True,
            change_set_id=change_set_id,
        )
    except publish_service.PublishError as exc:
        raise ValueError(str(exc)) from exc
    await fetch_one(
        conn,
        """
        UPDATE code_proposals
           SET state = 'applied', change_set_id = :cid, closed_by = :by, closed_at = now()
         WHERE id = :id RETURNING id
        """,
        {"cid": str(change_set_id), "by": str(actor_id), "id": str(proposal_id)},
    )
    return await get_proposal(conn, project_id, proposal_id)


async def withdraw_proposal(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID, *, actor_id: UUID
) -> dict[str, Any]:
    proposal = await _proposal_row(conn, project_id, proposal_id)
    if proposal["state"] != "open":
        raise ValueError("this proposal is closed")
    await fetch_one(
        conn,
        """
        UPDATE code_proposals SET state = 'withdrawn', closed_by = :by, closed_at = now()
         WHERE id = :id RETURNING id
        """,
        {"by": str(actor_id), "id": str(proposal_id)},
    )
    return await get_proposal(conn, project_id, proposal_id)


async def set_require_review(
    conn: AsyncConnection, project_id: UUID, *, required: bool
) -> bool:
    row = await fetch_one(
        conn,
        "UPDATE projects SET require_code_review = :req WHERE id = :pid "
        "RETURNING require_code_review",
        {"req": required, "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("project")
    return bool(row["require_code_review"])


# ---- the review surface (ROADMAP.md phase 2, item 2.7) -----------------------
"""Side-by-side diffs, line-anchored comments, and per-file resolution.

The governance half of review was built above and by migration 0031. This is
the part a reviewer touches, and it adds one idea to the data model: **a remark
about a line is a claim about a version of the file**. Line 14 of the code
somebody read is not line 14 of the code somebody else will apply, so a comment
records the `files_updated_at` it was written against and goes *outdated* when
the proposal is edited - shown and marked, never hidden, because it said
something true about the code it was written against.

The same derivation gives "I have read this file" its meaning, which is why
both live here rather than in two shapes.
"""

# One line, aligned against the other side. `kind` is what happened to it:
#   same    - present on both sides, unchanged
#   added   - only on the proposed side
#   removed - only on the live side
#   changed - a replacement, so both sides have text and they differ
SIDE_BY_SIDE_KINDS = ("same", "added", "removed", "changed")


def side_by_side(live: str, proposed: str) -> list[dict[str, Any]]:
    """Two texts as aligned rows, each carrying both sides' line numbers.

    Built on `SequenceMatcher` opcodes rather than by parsing a unified diff.
    A unified diff is a *rendering*: recovering line numbers from it means
    re-reading the hunk headers and counting, and a comment anchored to a
    number recovered that way is anchored to a parser bug waiting to happen.

    A `replace` opcode covering unequal run lengths pairs what it can and
    leaves the remainder as one-sided rows, so a 3-line block becoming 5 lines
    reads as three changes and two additions rather than as five of anything.
    """
    left, right = live.splitlines(), proposed.splitlines()
    rows: list[dict[str, Any]] = []

    def row(kind: str, ln: int | None, lt: str | None, rn: int | None, rt: str | None) -> None:
        rows.append({"kind": kind, "live_line": ln, "live_text": lt,
                     "proposed_line": rn, "proposed_text": rt})

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, left, right).get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                row("same", i1 + k + 1, left[i1 + k], j1 + k + 1, right[j1 + k])
        elif tag == "delete":
            for k in range(i1, i2):
                row("removed", k + 1, left[k], None, None)
        elif tag == "insert":
            for k in range(j1, j2):
                row("added", None, None, k + 1, right[k])
        else:  # replace
            paired = min(i2 - i1, j2 - j1)
            for k in range(paired):
                row("changed", i1 + k + 1, left[i1 + k], j1 + k + 1, right[j1 + k])
            for k in range(i1 + paired, i2):
                row("removed", k + 1, left[k], None, None)
            for k in range(j1 + paired, j2):
                row("added", None, None, k + 1, right[k])
    return rows


async def _assert_open_proposal(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID
) -> dict[str, Any]:
    proposal = await _proposal_row(conn, project_id, proposal_id)
    if proposal["state"] != "open":
        raise ValueError("this proposal is closed, so it cannot be commented on")
    return proposal


async def _assert_proposal_file(
    conn: AsyncConnection, project_id: UUID, proposal_id: UUID,
    model_id: UUID | None, source_path: str | None,
) -> None:
    """A comment has to hang on a file the proposal actually changes.

    Without this, a comment can be anchored to any model in any project the
    caller can reach, and it would render nowhere - a remark that exists and
    cannot be read is worse than one that was refused.

    Checked against the proposal's *derived* file list rather than against
    `code_proposal_files`, because a commit-backed proposal has no rows there
    (db 0039) and every one of its comments would otherwise be refused.
    """
    if (model_id is None) == (source_path is None):
        raise ValueError("a comment hangs on a model or on a path, not both or neither")
    files, _ = await proposal_files(conn, project_id, proposal_id)
    wanted = anchor_key(model_id, source_path)
    if not any(anchor_key(f["model_id"], f.get("path")) == wanted for f in files):
        raise ValueError("this proposal does not change that file")


async def add_comment(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    *,
    model_id: UUID | None,
    source_path: str | None,
    side: str,
    line: int | None,
    body: str,
    author_id: UUID,
) -> dict[str, Any]:
    """Anchor a remark to a line - or to the file, when `line` is None.

    Anyone who can read the project can comment, including the author. A
    reviewer's *verdict* is gated (nobody approves their own proposal); saying
    something about a line is not a verdict, and an author who cannot answer a
    question about their own change makes the conversation one-directional.
    """
    proposal = await _assert_open_proposal(conn, project_id, proposal_id)
    if side not in ("live", "proposed"):
        raise ValueError(f"a comment hangs on the live or the proposed side, not {side!r}")
    if line is not None and line < 1:
        raise ValueError("line numbers start at 1")
    if not body.strip():
        raise ValueError("a comment needs something in it")
    await _assert_proposal_file(conn, project_id, proposal_id, model_id, source_path)
    row = await fetch_one(
        conn,
        """
        INSERT INTO code_proposal_comments
            (proposal_id, model_id, source_path, side, line, body, author_id,
             anchored_at)
        VALUES (:pid, :mid, :path, CAST(:side AS code_comment_side), :line, :body,
                :by, :anchor)
        RETURNING id
        """,
        {
            "pid": str(proposal_id), "mid": str(model_id) if model_id else None,
            "path": source_path, "side": side, "line": line,
            "body": body.strip(), "by": str(author_id),
            # The anchor is the proposal's own timestamp, not `now()`: the
            # question is which version of the files this was said about, and
            # two clocks answering it is one clock too many.
            "anchor": proposal["files_updated_at"],
        },
    )
    assert row is not None
    return await get_proposal(conn, project_id, proposal_id)


async def resolve_comment(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    comment_id: UUID,
    *,
    resolved: bool,
    actor_id: UUID,
) -> dict[str, Any]:
    """Settle a thread, or reopen it. Both directions, because a comment marked
    settled by mistake otherwise needs a second comment saying so."""
    await _proposal_row(conn, project_id, proposal_id)
    row = await fetch_one(
        conn,
        """
        UPDATE code_proposal_comments
           SET resolved_at = CASE WHEN :on THEN now() ELSE NULL END,
               resolved_by = CASE WHEN :on THEN CAST(:by AS uuid) ELSE NULL END
         WHERE id = :id AND proposal_id = :pid
        RETURNING id
        """,
        {"on": resolved, "by": str(actor_id), "id": str(comment_id), "pid": str(proposal_id)},
    )
    if row is None:
        raise NotFoundError("comment")
    return await get_proposal(conn, project_id, proposal_id)


async def mark_file_read(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    *,
    model_id: UUID | None,
    source_path: str | None,
    read: bool,
    reviewer_id: UUID,
) -> dict[str, Any]:
    """"I have read this file", per reviewer, against a particular version.

    Upserted rather than toggled through a delete, so re-marking a file after
    the proposal changed is one statement and cannot leave a half-state.
    """
    proposal = await _assert_open_proposal(conn, project_id, proposal_id)
    await _assert_proposal_file(conn, project_id, proposal_id, model_id, source_path)
    mid = str(model_id) if model_id else None
    if read:
        await conn.exec_driver_sql(
            """
            INSERT INTO code_proposal_file_marks
                (proposal_id, model_id, source_path, reviewer_id, anchored_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (proposal_id, model_id, source_path, reviewer_id)
            DO UPDATE SET marked_at = now(), anchored_at = EXCLUDED.anchored_at
            """,
            (str(proposal_id), mid, source_path, str(reviewer_id),
             proposal["files_updated_at"]),
        )
    else:
        await conn.exec_driver_sql(
            "DELETE FROM code_proposal_file_marks WHERE proposal_id = %s "
            "AND model_id IS NOT DISTINCT FROM %s "
            "AND source_path IS NOT DISTINCT FROM %s AND reviewer_id = %s",
            (str(proposal_id), mid, source_path, str(reviewer_id)),
        )
    return await get_proposal(conn, project_id, proposal_id)


def anchor_key(model_id: Any, source_path: Any) -> str:
    """Which file a comment, mark or check is about.

    A model when there is one, and the repository path when there is not - a
    commit-backed proposal may create transforms that do not exist until it is
    applied (db 0039), and a remark about one of those has nothing else stable
    to hang on. Prefixed so a path can never collide with a uuid.
    """
    if model_id:
        return f"model:{model_id}"
    return f"path:{source_path}"


def _anchor_of(row: dict[str, Any]) -> str:
    return anchor_key(row.get("model_id"), row.get("source_path"))


async def _comments(conn: AsyncConnection, proposal_id: UUID,
                    files_updated_at: Any) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        """
        SELECT c.id, c.model_id, c.source_path, c.side, c.line, c.body,
               c.author_id, c.created_at,
               c.anchored_at, c.resolved_at, c.resolved_by,
               (SELECT u.email FROM users u WHERE u.id = c.author_id) AS author_email
          FROM code_proposal_comments c
         WHERE c.proposal_id = :pid
         ORDER BY c.created_at
        """,
        {"pid": str(proposal_id)},
    )
    return [
        # Derived, not stored: a stored flag would need a write on every edit,
        # and a write that can be missed is a flag that can be wrong.
        {**dict(r), "outdated": r["anchored_at"] < files_updated_at}
        for r in rows
    ]


async def _file_marks(conn: AsyncConnection, proposal_id: UUID,
                      files_updated_at: Any) -> dict[str, list[dict[str, Any]]]:
    rows = await fetch_all(
        conn,
        """
        SELECT m.model_id, m.source_path, m.reviewer_id, m.marked_at, m.anchored_at,
               (SELECT u.email FROM users u WHERE u.id = m.reviewer_id) AS reviewer_email
          FROM code_proposal_file_marks m
         WHERE m.proposal_id = :pid
        """,
        {"pid": str(proposal_id)},
    )
    by_model: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        # A mark from before the last edit says somebody read a file that no
        # longer exists in that form, so it does not count as read - the same
        # rule 0031 already applies to approvals.
        if r["anchored_at"] < files_updated_at:
            continue
        by_model.setdefault(_anchor_of(dict(r)), []).append(dict(r))
    return by_model
