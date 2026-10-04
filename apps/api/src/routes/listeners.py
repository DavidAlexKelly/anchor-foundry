"""HTTPS listeners (§516; db 0106; `data-connection` p.249-266).

Two routers:

- **the listener's settings**, project-scoped: anybody who can read the
  project reads its listeners and their events; an editor creates, starts,
  stops, reconfigures and deletes one;
- **the endpoint**, `POST /api/listen/{token}`, with no authentication: the
  sender is a system that cannot call this API (p.249), and what it proves is
  the listener's own verification scheme.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..lib.db import get_engine, user_connection
from ..lib.errors import ConflictError
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import listener_archive as archive_service
from ..services import listeners as listener_service
from .connections import secrets_gateway
from .models import _dataset_storage

router = APIRouter(prefix="/workspaces/{workspace_id}/projects/{project_id}/listeners",
                   tags=["listeners"])
ingress_router = APIRouter(tags=["listeners"])


class EndpointOut(BaseModel):
    id: UUID
    #: The whole address a sender posts to, built from the address this
    #: request reached, so it is right behind whatever proxy is in front.
    url: str
    active: bool
    expired: bool
    expires_at: datetime | None
    created_at: datetime


class ListenerOut(BaseModel):
    id: UUID
    display_name: str
    #: p.262's named listener, or `custom` (§518).
    listener_type: str
    verification: str
    verification_header: str | None
    running: bool
    events: int
    last_event_at: datetime | None
    endpoints: list[EndpointOut]
    #: p.264's backing dataset (§519), once there is one.
    archive_dataset_name: str | None
    archive_dataset_resource_id: UUID | None
    archived_at: datetime | None
    #: Events the next archive run will write.
    pending_events: int
    #: p.254's custom ingress (§520); empty is inherited, no restriction.
    ingress_allowlist: list[str]
    #: Requests refused over p.261's rate limit (§521), and the latest.
    throttled: int
    throttled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ListenerCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    listener_type: str = "custom"
    #: Null takes the type's default scheme.
    verification: str | None = None
    verification_header: str | None = Field(default=None, max_length=100)
    #: Write-only. Kept in the secrets store and never returned.
    secret: str | None = Field(default=None, max_length=1000)


class ListenerConfigure(BaseModel):
    verification: str | None = None
    verification_header: str | None = Field(default=None, max_length=100)
    secret: str | None = Field(default=None, max_length=1000)


class ListenerRename(BaseModel):
    display_name: str = Field(min_length=1, max_length=200, pattern=r"\S")


class EventOut(BaseModel):
    id: int
    received_at: datetime
    content_type: str | None
    size_bytes: int
    #: The body as text, cut at PREVIEW_CHARS; null for a body that is not.
    preview: str | None
    truncated: bool
    headers: dict[str, str]


def public_base(request: Request) -> str:
    """Where a sender reaches this platform: `PLATFORM_PUBLIC_URL` when the
    deployment says, which a stack does with its distribution's address
    (§849), and the request's own address otherwise, as in development.

    Not the request's address in a stack. Behind CloudFront and the load
    balancer this process hears plain HTTP, so that was an `http://` endpoint:
    the token in its path crossed the network in clear before CloudFront
    redirected it, and a sender that does not follow a redirected POST - most
    of them - never arrived at all."""
    configured = os.environ.get("PLATFORM_PUBLIC_URL", "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _out(request: Request, row: dict[str, Any]) -> ListenerOut:
    base = public_base(request)
    endpoints = [EndpointOut(url=f"{base}/api/listen/{e['token']}", **{
        k: v for k, v in e.items() if k != "token"}) for e in row["endpoints"]]
    return ListenerOut(**{**{k: v for k, v in row.items() if k in ListenerOut.model_fields
                             and k != "endpoints"}, "endpoints": endpoints})


def _refused(exc: listener_service.ListenerError) -> ValueError:
    return ValueError(str(exc))


@router.get("", response_model=list[ListenerOut])
async def list_listeners(
    request: Request, access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ListenerOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await listener_service.list_listeners(conn, access.project_id)
    return [_out(request, r) for r in rows]


@router.post("", response_model=ListenerOut, status_code=status.HTTP_201_CREATED)
async def create_listener(
    body: ListenerCreate, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await listener_service.create(
                conn, secrets_gateway(), workspace_id=access.workspace_id,
                project_id=access.project_id, display_name=body.display_name,
                listener_type=body.listener_type, verification=body.verification, header=body.verification_header,
                secret=body.secret, by=access.auth.user_id)
        except listener_service.ListenerError as exc:
            raise _refused(exc) from exc
    return _out(request, row)


@router.get("/{listener_id}", response_model=ListenerOut)
async def get_listener(
    listener_id: UUID, request: Request,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await listener_service.get(conn, access.project_id, listener_id)
    return _out(request, row)


@router.patch("/{listener_id}", response_model=ListenerOut)
async def rename_listener(
    listener_id: UUID, body: ListenerRename, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await listener_service.rename(conn, access.project_id, listener_id, body.display_name)
    return _out(request, row)


@router.put("/{listener_id}/verification", response_model=ListenerOut)
async def configure_listener(
    listener_id: UUID, body: ListenerConfigure, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await listener_service.configure(
                conn, secrets_gateway(), access.project_id, listener_id,
                verification=body.verification, header=body.verification_header,
                secret=body.secret)
        except listener_service.ListenerError as exc:
            raise _refused(exc) from exc
    return _out(request, row)


@router.post("/{listener_id}/start", response_model=ListenerOut)
async def start_listener(
    listener_id: UUID, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await listener_service.set_running(conn, access.project_id, listener_id, True)
    return _out(request, row)


@router.post("/{listener_id}/stop", response_model=ListenerOut)
async def stop_listener(
    listener_id: UUID, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await listener_service.set_running(conn, access.project_id, listener_id, False)
    return _out(request, row)


@router.delete("/{listener_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_listener(
    listener_id: UUID, access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await listener_service.delete(conn, secrets_gateway(), access.project_id, listener_id)


class IngressIn(BaseModel):
    allowlist: list[str] = Field(default_factory=list, max_length=200)


@router.put("/{listener_id}/ingress", response_model=ListenerOut)
async def set_ingress(
    listener_id: UUID, body: IngressIn, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    """p.254-255's ingress allowlist for one listener (§520)."""
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await listener_service.set_allowlist(conn, access.project_id, listener_id,
                                                       body.allowlist)
        except listener_service.ListenerError as exc:
            raise _refused(exc) from exc
    return _out(request, row)


