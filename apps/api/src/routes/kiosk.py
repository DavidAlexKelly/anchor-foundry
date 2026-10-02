"""Kiosk mode's routes (§684; Foundry `workshop` p.610-612).

Three audiences, three routers:

* the organisation's administrators - p.610's Control Panel allowlist and
  p.611's Session Launch History, from which "active kiosk mode sessions can
  also be ended by Administrators";
* a module's builders - p.610's Open kiosk modal ("outlines the contents of
  the currently published version of the module") and Launch session;
* the kiosk session itself - what it is, and p.610's "Exit kiosk mode".
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from ..lib.db import fetch_one, user_connection
from ..lib.errors import ForbiddenError, NotFoundError
from ..middleware.auth import AuthContext, get_current_user
from ..middleware.permissions import (
    WorkspaceAccess, require_org_admin, require_workspace_role, resolve_project_role,
)
from ..services import audit
from ..services import kiosk as kiosk_service
from ..services.canvas import get_published

org_router = APIRouter(prefix="/org/kiosk", tags=["kiosk"])
module_router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["kiosk"])
session_router = APIRouter(prefix="/kiosk", tags=["kiosk"])


class AllowedModuleOut(BaseModel):
    app_id: UUID
    name: str | None = None
    project_id: UUID | None = None
    added_at: datetime


class KioskSessionOut(BaseModel):
    id: UUID
    app_id: UUID
    app_name: str | None = None
    workspace_id: UUID
    version_number: int
    launched_by: UUID
    launched_by_name: str | None = None
    created_at: datetime
    expires_at: datetime
    ended_at: datetime | None = None
    active: bool


def _meta(request: Request) -> dict[str, Any]:
    return {"ip_address": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent")}


# ---- Control Panel (p.610-611) ----------------------------------------------------
@org_router.get("/modules", response_model=list[AllowedModuleOut])
async def list_allowed(auth: AuthContext = Depends(require_org_admin)) -> list[AllowedModuleOut]:
    async with user_connection(auth.user_id) as conn:
        rows = await kiosk_service.allowlist(conn, auth.organisation_id)
    return [AllowedModuleOut(**r) for r in rows]


class CandidateOut(BaseModel):
    app_id: UUID
    name: str
    workspace_name: str


@org_router.get("/candidates", response_model=list[CandidateOut])
async def list_candidates(auth: AuthContext = Depends(require_org_admin)) -> list[CandidateOut]:
    """Modules the administrator can see, for the allowlist's Add - by their
    own access, so the list cannot show a module they could not open."""
    async with user_connection(auth.user_id) as conn:
        rows = await kiosk_service.candidates(conn)
    return [CandidateOut(**r) for r in rows]


@org_router.put("/modules/{app_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def allow_module(
    app_id: UUID, request: Request, auth: AuthContext = Depends(require_org_admin),
) -> None:
    async with user_connection(auth.user_id) as conn:
        await kiosk_service.allow(conn, auth.organisation_id, app_id, by=auth.user_id)
        await audit.record(conn, organisation_id=auth.organisation_id, user_id=auth.user_id,
                           action="org.kiosk.allow", resource_type="canvas_app",
                           resource_id=app_id, **_meta(request))


@org_router.delete("/modules/{app_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def disallow_module(
    app_id: UUID, request: Request, auth: AuthContext = Depends(require_org_admin),
) -> None:
    async with user_connection(auth.user_id) as conn:
        await kiosk_service.disallow(conn, auth.organisation_id, app_id)
        await audit.record(conn, organisation_id=auth.organisation_id, user_id=auth.user_id,
                           action="org.kiosk.disallow", resource_type="canvas_app",
                           resource_id=app_id, **_meta(request))


@org_router.get("/sessions", response_model=list[KioskSessionOut])
async def list_sessions(auth: AuthContext = Depends(require_org_admin)) -> list[KioskSessionOut]:
    async with user_connection(auth.user_id) as conn:
        rows = await kiosk_service.sessions(conn, auth.organisation_id)
    return [KioskSessionOut(**r) for r in rows]


@org_router.post("/sessions/{session_id}/end", status_code=status.HTTP_204_NO_CONTENT,
                 response_model=None)
async def end_session(
    session_id: UUID, request: Request, auth: AuthContext = Depends(require_org_admin),
) -> None:
    async with user_connection(auth.user_id) as conn:
        if not await kiosk_service.end(conn, session_id, by=auth.user_id):
            raise NotFoundError("running kiosk session")
        await audit.record(conn, organisation_id=auth.organisation_id, user_id=auth.user_id,
                           action="org.kiosk.end_session", resource_type="kiosk_session",
                           resource_id=session_id, **_meta(request))


# ---- a module's builders (p.610's modal) --------------------------------------------
class ScopeEntry(BaseModel):
    id: str
    name: str


class KioskAvailabilityOut(BaseModel):
    available: bool
    reason: str | None = None
    version_number: int | None = None
    scope: dict[str, list[ScopeEntry]]


class LaunchedOut(BaseModel):
    session_id: UUID
    #: Shown once: only its hash is kept.
    token: str
    expires_at: datetime
    app_id: UUID
    project_id: UUID


async def _role(conn, access: WorkspaceAccess, app_id: UUID) -> str | None:
    app = await get_published(conn, access.workspace_id, app_id)
    return await resolve_project_role(conn, access.auth.user_id, app["project_id"])


@module_router.get("/published-canvas-apps/{app_id}/kiosk", response_model=KioskAvailabilityOut)
async def kiosk_availability(
    app_id: UUID, access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> KioskAvailabilityOut:
    async with user_connection(access.auth.user_id) as conn:
        state = await kiosk_service.availability(
            conn, organisation_id=access.auth.organisation_id,
            workspace_id=access.workspace_id, app_id=app_id,
            project_role=await _role(conn, access, app_id),
        )
    return KioskAvailabilityOut(**state)


@module_router.post("/published-canvas-apps/{app_id}/kiosk-sessions", response_model=LaunchedOut,
                    status_code=status.HTTP_201_CREATED)
async def launch_kiosk(
    app_id: UUID, request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> LaunchedOut:
    async with user_connection(access.auth.user_id) as conn:
        launched = await kiosk_service.launch(
            conn, organisation_id=access.auth.organisation_id,
            workspace_id=access.workspace_id, app_id=app_id,
            project_role=await _role(conn, access, app_id), by=access.auth.user_id,
        )
        await audit.record(conn, organisation_id=access.auth.organisation_id,
                           user_id=access.auth.user_id, action="canvas_app.kiosk_launch",
                           resource_type="kiosk_session", resource_id=launched["session_id"],
                           workspace_id=access.workspace_id,
                           metadata={"app_id": str(app_id)}, **_meta(request))
    return LaunchedOut(**launched)


# ---- the session itself ---------------------------------------------------------
class CurrentKioskOut(BaseModel):
    session_id: UUID
    workspace_id: UUID
    #: Where Exit kiosk mode goes back to: the module's own page.
    workspace_slug: str
    project_id: UUID
    app_id: UUID


def _kiosk_of(auth: AuthContext):
    if auth.kiosk is None:
        raise ForbiddenError("this is not a kiosk session")
    return auth.kiosk


@session_router.get("/current", response_model=CurrentKioskOut)
async def current_kiosk(auth: AuthContext = Depends(get_current_user)) -> CurrentKioskOut:
    session = _kiosk_of(auth)
    async with user_connection(auth.user_id) as conn:
        row = await fetch_one(conn, "SELECT slug FROM workspaces WHERE id = :wid",
                              {"wid": str(session.workspace_id)})
    if row is None:
        raise NotFoundError("workspace")
    return CurrentKioskOut(session_id=session.session_id, workspace_id=session.workspace_id,
                           workspace_slug=str(row["slug"]), project_id=session.project_id,
                           app_id=session.app_id)


@session_router.post("/end", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def exit_kiosk(request: Request, auth: AuthContext = Depends(get_current_user)) -> None:
    """p.610's "Exit kiosk mode", made with the session's own credential - the
    one thing a read-only session may write, and only to end itself."""
    session = _kiosk_of(auth)
    async with user_connection(auth.user_id) as conn:
        await kiosk_service.end(conn, session.session_id, by=auth.user_id)
        await audit.record(conn, organisation_id=auth.organisation_id, user_id=auth.user_id,
                           action="canvas_app.kiosk_exit", resource_type="kiosk_session",
                           resource_id=session.session_id,
                           workspace_id=session.workspace_id, **_meta(request))
