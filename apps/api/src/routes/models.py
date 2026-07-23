"""Model routes (spec §17: /workspaces/{id}/projects/{id}/models).

Role floors (conservative, flagged): read = viewer; create/update/delete/run
= editor. SQL runs execute inline via the sandboxed DuckDB engine and the
route returns the finished result; Python runs (and any cron-fired run,
whatever the language) are left 'queued' for the worker's
scheduled_model_runs job to pick up — see services/models.py's docstring for
the full reasoning. The cancel endpoint remains out of scope: a synchronous
SQL run has no meaningful cancel, and a real cancel for queued/running
worker jobs isn't built here.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import dataset_engine as engine
from ..services import datasets as ds_service
from ..services import models as model_service
from ..services.dataset_engine import DatasetEngineError

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/models",
    tags=["models"],
)


def _dataset_storage():
    from . import datasets as dataset_routes

    return dataset_routes._storage


class ModelInputIn(BaseModel):
    dataset_id: UUID
    input_alias: str = Field(min_length=1, max_length=63)


class ModelInputOut(BaseModel):
    dataset_id: UUID
    input_alias: str
    dataset_name: str


class ModelOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    description: str
    language: str
    code: str
    output_dataset_id: UUID | None
    trigger_mode: str
    cron_schedule: str | None = None
    next_run_at: datetime | None = None
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    inputs: list[ModelInputOut] = []
    created_at: datetime
    updated_at: datetime


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    language: str = Field(default="sql", pattern="^(sql|python)$")
    code: str = Field(default="", max_length=100_000)
    inputs: list[ModelInputIn] = Field(default_factory=list, max_length=20)


class ModelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    code: str | None = Field(default=None, max_length=100_000)
    inputs: list[ModelInputIn] | None = Field(default=None, max_length=20)
    trigger_mode: str | None = Field(default=None, pattern="^(manual|cron|upstream)$")
    cron_schedule: str | None = Field(default=None, max_length=100)


class RunOut(BaseModel):
    id: UUID
    status: str
    trigger_kind: str
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    rows_produced: int | None
    error_message: str | None
    output_version: UUID | None


class RunResult(BaseModel):
    run_id: UUID
    status: str  # 'queued' | 'succeeded' | 'failed'
    ok: bool
    error: str | None
    rows_produced: int
    output_dataset: dict[str, Any] | None


async def _with_inputs(conn, row: dict[str, Any]) -> ModelOut:
    inputs = await model_service.list_inputs(conn, UUID(str(row["id"])))
    return ModelOut(**row, inputs=[ModelInputOut(**i) for i in inputs])


@router.get("", response_model=list[ModelOut])
async def list_models(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ModelOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await model_service.list_for_project(conn, access.project_id)
        return [await _with_inputs(conn, r) for r in rows]


@router.post("", response_model=ModelOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: ModelCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ModelOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await model_service.create(
            conn,
            project_id=access.project_id,
            name=body.name,
            description=body.description,
            language=body.language,
            code=body.code,
            inputs=[i.model_dump() for i in body.inputs],
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="model.create",
            resource_type="model",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": body.name, "inputs": len(body.inputs)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return await _with_inputs(conn, row)


@router.get("/{model_id}", response_model=ModelOut)
async def get_model(
    model_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ModelOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await model_service.get(conn, access.project_id, model_id)
        return await _with_inputs(conn, dict(row))


@router.patch("/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: UUID,
    body: ModelUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ModelOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await model_service.update(
            conn,
            access.project_id,
            model_id,
            name=body.name,
            description=body.description,
            code=body.code,
            inputs=[i.model_dump() for i in body.inputs] if body.inputs is not None else None,
            trigger_mode=body.trigger_mode,
            cron_schedule=body.cron_schedule,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="model.update",
            resource_type="model",
            resource_id=model_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"code_changed": body.code is not None,
                      "inputs_changed": body.inputs is not None,
                      "trigger_mode": body.trigger_mode},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return await _with_inputs(conn, row)


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_model(
    model_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await model_service.delete(conn, access.project_id, model_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="model.delete",
            resource_type="model",
            resource_id=model_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


@router.post("/{model_id}/run", response_model=RunResult)
async def run_model(
    model_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> RunResult:
    storage = _dataset_storage()
    async with user_connection(access.auth.user_id) as conn:
        model = dict(await model_service.get(conn, access.project_id, model_id))
        inputs = await model_service.list_inputs(conn, model_id)
        if not str(model["code"]).strip():
            raise DatasetEngineError("the model has no code yet")
        if not inputs:
            raise DatasetEngineError("add at least one input dataset before running")

        if model["language"] == "python":
            # Needs a real process boundary DuckDB can't give it — leave the
            # run queued for the worker's scheduled_model_runs job and return
            # immediately rather than blocking on its poll cycle.
            run_id = await model_service.open_queued_run(conn, model_id, access.auth.user_id)
            await audit.record(
                conn,
                organisation_id=access.auth.organisation_id,
                user_id=access.auth.user_id,
                action="model.run",
                resource_type="model",
                resource_id=model_id,
                workspace_id=access.workspace_id,
                project_id=access.project_id,
                metadata={"status": "queued", "language": "python"},
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            )
            return RunResult(
                run_id=run_id, status="queued", ok=True, error=None,
                rows_produced=0, output_dataset=None,
            )

        input_paths: dict[str, str] = {}
        for item in inputs:
            ds_row = await ds_service.get(
                conn, access.project_id, UUID(str(item["dataset_id"]))
            )
            path = await anyio.to_thread.run_sync(
                storage.local_path, str(ds_row["s3_location"])
            )
            input_paths[str(item["input_alias"])] = path
        run_id = await model_service.open_run(conn, model_id, access.auth.user_id)

    ok, error, rows_produced = True, None, 0
    output_dataset: dict[str, Any] | None = None
    output_version_id: UUID | None = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.parquet")
            schema, rows_produced = await anyio.to_thread.run_sync(
                engine.run_transform, input_paths, str(model["code"]), dest
            )
            with open(dest, "rb") as handle:
                parquet_bytes = handle.read()
        async with user_connection(access.auth.user_id) as conn:
            output_dataset, output_version_id = await model_service.record_output(
                conn,
                storage,
                model=model,
                workspace_id=access.workspace_id,
                project_id=access.project_id,
                parquet_bytes=parquet_bytes,
                schema=schema,
                row_count=rows_produced,
                triggered_by=access.auth.user_id,
            )
    except DatasetEngineError as exc:
        ok, error = False, str(exc)

    async with user_connection(access.auth.user_id) as conn:
        await model_service.close_run(
            conn,
            run_id,
            ok=ok,
            rows_produced=rows_produced if ok else None,
            output_version_id=output_version_id,
            error=error,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="model.run",
            resource_type="model",
            resource_id=model_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"ok": ok, "rows": rows_produced},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return RunResult(
        run_id=run_id,
        status="succeeded" if ok else "failed",
        ok=ok,
        error=error,
        rows_produced=rows_produced if ok else 0,
        output_dataset=output_dataset,
    )


@router.get("/{model_id}/runs", response_model=list[RunOut])
async def run_history(
    model_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[RunOut]:
    async with user_connection(access.auth.user_id) as conn:
        await model_service.get(conn, access.project_id, model_id)
        rows = await model_service.list_runs(conn, model_id)
    return [RunOut(**r) for r in rows]
