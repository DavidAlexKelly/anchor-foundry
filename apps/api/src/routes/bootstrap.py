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

from uuid import UUID

from fastapi import APIRouter, status
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
    return BootstrapStatus(needs_setup=needs_setup)


@router.post("/first-owner", response_model=FirstOwnerOut, status_code=status.HTTP_201_CREATED)
async def bootstrap_first_owner(body: FirstOwnerIn) -> FirstOwnerOut:
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
