"""Dataset routes (spec §17: /workspaces/{id}/projects/{id}/datasets).

Role floors (conservative, flagged): read/preview/query/export = project
viewer (a viewer's purpose is reading the data); upload/update/delete =
project editor.

Upload pipeline: size-capped read → original bytes to storage → DuckDB
ingest to canonical Parquet → parquet to storage → row + version in one
transaction. Storage writes precede the row so failure leaves recoverable
files, never a dataset that 404s on read.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import expectations
from ..services import dataset_engine as engine
from ..services import datasets as ds_service
from ..services.dataset_engine import DatasetEngineError
from ..services.storage import LocalStorageGateway, StorageGateway

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/datasets",
    tags=["datasets"],
)

# Injected at startup: S3StorageGateway in production. Flagged for review:
# the default local gateway is development-only.
_storage: StorageGateway = LocalStorageGateway(
    os.environ.get("STORAGE_ROOT", "/tmp/anchor-storage")
)


def configure_storage_gateway(gateway: StorageGateway) -> None:
    global _storage
    _storage = gateway


# ---- schemas ----------------------------------------------------------------
class DatasetOut(BaseModel):
    id: UUID
    project_id: UUID
    workspace_id: UUID
    name: str
    slug: str
    description: str
    origin: str
    connection_id: UUID | None
    table_schema: list[dict[str, str]]
    row_count: int
    current_version: int
    # 'permissive' | 'strict' - whether a new version may remove or retype an
    # existing column (migration 0023). Adding columns is allowed under both.
    schema_policy: str = "permissive"
    # Where a forked dataset came from (migration 0025). Provenance only -
    # a fork never recomputes, so this is not a pipeline-graph edge.
    forked_from_dataset_id: UUID | None = None
    forked_from_version: int | None = None
    created_at: datetime
    updated_at: datetime


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    schema_policy: str | None = Field(default=None, pattern="^(permissive|strict)$")


class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    max_rows: int = Field(default=engine.MAX_RESULT_ROWS, ge=1, le=engine.MAX_RESULT_ROWS)


class TabularOut(BaseModel):
    columns: list[dict[str, str]]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool


class VersionOut(BaseModel):
    id: UUID
    version_number: int
    row_count: int
    table_schema: list[dict[str, str]]
    produced_by_kind: str | None
    created_at: datetime


class ColumnProfileOut(BaseModel):
    name: str
    data_type: str
    null_count: int
    null_rate: float
    distinct_count: int
    # Text because one array holds every column's type, and nothing computes
    # against these - null for types DuckDB cannot order (structs, lists).
    min: str | None
    max: str | None


class ExpectationOut(BaseModel):
    id: UUID
    dataset_id: UUID
    rule_type: str
    column_name: str
    config: dict[str, Any]
    severity: str
    created_at: datetime


class ExpectationCreate(BaseModel):
    rule_type: str = Field(min_length=1, max_length=64)
    column_name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    severity: str = Field(default="error", pattern="^(error|warn)$")


class ExpectationResultOut(BaseModel):
    expectation_id: UUID | None
    rule_type: str
    column_name: str
    severity: str
    # `error` is not `fail`: the rule could not be evaluated, which says
    # nothing about whether the data is good.
    status: str
    failing_rows: int
    rows_checked: int
    message: str | None


class DatasetHealthOut(BaseModel):
    dataset_id: UUID
    version_number: int
    # "none" when the dataset has no rules - different from passing, and shown
    # differently.
    status: str
    evaluated_at: str | None
    results: list[ExpectationResultOut]


class DatasetProfileOut(BaseModel):
    dataset_id: UUID
    version_number: int
    row_count: int
    columns: list[ColumnProfileOut]


def _out(row: dict[str, Any]) -> DatasetOut:
    data = dict(row)
    data.pop("s3_location", None)  # storage keys are internal plumbing
    if isinstance(data.get("table_schema"), str):
        import json

        data["table_schema"] = json.loads(data["table_schema"])
    return DatasetOut(**data)


def _tabular(result: engine.TabularResult) -> TabularOut:
    return TabularOut(
        columns=[c.as_dict() for c in result.columns],
        rows=result.rows,
        total_rows=result.total_rows,
        truncated=result.truncated,
    )


def _client_error(message: str) -> "DatasetEngineError":
    return DatasetEngineError(message)


# ---- CRUD -------------------------------------------------------------------
@router.get("", response_model=list[DatasetOut])
async def list_datasets(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[DatasetOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ds_service.list_for_project(conn, access.project_id)
    return [_out(r) for r in rows]


@router.post("/upload", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    name: str = Form(min_length=1, max_length=200),
    description: str = Form(default="", max_length=2000),
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> DatasetOut:
    original_name = ds_service.safe_filename(file.filename or "upload")
    extension = os.path.splitext(original_name)[1].lower()
    if extension not in engine.SUPPORTED_EXTENSIONS:
        supported = ", ".join(engine.SUPPORTED_EXTENSIONS)
        raise _client_error(f"unsupported file type {extension or '(none)'} - supported: {supported}")

    data = await file.read(ds_service.MAX_UPLOAD_BYTES + 1)
    if len(data) > ds_service.MAX_UPLOAD_BYTES:
        cap_mb = ds_service.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise _client_error(f"file exceeds the {cap_mb} MB upload limit")
    if not data:
        raise _client_error("the uploaded file is empty")

    dataset_id = uuid4()
    async with user_connection(access.auth.user_id) as conn:
        ws_prefix = await ds_service.workspace_s3_prefix(conn, access.workspace_id)
    prefix = ds_service.storage_prefix(ws_prefix, dataset_id)
    original_key = f"{prefix}original/{original_name}"
    parquet_key = f"{prefix}v1/data.parquet"

    def ingest() -> tuple[list[engine.ColumnSchema], int]:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, f"src{extension}")
            with open(src, "wb") as handle:
                handle.write(data)
            dest = os.path.join(tmp, "data.parquet")
            schema, rows = engine.ingest_to_parquet(src, extension, dest)
            _storage.put(original_key, data)
            with open(dest, "rb") as handle:
                _storage.put(parquet_key, handle.read())
            return schema, rows

    schema, row_count = await anyio.to_thread.run_sync(ingest)

    async with user_connection(access.auth.user_id) as conn:
        row = await ds_service.create_from_upload(
            conn,
            dataset_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            name=name,
            description=description,
            parquet_key=parquet_key,
            schema=schema,
            row_count=row_count,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.upload",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": name, "filename": original_name, "rows": row_count,
                      "bytes": len(data)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DatasetOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ds_service.get(conn, access.project_id, dataset_id)
    return _out(row)


@router.patch("/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: UUID,
    body: DatasetUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> DatasetOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ds_service.update(
            conn, access.project_id, dataset_id, name=body.name,
            description=body.description, schema_policy=body.schema_policy,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.update",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata=body.model_dump(exclude_none=True),
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


class DatasetFork(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Defaults to the source's current version - forking "as it is now" is
    # the common case.
    version_number: int | None = Field(default=None, ge=1)


@router.post("/{dataset_id}/fork", response_model=DatasetOut,
             status_code=status.HTTP_201_CREATED)
async def fork_dataset(
    dataset_id: UUID,
    body: DatasetFork,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> DatasetOut:
    """Copy a version into a new, independent dataset to experiment against.
    Editor level: it creates a resource, and reading one you can already read
    is not the operative permission."""
    async with user_connection(access.auth.user_id) as conn:
        row = await ds_service.fork(
            conn,
            _storage,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            dataset_id=dataset_id,
            name=body.name,
            version_number=body.version_number,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.fork",
            resource_type="dataset",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"source": str(dataset_id), "version": row["forked_from_version"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_dataset(
    dataset_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await ds_service.delete(
            conn,
            _storage,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            dataset_id=dataset_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.delete",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- data access ------------------------------------------------------------
async def _parquet_path(access: ProjectAccess, dataset_id: UUID) -> tuple[str, dict[str, Any]]:
    async with user_connection(access.auth.user_id) as conn:
        row = await ds_service.get(conn, access.project_id, dataset_id)
    path = await anyio.to_thread.run_sync(_storage.local_path, str(row["s3_location"]))
    return path, row


@router.get("/{dataset_id}/preview", response_model=TabularOut)
async def preview_dataset(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> TabularOut:
    path, _ = await _parquet_path(access, dataset_id)
    result = await anyio.to_thread.run_sync(engine.preview, path)
    return _tabular(result)


@router.get("/{dataset_id}/profile", response_model=DatasetProfileOut)
async def profile_dataset(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DatasetProfileOut:
    """Per-column statistics for the dataset's current version.

    Computed on first request and cached on the version row (migration 0019):
    a version's data never changes, so the answer is valid forever once
    written. Viewer-level like preview and query - this is a read of data the
    caller can already see, just aggregated.
    """
    path, row = await _parquet_path(access, dataset_id)
    version_number = int(row["current_version"])

    async with user_connection(access.auth.user_id) as conn:
        cached = await ds_service.get_cached_profile(conn, dataset_id, version_number)

    if cached is None:
        cached = await anyio.to_thread.run_sync(engine.profile_columns, path)
        async with user_connection(access.auth.user_id) as conn:
            await ds_service.store_profile(conn, dataset_id, version_number, cached)

    return DatasetProfileOut(
        dataset_id=dataset_id,
        version_number=version_number,
        row_count=int(row["row_count"]),
        columns=[ColumnProfileOut(**column) for column in cached],
    )


# ---- expectations / data health (roadmap Datasets item 2) -------------------
@router.get("/{dataset_id}/expectations", response_model=list[ExpectationOut])
async def list_expectations(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ExpectationOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await expectations.list_rules(conn, access.project_id, dataset_id)
    return [ExpectationOut(**_rule_out(r)) for r in rows]


@router.post(
    "/{dataset_id}/expectations",
    response_model=ExpectationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_expectation(
    dataset_id: UUID,
    body: ExpectationCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ExpectationOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await expectations.create_rule(
            conn,
            access.project_id,
            dataset_id,
            rule_type=body.rule_type,
            column_name=body.column_name,
            config=body.config,
            severity=body.severity,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.expectation.create",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"rule_type": body.rule_type, "column": body.column_name,
                      "severity": body.severity},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ExpectationOut(**_rule_out(row))


@router.delete(
    "/{dataset_id}/expectations/{expectation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_expectation(
    dataset_id: UUID,
    expectation_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await expectations.delete_rule(conn, access.project_id, dataset_id, expectation_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.expectation.delete",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


@router.get("/{dataset_id}/health", response_model=DatasetHealthOut)
async def dataset_health(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> DatasetHealthOut:
    """The dataset's current version evaluated against its rules.

    The single read path for expectations: it returns the cached result, or
    computes and caches one if there isn't a current one. That is what lets
    every version-creating path stay unaware expectations exist - see
    migration 0020.
    """
    path, row = await _parquet_path(access, dataset_id)
    version_number = int(row["current_version"])

    async with user_connection(access.auth.user_id) as conn:
        cached = await expectations.cached_health(conn, dataset_id, version_number)
        rules = await expectations.list_rules(conn, access.project_id, dataset_id)

    if cached is None:
        cached = await anyio.to_thread.run_sync(
            expectations.evaluate, path, [dict(r) for r in rules]
        )
        async with user_connection(access.auth.user_id) as conn:
            await expectations.store_health(conn, dataset_id, version_number, cached)

    return DatasetHealthOut(
        dataset_id=dataset_id,
        version_number=version_number,
        status=str(cached.get("status", "none")),
        evaluated_at=cached.get("evaluated_at"),
        results=[ExpectationResultOut(**r) for r in cached.get("results", [])],
    )


def _rule_out(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    if isinstance(data.get("config"), str):
        import json

        data["config"] = json.loads(data["config"])
    return data


@router.post("/{dataset_id}/query", response_model=TabularOut)
async def query_dataset(
    dataset_id: UUID,
    body: QueryRequest,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> TabularOut:
    path, _ = await _parquet_path(access, dataset_id)
    result = await anyio.to_thread.run_sync(engine.query, path, body.sql, body.max_rows)
    async with user_connection(access.auth.user_id) as conn:
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.query",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"sql": body.sql[:200], "rows_returned": result.total_rows},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _tabular(result)


@router.get("/{dataset_id}/export")
async def export_dataset(
    dataset_id: UUID,
    request: Request,
    format: str = "parquet",
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> Response:
    """Spec §11 export: open formats, any time. parquet streams the stored
    file verbatim; csv converts on the fly."""
    if format not in ("parquet", "csv"):
        raise _client_error("format must be 'parquet' or 'csv'")
    path, row = await _parquet_path(access, dataset_id)

    if format == "parquet":
        payload = await anyio.to_thread.run_sync(_storage.read, str(row["s3_location"]))
        media = "application/vnd.apache.parquet"
        filename = f"{row['slug']}.parquet"
    else:
        def convert() -> bytes:
            with tempfile.TemporaryDirectory() as tmp:
                dest = os.path.join(tmp, "out.csv")
                engine.export_csv(path, dest)
                with open(dest, "rb") as handle:
                    return handle.read()

        payload = await anyio.to_thread.run_sync(convert)
        media = "text/csv"
        filename = f"{row['slug']}.csv"

    async with user_connection(access.auth.user_id) as conn:
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="dataset.export",
            resource_type="dataset",
            resource_id=dataset_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"format": format, "bytes": len(payload)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return Response(
        content=payload,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{dataset_id}/versions", response_model=list[VersionOut])
async def list_versions(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[VersionOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ds_service.list_versions(conn, access.project_id, dataset_id)
    out: list[VersionOut] = []
    for row in rows:
        data = dict(row)
        if isinstance(data.get("table_schema"), str):
            import json

            data["table_schema"] = json.loads(data["table_schema"])
        out.append(VersionOut(**data))
    return out


# ---- lineage (spec §"Models": automatic tracking, Mermaid export) -----------
from ..services import models as _model_service  # noqa: E402


@router.get("/{dataset_id}/lineage")
async def dataset_lineage(
    dataset_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> dict[str, Any]:
    async with user_connection(access.auth.user_id) as conn:
        return await _model_service.lineage_for_dataset(conn, access.project_id, dataset_id)
