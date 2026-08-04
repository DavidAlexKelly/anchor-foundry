"""Repository routes (ROADMAP.md phase 2, section 2).

The first writer `code_repos` has ever had. The table has been in the schema
since migration 0003 and empty in every deployment, because decision 0001
declined to build a git server and left it with nothing to do; decision 0003
gives it a data model, and this gives it a door.

Role floors match every other project-scoped resource: read = viewer, write =
editor. Committing is a write to the repository, not to what it produces -
publishing a transform from a commit is a separate act, at its own endpoint
(item 2.5), and a commit changes nothing about what runs until somebody
performs it. A project that requires code review refuses to publish at all,
with a sentence saying why: reviewing a publish needs proposals that understand
commits, and they do not.

Creating a repository registers it in the resource registry automatically
(db 0032's trigger), so a new repository appears in the project browser and
resolves at `/r/{id}` without this module knowing either exists.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ConflictError, NotFoundError
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import dataset_engine as engine
from ..services import datasets as ds_service
from ..services import repositories as repo_service
from ..services import transform_declarations as declarations
from ..services import transform_publish as publish_service
from ..services.dataset_engine import DatasetEngineError

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/repositories",
    tags=["repositories"],
)


def _dataset_storage():
    """The one gateway `main.py` configured, not a second one pointed
    somewhere else - same reason `models.py` reaches for it this way."""
    from . import datasets as dataset_routes

    return dataset_routes._storage


class RepositoryOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    slug: str
    description: str
    default_branch: str
    resource_id: UUID
    created_at: datetime
    updated_at: datetime


class RepositoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    default_branch: str = Field(default="main", min_length=1, max_length=100)


class BranchOut(BaseModel):
    id: UUID
    name: str
    head_commit_id: UUID | None


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # Where to start it. A branch off nothing is legitimate - an empty
    # repository has no commit to point at.
    from_commit_id: UUID | None = None
    from_branch: str | None = None


class CommitOut(BaseModel):
    id: UUID
    parent_id: UUID | None
    message: str
    created_by: UUID | None
    created_at: datetime


class CommitIn(BaseModel):
    branch: str = Field(min_length=1, max_length=100)
    # The complete tree, not a patch (decision 0003). A caller sending a patch
    # would have to be trusted to have read the parent correctly.
    files: dict[str, str]
    message: str = Field(default="", max_length=4000)


class TreeOut(BaseModel):
    commit_id: UUID | None
    files: dict[str, str]


class DiffOut(BaseModel):
    added: list[str]
    deleted: list[str]
    modified: list[str]


class CompareOut(BaseModel):
    base: str
    base_commit_id: UUID | None
    head: str
    head_commit_id: UUID | None
    # One of repo_service.MERGE_STATES. A string rather than an enum here
    # because the service owns the vocabulary and duplicating it as a second
    # enum is a second place for it to drift.
    state: str
    ahead_by: int
    behind_by: int
    commits: list[CommitOut]
    files: DiffOut


class MergeOut(CompareOut):
    # False for a merge that had nothing to do, which is not a failure.
    merged: bool


class MergeIn(BaseModel):
    # `head` merges into `base`; `base` is the branch that moves. Named the way
    # the comparison reads rather than "source"/"target", because the screen
    # asks "what would merging this into that do".
    base: str = Field(min_length=1, max_length=100)
    head: str = Field(min_length=1, max_length=100)


class PublishStepOut(BaseModel):
    path: str
    output: str
    language: str
    model_id: UUID | None
    model_name: str
    # True when the source is byte-identical to what is already live, so
    # publishing writes nothing for this file.
    unchanged: bool
    renames: bool
    inputs: list[dict[str, Any]]
    # created / updated / unchanged. Absent from a plan, which has not done
    # anything yet.
    action: str | None = None
    version_number: int | None = None


class OrphanOut(BaseModel):
    """A model this repository published from a file the commit no longer has.
    Reported, never deleted: a transform that has run holds a dataset other
    things read."""
    id: UUID
    name: str
    source_path: str


class PublishPlanOut(BaseModel):
    commit_id: UUID
    steps: list[PublishStepOut]
    orphaned: list[OrphanOut]


class PublishIn(BaseModel):
    branch: str | None = None
    commit_id: UUID | None = None


class PreviewIn(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    # The editor's buffer, not the commit. Previewing only what is committed
    # would make this ceremonial - the question a person asks is "does what I
    # just typed work", and they ask it before they are willing to commit.
    content: str | None = None
    branch: str | None = None
    commit_id: UUID | None = None


class PreviewedInputOut(BaseModel):
    alias: str
    dataset: str
    dataset_id: UUID
    rows_available: int
    rows_used: int
    sampled: bool


class PreviewOut(BaseModel):
    output: str
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    # Rows produced *from the sample*. `sampled` says whether that is the same
    # thing as the answer.
    row_count: int
    truncated: bool
    sampled: bool
    inputs: list[PreviewedInputOut]
    # Against the dataset this transform already writes, when it exists.
    schema_changes: dict[str, Any] | None = None
    writes_to_existing_dataset: bool = False


@router.get("", response_model=list[RepositoryOut])
async def list_repositories(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[RepositoryOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await repo_service.list_repositories(conn, access.project_id)
    return [RepositoryOut(**r) for r in rows]


@router.post("", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
async def create_repository(
    body: RepositoryCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> RepositoryOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await repo_service.create_repository(
            conn,
            project_id=access.project_id,
            name=body.name,
            description=body.description,
            default_branch=body.default_branch,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.create",
            resource_type="code_repo",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return RepositoryOut(**row)


@router.get("/{repo_id}", response_model=RepositoryOut)
async def get_repository(
    repo_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> RepositoryOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
    return RepositoryOut(**row)


# ---- branches ----------------------------------------------------------------
@router.get("/{repo_id}/branches", response_model=list[BranchOut])
async def list_branches(
    repo_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[BranchOut]:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        rows = await repo_service.list_branches(conn, repo_id)
    return [BranchOut(**{k: r[k] for k in ("id", "name", "head_commit_id")}) for r in rows]


@router.post("/{repo_id}/branches", response_model=BranchOut, status_code=status.HTTP_201_CREATED)
async def create_branch(
    repo_id: UUID,
    body: BranchCreate,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> BranchOut:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        start = body.from_commit_id
        if start is None and body.from_branch:
            start = await repo_service.resolve_ref(
                conn, repo_id=repo_id, branch=body.from_branch, commit_id=None
            )
        row = await repo_service.create_branch(
            conn,
            repo_id=repo_id,
            name=body.name,
            from_commit=start,
            created_by=access.auth.user_id,
        )
    return BranchOut(**row)


@router.delete("/{repo_id}/branches/{name}", status_code=status.HTTP_204_NO_CONTENT,
               response_model=None)
async def delete_branch(
    repo_id: UUID,
    name: str,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    """Deletes the pointer. The commits stay - they are still referenced by
    anything published from them (decision 0003)."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        await repo_service.delete_branch(conn, repo_id=repo_id, name=name)


