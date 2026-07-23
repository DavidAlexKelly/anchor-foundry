"""Connection routes (spec §17: /workspaces/{id}/projects/{id}/connections).

Role floors (conservative where the spec is silent — flagged): read = project
viewer; create/update/delete/test/discover = project editor, and creating a
workspace-scoped connection additionally requires workspace admin (it becomes
visible to every project in the workspace). Test and discover reach into the
customer's source system, which is why they sit at editor rather than viewer.

The credential boundary in one place: request models accept `secret` values;
no response model has a field that could carry them; `secret_arn` never
leaves the service layer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ForbiddenError
from ..middleware.permissions import ProjectAccess, require_project_role
from ..services import audit
from ..services import connections as conn_service
from ..services.connectors import (
    ConnectorConfigError,
    ConnectorOperationError,
    get_connector,
    list_source_types,
)
from ..services.secrets import InMemorySecretsGateway, SecretsGateway

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/connections",
    tags=["connections"],
)

# Injected at startup: Boto3SecretsGateway in production, in-memory for
# dev/tests. Flagged for review: the default is development-only.
_secrets: SecretsGateway = InMemorySecretsGateway()


def configure_secrets_gateway(gateway: SecretsGateway) -> None:
    global _secrets
    _secrets = gateway


# ---- schemas ----------------------------------------------------------------
class ConnectionOut(BaseModel):
    """Wire shape for a connection. Deliberately no secret_arn and no secret
    field of any kind."""

    id: UUID
    workspace_id: UUID
    project_id: UUID | None
    scope: str
    name: str
    source_type: str
    config: dict[str, Any]
    sync_mode: str
    status: str
    last_tested_at: datetime | None
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    source_type: str = Field(min_length=1, max_length=64)
    scope: str = Field(default="project", pattern="^(project|workspace)$")
    config: dict[str, Any] = Field(default_factory=dict)
    secret: dict[str, str] = Field(
        default_factory=dict,
        description="Credential fields (e.g. password). Stored in Secrets "
        "Manager; never returned by any endpoint.",
    )


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    secret: dict[str, str] | None = None


class TestResult(BaseModel):
    ok: bool
    error: str | None
    connection: ConnectionOut


class ColumnOut(BaseModel):
    name: str
    data_type: str
    nullable: bool
    is_primary_key: bool


class TableOut(BaseModel):
    schema_name: str
    name: str
    kind: str
    columns: list[ColumnOut]


def _out(row: dict[str, Any]) -> ConnectionOut:
    data = {k: v for k, v in row.items() if k != "secret_arn"}
    if isinstance(data.get("config"), str):
        import json

        data["config"] = json.loads(data["config"])
    return ConnectionOut(**data)


# ---- source type catalog (for the create wizard) ----------------------------
@router.get("/source-types")
async def source_types(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[dict[str, Any]]:
    return list_source_types()


# ---- CRUD -------------------------------------------------------------------
@router.get("", response_model=list[ConnectionOut])
async def list_connections(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ConnectionOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await conn_service.list_for_project(conn, access.workspace_id, access.project_id)
    return [_out(r) for r in rows]


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ConnectionOut:
    # Workspace-scoped connections are visible to every project in the
    # workspace, so creating one requires workspace admin.
    if body.scope == "workspace" and access.workspace_role != "admin":
        raise ForbiddenError("workspace-scoped connections require the workspace admin role")
    # Validate config before touching the secrets store.
    get_connector(body.source_type).validate_config(body.config)

    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.create(
            conn,
            _secrets,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            scope=body.scope,
            name=body.name,
            source_type=body.source_type,
            config=body.config,
            secret_values=body.secret,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.create",
            resource_type="connection",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": body.name, "source_type": body.source_type, "scope": body.scope},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.patch("/{connection_id}", response_model=ConnectionOut)
async def update_connection(
    connection_id: UUID,
    body: ConnectionUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ConnectionOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.update(
            conn,
            _secrets,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            connection_id=connection_id,
            name=body.name,
            config=body.config,
            secret_values=body.secret,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.update",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "name": body.name,
                "config_changed": body.config is not None,
                "credentials_rotated": bool(body.secret),
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.delete(
    "/{connection_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_connection(
    connection_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await conn_service.delete(
            conn,
            _secrets,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            connection_id=connection_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.delete",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- test & discover --------------------------------------------------------
@router.post("/{connection_id}/test", response_model=TestResult)
async def test_connection(
    connection_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> TestResult:
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.get(conn, access.workspace_id, access.project_id, connection_id)

    connector = get_connector(str(row["source_type"]))
    config = row["config"] if isinstance(row["config"], dict) else _parse(row["config"])
    ok, error = True, None
    try:
        secret = conn_service.secret_values_for(_secrets, row)
        await anyio.to_thread.run_sync(connector.test, config, secret)
    except ConnectorOperationError as exc:
        ok, error = False, str(exc)
    except KeyError:
        ok, error = False, "stored credentials are missing — update the connection"

    async with user_connection(access.auth.user_id) as conn:
        updated = await conn_service.record_test_result(conn, connection_id, ok=ok, error=error)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.test",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"ok": ok},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return TestResult(ok=ok, error=error, connection=_out(updated))


@router.post("/{connection_id}/discover", response_model=list[TableOut])
async def discover_schema(
    connection_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> list[TableOut]:
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.get(conn, access.workspace_id, access.project_id, connection_id)

    connector = get_connector(str(row["source_type"]))
    config = row["config"] if isinstance(row["config"], dict) else _parse(row["config"])
    try:
        secret = conn_service.secret_values_for(_secrets, row)
        tables = await anyio.to_thread.run_sync(connector.discover, config, secret)
    except ConnectorOperationError as exc:
        # Surface as a failed test too: discovery reaching a dead source is
        # the same signal.
        async with user_connection(access.auth.user_id) as conn:
            await conn_service.record_test_result(conn, connection_id, ok=False, error=str(exc))
        raise ConnectorConfigError(str(exc)) from exc

    async with user_connection(access.auth.user_id) as conn:
        await conn_service.record_test_result(conn, connection_id, ok=True, error=None)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.discover",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"tables": len(tables)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return [
        TableOut(
            schema_name=t.schema,
            name=t.name,
            kind=t.kind,
            columns=[ColumnOut(**c.__dict__) for c in t.columns],
        )
        for t in tables
    ]


def _parse(raw: Any) -> dict[str, Any]:
    import json

    parsed = json.loads(raw)
    return parsed if isinstance(parsed, dict) else {}


# ---- sync (spec §17 "trigger sync") -----------------------------------------
# Imports local to this section to keep the module's top intact.
import os as _os
import tempfile as _tempfile

from ..services import sync as sync_service
from ..services.storage import StorageGateway as _StorageGateway
from ..services.sync import SyncError


class SyncRequest(BaseModel):
    source_schema: str = Field(default="public", min_length=1, max_length=63)
    source_table: str = Field(min_length=1, max_length=63)
    dataset_name: str | None = Field(default=None, min_length=1, max_length=200)
    mode: str = Field(default="full", pattern="^(full|incremental)$")


class SyncDatasetOut(BaseModel):
    id: UUID
    name: str
    slug: str
    row_count: int
    current_version: int


class SyncResult(BaseModel):
    run_id: UUID
    ok: bool
    error: str | None
    rows_synced: int
    created_dataset: bool
    dataset: SyncDatasetOut | None


class SyncRunOut(BaseModel):
    id: UUID
    mode: str
    source_table: str
    status: str
    rows_synced: int
    error: str | None
    started_at: datetime
    finished_at: datetime | None
    dataset_id: UUID | None
    dataset_name: str | None


def _dataset_storage() -> "_StorageGateway":
    # The datasets router owns the storage gateway; sync writes into the same
    # place uploads land, so it must use the same gateway instance.
    from . import datasets as dataset_routes

    return dataset_routes._storage


@router.post("/{connection_id}/sync", response_model=SyncResult)
async def trigger_sync(
    connection_id: UUID,
    body: SyncRequest,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SyncResult:
    if body.mode == "incremental":
        raise ConnectorConfigError(
            "incremental sync needs stored cursor progress — set up a scheduled "
            "sync (POST .../scheduled-sync) and use its 'run now' endpoint instead "
            "of an ad hoc trigger"
        )
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.get(conn, access.workspace_id, access.project_id, connection_id)
        run_id = await sync_service.open_run(
            conn,
            connection_id=connection_id,
            source_table=f"{body.source_schema}.{body.source_table}",
            requested_by=access.auth.user_id,
        )

    config = row["config"] if isinstance(row["config"], dict) else _parse(row["config"])
    ok, error, rows_synced, created = True, None, 0, False
    dataset: dict[str, Any] | None = None
    tmp_dir = _tempfile.mkdtemp()
    csv_path = _os.path.join(tmp_dir, "snapshot.csv")
    try:
        secret = conn_service.secret_values_for(_secrets, row)
        await anyio.to_thread.run_sync(
            sync_service.snapshot_source_table,
            config, secret, body.source_schema, body.source_table, csv_path,
        )
        async with user_connection(access.auth.user_id) as conn:
            dataset, rows_synced, created = await sync_service.run_full_sync(
                conn,
                _dataset_storage(),
                _secrets,
                connection_row=row,
                workspace_id=access.workspace_id,
                project_id=access.project_id,
                source_schema=body.source_schema,
                source_table=body.source_table,
                dataset_name=body.dataset_name,
                requested_by=access.auth.user_id,
                snapshot_csv_path=csv_path,
            )
    except (SyncError, ConnectorOperationError) as exc:
        ok, error = False, str(exc)
    except KeyError:
        ok, error = False, "stored credentials are missing — update the connection"
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmp_dir, ignore_errors=True)

    async with user_connection(access.auth.user_id) as conn:
        await sync_service.close_run(
            conn,
            run_id,
            ok=ok,
            rows_synced=rows_synced,
            dataset_id=UUID(str(dataset["id"])) if dataset else None,
            error=error,
        )
        await conn_service.record_test_result(conn, connection_id, ok=ok, error=error)
        if ok:
            await conn.execute(
                _sql_text("UPDATE connections SET last_synced_at = now() WHERE id = :cid"),
                {"cid": str(connection_id)},
            )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.sync",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"table": f"{body.source_schema}.{body.source_table}",
                      "ok": ok, "rows": rows_synced},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SyncResult(
        run_id=run_id,
        ok=ok,
        error=error,
        rows_synced=rows_synced,
        created_dataset=created,
        dataset=SyncDatasetOut(**dataset) if dataset else None,
    )


@router.get("/{connection_id}/sync-runs", response_model=list[SyncRunOut])
async def sync_runs(
    connection_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[SyncRunOut]:
    async with user_connection(access.auth.user_id) as conn:
        await conn_service.get(conn, access.workspace_id, access.project_id, connection_id)
        rows = await sync_service.list_runs(conn, connection_id)
    return [SyncRunOut(**r) for r in rows]


# ---- scheduled/incremental sync (spec: cron-triggered, cursor-based sync) ---
# A connection carries at most one managed sync target — migration 0014
# completes the sync_mode/sync_schedule columns that existed since 0003 with
# the fields a schedulable/incremental sync needs to be self-contained.
# Firing on schedule is the worker's job (scheduled_connection_syncs);
# "run now" here executes the identical steps inline, same relationship as
# models' manual run vs. its own scheduled_model_runs job.
class ScheduledSyncSet(BaseModel):
    mode: str = Field(pattern="^(full|incremental)$")
    source_schema: str = Field(default="public", min_length=1, max_length=63)
    source_table: str = Field(min_length=1, max_length=63)
    dataset_name: str | None = Field(default=None, min_length=1, max_length=200)
    primary_key_column: str | None = Field(default=None, min_length=1, max_length=200)
    cursor_column: str | None = Field(default=None, min_length=1, max_length=200)
    cron_schedule: str | None = Field(default=None, min_length=1, max_length=100)


class ScheduledSyncOut(BaseModel):
    id: UUID
    sync_mode: str
    sync_schedule: str | None
    sync_source_schema: str | None
    sync_source_table: str | None
    sync_dataset_name: str | None
    sync_dataset_id: UUID | None
    sync_primary_key_column: str | None
    sync_cursor_column: str | None
    sync_last_cursor_value: str | None
    sync_next_run_at: datetime | None


@router.get("/{connection_id}/scheduled-sync", response_model=ScheduledSyncOut)
async def get_scheduled_sync(
    connection_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> ScheduledSyncOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.get_schedule(
            conn, access.workspace_id, access.project_id, connection_id
        )
    return ScheduledSyncOut(**row)


@router.put("/{connection_id}/scheduled-sync", response_model=ScheduledSyncOut)
async def set_scheduled_sync(
    connection_id: UUID,
    body: ScheduledSyncSet,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ScheduledSyncOut:
    if body.mode == "incremental" and (not body.primary_key_column or not body.cursor_column):
        raise ConnectorConfigError(
            "incremental sync needs both a primary key column and a cursor column"
        )
    next_run_at = next_run_after(body.cron_schedule) if body.cron_schedule else None
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.set_schedule(
            conn, access.workspace_id, access.project_id, connection_id,
            mode=body.mode, source_schema=body.source_schema, source_table=body.source_table,
            dataset_name=body.dataset_name, primary_key_column=body.primary_key_column,
            cursor_column=body.cursor_column, cron_schedule=body.cron_schedule,
            next_run_at=next_run_at,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.scheduled_sync.set",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "mode": body.mode, "table": f"{body.source_schema}.{body.source_table}",
                "cron_schedule": body.cron_schedule,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ScheduledSyncOut(**row)


@router.delete("/{connection_id}/scheduled-sync", response_model=ScheduledSyncOut)
async def clear_scheduled_sync(
    connection_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ScheduledSyncOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await conn_service.clear_schedule(
            conn, access.workspace_id, access.project_id, connection_id
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.scheduled_sync.clear",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ScheduledSyncOut(**row)


@router.post("/{connection_id}/scheduled-sync/run", response_model=SyncResult)
async def run_scheduled_sync(
    connection_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SyncResult:
    async with user_connection(access.auth.user_id) as conn:
        schedule = await conn_service.get_schedule(
            conn, access.workspace_id, access.project_id, connection_id
        )
        if not schedule["sync_source_table"]:
            raise ConnectorConfigError(
                "no scheduled sync target is configured — set one with PUT .../scheduled-sync first"
            )
        row = await conn_service.get(conn, access.workspace_id, access.project_id, connection_id)
        run_id = await sync_service.open_run(
            conn,
            connection_id=connection_id,
            source_table=f"{schedule['sync_source_schema']}.{schedule['sync_source_table']}",
            requested_by=access.auth.user_id,
        )

    config = row["config"] if isinstance(row["config"], dict) else _parse(row["config"])
    mode = schedule["sync_mode"]
    ok, error, rows_synced, created = True, None, 0, False
    dataset: dict[str, Any] | None = None
    new_cursor_value = schedule["sync_last_cursor_value"]
    tmp_dir = _tempfile.mkdtemp()
    csv_path = _os.path.join(tmp_dir, "snapshot.csv")
    try:
        secret = conn_service.secret_values_for(_secrets, row)
        cursor_col = schedule["sync_cursor_column"] if mode == "incremental" else None
        await anyio.to_thread.run_sync(
            sync_service.snapshot_source_table,
            config, secret, schedule["sync_source_schema"], schedule["sync_source_table"],
            csv_path, cursor_col, schedule["sync_last_cursor_value"],
        )
        if mode == "incremental" and cursor_col:
            new_cursor_value = await anyio.to_thread.run_sync(
                sync_service.max_cursor_value,
                config, secret, schedule["sync_source_schema"], schedule["sync_source_table"], cursor_col,
            ) or schedule["sync_last_cursor_value"]

        async with user_connection(access.auth.user_id) as conn:
            if mode == "incremental":
                dataset, rows_synced, created = await sync_service.run_incremental_sync(
                    conn, _dataset_storage(),
                    connection_row=schedule,
                    workspace_id=access.workspace_id, project_id=access.project_id,
                    source_schema=schedule["sync_source_schema"],
                    source_table=schedule["sync_source_table"],
                    dataset_name=schedule["sync_dataset_name"],
                    primary_key_column=schedule["sync_primary_key_column"],
                    new_cursor_value=new_cursor_value,
                    requested_by=access.auth.user_id,
                    snapshot_csv_path=csv_path,
                )
            else:
                dataset, rows_synced, created = await sync_service.run_full_sync(
                    conn, _dataset_storage(),
                    connection_row=row,
                    workspace_id=access.workspace_id, project_id=access.project_id,
                    source_schema=schedule["sync_source_schema"],
                    source_table=schedule["sync_source_table"],
                    dataset_name=schedule["sync_dataset_name"],
                    requested_by=access.auth.user_id,
                    snapshot_csv_path=csv_path,
                )
                if dataset:
                    await conn.execute(
                        _sql_text("UPDATE connections SET sync_dataset_id = :did WHERE id = :cid"),
                        {"did": str(dataset["id"]), "cid": str(connection_id)},
                    )
    except (SyncError, ConnectorOperationError) as exc:
        ok, error = False, str(exc)
    except KeyError:
        ok, error = False, "stored credentials are missing — update the connection"
    finally:
        import shutil as _shutil

        _shutil.rmtree(tmp_dir, ignore_errors=True)

    async with user_connection(access.auth.user_id) as conn:
        await sync_service.close_run(
            conn, run_id, ok=ok, rows_synced=rows_synced,
            dataset_id=UUID(str(dataset["id"])) if dataset else None, error=error,
        )
        await conn_service.record_test_result(conn, connection_id, ok=ok, error=error)
        if ok:
            await conn.execute(
                _sql_text("UPDATE connections SET last_synced_at = now() WHERE id = :cid"),
                {"cid": str(connection_id)},
            )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="connection.scheduled_sync.run",
            resource_type="connection",
            resource_id=connection_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"mode": mode, "ok": ok, "rows": rows_synced},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SyncResult(
        run_id=run_id, ok=ok, error=error, rows_synced=rows_synced,
        created_dataset=created, dataset=SyncDatasetOut(**dataset) if dataset else None,
    )


from ..lib.cron import next_run_after  # noqa: E402
from sqlalchemy import text as _sql_text  # noqa: E402
