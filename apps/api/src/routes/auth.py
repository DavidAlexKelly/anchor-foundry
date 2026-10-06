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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..lib.config import get_settings
from ..lib.db import user_connection
from ..lib.errors import UnauthorizedError
from ..lib.observability import API_PREFIX
from ..middleware.auth import (
    SESSION_COOKIE,
    SESSION_HEADER,
    AuthContext,
    authenticate_token,
    get_current_user,
)
from ..services import audit, cognito_tokens

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


class SignInConfig(BaseModel):
    """Where the web app sends a person to sign in. Both null when this
    deployment has no hosted UI, as in development."""
    domain: str | None
    client_id: str | None


@router.get("/config", response_model=SignInConfig)
async def sign_in_config() -> SignInConfig:
    """The hosted UI's address and the app client, for the sign-in page (§851).

    Public, since it is what a person who is not signed in needs, and nothing
    in it is a secret: both appear in the address bar the moment sign-in
    starts. The web app used to read them from `NEXT_PUBLIC_COGNITO_*`, which
    Next writes into the bundle at build time. One web image serves every
    customer's stack, each with its own pool, and the documented builds pass
    neither - so a deployed sign-in page had no hosted UI to send anyone to.
    """
    settings = get_settings()
    configured = bool(settings.cognito_domain and settings.cognito_client_id)
    return SignInConfig(
        domain=settings.cognito_domain.rstrip("/") if configured else None,
        client_id=settings.cognito_client_id if configured else None,
    )


#: Cognito's refresh token (§859), in a cookie of its own. Sent only to the
#: renewal route - `path` - and never cross-site, so it travels on one request
#: in fifteen minutes rather than on every one.
REFRESH_COOKIE = "anchor_refresh"
REFRESH_PATH = f"{API_PREFIX}/auth/refresh"


class SessionIn(BaseModel):
    access_token: str = Field(min_length=1, max_length=8192)
    #: Cognito's, from the same token response. Optional: a development token
    #: has none, and a session without one simply cannot be renewed.
    refresh_token: str | None = Field(default=None, min_length=1, max_length=8192)


def _set_session(response: Response, access_token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        access_token,
        httponly=True,
        secure=get_settings().session_cookie_secure,
        samesite="lax",
        path="/",
        # No max-age: a session cookie, so closing the browser ends it. The
        # token's own expiry still bounds it independently - the cookie is a
        # carrier, not a second source of truth about how long a session lasts.
    )


def _refresh_cookie(response: Response, value: str | None) -> None:
    """Set it, or with None delete it - with the same attributes either way,
    because a delete that names another path leaves the original in place."""
    attributes = {"path": REFRESH_PATH, "httponly": True,
                  "secure": get_settings().session_cookie_secure, "samesite": "strict"}
    if value is None:
        response.delete_cookie(REFRESH_COOKIE, **attributes)
    else:
        response.set_cookie(REFRESH_COOKIE, value, **attributes)


def _me(auth: AuthContext) -> Me:
    return Me(
        user_id=auth.user_id,
        organisation_id=auth.organisation_id,
        email=auth.email,
        display_name=auth.display_name,
        org_role=auth.org_role,
    )


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
    _set_session(response, body.access_token)
    if body.refresh_token:
        _refresh_cookie(response, body.refresh_token)
    return _me(auth)


@router.post("/refresh", response_model=Me)
async def refresh_session(request: Request, response: Response) -> Me | JSONResponse:
    """A new session from the refresh cookie, when the access token has run
    out (§859). The web client calls this on a 401 and retries what failed, so
    a session lasts as long as Cognito's refresh token rather than fifteen
    minutes.

    The CSRF header is required here as on every cookie-authenticated route,
    though the cookie is SameSite=Strict as well: a renewal is a credential
    being issued, and a cross-site page must not be able to cause one.
    """
    if not request.headers.get(SESSION_HEADER):
        raise UnauthorizedError(f"renewing a session requires the {SESSION_HEADER} header")
    token = request.cookies.get(REFRESH_COOKIE, "").strip()
    if not token:
        raise UnauthorizedError("there is no session to renew")
    settings = get_settings()
    if not (settings.cognito_domain and settings.cognito_client_id):
        raise UnauthorizedError("this deployment does not renew sessions")
    try:
        access = await cognito_tokens.refreshed_access_token(
            settings.cognito_domain, settings.cognito_client_id, token)
    except cognito_tokens.RefreshRefused as exc:
        # Over for good: say so, and drop the cookie so the next 401 goes
        # straight to sign-in rather than asking Cognito again. A raised error
        # would discard this response, cookie deletion and all.
        refused = JSONResponse(status_code=401, content={
            "detail": f"the session could not be renewed ({exc}) - sign in again"})
        _refresh_cookie(refused, None)
        return refused
    except cognito_tokens.RefreshUnavailable as exc:
        return JSONResponse(status_code=503, content={
            "detail": f"the session could not be renewed just now: {exc}"})
    auth = await authenticate_token(access)
    _set_session(response, access)
    return _me(auth)


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
    # And what would have renewed it (§859): signing out that left this would
    # be undone by the next request's renewal.
    _refresh_cookie(response, None)
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