@router.get("/{repo_id}/compare", response_model=CompareOut)
async def compare_branches(
    repo_id: UUID,
    base: str = Query(..., min_length=1, max_length=100),
    head: str = Query(..., min_length=1, max_length=100),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> CompareOut:
    """What merging `head` into `base` would do. Viewer, because it does none
    of it - this is the screen a reviewer reads before anybody merges."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        try:
            result = await repo_service.compare_branches(
                conn, repo_id=repo_id, base=base, head=head
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
    return CompareOut(**result)


@router.post("/{repo_id}/merge", response_model=MergeOut)
async def merge_branch(
    repo_id: UUID,
    body: MergeIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> MergeOut:
    """Fast-forward `base` onto `head`, or refuse with what diverged.

    200 rather than 201: nothing is created. A fast-forward moves a pointer to
    commits that already existed, and a merge with nothing to do returns the
    same shape with `merged: false`.
    """
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        try:
            result = await repo_service.merge_branch(
                conn, repo_id=repo_id, base=body.base, head=body.head
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        if result["merged"]:
            await audit.record(
                conn,
                organisation_id=access.auth.organisation_id,
                user_id=access.auth.user_id,
                action="repository.merge",
                resource_type="code_repo",
                resource_id=repo_id,
                workspace_id=access.workspace_id,
                project_id=access.project_id,
                metadata={
                    "base": body.base,
                    "head": body.head,
                    "to_commit": str(result["head_commit_id"]),
                    "commits": result["ahead_by"],
                },
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
    return MergeOut(**result)


# ---- content -----------------------------------------------------------------
@router.get("/{repo_id}/tree", response_model=TreeOut)
async def read_tree(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    commit_id: UUID | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> TreeOut:
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        ref = await repo_service.resolve_ref(
            conn,
            repo_id=repo_id,
            branch=branch or repo["default_branch"],
            commit_id=commit_id,
            # Only when falling back to the default: a repository nobody has
            # committed to has no branch row, and an editor cannot open a
            # repository it is told does not exist.
            allow_missing_branch=branch is None,
        )
        # A branch with no commits is a real state, not an error: a repository
        # that has just been created renders as empty rather than as missing.
        files = (
            {}
            if ref is None
            else await repo_service.read_tree(
                conn, workspace_id=access.workspace_id, commit_id=ref
            )
        )
    return TreeOut(commit_id=ref, files=files)


@router.post("/{repo_id}/commits", response_model=CommitOut, status_code=status.HTTP_201_CREATED)
async def create_commit(
    repo_id: UUID,
    body: CommitIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CommitOut:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        row = await repo_service.commit(
            conn,
            repo_id=repo_id,
            workspace_id=access.workspace_id,
            branch=body.branch,
            files=body.files,
            message=body.message,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.commit",
            resource_type="code_repo",
            resource_id=repo_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"commit_id": str(row["id"]), "branch": body.branch,
                      "files": len(body.files)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return CommitOut(**{k: row[k] for k in
                        ("id", "parent_id", "message", "created_by", "created_at")})


@router.get("/{repo_id}/commits", response_model=list[CommitOut])
async def list_commits(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[CommitOut]:
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        rows = await repo_service.history(conn, repo_id=repo_id, branch=branch, limit=limit)
    return [CommitOut(**r) for r in rows]


@router.get("/{repo_id}/diff", response_model=DiffOut)
async def diff_commits(
    repo_id: UUID,
    from_commit_id: UUID | None = Query(default=None),
    to_commit_id: UUID = Query(...),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DiffOut:
    """Two commits, three sets. `from` defaults to the target's parent, which
    is the diff a reviewer means by "what changed in this commit"."""
    async with user_connection(access.auth.user_id) as conn:
        await repo_service.get_repository(conn, project_id=access.project_id, repo_id=repo_id)
        target = await repo_service.get_commit(conn, to_commit_id)
        base_id = from_commit_id or target["parent_id"]
        base: dict[str, Any] = (
            {} if base_id is None
            else (await repo_service.get_commit(conn, UUID(str(base_id))))["manifest"]
        )
    return DiffOut(**repo_service.diff(base, target["manifest"]))


# ---- publishing (ROADMAP.md phase 2, item 2.5) -------------------------------
async def _publish_target(conn, access, repo_id: UUID, branch, commit_id) -> tuple[dict, UUID]:
    repo = await repo_service.get_repository(
        conn, project_id=access.project_id, repo_id=repo_id
    )
    ref = await publish_service.resolve_commit(
        conn, repo_id=repo_id, branch=branch, commit_id=commit_id,
        default_branch=str(repo["default_branch"]),
    )
    return repo, ref


@router.get("/{repo_id}/publish", response_model=PublishPlanOut)
async def plan_publish(
    repo_id: UUID,
    branch: str | None = Query(default=None),
    commit_id: UUID | None = Query(default=None),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> PublishPlanOut:
    """What publishing this commit would do, without doing it.

    Viewer, because it does none of it - and separate from the POST for the
    same reason 2.4's comparison is separate from its merge: a screen that can
    only report a problem after the button has been pressed teaches people to
    press and hope.
    """
    async with user_connection(access.auth.user_id) as conn:
        _, ref = await _publish_target(conn, access, repo_id, branch, commit_id)
        try:
            steps = await publish_service.plan(
                conn, project_id=access.project_id, workspace_id=access.workspace_id,
                repo_id=repo_id, commit_id=ref,
            )
        except publish_service.PublishError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        left = await publish_service.orphaned(
            conn, project_id=access.project_id, repo_id=repo_id,
            workspace_id=access.workspace_id, commit_id=ref,
        )
    return PublishPlanOut(
        commit_id=ref,
        steps=[PublishStepOut(**s) for s in steps],
        orphaned=[OrphanOut(**{k: o[k] for k in ("id", "name", "source_path")}) for o in left],
    )


@router.post("/{repo_id}/publish", response_model=PublishPlanOut)
async def publish_transforms(
    repo_id: UUID,
    body: PublishIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> PublishPlanOut:
    """Make the declared transforms at this commit the project's definitions.

    One transaction for the whole commit: a commit is a snapshot, and half of
    one landing would leave a pipeline matching no state the repository has ever
    been in.
    """
    async with user_connection(access.auth.user_id) as conn:
        _, ref = await _publish_target(conn, access, repo_id, body.branch, body.commit_id)
        try:
            steps = await publish_service.publish(
                conn, project_id=access.project_id, workspace_id=access.workspace_id,
                repo_id=repo_id, commit_id=ref, actor_id=access.auth.user_id,
            )
        except publish_service.PublishError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        left = await publish_service.orphaned(
            conn, project_id=access.project_id, repo_id=repo_id,
            workspace_id=access.workspace_id, commit_id=ref,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="repository.publish",
            resource_type="code_repo",
            resource_id=repo_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "commit_id": str(ref),
                "transforms": [
                    {"path": s["path"], "output": s["output"], "action": s["action"]}
                    for s in steps
                ],
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return PublishPlanOut(
        commit_id=ref,
        steps=[PublishStepOut(**{**s, "model_id": s["model_id"]}) for s in steps],
        orphaned=[OrphanOut(**{k: o[k] for k in ("id", "name", "source_path")}) for o in left],
    )


# ---- preview (ROADMAP.md phase 2, item 2.6) ----------------------------------
@router.post("/{repo_id}/preview", response_model=PreviewOut)
async def preview_transform(
    repo_id: UUID,
    body: PreviewIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> PreviewOut:
    """Run one file's transform against a sample of its declared inputs and
    return the rows, writing nothing.

    Editor rather than viewer, unlike every other read here. A preview
    executes SQL the caller supplied against datasets in the project, which is
    the same act `POST /datasets/{id}/query` performs - but this one arrives
    from an editor buffer rather than a saved model, so the floor matches who
    is allowed to write the file rather than who is allowed to read it.

    The inputs are resolved *by name*, from the declaration. A transform that
    names a dataset the project does not have is refused with the name in the
    message, which is the answer to the question the author is actually asking.
    """
    content = body.content
    async with user_connection(access.auth.user_id) as conn:
        repo = await repo_service.get_repository(
            conn, project_id=access.project_id, repo_id=repo_id
        )
        if content is None:
            ref = await repo_service.resolve_ref(
                conn,
                repo_id=repo_id,
                branch=body.branch or repo["default_branch"],
                commit_id=body.commit_id,
                allow_missing_branch=body.branch is None,
            )
            files = (
                {} if ref is None
                else await repo_service.read_tree(
                    conn, workspace_id=access.workspace_id, commit_id=ref
                )
            )
            if body.path not in files:
                raise NotFoundError(f"{body.path} at this commit")
            content = files[body.path]

        try:
            declaration = declarations.read(body.path, content)
        except declarations.DeclarationError as exc:
            # 422: the file is the request body and it is the thing that is
            # wrong. The message is already phrased for whoever wrote it.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        if declaration is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"{body.path} does not declare a transform, so there is nothing to "
                    "preview - a transform declares the dataset it produces"
                ),
            )
        if not body.path.endswith(".sql"):
            # Decision 0004: customer Python runs in the runner task, never in
            # the API. Previewing it means dispatching a Fargate task and
            # waiting on it, which is a job with a status rather than an HTTP
            # response (STATUS.md §69).
            raise ConflictError(
                "previewing Python transforms is not built yet - they run in an isolated "
                "task rather than in the API, which takes long enough to need a job you "
                "can watch rather than a request that waits. SQL transforms preview now."
            )

        datasets_by_name = {
            str(row["name"]): row
            for row in await ds_service.list_for_project(conn, access.project_id)
        }
        missing = [
            name for name in declaration.inputs.values() if name not in datasets_by_name
        ]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "this transform reads "
                    + ", ".join(sorted(set(missing)))
                    + ", which this project does not have"
                ),
            )
        input_rows = {
            alias: datasets_by_name[name] for alias, name in declaration.inputs.items()
        }
        output_row = datasets_by_name.get(declaration.output)

    storage = _dataset_storage()
    input_paths: dict[str, str] = {}
    for alias, row in input_rows.items():
        input_paths[alias] = await anyio.to_thread.run_sync(
            storage.local_path, str(row["s3_location"])
        )

    try:
        result, previewed = await anyio.to_thread.run_sync(
            engine.preview_transform, input_paths, content
        )
    except DatasetEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except FileNotFoundError as exc:
        # A dataset row with no bytes behind it. Not the author's fault, and
        # saying "your SQL is wrong" would send them to the wrong place.
        raise ConflictError(
            "one of this transform's inputs has no stored data yet, so there is nothing "
            "to preview against"
        ) from exc

    used = {p.alias: p for p in previewed}
    return PreviewOut(
        output=declaration.output,
        columns=[c.as_dict() for c in result.columns],
        rows=result.rows,
        row_count=result.total_rows,
        truncated=result.truncated,
        sampled=any(p.sampled for p in previewed),
        inputs=[
            PreviewedInputOut(
                alias=alias,
                dataset=str(row["name"]),
                dataset_id=UUID(str(row["id"])),
                rows_available=used[alias].rows_available,
                rows_used=used[alias].rows_used,
                sampled=used[alias].sampled,
            )
            for alias, row in input_rows.items()
        ],
        # The drift the roadmap asked this to catch: what this change would do
        # to the dataset the transform already writes.
        schema_changes=engine.diff_schemas(
            output_row.get("table_schema") if output_row else None, result.columns
        ),
        writes_to_existing_dataset=output_row is not None,
    )
