"""Permission enforcement (spec §9, §10 "Broken access control").

Every resource route composes one of these dependencies AFTER authentication
and BEFORE any business logic — the ordering the user-facing contract in the
build brief demands: validate JWT → resolve user → check effective role →
only then execute.

Role resolution delegates to the database functions
``effective_workspace_role`` / ``effective_project_role`` (db 0005): the same
code path RLS uses, so application checks and the database backstop can never
disagree.

Denial semantics (spec §9): no access → the resource "does not exist for this
user" → 404. A 403 is raised only when the resource is visible but the role
is insufficient for the attempted action.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_one, user_connection
from ..lib.errors import ForbiddenError, NotFoundError
from .auth import AuthContext, get_current_user

_WS_RANK = {"viewer": 1, "editor": 2, "admin": 3}
_PROJ_RANK = {"viewer": 1, "editor": 2, "owner": 3}


@dataclass(frozen=True)
class WorkspaceAccess:
    auth: AuthContext
    workspace_id: UUID
    role: str  # 'admin' | 'editor' | 'viewer'

    def rank(self) -> int:
        return _WS_RANK[self.role]


@dataclass(frozen=True)
class ProjectAccess:
    auth: AuthContext
    workspace_id: UUID
    project_id: UUID
    role: str  # 'owner' | 'editor' | 'viewer'
    workspace_role: str | None = None  # None when access comes via project-only grant

    def rank(self) -> int:
        return _PROJ_RANK[self.role]


async def resolve_workspace_role(
    conn: AsyncConnection, user_id: UUID, workspace_id: UUID
) -> str | None:
    row = await fetch_one(
        conn,
        "SELECT effective_workspace_role(:uid, :wid) AS role",
        {"uid": str(user_id), "wid": str(workspace_id)},
    )
    return row["role"] if row and row["role"] is not None else None


async def resolve_project_role(
    conn: AsyncConnection, user_id: UUID, project_id: UUID
) -> str | None:
    row = await fetch_one(
        conn,
        "SELECT effective_project_role(:uid, :pid) AS role",
        {"uid": str(user_id), "pid": str(project_id)},
    )
    return row["role"] if row and row["role"] is not None else None


def require_org_admin(auth: AuthContext = Depends(get_current_user)) -> AuthContext:
    """Org-level administrative routes (settings, members, groups, audit)."""
    if not auth.is_org_admin:
        raise ForbiddenError("organisation admin role required")
    return auth


def require_workspace_role(minimum: str):
    """Dependency factory: the caller must hold at least ``minimum`` on the
    workspace in the path. 404 when the workspace is invisible to them."""
    if minimum not in _WS_RANK:
        raise ValueError(f"unknown workspace role {minimum!r}")

    async def dependency(
        workspace_id: UUID, auth: AuthContext = Depends(get_current_user)
    ) -> WorkspaceAccess:
        async with user_connection(auth.user_id) as conn:
            role = await resolve_workspace_role(conn, auth.user_id, workspace_id)
        if role is None:
            raise NotFoundError("workspace")  # §9: 404, not 403
        if _WS_RANK[role] < _WS_RANK[minimum]:
            raise ForbiddenError(f"workspace {minimum} role required")
        return WorkspaceAccess(auth=auth, workspace_id=workspace_id, role=role)

    return dependency


def require_project_role(minimum: str):
    """Dependency factory for project-scoped routes. Additionally verifies the
    project actually belongs to the workspace in the path — resource IDs from
    URLs are never trusted without confirming the hierarchy (§10)."""
    if minimum not in _PROJ_RANK:
        raise ValueError(f"unknown project role {minimum!r}")

    async def dependency(
        workspace_id: UUID, project_id: UUID, auth: AuthContext = Depends(get_current_user)
    ) -> ProjectAccess:
        async with user_connection(auth.user_id) as conn:
            row = await fetch_one(
                conn,
                "SELECT workspace_id FROM projects WHERE id = :pid",
                {"pid": str(project_id)},
            )
            if row is None or row["workspace_id"] != workspace_id:
                raise NotFoundError("project")
            role = await resolve_project_role(conn, auth.user_id, project_id)
            ws_role = await resolve_workspace_role(conn, auth.user_id, workspace_id)
        if role is None:
            raise NotFoundError("project")  # §9: 404, not 403
        if _PROJ_RANK[role] < _PROJ_RANK[minimum]:
            raise ForbiddenError(f"project {minimum} role required")
        return ProjectAccess(
            auth=auth, workspace_id=workspace_id, project_id=project_id, role=role,
            workspace_role=ws_role,
        )

    return dependency
