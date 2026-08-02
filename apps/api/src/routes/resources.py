"""Resource registry routes (ROADMAP.md phase 2, section 0 item 1).

The read surface behind the project resource browser: one list of everything
in a project, whatever kind it is. Viewer is the floor, matching every other
project-scoped read - the registry holds names and kinds, which is exactly the
metadata project membership is meant to gate.

There is no write surface here on purpose. Resources are registered by the
database when their kind row is inserted (migration 0032), so "create a
resource" is not an operation this API can offer without also deciding what
kind of thing it is creating - which is what the existing per-kind endpoints
are for.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..lib.db import user_connection
from ..lib.errors import NotFoundError
from ..middleware.auth import AuthContext, get_current_user
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import resources as resources_service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/resources", tags=["resources"]
)

# Resolution by id alone, with no workspace or project in the path. The whole
# point of a stable resource id is that a link keeps working when the resource
# is renamed or moved, which a path carrying its location cannot do. Access is
# decided by RLS on the connection rather than by a path-shaped permission
# dependency: a resource the caller cannot see is indistinguishable from one
# that does not exist, which is the intended answer and not a limitation.
resolve_router = APIRouter(prefix="/resources", tags=["resources"])


class ResourceOut(BaseModel):
    id: UUID
    workspace_id: UUID
    # Null for resources that belong to the workspace rather than a project -
    # object types, and workspace-scoped connections.
    project_id: UUID | None
    kind: str
    name: str
    description: str
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class ResourceListOut(BaseModel):
    resources: list[ResourceOut]
    total: int
    limit: int
    offset: int


class ResourceCountsOut(BaseModel):
    counts: dict[str, int]


@router.get("", response_model=ResourceListOut)
async def list_resources(
    kind: list[str] | None = Query(default=None, description="Filter by resource kind; repeatable"),
    search: str | None = Query(default=None, max_length=200),
    sort: str = Query(default="updated_at"),
    direction: str = Query(default="desc"),
    limit: int = Query(default=resources_service.DEFAULT_LIMIT, ge=1, le=resources_service.MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    include_workspace_level: bool = Query(default=False),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ResourceListOut:
    # The service refuses an unknown sort or kind with a ValueError carrying a
    # sentence; main.py's handler turns that into a 422 with a string `detail`.
    # Catching it here to re-raise would only risk replacing that sentence with
    # a validation blob the caller has to decode (STATUS.md §52).
    async with user_connection(access.auth.user_id) as conn:
        result: dict[str, Any] = await resources_service.list_for_project(
            conn,
            access.workspace_id,
            access.project_id,
            kinds=kind,
            search=search,
            sort=sort,
            direction=direction,
            limit=limit,
            offset=offset,
            include_workspace_level=include_workspace_level,
        )
    return ResourceListOut(**result)


@router.get("/counts", response_model=ResourceCountsOut)
async def resource_counts(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ResourceCountsOut:
    async with user_connection(access.auth.user_id) as conn:
        counts = await resources_service.counts_for_project(conn, access.project_id)
    return ResourceCountsOut(counts=counts)


class ResourceResolved(ResourceOut):
    """What the application shell needs to render a resource's page before it
    knows anything kind-specific: where it sits (for the breadcrumb) and
    whether it is still there."""
    workspace_slug: str
    workspace_name: str
    project_slug: str | None
    project_name: str | None
    trashed: bool
    # The row's id in its own table - what every per-kind endpoint is keyed by.
    kind_id: UUID


@resolve_router.get("/{resource_id}", response_model=ResourceResolved)
async def resolve_resource(
    resource_id: UUID,
    auth: AuthContext = Depends(get_current_user),
) -> ResourceResolved:
    async with user_connection(auth.user_id) as conn:
        row = await resources_service.resolve(conn, resource_id)
    if row is None:
        raise NotFoundError("this resource does not exist, or you do not have access to it")
    return ResourceResolved(**row)
