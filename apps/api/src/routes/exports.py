"""Export routes (decision 0014; `data-connection` p.192-206; §265).

An export lives in a project, beside the source it writes to and the dataset it
reads — p.203 creates one "from the Overview page of the source to which you
want to export", and the URL says so.

**Role floors.** Read at project viewer; create, delete and **run** at project
editor. Running is an editor's act for the same reason `POST
/connections/{id}/test` is: it reaches out of the platform, and a viewer's read
should not become a write to somebody else's database.

**Enabling exports on a source is a workspace admin's act, and it is not here.**
p.202 gives that to the `Information Security Officer` role; this platform has
no such role and workspace admin is the nearest, which decision 0014 §4 records
as a genuine narrowing. It lives on the connections router because it is a
property of the source, not of any export — and putting it here would let a
project editor reach a workspace-level switch by finding the right URL.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ConflictError, NotFoundError
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import connections as conn_service
from ..services import datasets as ds_service
from ..services import egress_store, export_runs, export_store
from ..services import exports as exports_service
from ..services.storage import StorageKeyError
from . import connections as connection_routes
from . import datasets as dataset_routes

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/exports",
    tags=["exports"],
)


class ExportOut(BaseModel):
    id: UUID
    project_id: UUID
    connection_id: UUID
    connection_name: str
    connection_source_type: str
    dataset_id: UUID
    dataset_name: str
    #: The dataset's current version, so a caller can see at a glance whether
    #: this export is behind — which is p.192's whole question and otherwise
    #: needs a second request per row.
    dataset_version: int
    name: str
    kind: str
    mode: str | None
    destination: dict[str, Any]
    last_version: int | None
    created_at: datetime
    updated_at: datetime


class ExportCreate(BaseModel):
    """Validated by `services/exports.parse` rather than here, for the reason
    every other create in this codebase gives: pydantic can say a field is a
    string, and what this needs said is that the string is a table name, that
    the mode belongs to the kind, and that the dataset has no Struct column."""

    connection_id: UUID
    dataset_id: UUID
    name: str = Field(min_length=1, max_length=exports_service.MAX_NAME)
    mode: str | None = None
    destination: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: UUID
    status: str
    skipped: bool
    dataset_version: int | None
    rows_written: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class RunPage(BaseModel):
    runs: list[RunOut]
    total: int
    limit: int
    offset: int


@router.get("", response_model=list[ExportOut])
async def list_exports(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ExportOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await export_store.list_for_project(conn, access.project_id)
    return [ExportOut(**row) for row in rows]


@router.get("/{export_id}", response_model=ExportOut)
async def get_export(
    export_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ExportOut:
    async with user_connection(access.auth.user_id) as conn:
        return ExportOut(**await export_store.get(conn, access.project_id, export_id))


@router.post("", response_model=ExportOut, status_code=status.HTTP_201_CREATED)
async def create_export(
    body: ExportCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ExportOut:
    async with user_connection(access.auth.user_id) as conn:
        # Both refusals happen here and neither is the other: whether this
        # source is a possible destination, and whether somebody has turned
        # exports on for it (p.202).
        connection = await export_store.connection_for(
            conn, access.project_id, body.connection_id
        )
        dataset = await ds_service.get(conn, access.project_id, body.dataset_id)
        config = exports_service.parse(
            body.model_dump(),
            source_type=str(connection["source_type"]),
            schema=list(dataset["table_schema"] or []),
        )
        row = await export_store.create(
            conn,
            project_id=access.project_id,
            connection_id=body.connection_id,
            dataset_id=body.dataset_id,
            config=config,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="export.create",
            resource_type="export",
            resource_id=UUID(str(row["id"])),
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": config["name"], "kind": config["kind"],
                      "mode": config["mode"], "dataset": str(body.dataset_id)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await conn.commit()
    return ExportOut(**row)


@router.delete("/{export_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_export(
    export_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        existing = await export_store.get(conn, access.project_id, export_id)
        await export_store.delete(conn, access.project_id, export_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="export.delete",
            resource_type="export",
            resource_id=export_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": existing["name"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await conn.commit()


@router.post("/{export_id}/run", response_model=RunOut)
async def run_export(
    export_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> RunOut:
    """p.205: "Manually run the export."

    **Every outcome is recorded, including the one where nothing happened.**
    p.192's June 2025 change makes "nothing new to export" a success, and a
    success that left no row would make a schedule's history read as gaps —
    "nothing happened" and "nothing ran" being exactly the two answers a person
    looking at that list is trying to tell apart.
    """
    async with user_connection(access.auth.user_id) as conn:
        export = await export_store.get(conn, access.project_id, export_id)
        # Re-checked at run time, not only at create time. p.202's switch is
        # reversible, and an export configured while it was on must stop
        # working when somebody turns it off — otherwise the control only ever
        # applies to exports nobody has made yet.
        connection = await export_store.connection_for(
            conn, access.project_id, UUID(str(export["connection_id"]))
        )
        dataset = await ds_service.get(
            conn, access.project_id, UUID(str(export["dataset_id"]))
        )
        policies = await egress_store.for_connection(conn, UUID(str(connection["id"])))

    version = int(dataset["current_version"] or 0)
    if version < 1:
        raise ConflictError(
            f"{dataset['name']} has no versions yet, so there is nothing to export"
        )

    secret = conn_service.secret_values_for(
        connection_routes.secrets_gateway(), connection
    )
    # The bytes of the current version. Resolved before the call so a missing
    # file is a recorded failure with a sentence rather than an exception from
    # inside a worker thread.
    #
    # Three ways this can come back empty, and they end in the same place: no
    # version row, a version row with no recorded key, or a key whose bytes are
    # gone from storage. All three are an export that could not read its input,
    # which is a **recorded failure** rather than a 500 — `perform` turns the
    # None into the sentence. The exception list is enumerated rather than bare,
    # for the reason §263 relearned in the worker: a broad `except` here would
    # also swallow a bug in the lookup and report it as a missing file.
    parquet_path: str | None = None
    try:
        async with user_connection(access.auth.user_id) as conn:
            location = await ds_service.version_location(
                conn, access.project_id, UUID(str(export["dataset_id"])), version
            )
        key = str(location["s3_manifest_key"] or "")
        if key:
            parquet_path = await anyio.to_thread.run_sync(
                dataset_routes.storage().local_path, key
            )
    except (NotFoundError, FileNotFoundError, StorageKeyError, OSError):
        parquet_path = None

    outcome = await export_runs.perform(
        export, connection, secret,
        parquet_path=parquet_path,
        dataset_version=version,
        dataset_schema=list(dataset["table_schema"] or []),
        policies=policies,
    )

    async with user_connection(access.auth.user_id) as conn:
        run = await export_store.record(
            conn, export_id=export_id, result=outcome, run_by=access.auth.user_id
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="export.run",
            resource_type="export",
            resource_id=export_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "ok": outcome["ok"], "skipped": outcome["skipped"],
                "rows": outcome["rows_written"], "version": version,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        await conn.commit()
    return RunOut(**run)


@router.get("/{export_id}/runs", response_model=RunPage)
async def list_runs(
    export_id: UUID,
    limit: int = Query(export_store.PAGE, ge=1, le=export_store.PAGE),
    offset: int = Query(0, ge=0),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> RunPage:
    """p.206: "the History view of an export shows the history of the jobs
    associated with it."

    Bounded and paged from the start (§209, §256): this list grows on a timer
    once scheduling exists, so a route that returned all of it would be a route
    that gets slower every day nobody looks at it.
    """
    async with user_connection(access.auth.user_id) as conn:
        await export_store.get(conn, access.project_id, export_id)
        rows, total = await export_store.runs(
            conn, export_id, limit=limit, offset=offset
        )
    return RunPage(
        runs=[RunOut(**row) for row in rows], total=total, limit=limit, offset=offset
    )
