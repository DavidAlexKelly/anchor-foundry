"""Saved time series analyses (§662; `workshop` p.397).

> "Save as a time series analysis resource: Toggle on the Enable analysis
>  saving configuration to allow users to preserve and easily share their
>  analyses. Saved analyses can be … loaded into the Workshop widget using its
>  RID." (p.397)

**Viewer level for every route, saving included.** An analysis is the
reader's own, private unless they share it, so saving one is not an edit of
anything the project holds - the Workshop app's reader is the person p.397
means. Only its author saves over or deletes one (db 0131).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import audit
from ..services import series_analyses as service

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/series-analyses",
    tags=["series-analyses"],
)


#: p.397's RID alone (§663): "loaded into the Workshop widget using its RID",
#: and a widget's autoload names analyses by that and nothing else.
workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/series-analyses",
    tags=["series-analyses"],
)


class AnalysisOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    visibility: str
    #: The widget's view this reopens - never readings (db 0131).
    state: dict[str, Any]
    created_by: UUID
    created_by_name: str | None
    #: Whether the caller wrote it, and so may save over or delete it.
    mine: bool
    created_at: datetime
    updated_at: datetime


class AnalysisCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    visibility: str = "private"
    state: dict[str, Any] = Field(default_factory=dict)


class AnalysisReplace(BaseModel):
    visibility: str = "private"
    state: dict[str, Any] = Field(default_factory=dict)


def _out(row: dict[str, Any], user_id: UUID) -> AnalysisOut:
    return AnalysisOut(**row, mine=str(row["created_by"]) == str(user_id))


@router.get("", response_model=list[AnalysisOut])
async def list_analyses(access: ProjectAccess = Depends(require_project_role("viewer"))) -> list[AnalysisOut]:
    """The reader's own analyses and the project's public ones."""
    async with user_connection(access.auth.user_id) as conn:
        rows = await service.list_analyses(conn, access.project_id)
    return [_out(r, access.auth.user_id) for r in rows]


@workspace_router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis_by_rid(
    analysis_id: UUID, access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> AnalysisOut:
    """One analysis by its id, in whichever of the workspace's projects it is
    - if the reader may see it there."""
    async with user_connection(access.auth.user_id) as conn:
        row = await service.by_id(conn, access.workspace_id, analysis_id)
    return _out(row, access.auth.user_id)


@router.get("/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(
    analysis_id: UUID, access: ProjectAccess = Depends(require_project_role("viewer")),
) -> AnalysisOut:
    """One analysis by its id, p.397's "RID" - what the widget loads."""
    async with user_connection(access.auth.user_id) as conn:
        row = await service.get(conn, access.project_id, analysis_id)
    return _out(row, access.auth.user_id)


def _record(conn, access: ProjectAccess, request: Request, action: str, row: dict[str, Any]):
    return audit.record(
        conn,
        organisation_id=access.auth.organisation_id,
        user_id=access.auth.user_id,
        action=action,
        resource_type="series_analysis",
        resource_id=row["id"],
        workspace_id=access.workspace_id,
        project_id=access.project_id,
        metadata={"name": row["name"], "visibility": row["visibility"]},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


@router.post("", response_model=AnalysisOut, status_code=status.HTTP_201_CREATED)
async def save_analysis(
    body: AnalysisCreate, request: Request,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> AnalysisOut:
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await service.create(
                conn, project_id=access.project_id, name=body.name.strip(),
                visibility=body.visibility, state=body.state, created_by=access.auth.user_id)
        except service.AnalysisError as exc:
            raise ValueError(str(exc)) from exc
        await _record(conn, access, request, "series_analysis.save", row)
    return _out(row, access.auth.user_id)


@router.put("/{analysis_id}", response_model=AnalysisOut)
async def replace_analysis(
    analysis_id: UUID, body: AnalysisReplace, request: Request,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> AnalysisOut:
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await service.replace(
                conn, access.project_id, analysis_id, state=body.state, visibility=body.visibility,
                user_id=access.auth.user_id)
        except service.AnalysisError as exc:
            raise ValueError(str(exc)) from exc
        await _record(conn, access, request, "series_analysis.replace", row)
    return _out(row, access.auth.user_id)


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_analysis(
    analysis_id: UUID, access: ProjectAccess = Depends(require_project_role("viewer")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await service.remove(conn, access.project_id, analysis_id, access.auth.user_id)
