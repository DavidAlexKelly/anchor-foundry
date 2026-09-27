"""Tags (§511; db 0105; `dataset-preview` p.3, `app-building` p.35).

Two routers, for the two halves p.35 describes:

- **the tags themselves**, made in "the Tags section of Platform Settings":
  anybody in the workspace may list them, and only a workspace admin may make,
  rename or delete one, as p.35 gives that to the administrator roles;
- **a resource's tags**, "added … in the filesystem": anybody who can see the
  resource may read them, and an editor of the resource may add or remove one.
  For a resource in a project that is the project's editor; for a
  workspace-level one, the workspace's.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import user_connection
from ..lib.errors import ForbiddenError, NotFoundError
from ..middleware.permissions import (
    WorkspaceAccess,
    require_workspace_role,
    resolve_project_role,
)
from ..services import resource_tags as tag_service
from ..services import resources as resources_service

router = APIRouter(prefix="/workspaces/{workspace_id}/tags", tags=["tags"])
resource_router = APIRouter(prefix="/workspaces/{workspace_id}/resource-tags", tags=["tags"])


class TagIn(BaseModel):
    #: "" for no category (`getting-started` p.66's categories are optional).
    category: str = Field(default="", max_length=100)
    name: str = Field(min_length=1, max_length=100, pattern=r"\S")


class TagOut(BaseModel):
    id: UUID
    category: str
    name: str
    created_at: datetime


class TagUsageOut(TagOut):
    #: Resources the caller can see that carry it.
    uses: int


@router.get("", response_model=list[TagUsageOut])
async def list_tags(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[TagUsageOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await tag_service.list_tags(conn, access.workspace_id)
    return [TagUsageOut(**r) for r in rows]


@router.post("", response_model=TagUsageOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    body: TagIn,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> TagUsageOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await tag_service.create_tag(
            conn, access.workspace_id, category=body.category, name=body.name,
            by=access.auth.user_id)
    return TagUsageOut(**row)


@router.patch("/{tag_id}", response_model=TagUsageOut)
async def update_tag(
    tag_id: UUID,
    body: TagIn,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> TagUsageOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await tag_service.update_tag(
            conn, access.workspace_id, tag_id, category=body.category, name=body.name)
    return TagUsageOut(**row)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_tag(
    tag_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("admin")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await tag_service.delete_tag(conn, access.workspace_id, tag_id)


async def _resource(conn: AsyncConnection, access: WorkspaceAccess, resource_id: UUID) -> dict[str, Any]:
    """The resource, if the caller can see it and it is in this workspace."""
    found = await resources_service.resolve(conn, resource_id)
    if found is None or str(found["workspace_id"]) != str(access.workspace_id):
        raise NotFoundError("resource")
    return found


async def _require_editor(conn: AsyncConnection, access: WorkspaceAccess, found: dict[str, Any]) -> None:
    if found["project_id"] is None:
        if access.role == "viewer":
            raise ForbiddenError("workspace editor role required")
        return
    role = await resolve_project_role(conn, access.auth.user_id, found["project_id"])
    if role not in ("editor", "owner"):
        raise ForbiddenError("project editor role required")


@resource_router.get("/{resource_id}", response_model=list[TagOut])
async def resource_tags(
    resource_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[TagOut]:
    async with user_connection(access.auth.user_id) as conn:
        await _resource(conn, access, resource_id)
        rows = await tag_service.tags_on(conn, resource_id)
    return [TagOut(**r) for r in rows]


@resource_router.put("/{resource_id}/{tag_id}", response_model=list[TagOut])
async def add_resource_tag(
    resource_id: UUID,
    tag_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[TagOut]:
    """PUT, because tagging twice is the same tag. Answers with the
    resource's tags, which is what the caller draws next."""
    async with user_connection(access.auth.user_id) as conn:
        found = await _resource(conn, access, resource_id)
        await _require_editor(conn, access, found)
        await tag_service.add(conn, resource_id, tag_id, by=access.auth.user_id)
        rows = await tag_service.tags_on(conn, resource_id)
    return [TagOut(**r) for r in rows]


@resource_router.delete("/{resource_id}/{tag_id}", response_model=list[TagOut])
async def remove_resource_tag(
    resource_id: UUID,
    tag_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[TagOut]:
    async with user_connection(access.auth.user_id) as conn:
        found = await _resource(conn, access, resource_id)
        await _require_editor(conn, access, found)
        await tag_service.remove(conn, resource_id, tag_id)
        rows = await tag_service.tags_on(conn, resource_id)
    return [TagOut(**r) for r in rows]
