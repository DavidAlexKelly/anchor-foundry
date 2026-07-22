"""Auth routes. Token issuance happens against Cognito's hosted UI + PKCE on
the client (spec §9 "Login flow" steps 1-6); the API's job is identity echo
and audit. No route here ever returns or stores tokens."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ..lib.db import user_connection
from ..middleware.auth import AuthContext, get_current_user
from ..services import audit

router = APIRouter(prefix="/auth", tags=["auth"])


class Me(BaseModel):
    user_id: UUID
    organisation_id: UUID
    email: str
    display_name: str
    org_role: str


@router.get("/me", response_model=Me)
async def me(auth: AuthContext = Depends(get_current_user)) -> Me:
    return Me(
        user_id=auth.user_id,
        organisation_id=auth.organisation_id,
        email=auth.email,
        display_name=auth.display_name,
        org_role=auth.org_role,
    )


@router.post("/logout", status_code=204, response_model=None)
async def logout(request: Request, auth: AuthContext = Depends(get_current_user)) -> None:
    """Client discards tokens; server records the event (§9 audit: logins —
    logouts recorded symmetrically)."""
    async with user_connection(auth.user_id) as conn:
        await audit.record(
            conn,
            organisation_id=auth.organisation_id,
            user_id=auth.user_id,
            action="auth.logout",
            resource_type="user",
            resource_id=auth.user_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
