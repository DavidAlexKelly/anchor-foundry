"""Project routes (spec §17: /workspaces/{id}/projects/{id}/...).

Conservative role requirements where the spec is silent (flagged): create
project = workspace editor+; update settings / manage custom permissions =
project owner; delete = project owner (workspace admins map to owner in
inherited mode, and org admins are always owner, so both retain control).
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import (
    ProjectAccess,
    WorkspaceAccess,
    require_project_role,
    require_workspace_role,
)
from ..services import audit
from ..services import projects as proj_service

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["projects"])


class ProjectSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    permission_mode: str
    effective_role: str
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectSummary):
    resource_counts: dict[str, int]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    permission_mode: str | None = Field(default=None, pattern="^(inherited|custom)$")


class ProjectMemberOut(BaseModel):
    id: UUID
    role: str
    user_id: UUID | None
    email: str | None
    display_name: str | None
    group_id: UUID | None
    group_name: str | None
    created_at: datetime


class ProjectMemberSet(BaseModel):
    user_id: UUID | None = None
    group_id: UUID | None = None
    # 'none' is meaningful: it revokes access that inheritance/groups grant.
    role: str = Field(pattern="^(owner|editor|viewer|none)$")


@router.get("", response_model=list[ProjectSummary])
async def list_projects(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ProjectSummary]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await proj_service.list_for_user(conn, access.auth.user_id, access.workspace_id)
    return [ProjectSummary(**row) for row in rows]


@router.post("", response_model=ProjectSummary, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),  # Flagged
) -> ProjectSummary:
    async with user_connection(access.auth.user_id) as conn:
        row = await proj_service.create(
            conn,
            workspace_id=access.workspace_id,
            name=body.name,
            description=body.description,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="project.create",
            resource_type="project",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=row["id"],
            metadata={"name": body.name, "slug": row["slug"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    effective = "owner" if access.role == "admin" else access.role
    return ProjectSummary(**{**row, "effective_role": effective})


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ProjectDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await proj_service.get(conn, access.project_id)
        counts = await proj_service.resource_counts(conn, access.project_id)
    return ProjectDetail(**{**row, "effective_role": access.role, "resource_counts": counts})


@router.patch("/{project_id}", response_model=ProjectSummary)
async def update_project(
    body: ProjectUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("owner")),
) -> ProjectSummary:
    async with user_connection(access.auth.user_id) as conn:
        row = await proj_service.update(
            conn,
            access.project_id,
            name=body.name,
            description=body.description,
            permission_mode=body.permission_mode,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="project.update",
            resource_type="project",
            resource_id=access.project_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata=body.model_dump(exclude_none=True),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ProjectSummary(**{**row, "effective_role": access.role})


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_project(
    request: Request,
    access: ProjectAccess = Depends(require_project_role("owner")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await proj_service.delete(conn, access.project_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="project.delete",
            resource_type="project",
            resource_id=access.project_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- custom permissions -----------------------------------------------------
@router.get("/{project_id}/permissions", response_model=list[ProjectMemberOut])
async def list_permissions(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ProjectMemberOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await proj_service.list_members(conn, access.project_id)
    return [ProjectMemberOut(**row) for row in rows]


@router.put(
    "/{project_id}/permissions", response_model=ProjectMemberOut,
    status_code=status.HTTP_201_CREATED,
)
async def set_permission(
    body: ProjectMemberSet,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("owner")),
) -> ProjectMemberOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await proj_service.set_member(
            conn,
            access.project_id,
            workspace_id=access.workspace_id,
            user_id=body.user_id,
            group_id=body.group_id,
            role=body.role,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="project.permission.set",
            resource_type="project_member",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"role": body.role, "user_id": str(body.user_id) if body.user_id else None,
                      "group_id": str(body.group_id) if body.group_id else None},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    row.setdefault("email", None)
    row.setdefault("display_name", None)
    row.setdefault("group_name", None)
    return ProjectMemberOut(**row)


@router.delete(
    "/{project_id}/permissions/{member_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def remove_permission(
    member_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("owner")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await proj_service.remove_member(conn, access.project_id, member_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="project.permission.remove",
            resource_type="project_member",
            resource_id=member_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
