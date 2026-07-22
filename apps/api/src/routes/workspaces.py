"""Workspace routes (spec §17: /workspaces...). Every handler's first
dependency is authentication + effective-role resolution; business logic
never runs before the check passes.

Role requirements chosen conservatively where the spec is silent (each
flagged): create workspace = org admin; update = workspace admin; delete =
org admin; member management = workspace admin.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.auth import AuthContext, get_current_user
from ..middleware.permissions import (
    WorkspaceAccess,
    require_org_admin,
    require_workspace_role,
)
from ..services import audit
from ..services import workspaces as ws_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ---- schemas ----------------------------------------------------------------
class WorkspaceSummary(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    effective_role: str
    project_count: int
    created_at: datetime


class WorkspaceDetail(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str
    effective_role: str
    created_at: datetime
    updated_at: datetime


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class MemberOut(BaseModel):
    id: UUID
    role: str
    user_id: UUID | None
    email: str | None
    display_name: str | None
    group_id: UUID | None
    group_name: str | None
    created_at: datetime


class MemberAdd(BaseModel):
    user_id: UUID | None = None
    group_id: UUID | None = None
    role: str = Field(pattern="^(admin|editor|viewer)$")


class MemberRoleUpdate(BaseModel):
    role: str = Field(pattern="^(admin|editor|viewer)$")


# ---- routes -----------------------------------------------------------------
@router.get("", response_model=list[WorkspaceSummary])
async def list_workspaces(auth: AuthContext = Depends(get_current_user)) -> list[WorkspaceSummary]:
    async with user_connection(auth.user_id) as conn:
        rows = await ws_service.list_for_user(conn, auth.user_id)
    return [WorkspaceSummary(**row) for row in rows]


@router.post("", response_model=WorkspaceDetail, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    body: WorkspaceCreate,
    request: Request,
    auth: AuthContext = Depends(require_org_admin),  # Flagged: spec silent; org admin only
) -> WorkspaceDetail:
    async with user_connection(auth.user_id) as conn:
        row = await ws_service.create(
            conn,
            organisation_id=auth.organisation_id,
            name=body.name,
            description=body.description,
            created_by=auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="workspace.create",
            resource_type="workspace",
            resource_id=row["id"],
            workspace_id=row["id"],
            metadata={"name": body.name, "slug": row["slug"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return WorkspaceDetail(**{**row, "effective_role": "admin"})


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
async def get_workspace(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> WorkspaceDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await ws_service.get(conn, access.workspace_id)
    # Isolation anchors (s3_prefix etc.) are internal plumbing — not exposed.
    return WorkspaceDetail(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        description=row["description"],
        effective_role=access.role,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.patch("/{workspace_id}", response_model=WorkspaceDetail)
async def update_workspace(
    body: WorkspaceUpdate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> WorkspaceDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await ws_service.update(
            conn, access.workspace_id, name=body.name, description=body.description
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="workspace.update",
            resource_type="workspace",
            resource_id=access.workspace_id,
            workspace_id=access.workspace_id,
            metadata=body.model_dump(exclude_none=True),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return WorkspaceDetail(**{**row, "effective_role": access.role})


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_workspace(
    workspace_id: UUID,
    request: Request,
    auth: AuthContext = Depends(require_org_admin),  # Flagged: destructive → org admin
) -> None:
    async with user_connection(auth.user_id) as conn:
        await ws_service.delete(conn, workspace_id)
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="workspace.delete",
            resource_type="workspace",
            resource_id=workspace_id,
            workspace_id=workspace_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- members ----------------------------------------------------------------
@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[MemberOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ws_service.list_members(conn, access.workspace_id)
    return [MemberOut(**row) for row in rows]


@router.post(
    "/{workspace_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED
)
async def add_member(
    body: MemberAdd,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> MemberOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ws_service.add_member(
            conn,
            access.workspace_id,
            organisation_id=access.auth.organisation_id,
            user_id=body.user_id,
            group_id=body.group_id,
            role=body.role,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="workspace.member.add",
            resource_type="workspace_member",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"role": body.role, "user_id": str(body.user_id) if body.user_id else None,
                      "group_id": str(body.group_id) if body.group_id else None},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    row.setdefault("email", None)
    row.setdefault("display_name", None)
    row.setdefault("group_name", None)
    return MemberOut(**row)


@router.patch("/{workspace_id}/members/{member_id}", response_model=MemberOut)
async def update_member(
    member_id: UUID,
    body: MemberRoleUpdate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> MemberOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ws_service.update_member_role(conn, access.workspace_id, member_id, body.role)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="workspace.member.update",
            resource_type="workspace_member",
            resource_id=member_id,
            workspace_id=access.workspace_id,
            metadata={"role": body.role},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    row.setdefault("email", None)
    row.setdefault("display_name", None)
    row.setdefault("group_name", None)
    return MemberOut(**row)


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_member(
    member_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await ws_service.remove_member(conn, access.workspace_id, member_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="workspace.member.remove",
            resource_type="workspace_member",
            resource_id=member_id,
            workspace_id=access.workspace_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
