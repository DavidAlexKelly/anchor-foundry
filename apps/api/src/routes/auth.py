"""Auth routes. Token issuance happens against Cognito's hosted UI + PKCE on
the client (spec §9 "Login flow" steps 1-6); the API's job is identity echo,
audit, and - since STATUS.md §55 - turning a verified token into a browser
session the page's own JavaScript cannot read.

No route here returns a token. `POST /session` accepts one and gives back
nothing but a `Set-Cookie`, which is the direction that matters: a credential
that only ever travels inward cannot be exfiltrated by a script that gets to
run on this origin.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ..lib.config import get_settings
from ..lib.db import user_connection
from ..middleware.auth import (
    SESSION_COOKIE,
    AuthContext,
    authenticate_token,
    get_current_user,
)
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


class SessionIn(BaseModel):
    access_token: str = Field(min_length=1, max_length=8192)


@router.post("/session", response_model=Me)
async def create_session(body: SessionIn, request: Request, response: Response) -> Me:
    """Exchange a verified access token for an httpOnly session cookie.

    Deliberately not dependent on `get_current_user`: this is the route that
    *creates* the session, so it verifies the supplied token itself rather than
    reading one that is already established. Verification is the same code path
    every other route uses - a token this refuses is a token nothing else would
    have accepted either.
    """
    # The same verification every other route runs, called directly rather
    # than through the request-reading dependency.
    auth = await authenticate_token(body.access_token)

    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        body.access_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        # No max-age: a session cookie, so closing the browser ends it. The
        # token's own expiry still bounds it independently - the cookie is a
        # carrier, not a second source of truth about how long a session lasts.
    )
    return Me(
        user_id=auth.user_id,
        organisation_id=auth.organisation_id,
        email=auth.email,
        display_name=auth.display_name,
        org_role=auth.org_role,
    )


@router.post("/logout", status_code=204, response_model=None)
async def logout(
    request: Request, response: Response, auth: AuthContext = Depends(get_current_user)
) -> None:
    """Clear the session cookie and record the event (§9 audit: logins and
    logouts recorded symmetrically).

    The cookie is deleted with the same attributes it was set with - a
    mismatched path or samesite leaves the original in place, and the user
    stays signed in while being told they are not."""
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )
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
