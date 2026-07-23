"""Canvas app routes (spec §11 "Canvas", §5 "Publishing").

Definitions and editing are project-scoped, same floor as models/datasets/
connections: read = viewer, create/edit/save/delete = editor. Publishing to
the whole workspace or to specific groups additionally requires the
workspace admin role — same conservative bar routes/connections.py already
applies to workspace-scoped connections, since both expose project data
beyond the project's own membership. A project editor can always keep an
app private.

A second, workspace-scoped router (``published_router``) is the read path
for a workspace member who isn't a member of the app's own project: listing
and viewing apps that have actually been published. It never accepts writes.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ForbiddenError
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import audit
from ..services import canvas as canvas_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/canvas-apps", tags=["canvas"]
)
published_router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["canvas"])


def _parse_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class CanvasAppOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    slug: str
    description: str
    current_version: int
    publish_scope: str
    published_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CanvasAppDetail(CanvasAppOut):
    definition: dict[str, Any]


class CanvasAppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class CanvasAppUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DefinitionIn(BaseModel):
    definition: dict[str, Any] = Field(default_factory=dict)


class VersionOut(BaseModel):
    id: UUID
    version_number: int
    created_by: UUID | None
    created_at: datetime


class PublishIn(BaseModel):
    scope: str = Field(pattern="^(private|workspace|groups)$")
    group_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ShareOut(BaseModel):
    group_id: UUID
    group_name: str


def _out(row: dict[str, Any]) -> CanvasAppDetail:
    return CanvasAppDetail(**{**row, "definition": _parse_json(row["definition"])})


def _summary(row: dict[str, Any]) -> CanvasAppOut:
    return CanvasAppOut(**row)


# ---- project-scoped CRUD ------------------------------------------------------
@router.get("", response_model=list[CanvasAppOut])
async def list_apps(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[CanvasAppOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_for_project(conn, access.project_id)
    return [_summary(r) for r in rows]


@router.post("", response_model=CanvasAppDetail, status_code=status.HTTP_201_CREATED)
async def create_app(
    body: CanvasAppCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.create(
            conn,
            project_id=access.project_id,
            name=body.name,
            description=body.description,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.create",
            resource_type="canvas_app",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": body.name},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{app_id}", response_model=CanvasAppDetail)
async def get_app(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
    return _out(row)


@router.patch("/{app_id}", response_model=CanvasAppDetail)
async def update_app(
    app_id: UUID,
    body: CanvasAppUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.update_metadata(
            conn, access.project_id, app_id, name=body.name, description=body.description
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.update",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": body.name},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_app(
    app_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.delete(conn, access.project_id, app_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.delete",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- definition versioning ----------------------------------------------------
@router.put("/{app_id}/definition", response_model=CanvasAppDetail)
async def save_definition(
    app_id: UUID,
    body: DefinitionIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.save_definition(
            conn, access.project_id, app_id,
            definition=body.definition, created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.save",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"version": row["current_version"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{app_id}/versions", response_model=list[VersionOut])
async def list_versions(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[VersionOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_versions(conn, access.project_id, app_id)
    return [VersionOut(**r) for r in rows]


# ---- publishing ---------------------------------------------------------------
@router.put("/{app_id}/publish", response_model=CanvasAppDetail)
async def set_publish_scope(
    app_id: UUID,
    body: PublishIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    if body.scope != "private" and access.workspace_role != "admin":
        raise ForbiddenError("publishing beyond the project requires the workspace admin role")
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.set_publish_scope(
            conn, access.project_id, app_id,
            organisation_id=access.auth.organisation_id,
            scope=body.scope, group_ids=body.group_ids,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.publish",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"scope": body.scope, "groups": len(body.group_ids)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{app_id}/shares", response_model=list[ShareOut])
async def list_shares(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ShareOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_shares(conn, access.project_id, app_id)
    return [ShareOut(**r) for r in rows]


# ---- workspace-wide read path for published apps ------------------------------
@published_router.get("/published-canvas-apps", response_model=list[CanvasAppOut])
async def list_published_apps(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[CanvasAppOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_published(conn, access.workspace_id)
    return [_summary(r) for r in rows]


@published_router.get("/published-canvas-apps/{app_id}", response_model=CanvasAppDetail)
async def get_published_app(
    app_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get_published(conn, access.workspace_id, app_id)
    return _out(row)
