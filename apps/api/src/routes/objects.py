"""Ontology routes (spec §16: Objects — the semantic layer).

Object types and link types are workspace-level (the ontology is shared
across every project in a workspace) and live under
``/workspaces/{workspace_id}/object-types`` and ``.../link-types``. Object
type sources — the per-project mapping of a dataset onto a workspace type —
are project-level and live under
``/workspaces/{workspace_id}/projects/{project_id}/object-type-sources``,
mirroring the connections/models split between workspace- and
project-scoped resources.

Role floors (conservative, flagged — the spec is silent on exact roles):
read = viewer everywhere; object type/link type create & delete = workspace
editor (the same floor already used for "who can create a project");
source create/delete/sync = project editor. Suggestion is read-only dataset
inspection, so it sits at viewer like dataset preview/query. Instance
browsing (GET .../instances) sits at workspace viewer, same as everything
else that only reads the ontology.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import anyio
from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import audit
from ..services import datasets as dataset_service
from ..services import instances as instances_service
from ..services import ontology as ontology_service
from ..services.dataset_engine import DatasetEngineError

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["objects"])
project_router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/object-type-sources",
    tags=["objects"],
)


def _dataset_storage():
    # The datasets router owns the storage gateway; instance sync reads the
    # same Parquet files uploads/models/sync write, so it must use the same
    # gateway instance (mirrors connections.py / models.py).
    from . import datasets as dataset_routes

    return dataset_routes._storage


# ---- schemas ----------------------------------------------------------------
class PropertyIn(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=200)
    data_type: str = Field(
        pattern="^(string|integer|float|boolean|date|timestamp|geopoint|json)$"
    )
    required: bool = False
    description: str = Field(default="", max_length=1000)


class PropertyOut(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    data_type: str
    required: bool
    description: str
    sort_order: int


class ObjectTypeSummary(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    description: str
    icon: str
    colour: str
    title_property_id: UUID | None
    source_count: int
    created_at: datetime
    updated_at: datetime


class ObjectTypeDetail(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    description: str
    icon: str
    colour: str
    title_property_id: UUID | None
    properties: list[PropertyOut]
    created_at: datetime
    updated_at: datetime


class ObjectTypeCreate(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="cube", max_length=64)
    colour: str = Field(default="#2f6f4f", max_length=32)
    properties: list[PropertyIn] = Field(default_factory=list, max_length=100)
    title_property: str | None = Field(default=None, max_length=100)


class LinkTypeOut(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    cardinality: str
    from_object_type_id: UUID
    from_display_name: str
    to_object_type_id: UUID
    to_display_name: str
    created_at: datetime


class LinkTypeCreate(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    from_type_id: UUID
    to_type_id: UUID
    cardinality: str = Field(pattern="^(one_to_one|one_to_many|many_to_many)$")


class SourceOut(BaseModel):
    id: UUID
    object_type_id: UUID
    object_type_name: str
    dataset_id: UUID
    dataset_name: str
    primary_key_column: str
    column_mappings: dict[str, str]
    sync_status: str
    last_synced_at: datetime | None
    last_error: str | None
    created_at: datetime


class SourceCreate(BaseModel):
    object_type_id: UUID
    dataset_id: UUID
    primary_key_column: str = Field(min_length=1, max_length=200)
    column_mappings: dict[str, str] = Field(default_factory=dict)


class SuggestRequest(BaseModel):
    dataset_id: UUID


class SuggestedProperty(BaseModel):
    api_name: str
    display_name: str
    data_type: str
    required: bool
    source_column: str


class SuggestResponse(BaseModel):
    dataset_name: str
    suggested_api_name: str
    suggested_display_name: str
    suggested_primary_key: str | None
    suggested_title_property: str | None
    properties: list[SuggestedProperty]


class SyncResult(BaseModel):
    ok: bool
    error: str | None
    upserted: int
    removed: int
    source: SourceOut


class InstanceOut(BaseModel):
    id: UUID
    primary_key: str
    properties: dict[str, Any]
    updated_at: datetime


class InstancePage(BaseModel):
    items: list[InstanceOut]
    total: int
    limit: int
    offset: int


def _jsonb(value: Any) -> dict[str, Any]:
    return json.loads(value) if isinstance(value, str) else value


def _source_out(row: dict[str, Any]) -> SourceOut:
    return SourceOut(**{**row, "column_mappings": _jsonb(row["column_mappings"])})


async def _type_detail(conn, workspace_id: UUID, type_id: UUID) -> ObjectTypeDetail:
    row = await ontology_service.get_type(conn, workspace_id, type_id)
    props = await ontology_service.list_properties(conn, type_id)
    return ObjectTypeDetail(**row, properties=[PropertyOut(**p) for p in props])


# ---- object types (workspace-scoped) ----------------------------------------
@router.get("/object-types", response_model=list[ObjectTypeSummary])
async def list_object_types(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ObjectTypeSummary]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ontology_service.list_types(conn, access.workspace_id)
    return [ObjectTypeSummary(**r) for r in rows]


@router.post(
    "/object-types", response_model=ObjectTypeDetail, status_code=status.HTTP_201_CREATED
)
async def create_object_type(
    body: ObjectTypeCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ObjectTypeDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.create_type(
            conn,
            workspace_id=access.workspace_id,
            api_name=body.api_name,
            display_name=body.display_name,
            description=body.description,
            icon=body.icon,
            colour=body.colour,
            properties=[p.model_dump() for p in body.properties],
            title_property=body.title_property,
            created_by=access.auth.user_id,
        )
        props = await ontology_service.list_properties(conn, UUID(str(row["id"])))
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type.create",
            resource_type="object_type",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"api_name": body.api_name, "properties": len(body.properties)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ObjectTypeDetail(**row, properties=[PropertyOut(**p) for p in props])


@router.get("/object-types/{type_id}", response_model=ObjectTypeDetail)
async def get_object_type(
    type_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectTypeDetail:
    async with user_connection(access.auth.user_id) as conn:
        return await _type_detail(conn, access.workspace_id, type_id)


@router.delete(
    "/object-types/{type_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_object_type(
    type_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.delete_type(conn, access.workspace_id, type_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type.delete",
            resource_type="object_type",
            resource_id=type_id,
            workspace_id=access.workspace_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- object instances (workspace-scoped browsing) ---------------------------
@router.get("/object-types/{type_id}/instances", response_model=InstancePage)
async def list_instances(
    type_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> InstancePage:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, type_id)  # 404 if invisible
        rows, total = await instances_service.list_for_type(
            conn, type_id, limit=limit, offset=offset
        )
    return InstancePage(
        items=[InstanceOut(**{**r, "properties": _jsonb(r["properties"])}) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/object-types/{type_id}/instances/{instance_id}", response_model=InstanceOut)
async def get_instance(
    type_id: UUID,
    instance_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> InstanceOut:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, type_id)
        row = await instances_service.get(conn, type_id, instance_id)
    return InstanceOut(**{**row, "properties": _jsonb(row["properties"])})


# ---- link types (workspace-scoped) ------------------------------------------
@router.get("/link-types", response_model=list[LinkTypeOut])
async def list_link_types(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[LinkTypeOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ontology_service.list_link_types(conn, access.workspace_id)
    return [LinkTypeOut(**r) for r in rows]


@router.post("/link-types", response_model=LinkTypeOut, status_code=status.HTTP_201_CREATED)
async def create_link_type(
    body: LinkTypeCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> LinkTypeOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.create_link_type(
            conn,
            workspace_id=access.workspace_id,
            api_name=body.api_name,
            display_name=body.display_name,
            from_type_id=body.from_type_id,
            to_type_id=body.to_type_id,
            cardinality=body.cardinality,
            created_by=access.auth.user_id,
        )
        from_type = await ontology_service.get_type(conn, access.workspace_id, body.from_type_id)
        to_type = await ontology_service.get_type(conn, access.workspace_id, body.to_type_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="link_type.create",
            resource_type="link_type",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"api_name": body.api_name, "cardinality": body.cardinality},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return LinkTypeOut(
        **row,
        from_display_name=from_type["display_name"],
        to_display_name=to_type["display_name"],
    )


@router.delete(
    "/link-types/{link_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_link_type(
    link_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.delete_link_type(conn, access.workspace_id, link_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="link_type.delete",
            resource_type="link_type",
            resource_id=link_id,
            workspace_id=access.workspace_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- object type sources (project-scoped) -----------------------------------
@project_router.get("", response_model=list[SourceOut])
async def list_sources(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[SourceOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ontology_service.list_sources(conn, access.project_id, access.workspace_id)
    return [_source_out(r) for r in rows]


@project_router.post("", response_model=SourceOut, status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SourceOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.create_source(
            conn,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            object_type_id=body.object_type_id,
            dataset_id=body.dataset_id,
            primary_key_column=body.primary_key_column,
            column_mappings=body.column_mappings,
            created_by=access.auth.user_id,
        )
        object_type = await ontology_service.get_type(
            conn, access.workspace_id, body.object_type_id
        )
        dataset = await dataset_service.get(conn, access.project_id, body.dataset_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_source.create",
            resource_type="object_type_source",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"object_type_id": str(body.object_type_id), "dataset_id": str(body.dataset_id)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _source_out(
        {**row, "object_type_name": object_type["display_name"], "dataset_name": dataset["name"]}
    )


@project_router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_source(
    source_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.delete_source(conn, access.project_id, source_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_source.delete",
            resource_type="object_type_source",
            resource_id=source_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


@project_router.post("/suggest", response_model=SuggestResponse)
async def suggest_from_dataset(
    body: SuggestRequest,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> SuggestResponse:
    async with user_connection(access.auth.user_id) as conn:
        suggestion = await ontology_service.suggest_from_dataset(
            conn, access.project_id, body.dataset_id
        )
    return SuggestResponse(**suggestion)


@project_router.post("/{source_id}/sync", response_model=SyncResult)
async def sync_source(
    source_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SyncResult:
    storage = _dataset_storage()
    async with user_connection(access.auth.user_id) as conn:
        source = await ontology_service.get_source(conn, access.project_id, source_id)

    synced_at = datetime.now(timezone.utc)
    ok, error = True, None
    upserted = removed = 0
    rows: list[tuple[str, dict[str, Any]]] = []
    try:
        local_path = await anyio.to_thread.run_sync(
            storage.local_path, str(source["s3_location"])
        )
        rows = await anyio.to_thread.run_sync(
            instances_service.extract_rows,
            local_path,
            str(source["primary_key_column"]),
            _jsonb(source["column_mappings"]),
        )
    except DatasetEngineError as exc:
        ok, error = False, str(exc)

    if ok:
        async with user_connection(access.auth.user_id) as conn:
            upserted = await instances_service.upsert_instances(
                conn,
                object_type_id=UUID(str(source["object_type_id"])),
                source_id=source_id,
                rows=rows,
                synced_at=synced_at,
            )
            removed = await instances_service.delete_stale_instances(
                conn, source_id=source_id, synced_before=synced_at
            )

    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.mark_source_synced(conn, source_id, ok=ok, error=error)
        updated_source = await ontology_service.get_source(conn, access.project_id, source_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_source.sync",
            resource_type="object_type_source",
            resource_id=source_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"ok": ok, "upserted": upserted, "removed": removed},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SyncResult(
        ok=ok, error=error, upserted=upserted, removed=removed,
        source=_source_out(updated_source),
    )
