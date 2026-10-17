"""Organisation admin routes (spec §5 "Org settings"): members, groups,
audit log. All gated on org owner/admin except where noted."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, EmailStr, Field

from ..lib.proxy import client_address
from ..lib.db import user_connection
from ..middleware.auth import AuthContext, clear_identity_cache, get_current_user
from ..middleware.permissions import require_org_admin
from ..services import audit
from ..services import orgs as org_service
from ..services.orgs import CognitoAdminGateway, NullCognitoGateway

router = APIRouter(prefix="/org", tags=["org"])

# Injected at startup (production wires the boto3 gateway; tests/dev the null).
_cognito: CognitoAdminGateway = NullCognitoGateway()


def configure_cognito_gateway(gateway: CognitoAdminGateway) -> None:
    global _cognito
    _cognito = gateway


class OrgOut(BaseModel):
    id: UUID
    name: str
    slug: str
    plan: str
    aws_region: str | None
    stack_status: str
    created_at: datetime


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    org_role: str
    status: str
    identity_linked: bool | None = None
    created_at: datetime


class UserInvite(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    org_role: str = Field(pattern="^(admin|member)$")


class UserRoleUpdate(BaseModel):
    org_role: str = Field(pattern="^(admin|member)$")


class GroupOut(BaseModel):
    id: UUID
    name: str
    description: str
    member_count: int | None = None
    created_at: datetime


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)


class AuditEntry(BaseModel):
    id: int
    action: str
    resource_type: str
    resource_id: UUID | None
    workspace_id: UUID | None
    project_id: UUID | None
    metadata: dict[str, Any]
    actor_email: str | None
    actor_name: str | None
    created_at: datetime
    #: Where the request came from and with what (§988): recorded on every
    #: entry since §955, and the first two things an investigation asks.
    ip_address: str | None = None
    user_agent: str | None = None


@router.get("", response_model=OrgOut)
async def get_org(auth: AuthContext = Depends(get_current_user)) -> OrgOut:
    # Any member can see basic org info; admin routes below are gated.
    async with user_connection(auth.user_id) as conn:
        row = await org_service.get_org(conn, auth.organisation_id)
    return OrgOut(**row)


@router.get("/members", response_model=list[UserOut])
async def list_members(
    group_id: list[UUID] | None = Query(default=None),
    auth: AuthContext = Depends(get_current_user),
) -> list[UserOut]:
    # Visible to all members: needed for member pickers when granting
    # workspace/project roles. Emails within one org are not sensitive to it.
    #
    # **`group_id` narrows to the members of those groups** (p.478's "Specify
    # Multipass group IDs", for §234's User Select). Repeatable, and absent
    # means the whole org - which is what every caller before §234 sends. The
    # narrowing happens in `list_users` rather than here so the browser never
    # needs the membership graph to answer a dropdown; see the note there for
    # why an *empty* list is nobody rather than everybody.
    async with user_connection(auth.user_id) as conn:
        rows = await org_service.list_users(conn, auth.organisation_id, group_ids=group_id)
    return [UserOut(**row) for row in rows]


@router.post("/members", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: UserInvite, request: Request, auth: AuthContext = Depends(require_org_admin)
) -> UserOut:
    async with user_connection(auth.user_id) as conn:
        row = await org_service.invite_user(
            conn,
            _cognito,
            organisation_id=auth.organisation_id,
            email=str(body.email),
            display_name=body.display_name,
            org_role=body.org_role,
        )
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="org.member.invite",
            resource_type="user",
            resource_id=row["id"],
            metadata={"email": str(body.email), "org_role": body.org_role},
            ip_address=client_address(request),
            user_agent=request.headers.get("user-agent"),
        )
    return UserOut(**row, identity_linked=True)


@router.patch("/members/{user_id}", response_model=UserOut)
async def update_member_role(
    user_id: UUID,
    body: UserRoleUpdate,
    request: Request,
    auth: AuthContext = Depends(require_org_admin),
) -> UserOut:
    async with user_connection(auth.user_id) as conn:
        row = await org_service.set_user_role(conn, auth.organisation_id, user_id, body.org_role)
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="org.member.role_change",
            resource_type="user",
            resource_id=user_id,
            metadata={"org_role": body.org_role},
            ip_address=client_address(request),
            user_agent=request.headers.get("user-agent"),
        )
    clear_identity_cache()  # role changes take effect on the next request
    return UserOut(**row, identity_linked=None)


@router.delete("/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def disable_member(
    user_id: UUID, request: Request, auth: AuthContext = Depends(require_org_admin)
) -> None:
    async with user_connection(auth.user_id) as conn:
        await org_service.disable_user(conn, _cognito, auth.organisation_id, user_id)
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="org.member.disable",
            resource_type="user",
            resource_id=user_id,
            ip_address=client_address(request),
            user_agent=request.headers.get("user-agent"),
        )
    clear_identity_cache()  # a disabled user's cached identity must not survive


@router.get("/groups", response_model=list[GroupOut])
async def list_groups(auth: AuthContext = Depends(get_current_user)) -> list[GroupOut]:
    async with user_connection(auth.user_id) as conn:
        rows = await org_service.list_groups(conn, auth.organisation_id)
    return [GroupOut(**row) for row in rows]


@router.post("/groups", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate, request: Request, auth: AuthContext = Depends(require_org_admin)
) -> GroupOut:
    async with user_connection(auth.user_id) as conn:
        row = await org_service.create_group(
            conn, auth.organisation_id, body.name, body.description
        )
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="org.group.create",
            resource_type="group",
            resource_id=row["id"],
            metadata={"name": body.name},
            ip_address=client_address(request),
            user_agent=request.headers.get("user-agent"),
        )
    return GroupOut(**row, member_count=0)


@router.put("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def add_group_member(
    group_id: UUID, user_id: UUID, request: Request,
    auth: AuthContext = Depends(require_org_admin),
) -> None:
    async with user_connection(auth.user_id) as conn:
        await org_service.add_group_member(conn, auth.organisation_id, group_id, user_id)
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="org.group.member.add",
            resource_type="group",
            resource_id=group_id,
            metadata={"user_id": str(user_id)},
            ip_address=client_address(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.delete("/groups/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_group_member(
    group_id: UUID, user_id: UUID, request: Request,
    auth: AuthContext = Depends(require_org_admin),
) -> None:
    async with user_connection(auth.user_id) as conn:
        await org_service.remove_group_member(conn, auth.organisation_id, group_id, user_id)
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="org.group.member.remove",
            resource_type="group",
            resource_id=group_id,
            metadata={"user_id": str(user_id)},
            ip_address=client_address(request),
            user_agent=request.headers.get("user-agent"),
        )


@router.get("/audit", response_model=list[AuditEntry])
async def list_audit(
    auth: AuthContext = Depends(require_org_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    # §988: what an investigation narrows by. `action` is a prefix, so
    # `dataset.` is every dataset action and `dataset.export` one of them.
    action: str | None = Query(default=None, min_length=1, max_length=200),
    user_id: UUID | None = None,
    resource_id: UUID | None = None,
    workspace_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    # The page after the entry with this id, newest first: a cursor rather
    # than an offset, which reads and discards every entry before it - on a
    # log that only grows, a cost that grows with it.
    before_id: int | None = Query(default=None, ge=1),
) -> list[AuditEntry]:
    async with user_connection(auth.user_id) as conn:
        rows = await org_service.list_audit(
            conn, auth.organisation_id, limit=limit, offset=offset,
            filters=org_service.AuditFilters(
                action=action, user_id=user_id, resource_id=resource_id,
                workspace_id=workspace_id, since=since, until=until, before_id=before_id))
    return [AuditEntry(**row) for row in rows]
