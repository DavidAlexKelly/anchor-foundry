"""Which repository files name a dataset (§435; `dataset-preview` p.2).

    "The header also allows some file related operations such as sharing,
     moving, renaming, and more." (p.2)

**Renaming a dataset here is not a cosmetic change, and that is the whole
reason this module exists.** A transform declares what it reads and writes by
*name* — `-- input: raw = raw_orders`, `-- output: daily_orders` — and
`transform_publish.plan` resolves those names against `datasets.name`. So a
rename edits, at a distance, every file that mentions the old one.

The two directions are not equally bad, and a screen that lumped them together
would bury the worse one:

  * **A file that reads it** stops publishing. `plan` refuses an input it
    cannot resolve, so the failure is loud and arrives the next time somebody
    publishes that repository.
  * **A file that writes it** does something worse: the declaration still
    parses, the name simply no longer belongs to anything, so publishing
    *creates a new dataset* under the old name. The renamed one stops being
    updated and nothing says so. A pipeline forks in silence.

**Already-published transforms are not affected, and saying so is half the
value.** `model_inputs` holds a `dataset_id` (db 0003), so a model that has
been published keeps reading the same table whatever it is called. What breaks
is the *next publish of the file*, which is a different moment and a different
list of things to fix.

**Read from each repository's default branch**, because that is the ref a
publish is made against (§283) and the one every reader opens. A sandbox
naming the old dataset is somebody's work in progress; reporting it would be
reporting a file whose author has not finished deciding.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all
from . import repositories as repo_service
from . import transform_declarations as declarations


async def naming(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    workspace_id: UUID,
    name: str,
) -> dict[str, list[dict[str, Any]]]:
    """Every file in this project's repositories that declares `name`.

    `{"reads": [...], "writes": [...]}`, each entry naming the repository and
    the path — which is what somebody has to open to fix it.
    """
    repositories = await fetch_all(
        conn,
        "SELECT id, name, default_branch, resource_id FROM code_repos "
        " WHERE project_id = :pid ORDER BY name",
        {"pid": str(project_id)},
    )

    reads: list[dict[str, Any]] = []
    writes: list[dict[str, Any]] = []
    for repo in repositories:
        head = await repo_service.branch_head(
            conn, repo_id=UUID(str(repo["id"])), name=str(repo["default_branch"]),
        )
        # **One expression, not two branches.** A repository nobody has
        # committed to has no branch row, and `code_branches.head_commit_id`
        # is nullable besides (db 0033) - two spellings of "there is no tree
        # here", and writing them as two checks left one of them unreachable
        # through the API and so untestable. Read as one, there is nothing to
        # get out of step.
        at = (head or {}).get("head_commit_id")
        if at is None:
            continue
        files = await repo_service.read_tree(
            conn,
            workspace_id=workspace_id,
            commit_id=UUID(str(at)),
        )
        # **`read_repository`, which skips what it cannot parse.** A file with
        # a broken declaration is a problem the Problems panel already reports;
        # refusing to answer "who names this dataset" because some unrelated
        # file is malformed would make this screen fail for a reason that has
        # nothing to do with it.
        for path, found in sorted(declarations.read_repository(files).items()):
            where = {
                "repository_id": str(repo["id"]),
                # The id the *web* addresses a repository by, so a screen can
                # link straight to the file somebody has to change rather than
                # describing where it is.
                "resource_id": str(repo["resource_id"]),
                "repository": str(repo["name"]),
                "branch": str(repo["default_branch"]),
                "path": path,
            }
            if found.output == name:
                writes.append(where)
            aliases = sorted(
                alias for alias, dataset in found.inputs.items() if dataset == name
            )
            if aliases:
                reads.append({**where, "aliases": aliases})

    return {"reads": reads, "writes": writes}


def warning(references: dict[str, list[dict[str, Any]]], name: str) -> str | None:
    """One sentence about what renaming would cost, or `None` when nothing
    names it.

    **The writer first, because it is the one that fails quietly.** A reader
    stops publishing and says so; a writer goes on publishing and starts
    filling a different table.
    """
    reads = references.get("reads", [])
    writes = references.get("writes", [])
    if not reads and not writes:
        return None

    parts: list[str] = []
    if writes:
        parts.append(
            f"{_files(len(writes))} still declare{_s(len(writes))} "
            f"`-- output: {name}`. Publishing after a rename would create a new "
            "dataset under the old name and leave this one behind."
        )
    if reads:
        parts.append(
            f"{_files(len(reads))} read{_s(len(reads))} it by name and would be "
            "refused at the next publish until the declaration is updated."
        )
    parts.append(
        "Transforms that have already been published keep reading this dataset "
        "whatever it is called."
    )
    return " ".join(parts)


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


def _s(count: int) -> str:
    return "s" if count == 1 else ""