class RotateIn(BaseModel):
    #: When the endpoint being replaced stops answering; null deletes it now
    #: (p.258: "set an expiration date … for zero-downtime rotations, or …
    #: delete it immediately").
    expire_old_at: datetime | None = None


class ExtendIn(BaseModel):
    expires_at: datetime


@router.post("/{listener_id}/endpoints/rotate", response_model=ListenerOut)
async def rotate_endpoint(
    listener_id: UUID, body: RotateIn, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    """p.258's Rotate endpoints (§517)."""
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await listener_service.rotate(conn, access.project_id, listener_id,
                                                body.expire_old_at)
        except listener_service.ListenerError as exc:
            raise ConflictError(str(exc)) from exc
    return _out(request, row)


@router.put("/{listener_id}/endpoints/{endpoint_id}", response_model=ListenerOut)
async def extend_endpoint(
    listener_id: UUID, endpoint_id: UUID, body: ExtendIn, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    """p.259's extension of a retiring endpoint (§517)."""
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await listener_service.extend(conn, access.project_id, listener_id,
                                                endpoint_id, body.expires_at)
        except listener_service.ListenerError as exc:
            raise ConflictError(str(exc)) from exc
    return _out(request, row)


@router.delete("/{listener_id}/endpoints/{endpoint_id}", response_model=ListenerOut)
async def delete_endpoint(
    listener_id: UUID, endpoint_id: UUID, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ListenerOut:
    async with user_connection(access.auth.user_id) as conn:
        try:
            row = await listener_service.delete_endpoint(conn, access.project_id, listener_id,
                                                         endpoint_id)
        except listener_service.ListenerError as exc:
            raise ConflictError(str(exc)) from exc
    return _out(request, row)


class ArchiveOut(BaseModel):
    #: How many events this run wrote; zero when there was nothing new.
    archived: int
    #: The dataset version it made, when it made one.
    version: int | None
    listener: ListenerOut


@router.post("/{listener_id}/archive", response_model=ArchiveOut)
async def archive_listener(
    listener_id: UUID, request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ArchiveOut:
    """p.264's archive, now rather than at the next five-minute run (§519)."""
    async with user_connection(access.auth.user_id) as conn:
        await listener_service.get(conn, access.project_id, listener_id)
        done = await archive_service.archive(conn, _dataset_storage(), listener_id,
                                             by=access.auth.user_id)
        row = await listener_service.get(conn, access.project_id, listener_id)
    return ArchiveOut(archived=done["archived"] if done else 0,
                      version=done["version"] if done else None, listener=_out(request, row))


@router.get("/{listener_id}/events", response_model=list[EventOut])
async def listener_events(
    listener_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[EventOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await listener_service.events(conn, access.project_id, listener_id, limit)
    return [EventOut(**r) for r in rows]


def _proxy_hops() -> int:
    """How many proxies stand between a sender and this process, from
    LISTENER_PROXY_HOPS (one behind the ALB, set in the CDK services
    construct; none in development)."""
    raw = os.environ.get("LISTENER_PROXY_HOPS", "0")
    return int(raw) if raw.isdigit() else 0


@ingress_router.post("/listen/{token}")
async def receive(token: str, request: Request) -> JSONResponse:
    """p.261's endpoint. **No user**: what a request proves is its listener's
    scheme, checked in `listener_service.accept`. Counting the request
    (`admit`) and appending the event are the only things this route can
    make happen.

    The body is read only to one byte past the limit (`read_capped`), so an
    oversized request is refused without holding all of it."""
    body = await listener_service.read_capped(request.stream(), listener_service.MAX_BODY)
    headers = {k.lower(): v for k, v in request.headers.items()}
    try:
        async with get_engine().begin() as conn:
            found = await listener_service.admit(
                conn, token, sender=listener_service.sender_address(
                    request.client.host if request.client else None,
                    request.headers.get("x-forwarded-for"), _proxy_hops()))
        # A second transaction, so the count above stands whatever is
        # decided here (db 0110).
        async with get_engine().begin() as conn:
            taken = await listener_service.accept(
                conn, secrets_gateway(), found, headers, body, query=dict(request.query_params),
                url=str(request.url))
    except listener_service.Refusal as refusal:
        return JSONResponse({"detail": refusal.detail}, status_code=refusal.status,
                            headers=refusal.headers)
    if "challenge" in taken:
        return JSONResponse({"challenge": taken["challenge"]})
    return JSONResponse({"received": True, "event": taken["event"]})
