"""Webhook routes (decision 0012; `data-connection` p.216-242; §259).

A webhook lives in a project, beside the connection it is built on, because
that is where p.216 puts it: "each webhook is associated with a single source
in Data Connection". The URL says so.

**Role floors.** Read at project viewer; create, edit and delete at project
editor, matching connections — a webhook is a request against somebody else's
system and configuring one is an editor's act. The **test call** (p.222: "after
saving, you will be able to run a test request to see if your configuration is
correct") is also editor, for the same reason `POST /connections/{id}/test` is:
it reaches out of the platform, and a viewer's read should not.

**History is not gated by role at all**, and that is deliberate: db 0067's
policy scopes a run to the person who made it, so a project admin reading
somebody else's test responses is not a thing this API can express. p.242 is
explicit that it should not be, and the privileged read it names has no
custom-role mechanism here to hang off.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import (
    ProjectAccess,
    WorkspaceAccess,
    require_project_role,
    require_workspace_role,
)
from ..services import audit
from ..services import connections as conn_service
from ..services import egress_store, webhook_calls, webhook_store
from ..services import webhooks as webhooks_service
from . import connections as connection_routes

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/webhooks",
    tags=["webhooks"],
)

#: The workspace-wide listing, for the one caller that needs it: the action
#: definition editor's picker. An action type is a workspace resource, so a
#: rule may name any webhook the caller can see — and a picker fed by the
#: project listing would offer a narrower set than the server accepts, which is
#: §258's defect exactly.
workspace_router = APIRouter(
    prefix="/workspaces/{workspace_id}/webhooks", tags=["webhooks"]
)


# **No gateway of its own**, and that is the point. The secret a webhook sends
# is the *connection's*, so it comes from the one place connections keep it.
# A second module-level `_secrets` with its own `configure_` would be a second
# thing for `_wire_production_gateways` to forget, and §17's comment on that
# function records what forgetting it cost the first time: credentials that
# only ever lived in process memory on every deployed stack.


# ---- schemas --------------------------------------------------------------------
class WebhookDefinition(BaseModel):
    """The request shape. Validated by `services/webhooks.parse` rather than
    here: pydantic can say a field is a string, and what this needs said is
    that a reference in it names a declared input."""

    method: str = "POST"
    path: str = ""
    query: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    body: Any = None
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    outputs: list[dict[str, Any]] = Field(default_factory=list)
    store_responses: bool = True
    retry_statuses: list[int] = Field(default_factory=list)
    timeout_seconds: int = 20


class WebhookCreate(WebhookDefinition):
    connection_id: UUID
    api_name: str = Field(min_length=1, max_length=63)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class WebhookUpdate(WebhookDefinition):
    connection_id: UUID
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class WebhookOut(BaseModel):
    id: UUID
    workspace_id: UUID
    project_id: UUID
    connection_id: UUID
    connection_name: str
    api_name: str
    display_name: str
    description: str
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    body: Any = None
    inputs: list[dict[str, Any]]
    outputs: list[dict[str, Any]]
    store_responses: bool
    retry_statuses: list[int]
    timeout_seconds: int
    created_at: datetime
    updated_at: datetime


class TestCall(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: UUID
    mode: str
    ok: bool
    status_code: int | None = None
    #: p.237's three-valued answer. `None` means *unknown*, which is not the
    #: same as `false` and must not be rendered as one.
    system_changed: bool | None = None
    error: str | None = None
    duration_ms: int | None = None
    #: NULL when the webhook has `store_responses` off (p.242). An absent body
    #: is "deliberately not kept"; an empty one is a stored empty body.
    request_body: Any = None
    response_body: Any = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    action_run_id: UUID | None = None
    created_at: datetime


class RunPage(BaseModel):
    items: list[RunOut]
    total: int
    limit: int
    offset: int


def _out(row: dict[str, Any]) -> WebhookOut:
    return WebhookOut(**{k: v for k, v in row.items() if k in WebhookOut.model_fields})


@workspace_router.get("", response_model=list[WebhookOut])
async def list_workspace_webhooks(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[WebhookOut]:
    """Every webhook this workspace has, for the action definition editor.

    **Below `WebhookOut` rather than beside `workspace_router`**, which is not
    style: a `response_model` is evaluated when the decorator runs, so a
    forward reference there is a pydantic error at import time rather than a
    type-checker's complaint.
    """
    async with user_connection(access.auth.user_id) as conn:
        rows = await webhook_store.list_for_workspace(conn, access.workspace_id)
    return [_out(row) for row in rows]


# ---- CRUD -----------------------------------------------------------------------
@router.get("", response_model=list[WebhookOut])
async def list_webhooks(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[WebhookOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await webhook_store.list_for_project(conn, access.project_id)
    return [_out(row) for row in rows]


@router.get("/{webhook_id}", response_model=WebhookOut)
async def get_webhook(
    webhook_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> WebhookOut:
    async with user_connection(access.auth.user_id) as conn:
        return _out(await webhook_store.get(conn, webhook_id))


@router.post("", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
async def create_webhook(
    body: WebhookCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> WebhookOut:
    definition = webhooks_service.parse(body.model_dump(exclude={
        "connection_id", "api_name", "display_name", "description",
    }))
    async with user_connection(access.auth.user_id) as conn:
        # The connection is resolved *before* the insert rather than left to
        # the foreign key: the FK would answer "no such row" for a connection
        # in another project and for one of the wrong source type alike, and
        # those are different sentences.
        await webhook_store.connection_for(conn, access.project_id, body.connection_id)
        row = await webhook_store.create(
            conn,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            connection_id=body.connection_id,
            api_name=body.api_name,
            display_name=body.display_name,
            description=body.description,
            definition=definition,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="webhook.create",
            resource_type="webhook",
            resource_id=UUID(str(row["id"])),
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"api_name": body.api_name, "method": definition["method"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.put("/{webhook_id}", response_model=WebhookOut)
async def update_webhook(
    webhook_id: UUID,
    body: WebhookUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> WebhookOut:
    definition = webhooks_service.parse(body.model_dump(exclude={
        "connection_id", "display_name", "description",
    }))
    async with user_connection(access.auth.user_id) as conn:
        await webhook_store.connection_for(conn, access.project_id, body.connection_id)
        row = await webhook_store.update(
            conn, webhook_id,
            display_name=body.display_name,
            description=body.description,
            connection_id=body.connection_id,
            definition=definition,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="webhook.update",
            resource_type="webhook",
            resource_id=webhook_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"method": definition["method"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_webhook(
    webhook_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await webhook_store.delete(conn, webhook_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="webhook.delete",
            resource_type="webhook",
            resource_id=webhook_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- the test call (p.222) ------------------------------------------------------
@router.post("/{webhook_id}/test", response_model=RunOut)
async def test_webhook(
    webhook_id: UUID,
    body: TestCall,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> RunOut:
    """p.222: "After saving, you will be able to run a test request to see if
    your configuration is correct."

    **Recorded in the history like any other call**, with mode `test`. A test
    that left no trace would be a request to somebody's production system that
    the platform has no record of making — and p.222's next sentence is that
    the response is what output parameters get configured from, which means it
    has to be readable afterwards.
    """
    async with user_connection(access.auth.user_id) as conn:
        webhook = await webhook_store.get(conn, webhook_id)
        connection = await webhook_store.connection_for(
            conn, access.project_id, UUID(str(webhook["connection_id"]))
        )
    secret = conn_service.secret_values_for(
        connection_routes.secrets_gateway(), connection
    )
    async with user_connection(access.auth.user_id) as conn:
        # §263. A test call reaches out exactly as an action's would, so it is
        # scoped exactly as an action's is — a source's allowlist that the test
        # button could step around would be an allowlist with a button.
        policies = await egress_store.for_connection(
            conn, UUID(str(connection["id"]))
        )

    try:
        outcome = await webhook_calls.perform(
            webhook, connection, secret, body.values, policies
        )
    except webhooks_service.WebhookError as exc:
        # A request that could not be *built* — a missing required input — is a
        # fault in the call rather than in the response, so it is a 4xx here
        # rather than a recorded failure. Recording it would put a row in the
        # history for a request that was never made.
        raise
    async with user_connection(access.auth.user_id) as conn:
        run_id = await webhook_store.record(
            conn,
            webhook_id=webhook_id,
            workspace_id=access.workspace_id,
            action_run_id=None,
            called_by=access.auth.user_id,
            mode="test",
            result=outcome,
            store_responses=bool(webhook["store_responses"]),
        )
        rows, _ = await webhook_store.history(conn, webhook_id, limit=1)
    return RunOut(**{k: v for k, v in rows[0].items() if k in RunOut.model_fields})


@router.get("/{webhook_id}/runs", response_model=RunPage)
async def list_runs(
    webhook_id: UUID,
    limit: int = Query(default=webhook_store.PAGE, ge=1, le=webhook_store.PAGE),
    offset: int = Query(default=0, ge=0),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> RunPage:
    """p.242's history — **yours**, whatever your role.

    The webhook is fetched first so a missing one is a 404 rather than an empty
    page: "no runs" and "no such webhook" are different answers, and only one
    of them means somebody typed the wrong id.
    """
    async with user_connection(access.auth.user_id) as conn:
        await webhook_store.get(conn, webhook_id)
        rows, total = await webhook_store.history(
            conn, webhook_id, limit=limit, offset=offset
        )
    return RunPage(
        items=[
            RunOut(**{k: v for k, v in row.items() if k in RunOut.model_fields})
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
