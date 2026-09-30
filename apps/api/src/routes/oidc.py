"""The OpenID Connect discovery document and key set (§599; `data-connection`
p.391).

**No user**, as a source system fetching them has none: they say only which
key checks this platform's tokens, which is what they are for. Both answer
404 when the deployment has not set the platform up as an identity provider,
so a source system configured against it fails at its first fetch rather
than trusting a document that names no key.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from ..services import oidc as oidc_service

router = APIRouter(prefix="/oidc", tags=["oidc"])


def _served(build) -> dict[str, Any]:
    try:
        return build()
    except oidc_service.OidcUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from None


@router.get("/.well-known/openid-configuration")
async def openid_configuration() -> dict[str, Any]:
    return _served(oidc_service.discovery)


@router.get("/jwks")
async def jwks() -> dict[str, Any]:
    return _served(oidc_service.jwks)
