"""Action routes (spec: "Canvas buttons/forms writing back to object
instances → source datasets").

Action types are workspace-scoped (they name writable properties on a
workspace object type), same split as object types/link types vs. object
type sources: definitions live under
``/workspaces/{workspace_id}/action-types``; executing one always targets a
specific instance whose data lives in exactly one project, so execution is
project-scoped under
``/workspaces/{workspace_id}/projects/{project_id}/actions``.

Role floors (conservative, flagged, consistent with the rest of objects.py):
read = viewer; action type create/delete = workspace editor+ (same floor as
object/link types); execute = project editor+ (it's a write to project
data, same floor as dataset/model/source mutations).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import actions as actions_service
from ..services import audit
from ..services import dataset_engine as engine
from ..services import datasets as dataset_service
from ..services import instances as instances_service
from ..services import ontology as ontology_service
from ..services.dataset_engine import DatasetEngineError
from .objects import InstanceOut

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["actions"])
project_router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/actions", tags=["actions"]
)


def _dataset_storage():
    from . import datasets as dataset_routes

    return dataset_routes._storage


def _parse_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class ActionTypeOut(BaseModel):
    id: UUID
    object_type_id: UUID
    object_type_name: str
    api_name: str
    display_name: str
    description: str
    editable_properties: list[str]
    created_at: datetime
    updated_at: datetime


class ActionTypeCreate(BaseModel):
    object_type_id: UUID
    api_name: str = Field(min_length=1, max_length=100, pattern="^[a-z][a-z0-9_]{0,99}$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    editable_properties: list[str] = Field(min_length=1, max_length=50)


class ActionRunOut(BaseModel):
    id: UUID
    instance_id: UUID | None
    dataset_id: UUID | None
    dataset_version: int | None
    submitted_values: dict[str, Any]
    status: str
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ExecuteRequest(BaseModel):
    instance_id: UUID
    values: dict[str, Any] = Field(default_factory=dict, max_length=50)


class ExecuteResult(BaseModel):
    ok: bool
    error: str | None
    dataset_version: int | None
    instance: InstanceOut


def _action_type_out(row: dict[str, Any]) -> ActionTypeOut:
    return ActionTypeOut(**{**row, "editable_properties": _parse_json(row["editable_properties"])})


# ---- action types (workspace-scoped) ----------------------------------------
@router.get("/action-types", response_model=list[ActionTypeOut])
async def list_action_types(
    object_type_id: UUID | None = Query(default=None),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ActionTypeOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await actions_service.list_action_types(
            conn, access.workspace_id, object_type_id=object_type_id
        )
    return [_action_type_out(r) for r in rows]


@router.post(
    "/action-types", response_model=ActionTypeOut, status_code=status.HTTP_201_CREATED
)
async def create_action_type(
    body: ActionTypeCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ActionTypeOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await actions_service.create_action_type(
            conn,
            workspace_id=access.workspace_id,
            object_type_id=body.object_type_id,
            api_name=body.api_name,
            display_name=body.display_name,
            description=body.description,
            editable_properties=body.editable_properties,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="action_type.create",
            resource_type="action_type",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"api_name": body.api_name, "object_type_id": str(body.object_type_id)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _action_type_out(row)


@router.get("/action-types/{action_type_id}", response_model=ActionTypeOut)
async def get_action_type(
    action_type_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ActionTypeOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await actions_service.get_action_type(conn, access.workspace_id, action_type_id)
    return _action_type_out(row)


@router.delete(
    "/action-types/{action_type_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_action_type(
    action_type_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await actions_service.delete_action_type(conn, access.workspace_id, action_type_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="action_type.delete",
            resource_type="action_type",
            resource_id=action_type_id,
            workspace_id=access.workspace_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


@router.get("/action-types/{action_type_id}/runs", response_model=list[ActionRunOut])
async def action_runs(
    action_type_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ActionRunOut]:
    async with user_connection(access.auth.user_id) as conn:
        await actions_service.get_action_type(conn, access.workspace_id, action_type_id)
        rows = await actions_service.list_runs(conn, action_type_id)
    return [
        ActionRunOut(**{**r, "submitted_values": _parse_json(r["submitted_values"])})
        for r in rows
    ]


# ---- execute (project-scoped) -------------------------------------------------
@project_router.post("/{action_type_id}/execute", response_model=ExecuteResult)
async def execute_action(
    action_type_id: UUID,
    body: ExecuteRequest,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ExecuteResult:
    storage = _dataset_storage()
    async with user_connection(access.auth.user_id) as conn:
        action_type = await actions_service.get_action_type(conn, access.workspace_id, action_type_id)
        object_type_id = UUID(str(action_type["object_type_id"]))
        instance = await instances_service.get(conn, object_type_id, body.instance_id)
        # 404s if this instance's source isn't a mapping in this project.
        source = await ontology_service.get_source(
            conn, access.project_id, UUID(str(instance["source_id"]))
        )
        properties = await ontology_service.list_properties(conn, object_type_id)
        property_types = {p["api_name"]: p["data_type"] for p in properties}
        column_mappings: dict[str, str] = _parse_json(source["column_mappings"])
        actions_service.validate_submitted_values(
            body.values,
            editable_properties=_parse_json(action_type["editable_properties"]),
            property_types=property_types,
            mapped_properties=set(column_mappings.values()),
        )
        run_id = await actions_service.open_run(
            conn,
            action_type_id=action_type_id,
            instance_id=body.instance_id,
            dataset_id=UUID(str(source["dataset_id"])),
            requested_by=access.auth.user_id,
            submitted_values=body.values,
        )

    ok, error = True, None
    dataset_version: int | None = None
    try:
        reverse_map = {prop: col for col, prop in column_mappings.items()}
        column_updates = {reverse_map[prop]: value for prop, value in body.values.items()}
        local_path = await anyio.to_thread.run_sync(
            storage.local_path, str(source["s3_location"])
        )
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.parquet")
            schema, row_count = await anyio.to_thread.run_sync(
                engine.write_back_row,
                local_path,
                str(source["primary_key_column"]),
                str(instance["primary_key"]),
                column_updates,
                dest,
            )
            with open(dest, "rb") as handle:
                parquet_bytes = handle.read()
        async with user_connection(access.auth.user_id) as conn:
            updated_dataset = await dataset_service.add_version(
                conn,
                storage,
                dataset_id=UUID(str(source["dataset_id"])),
                workspace_id=access.workspace_id,
                parquet_bytes=parquet_bytes,
                schema=schema,
                row_count=row_count,
                produced_by_kind="action",
                produced_by_id=run_id,
                created_by=access.auth.user_id,
            )
            dataset_version = int(updated_dataset["current_version"])
            await instances_service.update_properties(conn, body.instance_id, body.values)
    except DatasetEngineError as exc:
        ok, error = False, str(exc)

    async with user_connection(access.auth.user_id) as conn:
        await actions_service.close_run(
            conn, run_id, ok=ok, dataset_version=dataset_version, error=error
        )
        updated_instance = await instances_service.get(conn, object_type_id, body.instance_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="action.execute",
            resource_type="action_type",
            resource_id=action_type_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "instance_id": str(body.instance_id), "ok": ok,
                "properties": list(body.values.keys()),
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ExecuteResult(
        ok=ok,
        error=error,
        dataset_version=dataset_version,
        instance=InstanceOut(
            **{**updated_instance, "properties": _parse_json(updated_instance["properties"])}
        ),
    )
