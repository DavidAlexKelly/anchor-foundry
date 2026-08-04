"""Publishing a transform from a repository (ROADMAP.md phase 2, item 2.5).

The half of 2.5 that stayed open: SQL transforms were authored in a textarea
against a model, and a repository was a place to keep files that nothing read.
This joins them, in the shape migration 0033 already wrote down:

    "Repositories are where code is *authored*; publishing creates a
     `model_versions` row that copies the source in. The copy is the point - a
     record of what ran must not change when a branch does."

So publishing does not make a model *point at* a commit. It copies the source
into a version, the same way every other definition is written, and records
where the copy came from. Deleting the branch afterwards changes nothing about
what runs, which is the property the whole storage decision was chosen for.

**What publishing is, in one line:** the declared transforms at a commit become
this project's model definitions, and nothing else in the repository matters.

Four rules, each of which exists because the alternative is unrecoverable:

* **Identity is (repository, path)** (db 0038), not the model's name. A file
  renamed would otherwise publish to a second model and leave the first one
  running forever.
* **A name that is already taken by a model from somewhere else is refused**,
  rather than adopted. Silently taking over a hand-authored transform is how a
  publish deletes work nobody asked it to touch.
* **Two files declaring the same output are refused**, naming both. Applying
  them in filename order would make the winner depend on what the files are
  called.
* **Inputs are resolved by name and refused when missing**, with the name in
  the message - the question the author is actually asking is "what is this
  called here", and a publish that quietly dropped an input would produce a
  transform that runs and is wrong.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError
from . import code as code_service
from . import datasets as ds_service
from . import models as model_service
from . import repositories as repo_service
from . import transform_declarations as declarations


class PublishError(ValueError):
    """Refusal, phrased for whoever wrote the files."""


def _language(path: str) -> str:
    return "python" if path.endswith(".py") else "sql"


async def plan(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    workspace_id: UUID,
    repo_id: UUID,
    commit_id: UUID,
) -> list[dict[str, Any]]:
    """What publishing this commit would do, without doing it.

    Separated from `publish` for the same reason 2.4's comparison is separate
    from its merge: a screen that can only report a problem after the button
    has been pressed teaches people to press and hope. Every refusal below is
    raised here, so `publish` and this agree by construction rather than by two
    people remembering to keep them in step.
    """
    files = await repo_service.read_tree(
        conn, workspace_id=workspace_id, commit_id=commit_id
    )

    declared: list[tuple[str, declarations.Declaration]] = []
    for path in sorted(files):
        try:
            found = declarations.read(path, files[path])
        except declarations.DeclarationError as exc:
            raise PublishError(f"{path}: {exc}") from exc
        if found is not None:
            declared.append((path, found))

    if not declared:
        raise PublishError(
            "nothing at this commit declares a transform, so there is nothing to "
            "publish - a transform declares the dataset it produces"
        )

    seen: dict[str, str] = {}
    for path, found in declared:
        if found.output in seen:
            raise PublishError(
                f"{path} and {seen[found.output]} both declare the output "
                f"{found.output!r}. Publishing them would make the winner depend on "
                "what the files are called."
            )
        seen[found.output] = path

    datasets_by_name = {
        str(row["name"]): row
        for row in await ds_service.list_for_project(conn, project_id)
    }
    existing = {
        str(row["name"]): dict(row)
        for row in await fetch_all(
            conn,
            "SELECT id, name, code, source_repo_id, source_path FROM models "
            "WHERE project_id = :pid",
            {"pid": str(project_id)},
        )
    }
    by_source = {
        (str(m["source_repo_id"]), str(m["source_path"])): m
        for m in existing.values()
        if m["source_repo_id"]
    }

    steps: list[dict[str, Any]] = []
    for path, found in declared:
        missing = sorted(
            {name for name in found.inputs.values() if name not in datasets_by_name}
        )
        if missing:
            raise PublishError(
                f"{path} reads " + ", ".join(missing)
                + ", which this project does not have"
            )

        current = by_source.get((str(repo_id), path))
        clash = existing.get(found.output)
        if current is None and clash is not None:
            raise PublishError(
                f"{path} declares {found.output!r}, and a transform of that name "
                "already exists here"
                + (
                    f" - published from {clash['source_path']}."
                    if clash["source_repo_id"]
                    else " and was written directly rather than published."
                )
                + " Rename one of them."
            )
        if current is not None and clash is not None and str(clash["id"]) != str(current["id"]):
            raise PublishError(
                f"{path} declares {found.output!r}, which is already the name of "
                "another transform in this project. Rename one of them."
            )

        steps.append({
            "path": path,
            "output": found.output,
            "language": _language(path),
            "model_id": current["id"] if current else None,
            "model_name": current["name"] if current else found.output,
            # Nothing to write when the source is byte-identical. Said here so
            # the screen can show "no change" rather than manufacturing a
            # version whose diff is empty.
            "unchanged": bool(current and str(current["code"]) == files[path]),
            "renames": bool(current and str(current["name"]) != found.output),
            "inputs": [
                {
                    "dataset_id": datasets_by_name[name]["id"],
                    "input_alias": alias,
                    "dataset": name,
                }
                for alias, name in sorted(found.inputs.items())
            ],
            "code": files[path],
        })
    return steps


async def publish(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    workspace_id: UUID,
    repo_id: UUID,
    commit_id: UUID,
    actor_id: UUID,
) -> list[dict[str, Any]]:
    """Make the declared transforms at this commit the project's definitions.

    One transaction for the whole commit: a commit is a snapshot, and half of
    one landing would leave a pipeline that matches no state the repository has
    ever been in. The caller's `user_connection` provides it.
    """
    if await code_service.requires_review(conn, project_id):
        # Publishing changes what runs, so it is subject to the gate like every
        # other way of changing what runs. Letting it through would make
        # `require_code_review` trivially avoidable by putting the code in a
        # repository first - and a gate with a documented way round it is not a
        # gate. Reviewing a *publish* needs proposals that understand commits,
        # which is not built: proposals reference models, repositories hold
        # branches, and nothing joins them yet (STATUS.md §92).
        raise ConflictError(
            "this project requires code review, and reviewing a publish is not built "
            "yet - a proposal describes a change to a transform, not a commit. Turn "
            "review off to publish from a repository, or edit through proposals."
        )

    steps = await plan(
        conn, project_id=project_id, workspace_id=workspace_id,
        repo_id=repo_id, commit_id=commit_id,
    )

    published: list[dict[str, Any]] = []
    for step in steps:
        inputs = [
            {"dataset_id": i["dataset_id"], "input_alias": i["input_alias"]}
            for i in step["inputs"]
        ]
        if step["model_id"] is None:
            model = await model_service.create(
                conn,
                project_id=project_id,
                name=step["output"],
                description=f"Published from {step['path']}",
                language=step["language"],
                code=step["code"],
                inputs=inputs,
                created_by=actor_id,
            )
            model_id = UUID(str(model["id"]))
            await conn.exec_driver_sql(
                "UPDATE models SET source_repo_id = %s, source_path = %s WHERE id = %s",
                (str(repo_id), step["path"], str(model_id)),
            )
            # `create` wrote version 1 before this module could say where it
            # came from. Stamped rather than re-written: the version is the
            # same definition, and appending a second identical one to say so
            # would put a diff-less entry in every published model's history.
            await conn.exec_driver_sql(
                "UPDATE model_versions SET source_commit_id = %s, source_path = %s "
                "WHERE model_id = %s AND version_number = 1",
                (str(commit_id), step["path"], str(model_id)),
            )
            action = "created"
        else:
            model_id = UUID(str(step["model_id"]))
            action = "unchanged" if step["unchanged"] else "updated"
            # Through `models.update` rather than round it: that function owns
            # cycle refusal, input validation and when a version is written,
            # and a second implementation here would drift from it. It refuses
            # edits to a repository-authored model by default (db 0038);
            # `from_repository` lifts that one rule and nothing else.
            await model_service.update(
                conn, project_id, model_id,
                name=step["output"], description=None,
                code=step["code"], inputs=inputs,
                updated_by=actor_id,
                from_repository=True,
                source_commit_id=commit_id, source_path=step["path"],
            )

        latest = await fetch_one(
            conn,
            "SELECT max(version_number) AS n FROM model_versions WHERE model_id = :mid",
            {"mid": str(model_id)},
        )
        published.append({
            **step,
            "model_id": model_id,
            "action": action,
            "version_number": int(latest["n"]) if latest and latest["n"] else None,
        })
    return published


async def published_models(
    conn: AsyncConnection, *, project_id: UUID, repo_id: UUID
) -> list[dict[str, Any]]:
    """What this repository currently owns in this project, and from where."""
    rows = await fetch_all(
        conn,
        """
        SELECT m.id, m.name, m.source_path, m.output_dataset_id,
               (SELECT max(version_number) FROM model_versions v WHERE v.model_id = m.id)
                   AS version_number,
               (SELECT v.source_commit_id FROM model_versions v
                 WHERE v.model_id = m.id ORDER BY v.version_number DESC LIMIT 1)
                   AS source_commit_id
          FROM models m
         WHERE m.project_id = :pid AND m.source_repo_id = :rid
         ORDER BY m.source_path
        """,
        {"pid": str(project_id), "rid": str(repo_id)},
    )
    return [dict(r) for r in rows]


async def orphaned(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    repo_id: UUID,
    workspace_id: UUID,
    commit_id: UUID,
) -> list[dict[str, Any]]:
    """Models this repository published from files the commit no longer has.

    Reported, never deleted. A transform that has run holds a dataset other
    things read, and removing a file is not the same act as deciding that
    dataset should stop being produced - so this says what has been left behind
    and lets somebody decide.
    """
    files = await repo_service.read_tree(
        conn, workspace_id=workspace_id, commit_id=commit_id
    )
    live = {
        path for path in files
        if _has_declaration(path, files[path])
    }
    return [
        m for m in await published_models(conn, project_id=project_id, repo_id=repo_id)
        if str(m["source_path"]) not in live
    ]


def _has_declaration(path: str, source: str) -> bool:
    try:
        return declarations.read(path, source) is not None
    except declarations.DeclarationError:
        # A file that no longer parses is not evidence that the transform it
        # used to declare is gone - calling it orphaned would suggest deleting
        # a model because somebody typed a syntax error.
        return True


async def resolve_commit(
    conn: AsyncConnection, *, repo_id: UUID, branch: str | None, commit_id: UUID | None,
    default_branch: str,
) -> UUID:
    ref = await repo_service.resolve_ref(
        conn, repo_id=repo_id, branch=branch or default_branch, commit_id=commit_id,
        allow_missing_branch=branch is None,
    )
    if ref is None:
        raise ConflictError(
            "this repository has no commits yet, so there is nothing to publish"
        )
    return ref
