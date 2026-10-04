"""Functions (decision 0018, option B; §768; Foundry `functions` p.49-50).

Workspace-scoped, as the ontology they read is. An editor publishes; anyone
who may read the workspace may call one, because a call reads its inputs as
the caller (`services/functions.py`).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import WorkspaceAccess, require_workspace_role
from ..services import audit
from ..services import functions as functions_service

router = APIRouter(prefix="/workspaces/{workspace_id}/functions", tags=["functions"])


class FunctionParameter(BaseModel):
    api_name: str
    display_name: str = ""
    data_type: str
    object_type_id: UUID | None = None
    required: bool = True


class FunctionVersionIn(BaseModel):
    #: p.50's semantic version, chosen by the author (p.49).
    version: str = Field(min_length=1, max_length=64)
    parameters: list[FunctionParameter] = Field(default_factory=list)
    inputs: list[UUID] = Field(default_factory=list)
    output: dict[str, Any]
    sql: str = Field(min_length=1, max_length=20_000)

    def raw(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class FunctionVersionOut(BaseModel):
    id: UUID
    version: str
    parameters: list[dict[str, Any]]
    inputs: list[UUID]
    output: dict[str, Any]
    sql: str
    created_at: datetime


class FunctionSummary(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    description: str
    latest_version: str | None = None
    created_at: datetime
    updated_at: datetime


class FunctionOut(FunctionSummary):
    #: Newest first.
    versions: list[FunctionVersionOut]


class FunctionCreate(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    version: FunctionVersionIn


class FunctionMetadata(BaseModel):
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class FunctionCall(BaseModel):
    #: Absent calls the newest version.
    version: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)


class FunctionResult(BaseModel):
    kind: str
    version: str
    value: Any = None
    values: list[Any] | None = None
    columns: list[dict[str, str]] | None = None
    rows: list[list[Any]] | None = None
    truncated: bool = False


@router.get("", response_model=list[FunctionSummary])
async def list_functions(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[FunctionSummary]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await functions_service.list_functions(conn, access.workspace_id)
    return [FunctionSummary(**r) for r in rows]


@router.get("/{function_id}", response_model=FunctionOut)
async def get_function(
    function_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> FunctionOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await functions_service.get_function(conn, access.workspace_id, function_id)
    return FunctionOut(**row)


@router.post("", response_model=FunctionOut, status_code=status.HTTP_201_CREATED)
async def create_function(
    body: FunctionCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> FunctionOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await functions_service.create(
            conn, workspace_id=access.workspace_id, api_name=body.api_name,
            display_name=body.display_name, description=body.description,
            version=body.version.raw(), created_by=access.auth.user_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="function.create",
            resource_type="function",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"api_name": body.api_name, "version": body.version.version},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return FunctionOut(**row)


@router.post("/{function_id}/versions", response_model=FunctionOut,
             status_code=status.HTTP_201_CREATED)
async def add_function_version(
    function_id: UUID,
    body: FunctionVersionIn,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> FunctionOut:
    """p.49: a change is a new, immutable version."""
    async with user_connection(access.auth.user_id) as conn:
        row = await functions_service.add_version(
            conn, workspace_id=access.workspace_id, function_id=function_id,
            version=body.raw(), created_by=access.auth.user_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="function.version",
            resource_type="function",
            resource_id=function_id,
            workspace_id=access.workspace_id,
            metadata={"version": body.version},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return FunctionOut(**row)


@router.patch("/{function_id}", response_model=FunctionOut)
async def update_function(
    function_id: UUID,
    body: FunctionMetadata,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> FunctionOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await functions_service.update_metadata(
            conn, workspace_id=access.workspace_id, function_id=function_id,
            display_name=body.display_name, description=body.description)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="function.update",
            resource_type="function",
            resource_id=function_id,
            workspace_id=access.workspace_id,
            metadata={"api_name": row["api_name"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return FunctionOut(**row)


@router.delete("/{function_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_class=Response)
async def delete_function(
    function_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> Response:
    async with user_connection(access.auth.user_id) as conn:
        await functions_service.delete(conn, access.workspace_id, function_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="function.delete",
            resource_type="function",
            resource_id=function_id,
            workspace_id=access.workspace_id,
            metadata={},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{function_id}/execute", response_model=FunctionResult)
async def execute_function(
    function_id: UUID,
    body: FunctionCall,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> FunctionResult:
    """A call, as the caller. Not audited: calling a function reads, as a
    query does, and a table column calls one on every page."""
    async with user_connection(access.auth.user_id) as conn:
        result = await functions_service.execute(
            conn, workspace_id=access.workspace_id, function_id=function_id,
            version=body.version, values=body.values)
    return FunctionResult(**result)
