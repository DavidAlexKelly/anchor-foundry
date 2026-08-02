"""Repository routes (ROADMAP.md phase 2, section 2).

The first writer `code_repos` has ever had. The table has been in the schema
since migration 0003 and empty in every deployment, because decision 0001
declined to build a git server and left it with nothing to do; decision 0003
gives it a data model, and this gives it a door.

Role floors match every other project-scoped resource: read = viewer, write =
editor. Committing is a write to the repository, not to what it produces -
publishing a transform from a commit is a separate act with its own review
gate (`STATUS.md` §47), and this module deliberately does not do it.

Creating a repository registers it in the resource registry automatically
(db 0032's trigger), so a new repository appears in the project browser and
resolves at `/r/{id}` without this module knowing either exists.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import repositories as repo_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/repositories",
    tags=["repositories"],
)


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
