"""Canvas app routes (spec §11 "Canvas", §5 "Publishing").

Definitions and editing are project-scoped, same floor as models/datasets/
connections: read = viewer, create/edit/save/delete = editor. Publishing to
the whole workspace or to specific groups additionally requires the
workspace admin role - same conservative bar routes/connections.py already
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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ForbiddenError
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import audit
from ..services import canvas as canvas_service
from ..services import workshop_variables as variables_service

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


class EvaluateVariablesIn(BaseModel):
    """What the viewer has set. Values for derived variables are ignored - a
    derived variable is a function of its inputs (see the service)."""

    values: dict[str, Any] = Field(default_factory=dict)


class EvaluateVariablesOut(BaseModel):
    values: dict[str, Any]
    order: list[str]


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
    # Validated here rather than in `canvas_service`, which stores an opaque
    # blob and does not interpret it - a property decision 0002 records as
    # worth keeping. The API refuses the document; the storage layer stays
    # uninterested in what is inside it. v1 definitions pass through
    # untouched, or every unconverted app would stop being saveable.
    try:
        variables_service.validate_module(body.definition)
    except variables_service.VariableError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

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


# ---- variables (roadmap phase 2, item 1.2) -----------------------------------
@router.post("/{app_id}/variables/evaluate", response_model=EvaluateVariablesOut)
async def evaluate_variables(
    app_id: UUID,
    body: EvaluateVariablesIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> EvaluateVariablesOut:
    """Resolve every variable in the app, computing derived ones in dependency
    order.

    **Why the server does this rather than the browser**, since the transforms
    are pure functions and the browser is where the values are shown. This
    repo already carries five files mirrored between two runtimes and a
    standing note that a sixth should become a shared package instead
    (`STATUS.md`, rough edges). A TypeScript copy of `if_else`'s truthiness or
    `cast`'s refusals would be the sixth, and those are exactly the semantics
    two implementations get subtly and invisibly different.

    The round trip is close to free where it matters: derived values change
    when their *inputs* change - a filter selection, a row click - which is the
    same moment the app is already asking the server to re-evaluate an object
    set. It rides along with a call that was happening anyway. The honest cost
    is a text input, where every debounced keystroke now costs a request that a
    local computation would not.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(document)
        resolved = variables_service.evaluate(variables, body.values)
    except variables_service.VariableError as exc:
        # A saved app whose document no longer validates. Reachable: the module
        # could have been written before a rule existed, or by something other
        # than this API. Reported rather than swallowed, because the viewer
        # otherwise sees widgets quietly bound to nothing.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return EvaluateVariablesOut(
        values=resolved, order=variables_service.evaluation_order(variables)
    )


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
