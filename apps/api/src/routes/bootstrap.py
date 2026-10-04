"""First-owner bootstrap (spec gap found during real deploy validation, see
STATUS.md §17): self-signup is disabled and the invite flow (routes/org.py)
refuses to grant 'owner', so a freshly provisioned customer stack had no way
at all to create its first organisation or user - every real deploy needed
this done by hand directly against Postgres. These are the only genuinely
unauthenticated write routes in the API, and deliberately so: the guard is a
one-time, atomic, database-level check (services/orgs.bootstrap_first_owner,
migration 0017), not a permission check, since by definition no user exists
yet to hold one.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from ..lib.db import get_engine
from ..services import orgs as org_service
from ..services.orgs import CognitoAdminGateway, NullCognitoGateway

router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])

# Injected at startup (production wires the boto3 gateway; tests/dev the null).
_cognito: CognitoAdminGateway = NullCognitoGateway()


def configure_cognito_gateway(gateway: CognitoAdminGateway) -> None:
    global _cognito
    _cognito = gateway


class BootstrapStatus(BaseModel):
    needs_setup: bool
    #: Set up by whoever provisioned the stack, not on this page (§886).
    by_provisioner: bool = False


#: SHA-256 of the token the provisioner holds, in hex (§886).
TOKEN_HASH_ENV = "BOOTSTRAP_TOKEN_SHA256"


def _required_token_hash() -> str:
    return os.environ.get(TOKEN_HASH_ENV, "").strip().lower()


def _check_token(authorization: str) -> None:
    """**Only the provisioner may name a stack's first owner, where it says
    so (§886; roadmap E.28).** A stack is reachable at its address the moment
    it is deployed, and this route needs no sign-in, so whoever found the
    address before the customer's first visit could make themselves owner.

    The control plane derives a token for each stack, passes its SHA-256 to
    the deploy, and creates the first owner itself as soon as the stack is up,
    from the organisation and address the customer gave at onboarding. The
    template carries only the hash. Without it set, as in development, the
    setup page works as it always has."""
    wanted = _required_token_hash()
    if not wanted:
        return
    given = authorization.removeprefix("Bearer ").strip()
    digest = hashlib.sha256(given.encode()).hexdigest()
    if not given or not hmac.compare_digest(digest, wanted):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="this platform is set up by its provider; sign in with the "
                   "invitation it sent instead")


class FirstOwnerIn(BaseModel):
    organisation_name: str = Field(min_length=1, max_length=200)
    # Same pattern migration 0001 enforces on organisations.slug.
    organisation_slug: str = Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    owner_email: EmailStr
    owner_display_name: str = Field(min_length=1, max_length=120)


class FirstOwnerOut(BaseModel):
    organisation_id: UUID


@router.get("/status", response_model=BootstrapStatus)
async def bootstrap_status() -> BootstrapStatus:
    async with get_engine().connect() as conn:
        needs_setup = await org_service.platform_needs_setup(conn)
    return BootstrapStatus(needs_setup=needs_setup, by_provisioner=bool(_required_token_hash()))


@router.post("/first-owner", response_model=FirstOwnerOut, status_code=status.HTTP_201_CREATED)
async def bootstrap_first_owner(
    body: FirstOwnerIn, authorization: str = Header(default="")
) -> FirstOwnerOut:
    _check_token(authorization)
    async with get_engine().begin() as conn:
        org_id = await org_service.bootstrap_first_owner(
            conn,
            _cognito,
            org_name=body.organisation_name,
            org_slug=body.organisation_slug,
            owner_email=body.owner_email,
            owner_display_name=body.owner_display_name,
        )
    return FirstOwnerOut(organisation_id=org_id)
