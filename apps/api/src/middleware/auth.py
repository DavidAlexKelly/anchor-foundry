"""JWT authentication middleware (spec §9 "JWT Validation", steps 1-7):

  1. Validate the JWT signature against Cognito's public keys (fetched, cached)
  2. Check the token is not expired
  3. Verify audience and issuer match the expected Cognito pool
  4. Extract the cognito_sub
  5. Look up the user record by cognito_sub
  6. Attach user and organisation context to the request
  7. All subsequent permission checks use this context

Verification is behind the ``TokenVerifier`` protocol so tests can supply a
verifier keyed to a locally generated JWKS while production uses Cognito's.
Nothing downstream of step 4 differs between the two.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import jwt
from fastapi import Depends, Request
from jwt import PyJWKClient

from ..lib.config import Settings, get_settings
from ..lib.db import auth_lookup_connection, fetch_one
from ..lib.errors import UnauthorizedError


@dataclass(frozen=True)
class AuthContext:
    """Attached to every authenticated request (§9 step 6)."""

    user_id: UUID
    organisation_id: UUID
    email: str
    display_name: str
    org_role: str  # 'owner' | 'admin' | 'member'
    cognito_sub: str

    @property
    def is_org_admin(self) -> bool:
        return self.org_role in ("owner", "admin")


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, Any]:
        """Return validated claims or raise UnauthorizedError."""
        ...


class CognitoTokenVerifier:
    """Production verifier. PyJWKClient caches Cognito's JWKS (§9 step 1
    'fetched and cached') and handles key rotation via kid lookup."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._jwks = PyJWKClient(settings.jwks_url, cache_keys=True, lifespan=3600)

    def verify(self, token: str) -> dict[str, Any]:
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token)
            claims: dict[str, Any] = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],  # Cognito signs RS256 only; never accept others
                issuer=self._settings.issuer,  # §9 step 3 (issuer)
                options={"require": ["exp", "iss", "sub"], "verify_exp": True},  # §9 step 2
            )
        except jwt.PyJWTError as exc:
            raise UnauthorizedError(f"invalid token: {type(exc).__name__}") from exc

        # §9 step 3 (audience): Cognito puts the app client in `aud` on ID
        # tokens and `client_id` on access tokens; verify whichever is present.
        token_use = claims.get("token_use")
        if token_use == "access":
            if claims.get("client_id") != self._settings.cognito_client_id:
                raise UnauthorizedError("token client mismatch")
        elif token_use == "id":
            if claims.get("aud") != self._settings.cognito_client_id:
                raise UnauthorizedError("token audience mismatch")
        else:
            raise UnauthorizedError("unrecognised token_use")
        return claims


# Set at app startup; swapped in tests. Module-level because FastAPI
# dependencies need a stable callable.
_verifier: TokenVerifier | None = None
# Tiny in-process cache of sub -> (expiry, AuthContext) to avoid a DB round
# trip on every request within a short window. Access tokens live 15 minutes
# (§9); caching identity for 30s is a safe, bounded optimisation. Role and
# permission checks are NOT cached — they run against the DB on every request.
_identity_cache: dict[str, tuple[float, AuthContext]] = {}
_IDENTITY_CACHE_TTL_S = 30.0


def configure_verifier(verifier: TokenVerifier) -> None:
    global _verifier
    _verifier = verifier


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = CognitoTokenVerifier(get_settings())
    return _verifier


def _extract_bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise UnauthorizedError("missing bearer token")
    token = header[len("Bearer ") :].strip()
    if not token:
        raise UnauthorizedError("empty bearer token")
    return token


async def get_current_user(request: Request) -> AuthContext:
    """FastAPI dependency: §9 steps 1-6. Every API route depends on this
    (directly or via the permission dependencies); no route executes business
    logic without it."""
    token = _extract_bearer(request)
    claims = get_verifier().verify(token)  # steps 1-3
    sub = str(claims["sub"])  # step 4

    cached = _identity_cache.get(sub)
    if cached is not None and cached[0] > time.monotonic():
        ctx = cached[1]
    else:
        # Step 5: DB lookup by cognito_sub, under the narrow auth-lookup RLS
        # context (db 0007) — only this user's row is visible.
        async with auth_lookup_connection(sub) as conn:
            row = await fetch_one(
                conn,
                """
                SELECT id, organisation_id, email, display_name, org_role, status
                  FROM users
                 WHERE cognito_sub = :sub
                """,
                {"sub": sub},
            )
        if row is None:
            # Valid Cognito identity with no platform user: not provisioned.
            raise UnauthorizedError("user is not provisioned in this organisation")
        if row["status"] != "active":
            raise UnauthorizedError("user account is disabled")
        ctx = AuthContext(
            user_id=row["id"],
            organisation_id=row["organisation_id"],
            email=str(row["email"]),
            display_name=str(row["display_name"]),
            org_role=str(row["org_role"]),
            cognito_sub=sub,
        )
        _identity_cache[sub] = (time.monotonic() + _IDENTITY_CACHE_TTL_S, ctx)

    request.state.auth = ctx  # step 6
    return ctx


def clear_identity_cache() -> None:
    """For tests and for admin actions that disable users."""
    _identity_cache.clear()


CurrentUser = Depends(get_current_user)
