"""Code routes (ROADMAP Code item 2): a repository surface over a project's
transforms.

There is no repository resource to create, and that is the design rather than
an omission - `docs/decisions/0001-where-code-lives.md` decided the Code
pillar renders `model_versions` instead of storing code a second time, because
a run is pinned to the exact definition that produced it and a git ref cannot
promise that. So these are read paths over models, plus one write: the change
set, which saves several transforms as a single edit.

Role floors match Models exactly, deliberately: read = viewer, write =
editor. A second authoring surface that enforced a *different* floor from the
first would be a permission bug waiting for somebody to notice which door was
unlocked.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import code as code_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/code",
    tags=["code"],
)


class FileEntry(BaseModel):
    id: UUID
    path: str
    name: str
    language: str
    description: str
    size_bytes: int
    current_version: int | None
    updated_at: datetime


class FileDetail(FileEntry):
    code: str
    version_number: int | None
    inputs: list[dict[str, Any]] = []
    created_by_email: str | None = None
    restored_from: int | None = None
    change_set_id: UUID | None = None


class DiffOut(BaseModel):
    path: str
    model_id: UUID
    from_version: int | None
    to_version: int | None
    diff: str
    added: int
    removed: int


class HistoryEntry(BaseModel):
    kind: str
    id: UUID
    summary: str
    description: str
    created_at: datetime
    created_by_email: str | None
    model_count: int
    model_id: UUID | None = None
    version_number: int | None = None
    path: str | None = None


class ChangeSetMember(BaseModel):
    model_id: UUID
    model_name: str
    language: str
    path: str | None
    version_number: int
    previous_version: int | None


class ChangeSetOut(BaseModel):
    id: UUID
    project_id: UUID
    summary: str
    description: str
    created_at: datetime
    created_by_email: str | None = None
    models: list[ChangeSetMember]


class FileChange(BaseModel):
    model_id: UUID
    code: str | None = None
    inputs: list[dict[str, Any]] | None = None


class ChangeSetIn(BaseModel):
    summary: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    changes: list[FileChange] = Field(min_length=1)


@router.get("/tree", response_model=list[FileEntry])
async def get_tree(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[FileEntry]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await code_service.tree(conn, access.project_id)
    return [FileEntry(**r) for r in rows]


@router.get("/files/{model_id}", response_model=FileDetail)
async def get_file(
    model_id: UUID,
    version: int | None = Query(default=None, ge=1),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> FileDetail:
    """Head, or a numbered version. An old version returns the inputs it was
    saved with as well as its code: a transform that says `FROM orders` means
    nothing without knowing what `orders` was bound to at the time."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.file(conn, access.project_id, model_id, version)
    return FileDetail(**row)


@router.get("/files/{model_id}/diff", response_model=DiffOut)
async def get_diff(
    model_id: UUID,
    from_version: int | None = Query(default=None, ge=1),
    to_version: int | None = Query(default=None, ge=1),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DiffOut:
    """Computed on read, stored nowhere - a saved diff is a second copy that
    can disagree with the versions it claims to describe."""
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.diff(
            conn, access.project_id, model_id, from_version, to_version
        )
    return DiffOut(**row)


@router.get("/history", response_model=list[HistoryEntry])
async def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[HistoryEntry]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await code_service.history(conn, access.project_id, limit)
    return [HistoryEntry(**r) for r in rows]


@router.get("/change-sets/{change_set_id}", response_model=ChangeSetOut)
async def get_change_set(
    change_set_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ChangeSetOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.get_change_set(conn, access.project_id, change_set_id)
    return ChangeSetOut(**row)


@router.post("/change-sets", response_model=ChangeSetOut, status_code=201)
async def create_change_set(
    body: ChangeSetIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ChangeSetOut:
    """Save several transforms as one edit.

    Every file goes through the same `models.update` the inline editor calls,
    inside one transaction, so this cannot bypass a validation the other
    surface enforces (cycle refusal, input checks) and the versions it writes
    are the same rows a run resolves against.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await code_service.apply_change_set(
            conn,
            access.project_id,
            summary=body.summary,
            description=body.description,
            changes=[c.model_dump() for c in body.changes],
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="code_change_set.create",
            resource_type="code_change_set",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "summary": body.summary,
                "models": [str(m["model_id"]) for m in row["models"]],
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ChangeSetOut(**row)
