"""Ontology routes (spec §16: Objects - the semantic layer).

Object types and link types are workspace-level (the ontology is shared
across every project in a workspace) and live under
``/workspaces/{workspace_id}/object-types`` and ``.../link-types``. Object
type sources - the per-project mapping of a dataset onto a workspace type -
are project-level and live under
``/workspaces/{workspace_id}/projects/{project_id}/object-type-sources``,
mirroring the connections/models split between workspace- and
project-scoped resources.

Role floors (conservative, flagged - the spec is silent on exact roles):
read = viewer everywhere; object type/link type create & delete = workspace
editor (the same floor already used for "who can create a project");
source create/delete/sync = project editor. Suggestion is read-only dataset
inspection, so it sits at viewer like dataset preview/query. Instance
browsing (GET .../instances) sits at workspace viewer, same as everything
else that only reads the ontology.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..lib.cron import next_run_after
from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import audit
from ..services import datasets as dataset_service
from ..lib.errors import NotFoundError
from ..services import instance_store
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
        pattern="^(string|integer|float|boolean|date|timestamp|geopoint|json|attachment)$"
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
    # NULL as a pair when the link type has no join mapped, in which case it
    # is a valid ontology statement that cannot yet be traversed (db 0027).
    from_property: str | None = None
    to_property: str | None = None


# Either a property api_name or the reserved '$primary_key' (db 0027). Empty
# string is accepted and normalised to "unset" in the service, because that is
# what an unselected HTML <select> sends.
_JOIN_PROPERTY = r"^([a-z][a-z0-9_]{0,99}|\$primary_key)?$"


class LinkTypeCreate(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    from_type_id: UUID
    to_type_id: UUID
    cardinality: str = Field(pattern="^(one_to_one|one_to_many|many_to_many)$")
    from_property: str | None = Field(default=None, pattern=_JOIN_PROPERTY)
    to_property: str | None = Field(default=None, pattern=_JOIN_PROPERTY)


class LinkJoinUpdate(BaseModel):
    """Only the join is patchable - see ontology.set_link_join for why an
    endpoint or cardinality change is a different link type, not an edit."""

    from_property: str | None = Field(default=None, pattern=_JOIN_PROPERTY)
    to_property: str | None = Field(default=None, pattern=_JOIN_PROPERTY)


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


class ObjectTypeUpdate(BaseModel):
    """The whole definition, not a patch — see `ontology.update_type` for why.
    `api_name` is absent because it is immutable (db 0003 calls it the stable
    machine name used by exports)."""

    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    icon: str = Field(default="cube", max_length=64)
    colour: str = Field(default="#2f6f4f", max_length=32)
    properties: list[PropertyIn] = Field(min_length=1, max_length=100)
    title_property: str | None = Field(default=None, max_length=100)
    # Required to push through a change that would break an existing mapping,
    # action or link join. Default false so a client that never asks about
    # impact cannot silently break something.
    acknowledge_breaking: bool = False


class ImpactOut(BaseModel):
    property: str
    change: str  # "removed" | "retyped"
    consumer_kind: str  # "dataset_mapping" | "action" | "link"
    consumer_id: UUID
    consumer_name: str
    detail: str
    blocking: bool


class ObjectTypeVersionOut(BaseModel):
    id: UUID
    version_number: int
    display_name: str
    description: str
    icon: str
    colour: str
    properties: list[dict[str, Any]]
    title_property: str | None
    restored_from: int | None
    created_at: datetime
    created_by_email: str | None


@router.post("/object-types/{type_id}/impact", response_model=list[ImpactOut])
async def object_type_impact(
    type_id: UUID,
    body: ObjectTypeUpdate,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ImpactOut]:
    """Dry-run an edit: what would this change break? (roadmap Objects item 5)

    A POST because it takes a proposed definition, and read-only despite that
    — hence the viewer floor. Separate from the PATCH so the UI can warn
    *before* asking for confirmation; the PATCH re-computes the same analysis
    itself rather than trusting that this was called.
    """
    async with user_connection(access.auth.user_id) as conn:
        impacts = await ontology_service.type_impact(
            conn, access.workspace_id, type_id, [p.model_dump() for p in body.properties]
        )
    return [ImpactOut(**i) for i in impacts]


@router.patch("/object-types/{type_id}", response_model=ObjectTypeDetail)
async def update_object_type(
    type_id: UUID,
    body: ObjectTypeUpdate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ObjectTypeDetail:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.update_type(
            conn,
            workspace_id=access.workspace_id,
            type_id=type_id,
            display_name=body.display_name,
            description=body.description,
            icon=body.icon,
            colour=body.colour,
            properties=[p.model_dump() for p in body.properties],
            title_property=body.title_property,
            updated_by=access.auth.user_id,
            acknowledge_breaking=body.acknowledge_breaking,
        )
        detail = await _type_detail(conn, access.workspace_id, type_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type.update",
            resource_type="object_type",
            resource_id=type_id,
            workspace_id=access.workspace_id,
            metadata={"properties": len(body.properties),
                      "acknowledged_breaking": body.acknowledge_breaking},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return detail


@router.get("/object-types/{type_id}/versions", response_model=list[ObjectTypeVersionOut])
async def list_object_type_versions(
    type_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ObjectTypeVersionOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await ontology_service.list_type_versions(conn, access.workspace_id, type_id)
    return [
        ObjectTypeVersionOut(**{**r, "properties": _jsonb(r["properties"]) or []})
        for r in rows
    ]


class RestoreVersionIn(BaseModel):
    acknowledge_breaking: bool = False


@router.post("/object-types/{type_id}/versions/{version_number}/restore",
             response_model=ObjectTypeDetail)
async def restore_object_type_version(
    type_id: UUID,
    version_number: int,
    body: RestoreVersionIn,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ObjectTypeDetail:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.restore_type_version(
            conn,
            workspace_id=access.workspace_id,
            type_id=type_id,
            version_number=version_number,
            updated_by=access.auth.user_id,
            acknowledge_breaking=body.acknowledge_breaking,
        )
        detail = await _type_detail(conn, access.workspace_id, type_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type.restore_version",
            resource_type="object_type",
            resource_id=type_id,
            workspace_id=access.workspace_id,
            metadata={"restored_from": version_number,
                      "acknowledged_breaking": body.acknowledge_breaking},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return detail


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
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        rows, total = await instance_store.store_for(conn).list_for_type(
            search_prefix=prefix, object_type_id=type_id, limit=limit, offset=offset
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
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        row = await instance_store.store_for(conn).get_instance(
            search_prefix=prefix, object_type_id=type_id, instance_id=str(instance_id)
        )
    if row is None:
        raise NotFoundError("object instance")
    return InstanceOut(**{**row, "properties": _jsonb(row["properties"])})


class ExplorerInstanceOut(InstanceOut):
    """An instance plus the type it belongs to - a workspace-wide result set
    is meaningless without saying what each row *is*."""

    object_type_id: UUID
    object_type_api_name: str
    object_type_display_name: str


class ExplorerPage(BaseModel):
    items: list[ExplorerInstanceOut]
    total: int
    limit: int
    offset: int


@router.get("/object-instances", response_model=ExplorerPage)
async def explore_instances(
    q: str | None = Query(default=None, max_length=200),
    type_id: list[UUID] | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ExplorerPage:
    """Search and browse every instance in the workspace at once (roadmap
    Objects item 2), across types rather than within one.

    Workspace-scoped like the ontology it searches: object types are
    workspace-wide, so an explorer that stopped at a project boundary would
    show a partial ontology and call it the whole one.
    """
    async with user_connection(access.auth.user_id) as conn:
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        rows, total = await instance_store.store_for(conn).search(
            search_prefix=prefix,
            workspace_id=access.workspace_id,
            query=q,
            object_type_ids=type_id,
            limit=limit,
            offset=offset,
        )
        # Type names come from Postgres whichever store held the instances -
        # the ontology definition never moved.
        types = {
            str(t["id"]): t
            for t in await ontology_service.list_types(conn, access.workspace_id)
        }
    items = []
    for row in rows:
        meta = types.get(str(row["object_type_id"]))
        if meta is None:
            continue  # type deleted since the instance was indexed
        items.append(ExplorerInstanceOut(
            **{**row, "properties": _jsonb(row["properties"])},
            object_type_api_name=str(meta["api_name"]),
            object_type_display_name=str(meta["display_name"]),
        ))
    return ExplorerPage(items=items, total=total, limit=limit, offset=offset)


# ---- attachments (roadmap Objects item 4) -----------------------------------
# A conservative cap. Attachments are documents and images hanging off an
# object, not datasets - the dataset upload path (50 MB) is the route for
# anything that is actually data, and a limit that quietly allowed a 2 GB
# video through an in-memory read would be a denial of service, not a
# feature.
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


class AttachmentOut(BaseModel):
    """Exactly the object that becomes an `attachment` property's value.

    A storage key, not a URL: a permanent URL would be a public read of
    private bytes, and a presigned one would expire inside a value that
    claims to be stable. The key is exchanged for bytes by the download route
    below, which runs the caller's permission check first - the only point at
    which "may this person see this file" can honestly be answered.
    """

    key: str
    filename: str
    content_type: str
    size: int


@router.post("/attachments", response_model=AttachmentOut,
             status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    request: Request,
    file: UploadFile = File(...),
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> AttachmentOut:
    """Store a file and return the reference to put in a property value.

    Workspace-scoped rather than per-instance, and deliberately decoupled
    from the write that uses it: the upload happens while a form is being
    filled in, before anyone has decided which instance (or even which
    property) it belongs to. The consequence is stated rather than hidden -
    an upload that is never referenced leaves bytes in storage, which is the
    same class of orphan as replacing an attachment (see migration 0029).
    """
    storage = _dataset_storage()
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(
            f"attachment exceeds the {MAX_ATTACHMENT_BYTES // (1024 * 1024)} MB limit"
        )
    if not data:
        raise ValueError("attachment is empty")

    async with user_connection(access.auth.user_id) as conn:
        prefix = await dataset_service.workspace_s3_prefix(conn, access.workspace_id)
    # Under the workspace's own s3_prefix, like every other byte this
    # platform stores (§16's isolation anchor), with a random component so
    # two uploads of the same filename cannot collide or overwrite.
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "file")[:120]
    key = f"{prefix}attachments/{uuid4()}/{safe_name}"
    await anyio.to_thread.run_sync(storage.put, key, data)

    async with user_connection(access.auth.user_id) as conn:
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="attachment.upload",
            resource_type="attachment",
            resource_id=None,
            workspace_id=access.workspace_id,
            metadata={"filename": safe_name, "size": len(data)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return AttachmentOut(
        key=key,
        filename=safe_name,
        content_type=file.content_type or "application/octet-stream",
        size=len(data),
    )


@router.get("/attachments/download", response_class=Response)
async def download_attachment(
    key: str = Query(..., max_length=1024),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> Response:
    """Exchange a storage key for its bytes, having checked the caller may.

    **The key is checked against the workspace's own prefix**, not trusted.
    An attachment value is a plain string inside a JSON blob, so a caller can
    put any key they like in it; without this check, a workspace editor could
    store `<other-workspace-prefix>/datasets/.../data.parquet` as an
    "attachment" and read another tenant's data through this route. The
    prefix comparison is the isolation boundary here, exactly as the index
    name is for OpenSearch (§35).

    Content-Disposition is always `attachment` and the content type is always
    a generic octet-stream: the type recorded at upload is what the uploader
    *claimed*, nothing has sniffed the bytes, and serving user-supplied
    content inline with a user-supplied type is how a stored XSS happens.
    """
    storage = _dataset_storage()
    async with user_connection(access.auth.user_id) as conn:
        prefix = await dataset_service.workspace_s3_prefix(conn, access.workspace_id)
    if not key.startswith(f"{prefix}attachments/"):
        raise NotFoundError("attachment")
    try:
        data = await anyio.to_thread.run_sync(storage.read, key)
    except Exception as exc:  # StorageKeyError and friends
        raise NotFoundError("attachment") from exc
    filename = key.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
            from_property=body.from_property,
            to_property=body.to_property,
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


@router.patch("/link-types/{link_id}", response_model=LinkTypeOut)
async def update_link_join(
    link_id: UUID,
    body: LinkJoinUpdate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> LinkTypeOut:
    """Map the properties a link joins on, so it becomes traversable (roadmap
    Objects item 3), or clear them back to a definition-only link type."""
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.set_link_join(
            conn,
            access.workspace_id,
            link_id,
            from_property=body.from_property,
            to_property=body.to_property,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="link_type.update_join",
            resource_type="link_type",
            resource_id=link_id,
            workspace_id=access.workspace_id,
            metadata={"from_property": row["from_property"], "to_property": row["to_property"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return LinkTypeOut(**row)


# ---- link traversal ----------------------------------------------------------
class LinkedInstances(BaseModel):
    """One link, from the point of view of the instance in hand: what the
    relationship is called, which way it runs, and a first page of the
    instances on the far side."""

    link_type_id: UUID
    api_name: str
    display_name: str
    cardinality: str
    direction: str  # "outbound" (this type is the from end) | "inbound"
    far_type_id: UUID
    far_type_display_name: str
    near_property: str
    far_property: str
    matched_value: Any | None
    total: int
    items: list[InstanceOut]


LINK_PREVIEW_LIMIT = 10


@router.get(
    "/object-types/{type_id}/instances/{instance_id}/links",
    response_model=list[LinkedInstances],
)
async def instance_links(
    type_id: UUID,
    instance_id: UUID,
    limit: int = Query(default=LINK_PREVIEW_LIMIT, ge=1, le=50),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[LinkedInstances]:
    """Traverse every mapped link from one instance (roadmap Objects item 3).

    All of an instance's links in one response rather than one request per
    link: the point of the panel is "what is this object connected to", and
    that question is not answerable a link at a time - the client would have
    to fetch the link types, work out which end it is on, and fan out, which
    is exactly the reasoning that belongs here.

    Each group carries a `total` and a first page, not the whole far side. A
    one_to_many link can traverse to thousands of instances, and the panel
    that shows them is a preview with a count, so paging every group to
    exhaustion would be work nobody asked for. Follow-up paging goes through
    the ordinary instance list for the far type.
    """
    async with user_connection(access.auth.user_id) as conn:
        # Type visibility first, so an object type in a workspace this caller
        # cannot see 404s on the type rather than on the instance - the
        # instance lookup would also miss, but for the wrong reason.
        links = await ontology_service.links_for_type(conn, access.workspace_id, type_id)
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        store = instance_store.store_for(conn)
        instance = await store.get_instance(
            search_prefix=prefix, object_type_id=type_id, instance_id=str(instance_id)
        )
        if instance is None:
            raise NotFoundError("object instance")
        properties = _jsonb(instance["properties"])

        groups: list[LinkedInstances] = []
        for link in links:
            near = str(link["near_property"])
            far = str(link["far_property"])
            value = (
                instance["primary_key"]
                if near == ontology_service.PRIMARY_KEY_REF
                else properties.get(near)
            )
            rows, total = await store.find_by_property(
                search_prefix=prefix,
                object_type_id=UUID(str(link["far_type_id"])),
                property_name=None if far == ontology_service.PRIMARY_KEY_REF else far,
                value=value,
                limit=limit,
                offset=0,
            )
            groups.append(LinkedInstances(
                link_type_id=UUID(str(link["id"])),
                api_name=str(link["api_name"]),
                display_name=str(link["display_name"]),
                cardinality=str(link["cardinality"]),
                direction=str(link["direction"]),
                far_type_id=UUID(str(link["far_type_id"])),
                far_type_display_name=str(link["far_type_display_name"]),
                near_property=near,
                far_property=far,
                matched_value=value,
                total=total,
                items=[
                    InstanceOut(**{
                        "id": r["id"], "primary_key": r["primary_key"],
                        "properties": _jsonb(r["properties"]), "updated_at": r["updated_at"],
                    })
                    for r in rows
                ],
            ))
    return groups


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
        # The declared types are applied here rather than inside extract_rows,
        # so the reader stays a reader (roadmap Objects item 4). A value that
        # cannot be coerced fails the sync loudly rather than arriving as a
        # silently missing field.
        async with user_connection(access.auth.user_id) as conn:
            property_types = {
                str(p["api_name"]): str(p["data_type"])
                for p in await ontology_service.list_properties(
                    conn, UUID(str(source["object_type_id"]))
                )
            }
        rows = ontology_service.coerce_rows(rows, property_types)
    except (DatasetEngineError, ontology_service.PropertyValueError) as exc:
        ok, error = False, str(exc)

    if ok:
        async with user_connection(access.auth.user_id) as conn:
            prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
            store = instance_store.store_for(conn)
            upserted = await store.upsert_instances(
                search_prefix=prefix,
                object_type_id=UUID(str(source["object_type_id"])),
                source_id=source_id,
                rows=rows,
                synced_at=synced_at,
            )
            removed = await store.delete_stale_instances(
                search_prefix=prefix, source_id=source_id, synced_before=synced_at
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


# ---- scheduled sync (worker-driven, for datasets bigger than one request) ----
class SourceScheduleSet(BaseModel):
    cron_schedule: str = Field(min_length=1, max_length=100)


class SourceScheduleOut(BaseModel):
    id: UUID
    sync_schedule: str | None
    sync_next_run_at: datetime | None


@project_router.get("/{source_id}/schedule", response_model=SourceScheduleOut)
async def get_source_schedule(
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> SourceScheduleOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.get_source_schedule(conn, access.project_id, source_id)
    return SourceScheduleOut(**row)


@project_router.put("/{source_id}/schedule", response_model=SourceScheduleOut)
async def set_source_schedule(
    source_id: UUID,
    body: SourceScheduleSet,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SourceScheduleOut:
    next_run_at = next_run_after(body.cron_schedule)
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.set_source_schedule(
            conn, access.project_id, source_id,
            cron_schedule=body.cron_schedule, next_run_at=next_run_at,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_source.schedule_set",
            resource_type="object_type_source",
            resource_id=source_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"cron_schedule": body.cron_schedule},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SourceScheduleOut(**row)


@project_router.delete("/{source_id}/schedule", response_model=SourceScheduleOut)
async def clear_source_schedule(
    source_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SourceScheduleOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await ontology_service.clear_source_schedule(conn, access.project_id, source_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_source.schedule_clear",
            resource_type="object_type_source",
            resource_id=source_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SourceScheduleOut(**row)
