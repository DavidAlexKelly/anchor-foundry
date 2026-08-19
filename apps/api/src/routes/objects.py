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
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..lib.cron import next_run_after
from ..lib.db import user_connection
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import audit
from ..services import datasets as dataset_service
from ..services import dataset_engine as engine
from ..services import time_series as time_series_service
from ..lib.errors import NotFoundError
from ..services import instance_store
from ..services import object_sets
from ..services import object_views as object_views_service
from ..services import instances as instances_service
from ..services import object_searches as searches_service
from ..services import ontology as ontology_service
from ..services import ontology_search
from ..services import shared_properties as shared_properties_service
from ..services import value_types as value_types_service
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
    # **Built from `ontology.PROPERTY_TYPES`, not typed out again.** This was a
    # second copy of the list, and adding `time_series` to the service left it
    # behind - the type existed everywhere except the one place a client could
    # declare it, and the refusal named a pattern rather than a missing
    # feature. One list, one place.
    data_type: str = Field(
        pattern="^(" + "|".join(sorted(ontology_service.PROPERTY_TYPES)) + ")$"
    )
    required: bool = False
    description: str = Field(default="", max_length=1000)
    # How prominently applications should show this (Foundry
    # `object-link-types` p.111). Defaults to `normal`, so a client written
    # before this existed keeps saying exactly what it used to.
    visibility: str = Field(default="normal", pattern="^(normal|prominent|hidden)$")
    # How a reader should see the value (Foundry `object-link-types` p.94-101).
    # Typed as a free-form object here and checked in `services/value_format`,
    # because the rules that matter are about the property's *base type* -
    # which a per-field pydantic model cannot see. Null means unformatted.
    value_format: dict[str, Any] | None = None
    # Ordered conditional formatting rules, first match wins (Foundry
    # `object-link-types` p.102-109). Free-form here for `value_format`'s
    # reason and one more: a rule may name another property, so whether it is
    # legal depends on the *other* properties in the same request.
    conditional_format: list[dict[str, Any]] | None = None
    # No column in any backing dataset (Foundry `object-link-types` p.113).
    # Written by actions straight to the instance and preserved across syncs.
    edit_only: bool = False
    # Where a derived property gets its value (Foundry `object-link-types`
    # p.143). Free-form here and checked in `services/derived_properties`,
    # because whether a chain is legal is a fact about the workspace's link
    # types rather than about this request.
    derivation: dict[str, Any] | None = None
    # The shared property this one inherits its metadata from (Foundry
    # `object-link-types` p.187). Null detaches it (p.188), which is why this
    # is an explicit field rather than something only ever added: an omitted
    # id and a cleared one have to be tellable apart, and the object type
    # editor sends the whole definition every time.
    shared_property_id: UUID | None = None
    # The value type constraining this property (`object-link-types` p.227).
    # Null detaches it. Independent of `shared_property_id`: p.227 allows a
    # value type in either place, and a property may take one from its shared
    # property while choosing its own.
    value_type_id: UUID | None = None
    # Developmental state (`object-link-types` p.253). Defaults to
    # `experimental` (p.256) so a client written before statuses existed keeps
    # saying exactly what it used to.
    status: str = Field(
        default="experimental",
        pattern="^(promoted|active|experimental|deprecated|example)$",
    )
    deprecation: dict[str, Any] | None = None


class PropertyOut(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    data_type: str
    required: bool
    description: str
    sort_order: int
    visibility: str = "normal"
    value_format: dict[str, Any] | None = None
    conditional_format: list[dict[str, Any]] | None = None
    edit_only: bool = False
    derivation: dict[str, Any] | None = None
    shared_property_id: UUID | None = None
    # p.178: "Shared properties on objects are denoted with a globe icon next
    # to their name." The name comes back with the id so an application can
    # say *which* shared property without a second request per property.
    shared_property_api_name: str | None = None
    # This property's *own* choice, which is what a save sends back.
    value_type_id: UUID | None = None
    # What is actually in force, which may have come from the shared property
    # (p.227). Echoing this one back on a save would silently turn an inherited
    # value type into a locally chosen one, so the two are reported apart.
    effective_value_type_id: UUID | None = None
    value_type_api_name: str | None = None
    # The current version's rule (p.230), resolved on the way out so a reader
    # never sees a stale copy. Enforced by the sync and by actions.
    value_constraint: dict[str, Any] | None = None
    status: str = "experimental"
    deprecation: dict[str, Any] | None = None


class ObjectTypeSummary(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    description: str
    icon: str
    colour: str
    title_property_id: UUID | None
    source_count: int
    # The api_names an application should not draw (`object-link-types` p.111).
    # Only the hidden ones: a list endpoint should not carry every property of
    # every type to answer "which columns do I skip".
    hidden_properties: list[str] = Field(default_factory=list)
    # So a caller that has a type can open the type's application (item 4.2)
    # without a second lookup. NOT NULL since db 0032.
    resource_id: UUID
    status: str = "experimental"
    deprecation: dict[str, Any] | None = None
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
    status: str = "experimental"
    deprecation: dict[str, Any] | None = None
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
    # Per-side labels (Foundry `object-link-types` p.192). NULL falls back to
    # `display_name`, which is what every link type had before sides could be
    # named separately.
    from_side_name: str | None = None
    to_side_name: str | None = None
    # p.253's developmental state. What is stored is p.257's cap - a link type
    # may be no more production-ready than the object types it joins or the
    # properties it joins on - so this is the *capped* value, not a request.
    status: str = "experimental"
    deprecation: dict[str, Any] | None = None


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
    # Foundry p.192: each side "has its own display name". Optional, because a
    # link whose two directions read the same way needs only one name.
    from_side_name: str | None = Field(default=None, min_length=1, max_length=200)
    to_side_name: str | None = Field(default=None, min_length=1, max_length=200)
    # p.253's developmental state. Defaults to unchanged, and what is stored
    # is p.257's cap rather than what was asked for.
    status: str | None = Field(
        default=None,
        pattern="^(promoted|active|experimental|deprecated|example)$",
    )


class LinkJoinUpdate(BaseModel):
    """The join and the side names - see ontology.set_link_join for why an
    endpoint or cardinality change is a different link type, not an edit."""

    from_property: str | None = Field(default=None, pattern=_JOIN_PROPERTY)
    to_property: str | None = Field(default=None, pattern=_JOIN_PROPERTY)
    from_side_name: str | None = Field(default=None, min_length=1, max_length=200)
    to_side_name: str | None = Field(default=None, min_length=1, max_length=200)
    # p.253's developmental state. Defaults to unchanged, and what is stored is
    # p.257's cap rather than what was asked for.
    status: str | None = Field(
        default=None,
        pattern="^(promoted|active|experimental|deprecated|example)$",
    )


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
    #: How many synced rows leave each required property empty
    #: (`object-link-types` p.116). Reported rather than refused: the check
    #: belongs to indexing, and a sync that refused would leave an object type
    #: that will not load and no way to see why. Absent keys mean no failures.
    missing_required: dict[str, int]
    # p.227's rule, per property: how many rows broke the value type's
    # constraint and one example of why. Reported rather than refused - see
    # `instances.constraint_violation_counts`.
    constraint_violations: dict[str, dict[str, Any]] = Field(default_factory=dict)
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


# ---- searching the ontology (`ontology-manager` p.28) ------------------------
class OntologySearchHit(BaseModel):
    """One thing found, and **which field found it**.

    p.28: "the search results highlight the specific field that matched your
    query". That is a fact the matcher knows and the browser would otherwise
    have to re-derive - which would be a second matcher, free to disagree with
    the one that put the row in the list.
    """

    kind: str  # object_type | property | link_type | action_type | shared_property
    id: UUID
    api_name: str
    display_name: str
    # Where it lives. A property called "status" is not somewhere anybody can
    # navigate to; "status on Ticket" is.
    #
    # **Null for a shared property**, which belongs to no object type by
    # definition (`object-link-types` p.178). Optional rather than faked: a
    # made-up owner would send whoever clicked it to a type that has nothing
    # to do with what they searched for.
    object_type_id: UUID | None = None
    object_type_name: str = ""
    # How many properties use it, for the one kind with no owner to name.
    usage_count: int | None = None
    matched_field: str
    matched_value: str


@router.get("/ontology-search", response_model=list[OntologySearchHit])
async def search_ontology(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[OntologySearchHit]:
    """One search across object types, their properties, link types and action
    types (p.28). Viewer, like everything else that only reads the ontology."""
    async with user_connection(access.auth.user_id) as conn:
        rows = await ontology_search.search(conn, access.workspace_id, q, limit=limit)
    return [OntologySearchHit(**r) for r in rows]


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
    # p.253's developmental state. Optional and defaulting to *unchanged* -
    # not to `experimental` - because this is a whole-definition PUT and a
    # client that has never heard of statuses must not silently demote a type
    # somebody promoted.
    status: str | None = Field(
        default=None,
        pattern="^(promoted|active|experimental|deprecated|example)$",
    )
    deprecation: dict[str, Any] | None = None
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
            status=body.status,
            deprecation=body.deprecation,
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


# ---- configured Object Views (`object-views` p.2-4) --------------------------
class ObjectViewOut(BaseModel):
    """Which Workshop module stands in for this object type's standard view."""

    id: UUID
    object_type_id: UUID
    canvas_app_id: UUID
    canvas_app_name: str
    form_factor: str
    subject_variable: str
    created_at: datetime
    updated_at: datetime


class ObjectViewIn(BaseModel):
    canvas_app_id: UUID
    subject_variable: str = Field(min_length=1, max_length=200)
    form_factor: str = Field(default="full", max_length=16)


@router.get("/object-types/{type_id}/view", response_model=ObjectViewOut | None)
async def get_object_view(
    type_id: UUID,
    form_factor: str = Query(default="full", max_length=16),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectViewOut | None:
    """**Null, not 404, when there is none.** Every object screen asks this on
    the way to rendering something, and "this type has no configured view" is
    the ordinary answer rather than a mistake - p.10's standard view is what
    happens next."""
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, type_id)
        row = await object_views_service.get_view(
            conn, access.workspace_id, type_id, form_factor=form_factor
        )
    return ObjectViewOut(**row) if row else None


@router.put("/object-types/{type_id}/view", response_model=ObjectViewOut)
async def set_object_view(
    type_id: UUID,
    body: ObjectViewIn,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ObjectViewOut:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, type_id)
        row = await object_views_service.set_view(
            conn,
            access.workspace_id,
            type_id,
            canvas_app_id=body.canvas_app_id,
            subject_variable=body.subject_variable,
            form_factor=body.form_factor,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_view.set",
            resource_type="object_type",
            resource_id=type_id,
            workspace_id=access.workspace_id,
            metadata={
                "canvas_app_id": str(body.canvas_app_id),
                "form_factor": body.form_factor,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ObjectViewOut(**row)


@router.delete(
    "/object-types/{type_id}/view",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def clear_object_view(
    type_id: UUID,
    request: Request,
    form_factor: str = Query(default="full", max_length=16),
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> None:
    """Stop using a module as this type's view. The module is untouched - what
    goes is the pointer, and what comes back is the standard view, which never
    went anywhere (p.2)."""
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, type_id)
        await object_views_service.clear_view(
            conn, access.workspace_id, type_id, form_factor=form_factor
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_view.clear",
            resource_type="object_type",
            resource_id=type_id,
            workspace_id=access.workspace_id,
            metadata={"form_factor": form_factor},
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
        # p.143: derived properties are "calculated at runtime". Filled in
        # here, on the single-object read, and nowhere else - see
        # `_with_derived` for why a list read does not get them.
        row = await _with_derived(
            conn, instance_store.store_for(conn), prefix, access.workspace_id,
            type_id, row,
        )
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


# ---- saved searches (ROADMAP.md phase 2, item 4.1) --------------------------
class SearchDefinitionIn(BaseModel):
    q: str | None = Field(default=None, max_length=200)
    type_ids: list[UUID] = Field(default_factory=list)
    property: str | None = Field(default=None, max_length=100)
    value: str | None = Field(default=None, max_length=500)


class SearchOut(BaseModel):
    id: UUID
    workspace_id: UUID
    name: str
    description: str
    definition: dict[str, Any]
    # Resolved for display. `missing_types` are ids the workspace no longer
    # has: the search still opens and that filter simply matches nothing, which
    # is more useful than refusing to open something somebody may want to
    # repair.
    type_names: list[str]
    missing_types: list[str]
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class SearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    definition: SearchDefinitionIn


class SearchPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    definition: SearchDefinitionIn | None = None


def _parsed(body: SearchDefinitionIn) -> dict[str, Any]:
    try:
        return searches_service.parse(
            q=body.q, type_ids=body.type_ids,
            property_name=body.property, value=body.value,
        )
    except searches_service.SearchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/object-searches", response_model=list[SearchOut])
async def list_object_searches(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[SearchOut]:
    """Saved searches are shared within the workspace, not private to whoever
    wrote them - a saved search is usually a definition of a cohort a team
    argues about, and one only its author can see gets reinvented slightly
    differently by everybody else."""
    async with user_connection(access.auth.user_id) as conn:
        rows = await searches_service.list_searches(conn, access.workspace_id)
    return [SearchOut(**r) for r in rows]


@router.post("/object-searches", response_model=SearchOut, status_code=status.HTTP_201_CREATED)
async def create_object_search(
    body: SearchCreate,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> SearchOut:
    definition = _parsed(body.definition)
    async with user_connection(access.auth.user_id) as conn:
        row = await searches_service.create_search(
            conn, access.workspace_id,
            name=body.name.strip(), description=body.description,
            definition=definition, created_by=access.auth.user_id,
        )
    return SearchOut(**row)


@router.patch("/object-searches/{search_id}", response_model=SearchOut)
async def update_object_search(
    search_id: UUID,
    body: SearchPatch,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> SearchOut:
    definition = _parsed(body.definition) if body.definition is not None else None
    async with user_connection(access.auth.user_id) as conn:
        row = await searches_service.update_search(
            conn, access.workspace_id, search_id,
            name=body.name.strip() if body.name else None,
            description=body.description, definition=definition,
        )
    return SearchOut(**row)


@router.delete("/object-searches/{search_id}", status_code=status.HTTP_204_NO_CONTENT,
               response_model=None)
async def delete_object_search(
    search_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await searches_service.delete_search(conn, access.workspace_id, search_id)


@router.get("/object-instances", response_model=ExplorerPage)
async def explore_instances(
    q: str | None = Query(default=None, max_length=200),
    type_id: list[UUID] | None = Query(default=None),
    property: str | None = Query(default=None, max_length=100),
    value: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ExplorerPage:
    """Search and browse every instance in the workspace at once (roadmap
    Objects item 2), across types rather than within one.

    Workspace-scoped like the ontology it searches: object types are
    workspace-wide, so an explorer that stopped at a project boundary would
    show a partial ontology and call it the whole one.

    **`property`+`value` is an exact match, and is a different question from
    `q`** (roadmap Canvas item 3, which needed it). `q` is substring/prefix
    matching across every property at once - the right behaviour for a search
    box, and the wrong one for a dropdown, where picking the region "North"
    must not also return a customer called "Northwind". The store Protocol has
    had `find_by_property` since roadmap Objects item 3; this exposes it.

    It requires **exactly one** `type_id`, because a property api_name only
    means anything within a type - "status" on an Order and "status" on a
    Shipment are unrelated columns that happen to share a name, and matching
    across both would silently union two different questions.
    """
    # The same function a saved search is validated with (item 4.1). The rule
    # used to live here; it moved so that saving a search that cannot run is
    # refused at save time rather than at open time.
    try:
        searches_service.parse(
            q=q, type_ids=type_id, property_name=property, value=value,
            require_criteria=False,
        )
    except searches_service.SearchError as exc:
        raise ValueError(str(exc)) from exc

    async with user_connection(access.auth.user_id) as conn:
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        store = instance_store.store_for(conn)
        if property is not None:
            assert type_id is not None
            try:
                await ontology_service.get_type(conn, access.workspace_id, type_id[0])
            except NotFoundError:
                # A type id this workspace does not have matches nothing, which
                # is what the no-property branch below already answers for the
                # same id. A saved search (item 4.1) can outlive the type it
                # names, and it must give the same answer whether or not it
                # also carries a property filter - one branch refusing and the
                # other quietly returning nothing is two behaviours for one
                # question. Isolation does not rest on this lookup: the search
                # prefix above is workspace-scoped, so another workspace's
                # instances are unreachable either way, and an empty page is
                # what an unknown id gets whether or not it exists elsewhere.
                return ExplorerPage(items=[], total=0, limit=limit, offset=offset)
            rows, total = await store.find_by_property(
                search_prefix=prefix,
                object_type_id=type_id[0],
                # The primary key is a field on the instance, not one of its
                # properties - same reserved reference link joins use (db 0027).
                property_name=(
                    None if property == ontology_service.PRIMARY_KEY_REF else property
                ),
                value=value,
                limit=limit,
                offset=offset,
            )
            # find_by_property is the link-traversal read and returns rows
            # without the type id (its caller always knew it); the explorer's
            # response says what each row is, so fill it back in.
            rows = [{**row, "object_type_id": str(type_id[0])} for row in rows]
        else:
            rows, total = await store.search(
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


#: The only content types this route will ever serve **inline** (decision
#: 0009, part 2). Not a convenience list - it is the security boundary.
#:
#: The type recorded at upload is what the uploader *claimed*; nothing has
#: sniffed the bytes. Serving a claimed type inline is how a stored XSS
#: happens, so the claim is only honoured when it is one of these, and the
#: response carries `X-Content-Type-Options: nosniff` so a file that is
#: really HTML fails to decode as an image rather than being run as a
#: document.
#:
#: **`image/svg+xml` is deliberately absent.** An SVG is an image the browser
#: will execute script inside, and this route is same-origin. It downloads,
#: like it always did, and `components/media-kind.ts` makes the same call on
#: the other side so the two never disagree about what is showable.
INLINE_CONTENT_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/avif", "image/bmp",
    "video/mp4", "video/webm", "video/ogg",
    "audio/mpeg", "audio/ogg", "audio/wav", "audio/webm", "audio/aac", "audio/flac",
})


@router.get("/attachments/download", response_class=Response)
async def download_attachment(
    key: str = Query(..., max_length=1024),
    disposition: str = Query(default="attachment", max_length=16),
    content_type: str = Query(default="", max_length=128),
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

    **Downloading is still the default and still the safe one.** The original
    version of this route had no other mode, for a reason worth restating: the
    content type is the uploader's claim, so serving it inline is how a stored
    XSS happens. Decision 0009 needed an image to be *shown* rather than
    offered, and the way that is earned rather than assumed is:

      * inline only when the caller asks for it - a link that wants a file
        keeps getting a file;
      * only for a type on `INLINE_CONTENT_TYPES`, which this route decides,
        not the uploader - anything else falls back to a download rather than
        refusing, so a mislabelled file is a link and not an error;
      * with `nosniff`, so a file that is really HTML fails to decode as an
        image instead of being run as a document.

    A caller cannot widen this by asking: `content_type` is checked against
    the allowlist and ignored otherwise.
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

    wanted = content_type.split(";")[0].strip().lower()
    inline = disposition == "inline" and wanted in INLINE_CONTENT_TYPES
    return Response(
        content=data,
        media_type=wanted if inline else "application/octet-stream",
        headers={
            "Content-Disposition": (
                f'{"inline" if inline else "attachment"}; filename="{filename}"'
            ),
            # On every response, not just the inline ones: the download path
            # serves octet-stream and should not be sniffed into anything
            # either.
            "X-Content-Type-Options": "nosniff",
        },
    )


# ---- value types (workspace-scoped; `object-link-types` p.222-234) ----------
class ValueTypeOut(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    description: str
    example_value: str
    # From the current version (p.230), not from the value type itself: both
    # are immutable per version, and reporting them here is what stops a caller
    # having to fetch the version list to know what is being enforced.
    base_type: str
    version_number: int
    constraint: dict[str, Any] | None = None
    # The same rule as a sentence, so a listing has something to show that is
    # shorter than the shape and more use than the kind.
    constraint_summary: str = ""
    usage_count: int = 0
    created_at: datetime
    updated_at: datetime


class ValueTypeVersionOut(BaseModel):
    id: UUID
    version_number: int
    base_type: str
    constraint: dict[str, Any] | None = None
    constraint_summary: str = ""
    created_at: datetime


class ValueTypeUsageOut(BaseModel):
    # p.227 names two places a value type can be used, and they are different
    # enough that a row has to say which it is.
    kind: str  # "object_type_property" | "shared_property"
    owner_name: str
    property_api_name: str
    object_type_id: UUID | None = None


class ValueTypeCreate(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    example_value: str = Field(default="", max_length=200)
    base_type: str = Field(
        pattern="^(" + "|".join(sorted(ontology_service.PROPERTY_TYPES)) + ")$"
    )
    # Free-form here and checked in `services/value_constraints`, for
    # `value_format`'s reason: which fields are legal depends on the base type,
    # which a per-field pydantic model cannot see.
    constraint: dict[str, Any] | None = None


class ValueTypeMetadataUpdate(BaseModel):
    """p.229's mutable half. No `api_name` and no `base_type`: the first is the
    stable machine name a consumer holds, the second p.229 calls immutable."""

    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    example_value: str = Field(default="", max_length=200)


class ValueTypeVersionCreate(BaseModel):
    """p.229's immutable half: a constraint change is a new version."""

    constraint: dict[str, Any] | None = None


@router.get("/value-types", response_model=list[ValueTypeOut])
async def list_value_types(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ValueTypeOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await value_types_service.list_types(conn, access.workspace_id)
    return [ValueTypeOut(**r) for r in rows]


@router.post(
    "/value-types", response_model=ValueTypeOut, status_code=status.HTTP_201_CREATED
)
async def create_value_type(
    body: ValueTypeCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ValueTypeOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await value_types_service.create(
            conn,
            workspace_id=access.workspace_id,
            api_name=body.api_name,
            display_name=body.display_name,
            description=body.description,
            example_value=body.example_value,
            base_type=body.base_type,
            constraint_raw=body.constraint,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="value_type.create",
            resource_type="value_type",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"api_name": body.api_name, "base_type": body.base_type},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ValueTypeOut(**row)


@router.get("/value-types/{value_type_id}/versions",
            response_model=list[ValueTypeVersionOut])
async def list_value_type_versions(
    value_type_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ValueTypeVersionOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await value_types_service.list_versions(
            conn, access.workspace_id, value_type_id
        )
    return [ValueTypeVersionOut(**r) for r in rows]


@router.get("/value-types/{value_type_id}/usage",
            response_model=list[ValueTypeUsageOut])
async def value_type_usage(
    value_type_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[ValueTypeUsageOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await value_types_service.usage(
            conn, access.workspace_id, value_type_id
        )
    return [ValueTypeUsageOut(**r) for r in rows]


@router.patch("/value-types/{value_type_id}", response_model=ValueTypeOut)
async def update_value_type(
    value_type_id: UUID,
    body: ValueTypeMetadataUpdate,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ValueTypeOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await value_types_service.update_metadata(
            conn,
            workspace_id=access.workspace_id,
            value_type_id=value_type_id,
            display_name=body.display_name,
            description=body.description,
            example_value=body.example_value,
        )
    return ValueTypeOut(**row)


@router.post("/value-types/{value_type_id}/versions", response_model=ValueTypeOut,
             status_code=status.HTTP_201_CREATED)
async def add_value_type_version(
    value_type_id: UUID,
    body: ValueTypeVersionCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ValueTypeOut:
    """p.229: changing a constraint appends a version rather than editing one.

    A POST to `/versions` rather than a PATCH of the value type, because that
    is what it is - the old rule stays readable, which is the whole reason
    p.229 makes constraints immutable.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await value_types_service.add_version(
            conn,
            workspace_id=access.workspace_id,
            value_type_id=value_type_id,
            constraint_raw=body.constraint,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="value_type.version",
            resource_type="value_type",
            resource_id=value_type_id,
            workspace_id=access.workspace_id,
            metadata={"version_number": row["version_number"],
                      "usage_count": row["usage_count"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return ValueTypeOut(**row)


@router.delete("/value-types/{value_type_id}",
               status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_value_type(
    value_type_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> Response:
    async with user_connection(access.auth.user_id) as conn:
        users = await value_types_service.usage(
            conn, access.workspace_id, value_type_id
        )
        await value_types_service.delete(conn, access.workspace_id, value_type_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="value_type.delete",
            resource_type="value_type",
            resource_id=value_type_id,
            workspace_id=access.workspace_id,
            # The number that answers "what did that delete do" - these
            # properties are no longer constrained by anything.
            metadata={"unconstrained_properties": len(users)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- shared properties (workspace-scoped; `object-link-types` p.178-191) ----
class SharedPropertyOut(BaseModel):
    id: UUID
    api_name: str
    display_name: str
    description: str
    data_type: str
    visibility: str
    value_format: dict[str, Any] | None = None
    # p.227: a value type may sit on a shared property, so every property that
    # attaches to it inherits the constraint without choosing one itself.
    value_type_id: UUID | None = None
    # p.191's Usage, as a number. The list of object types is its own endpoint,
    # because "is anyone using this" and "who exactly" are asked at different
    # moments - the first before deleting, the second after being surprised.
    usage_count: int = 0
    created_at: datetime
    updated_at: datetime


class SharedPropertyUsageOut(BaseModel):
    object_type_id: UUID
    object_type_api_name: str
    object_type_display_name: str
    # p.188 lets the object type's own property keep a different name, so the
    # usage row has to say which property it is or it answers half the question.
    property_api_name: str


class SharedPropertyCreate(BaseModel):
    api_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    data_type: str = Field(
        pattern="^(" + "|".join(sorted(ontology_service.PROPERTY_TYPES)) + ")$"
    )
    visibility: str = Field(default="normal", pattern="^(normal|prominent|hidden)$")
    value_format: dict[str, Any] | None = None
    value_type_id: UUID | None = None


class SharedPropertyUpdate(BaseModel):
    """No `api_name`: it is the stable machine name a consumer holds, for
    `object_types.api_name`'s reason (db 0003)."""

    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    data_type: str = Field(
        pattern="^(" + "|".join(sorted(ontology_service.PROPERTY_TYPES)) + ")$"
    )
    visibility: str = Field(default="normal", pattern="^(normal|prominent|hidden)$")
    value_format: dict[str, Any] | None = None
    value_type_id: UUID | None = None


@router.get("/shared-properties", response_model=list[SharedPropertyOut])
async def list_shared_properties(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[SharedPropertyOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await shared_properties_service.list_shared(conn, access.workspace_id)
    return [SharedPropertyOut(**r) for r in rows]


@router.post(
    "/shared-properties",
    response_model=SharedPropertyOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_shared_property(
    body: SharedPropertyCreate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> SharedPropertyOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await shared_properties_service.create_shared(
            conn,
            workspace_id=access.workspace_id,
            api_name=body.api_name,
            display_name=body.display_name,
            description=body.description,
            data_type=body.data_type,
            visibility=body.visibility,
            value_format_raw=body.value_format,
            value_type_id=body.value_type_id,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="shared_property.create",
            resource_type="shared_property",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            metadata={"api_name": body.api_name, "data_type": body.data_type},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SharedPropertyOut(**row)


@router.get(
    "/shared-properties/{shared_id}/usage",
    response_model=list[SharedPropertyUsageOut],
)
async def shared_property_usage(
    shared_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[SharedPropertyUsageOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await shared_properties_service.usage(
            conn, access.workspace_id, shared_id
        )
    return [SharedPropertyUsageOut(**r) for r in rows]


@router.patch("/shared-properties/{shared_id}", response_model=SharedPropertyOut)
async def update_shared_property(
    shared_id: UUID,
    body: SharedPropertyUpdate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> SharedPropertyOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await shared_properties_service.update_shared(
            conn,
            workspace_id=access.workspace_id,
            shared_id=shared_id,
            display_name=body.display_name,
            description=body.description,
            data_type=body.data_type,
            visibility=body.visibility,
            value_format_raw=body.value_format,
            value_type_id=body.value_type_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="shared_property.update",
            resource_type="shared_property",
            resource_id=shared_id,
            workspace_id=access.workspace_id,
            metadata={"usage_count": row["usage_count"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SharedPropertyOut(**row)


@router.delete(
    "/shared-properties/{shared_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_shared_property(
    shared_id: UUID,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> Response:
    """p.185: every object type using it reverts to a regular property.

    Not refused when in use, and the audit record says how many reverted -
    which is the number somebody will want when they ask what that delete did.
    """
    async with user_connection(access.auth.user_id) as conn:
        users = await shared_properties_service.usage(
            conn, access.workspace_id, shared_id
        )
        await shared_properties_service.delete_shared(
            conn, access.workspace_id, shared_id
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="shared_property.delete",
            resource_type="shared_property",
            resource_id=shared_id,
            workspace_id=access.workspace_id,
            metadata={"reverted_properties": len(users)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
            from_side_name=body.from_side_name,
            to_side_name=body.to_side_name,
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
            from_side_name=body.from_side_name,
            to_side_name=body.to_side_name,
            status=body.status,
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
    # What the side you are traversing *to* is called (p.192). Already resolved
    # against `display_name`, so a caller never has to know which side it is on
    # to render a label - which is the same reason `near_property` exists.
    side_name: str
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
                side_name=str(link["side_name"]),
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
    missing: dict[str, int] = {}
    violations: dict[str, dict[str, Any]] = {}
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
            declared = await ontology_service.list_properties(
                conn, UUID(str(source["object_type_id"]))
            )
            # p.116's sync report, minus the properties this dataset cannot
            # speak for. An **edit-only** property (p.113) has no column here,
            # so `rows` never carries it and every row would be counted as
            # missing - a report that flagged every object of the type on
            # every sync, saying nothing about the data. Actions still refuse
            # to empty one, which is where a required edit-only property is
            # actually enforceable.
            missing = instances_service.missing_required(
                rows,
                ontology_service.required_properties(declared)
                - ontology_service.edit_only_properties(declared),
            )
            # p.227's rule, reported rather than refused - see
            # `constraint_violation_counts` for why this platform diverges
            # from "the object type will fail to index". Edit-only properties
            # are excluded for the same reason as above: this dataset has no
            # column for one, so every row would be judged on a value it was
            # never asked to carry.
            violations = instances_service.constraint_violation_counts(
                rows,
                {
                    name: rule
                    for name, rule in ontology_service.constrained_properties(
                        declared
                    ).items()
                    if name not in ontology_service.edit_only_properties(declared)
                },
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
            metadata={
                "ok": ok, "upserted": upserted, "removed": removed,
                # In the audit log too: "when did this type start failing its
                # own rule" is a question about history, and the sync result is
                # gone the moment the response is read.
                **({"missing_required": missing} if missing else {}),
                **({"constraint_violations": violations} if violations else {}),
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return SyncResult(
        ok=ok, error=error, upserted=upserted, removed=removed,
        missing_required=missing, constraint_violations=violations,
        source=_source_out(updated_source),
    )


# ---- scheduled sync (worker-driven, for datasets bigger than one request) ----
class SourceScheduleSet(BaseModel):
    cron_schedule: str = Field(min_length=1, max_length=100)


class SourceScheduleOut(BaseModel):
    id: UUID
    sync_schedule: str | None
    sync_next_run_at: datetime | None


# ---- time series (decision 0009 part 1; db 0047) -----------------------------
class SeriesOut(BaseModel):
    """Where one `time_series` property's points live."""

    id: UUID
    object_type_source_id: UUID
    property_api_name: str
    dataset_id: UUID
    dataset_name: str
    key_column: str
    timestamp_column: str
    value_column: str
    created_at: datetime
    updated_at: datetime


class SeriesIn(BaseModel):
    property_api_name: str = Field(min_length=1, max_length=100)
    dataset_id: UUID
    key_column: str = Field(min_length=1, max_length=200)
    timestamp_column: str = Field(min_length=1, max_length=200)
    value_column: str = Field(min_length=1, max_length=200)


class SeriesPoint(BaseModel):
    at: Any
    value: Any


class SeriesPoints(BaseModel):
    property_api_name: str
    series_id: str
    interval: str
    aggregate: str
    points: list[SeriesPoint]
    truncated: bool


@project_router.get("/{source_id}/series", response_model=list[SeriesOut])
async def list_series(
    source_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[SeriesOut]:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_source(conn, access.project_id, source_id)
        rows = await time_series_service.list_series(conn, source_id)
    return [SeriesOut(**r) for r in rows]


@project_router.put("/{source_id}/series", response_model=SeriesOut)
async def set_series(
    source_id: UUID,
    body: SeriesIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> SeriesOut:
    """Point a `time_series` property at the dataset holding its points.

    **The dataset's own schema is what the columns are checked against**, read
    here and handed to the service: the service does not touch Parquet, and a
    check against anything else - a remembered schema, the caller's word -
    would let a chart be configured that could never draw.
    """
    async with user_connection(access.auth.user_id) as conn:
        source = await ontology_service.get_source(conn, access.project_id, source_id)
        dataset = await dataset_service.get(conn, access.project_id, body.dataset_id)
        properties = await ontology_service.list_properties(
            conn, UUID(str(source["object_type_id"]))
        )
        columns = {
            str(c["name"]) for c in (_jsonb(dataset["table_schema"]) or [])
            if isinstance(c, dict) and c.get("name")
        }
        row = await time_series_service.set_series(
            conn, source_id,
            property_api_name=body.property_api_name,
            dataset_id=body.dataset_id,
            key_column=body.key_column,
            timestamp_column=body.timestamp_column,
            value_column=body.value_column,
            columns=columns,
            property_types={p["api_name"]: p["data_type"] for p in properties},
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_series.set",
            resource_type="object_type_source",
            resource_id=source_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"property": body.property_api_name,
                      "dataset_id": str(body.dataset_id)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        return SeriesOut(**{**row, "dataset_name": dataset["name"]})


@project_router.delete(
    "/{source_id}/series/{property_api_name}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def clear_series(
    source_id: UUID,
    property_api_name: str,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_source(conn, access.project_id, source_id)
        await time_series_service.clear_series(conn, source_id, property_api_name)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="object_type_series.clear",
            resource_type="object_type_source",
            resource_id=source_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"property": property_api_name},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


@project_router.get(
    "/{source_id}/series/{property_api_name}/points", response_model=SeriesPoints
)
async def read_series_points(
    source_id: UUID,
    property_api_name: str,
    series_id: str = Query(..., max_length=500),
    interval: str = Query(default="none", max_length=16),
    aggregate: str = Query(default="avg", max_length=16),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=time_series_service.MAX_POINTS, ge=1),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> SeriesPoints:
    """The points behind one instance's `time_series` property.

    **Read from the dataset, every time, and never copied** (decision 0009).
    The cost of that is stated in the decision and worth repeating where
    somebody is reading the endpoint: points are as fresh as the dataset, so a
    live feed is a sync away from the chart rather than a stream.
    """
    storage = _dataset_storage()
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_source(conn, access.project_id, source_id)
        series = await time_series_service.get_series(conn, source_id, property_api_name)
        if series is None:
            raise NotFoundError("time series")
        dataset = await dataset_service.get(
            conn, access.project_id, UUID(str(series["dataset_id"]))
        )

    sql = time_series_service.points_sql(
        key_column=str(series["key_column"]),
        timestamp_column=str(series["timestamp_column"]),
        value_column=str(series["value_column"]),
        series_id=series_id,
        interval=interval,
        aggregate=aggregate,
        start=start,
        end=end,
        limit=limit,
    )
    local_path = await anyio.to_thread.run_sync(
        storage.local_path, str(dataset["s3_location"])
    )
    result = await anyio.to_thread.run_sync(engine.query, local_path, sql)
    return SeriesPoints(
        property_api_name=property_api_name,
        series_id=series_id,
        interval=interval,
        aggregate=aggregate,
        points=[SeriesPoint(at=row[0], value=row[1]) for row in result.rows],
        truncated=result.truncated,
    )


@router.get(
    "/object-types/{type_id}/instances/{instance_id}/series/{property_api_name}/points",
    response_model=SeriesPoints,
)
async def instance_series_points(
    type_id: UUID,
    instance_id: UUID,
    property_api_name: str,
    interval: str = Query(default="none", max_length=16),
    aggregate: str = Query(default="avg", max_length=16),
    limit: int = Query(default=time_series_service.MAX_POINTS, ge=1),
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> SeriesPoints:
    """One object's points, asked for the way somebody looking at the object asks.

    **Workspace-scoped, like every other read of an instance.** The Object
    Explorer and the standard Object View are both workspace-wide (§17, §122) -
    the ontology is shared across a workspace, and instance *properties* are
    already visible at this floor. A time series property's points are the
    value of one of those properties, so putting them behind project
    membership would make one property readable and another not, on the same
    screen, for no reason a reader could see.

    **The series id is not a parameter.** It is the instance's own value for
    that property, read here - a caller passing one could ask for somebody
    else's series through an instance they can see, and the question this
    endpoint answers is "this object's readings" rather than "these readings".
    """
    storage = _dataset_storage()
    async with user_connection(access.auth.user_id) as conn:
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        instance = await instance_store.store_for(conn).get_instance(
            search_prefix=prefix, object_type_id=type_id, instance_id=str(instance_id)
        )
        if instance is None:
            raise NotFoundError("object instance")
        series = await time_series_service.series_for_source(
            conn, UUID(str(instance["source_id"])), property_api_name
        )
        if series is None:
            raise NotFoundError("time series")

    properties = _jsonb(instance["properties"]) or {}
    series_id = properties.get(property_api_name)
    if series_id is None or str(series_id).strip() == "":
        # The property is declared and the series is mapped; this object simply
        # has no series id. An empty chart is the honest answer - a 404 would
        # say the *configuration* is missing, which it is not.
        return SeriesPoints(
            property_api_name=property_api_name, series_id="",
            interval=interval, aggregate=aggregate, points=[], truncated=False,
        )

    sql = time_series_service.points_sql(
        key_column=str(series["key_column"]),
        timestamp_column=str(series["timestamp_column"]),
        value_column=str(series["value_column"]),
        series_id=str(series_id),
        interval=interval,
        aggregate=aggregate,
        limit=limit,
    )
    local_path = await anyio.to_thread.run_sync(
        storage.local_path, str(series["s3_location"])
    )
    result = await anyio.to_thread.run_sync(engine.query, local_path, sql)
    return SeriesPoints(
        property_api_name=property_api_name,
        series_id=str(series_id),
        interval=interval,
        aggregate=aggregate,
        points=[SeriesPoint(at=row[0], value=row[1]) for row in result.rows],
        truncated=result.truncated,
    )


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


# ---- object sets (roadmap phase 2, item 1.2) --------------------------------
class ObjectSetIn(BaseModel):
    """A set *definition*, not a set. What a Workshop variable holds is the
    description - type plus filters - which is small, serialisable and the same
    for every viewer; the rows come from evaluating it."""

    definition: dict[str, Any]
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    # Validated in the handler rather than by an enum here, so an unsupported
    # sort gets the sentence explaining what it would take (`object_sets`)
    # instead of Pydantic's list of permitted literals.
    sort: str | None = None


class ObjectSetOut(BaseModel):
    instances: list[InstanceOut]
    # The size of the whole set, not of this page. "127 sites match" is the
    # answer a Workshop app needs and the one a page of rows cannot give.
    total: int
    limit: int
    offset: int


class ObjectSetAggregateIn(BaseModel):
    definition: dict[str, Any]
    aggregation: str = "count"
    property: str | None = None


class ObjectSetAggregateOut(BaseModel):
    value: int
    aggregation: str
    property: str | None


@router.post("/object-sets/aggregate", response_model=ObjectSetAggregateOut)
async def aggregate_object_set(
    body: ObjectSetAggregateIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectSetAggregateOut:
    """One number over a whole set - what a Metric Card shows (roadmap 1.5).

    Separate from `/evaluate` rather than a flag on it, because they are
    different questions with different costs: a page of rows, or a number over
    every row. A card that got its number by paging would be wrong the moment
    a set outgrew a page, which is exactly when the number starts mattering.
    """
    definition = object_sets.parse(body.definition)
    try:
        aggregation, property_name = object_sets.parse_aggregation(body.aggregation, body.property)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, definition.object_type_id)
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        value = await instance_store.store_for(conn).aggregate_object_set(
            search_prefix=prefix,
            object_type_id=definition.object_type_id,
            filters=definition.filters,
            aggregation=aggregation,
            property_name=property_name,
        )
    return ObjectSetAggregateOut(
        value=value, aggregation=aggregation, property=property_name
    )


class ObjectSetGroupIn(BaseModel):
    definition: dict[str, Any]
    property: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=object_sets.MAX_GROUPS, ge=1, le=object_sets.MAX_GROUPS)


class ObjectSetGroupOut(BaseModel):
    groups: list[dict[str, Any]]
    """`[{value, count}]`, count descending then value ascending."""
    distinct_total: int
    """How many distinct values the set actually has. `truncated` is derived
    from it rather than from "did we fill the page", which would be wrong on a
    set with exactly `limit` groups."""
    truncated: bool


@router.post("/object-sets/group", response_model=ObjectSetGroupOut)
async def group_object_set(
    body: ObjectSetGroupIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectSetGroupOut:
    """How many in each distinct value of one property - what a chart over a
    set plots (roadmap 1.5).

    A grouped *count* only. A grouped sum has the same problem a plain sum
    does: instance properties are stored untyped, so the two stores would
    disagree about what the bar heights are. See `object_sets`.
    """
    definition = object_sets.parse(body.definition)
    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, definition.object_type_id)
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        buckets, distinct_total = await instance_store.store_for(conn).group_object_set(
            search_prefix=prefix,
            object_type_id=definition.object_type_id,
            filters=definition.filters,
            property_name=body.property,
            limit=body.limit,
        )
    return ObjectSetGroupOut(
        groups=[{"value": value, "count": count} for value, count in buckets],
        distinct_total=distinct_total,
        truncated=distinct_total > len(buckets),
    )


class ObjectSetCrossTabIn(BaseModel):
    definition: dict[str, Any]
    row_property: str = Field(min_length=1, max_length=200)
    column_property: str = Field(min_length=1, max_length=200)
    row_limit: int = Field(default=object_sets.MAX_GROUPS, ge=1, le=object_sets.MAX_GROUPS)
    column_limit: int = Field(
        default=object_sets.MAX_PIVOT_COLUMNS, ge=1, le=object_sets.MAX_PIVOT_COLUMNS
    )


class ObjectSetAxis(BaseModel):
    value: str
    count: int
    """How many objects have this value - **the whole row or column, not the
    part of it inside the grid.** A row's cells can sum to less than its count,
    for two reasons that are both real: columns past `column_limit` are not
    drawn, and an object with no value for the column property is in no cell at
    all. Making the total the sum of the cells instead would give a number that
    quietly disagrees with the same property's bar chart."""


class ObjectSetCrossTabOut(BaseModel):
    rows: list[ObjectSetAxis]
    columns: list[ObjectSetAxis]
    row_distinct_total: int
    column_distinct_total: int
    """How many distinct values each axis's property actually has. `truncated`
    is derived from these rather than from "did we fill the axis", which would
    be wrong on a set with exactly `limit` values."""
    rows_truncated: bool
    columns_truncated: bool
    cells: list[list[int]]
    """Counts, `rows` x `columns`, in that order. Dense - an empty cell is 0 -
    because a grid is read positionally and a client reassembling a sparse map
    would be re-deriving the axes it was already given."""
    total: int
    """The size of the whole set. `total` minus the sum of the cells is what
    the grid does not account for, which is a thing the widget says rather than
    leaves a viewer to notice."""


@router.post("/object-sets/cross-tab", response_model=ObjectSetCrossTabOut)
async def cross_tab_object_set(
    body: ObjectSetCrossTabIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectSetCrossTabOut:
    """Counts by two properties at once - what a Pivot Table shows (roadmap 1.5).

    **The axes are grouped counts, not a third thing.** Both come from the same
    `group_object_set` a chart plots, so a pivot's row totals and a bar chart
    over the same property are the same numbers by construction rather than by
    two implementations agreeing. Only the cells are new work.

    Counts only, like every other aggregation over a set: instance properties
    are stored untyped, so a cross-tab of *sums* would mean one thing on
    Postgres and nothing at all on OpenSearch. See `object_sets`.
    """
    definition = object_sets.parse(body.definition)
    try:
        row_property, column_property = object_sets.parse_cross_tab(
            body.row_property, body.column_property
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, definition.object_type_id)
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        store = instance_store.store_for(conn)
        shared = {
            "search_prefix": prefix,
            "object_type_id": definition.object_type_id,
            "filters": definition.filters,
        }
        row_buckets, row_distinct = await store.group_object_set(
            **shared, property_name=row_property, limit=body.row_limit
        )
        column_buckets, column_distinct = await store.group_object_set(
            **shared, property_name=column_property, limit=body.column_limit
        )
        cells = await store.cross_tab_object_set(
            **shared,
            row_property=row_property,
            column_property=column_property,
            row_values=tuple(value for value, _ in row_buckets),
            column_values=tuple(value for value, _ in column_buckets),
        )
        total = await store.aggregate_object_set(
            **shared, aggregation="count", property_name=None
        )

    return ObjectSetCrossTabOut(
        rows=[ObjectSetAxis(value=value, count=count) for value, count in row_buckets],
        columns=[ObjectSetAxis(value=value, count=count) for value, count in column_buckets],
        row_distinct_total=row_distinct,
        column_distinct_total=column_distinct,
        rows_truncated=row_distinct > len(row_buckets),
        columns_truncated=column_distinct > len(column_buckets),
        cells=[
            [cells.get((row, column), 0) for column, _ in column_buckets]
            for row, _ in row_buckets
        ],
        total=total,
    )


class ObjectSetTimeSeriesIn(BaseModel):
    definition: dict[str, Any]
    interval: str = object_sets.DEFAULT_TIME_INTERVAL


class ObjectSetTimePoint(BaseModel):
    start: datetime
    """The bucket's first instant, in UTC. The *start*, not a label: a client
    that wanted "March" can format one, and a client that wanted to line two
    series up needs the instant."""
    count: int


class ObjectSetTimeSeriesOut(BaseModel):
    points: list[ObjectSetTimePoint]
    interval: str
    total: int
    """The size of the set. Equal to the sum of the points here - unlike a
    cross-tab, every object has an `updated_at` and no bucket is dropped - and
    returned so a widget can say so rather than a viewer having to add up."""


@router.post("/object-sets/time-series", response_model=ObjectSetTimeSeriesOut)
async def time_series_object_set(
    body: ObjectSetTimeSeriesIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectSetTimeSeriesOut:
    """How many objects last changed in each time bucket (roadmap 1.5).

    **This plots `updated_at` - when the platform last saw each object change -
    and not a business date.** That is a real limitation, not a stand-in for
    one: a resync moves every object in a set to today, so this answers "what
    has been changing" rather than "when did things happen". Both stores agree
    about it, which a date *property* would not - properties are stored
    untyped (`object_sets.DATE_PROPERTY_HINT`, decision 0006). The widget says
    which of the two questions it is answering, because the difference is
    invisible from the shape of the chart.

    **Empty buckets are filled, and the range comes from the data.** A line
    drawn through a gap slopes gently across a week when nothing happened,
    which is a different claim rather than a smaller one. The range is the
    first and last populated bucket rather than "the last 30 days", so the same
    saved app does not draw a different picture tomorrow.
    """
    definition = object_sets.parse(body.definition)
    try:
        interval = object_sets.parse_interval(body.interval)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    async with user_connection(access.auth.user_id) as conn:
        await ontology_service.get_type(conn, access.workspace_id, definition.object_type_id)
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        store = instance_store.store_for(conn)
        shared = {
            "search_prefix": prefix,
            "object_type_id": definition.object_type_id,
            "filters": definition.filters,
        }
        buckets = await store.time_series_object_set(**shared, interval=interval)
        total = await store.aggregate_object_set(
            **shared, aggregation="count", property_name=None
        )

    try:
        filled = object_sets.fill_time_buckets(buckets, interval)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ObjectSetTimeSeriesOut(
        points=[ObjectSetTimePoint(start=start, count=count) for start, count in filled],
        interval=interval,
        total=total,
    )



async def _resolve_traversal(
    conn: Any,
    store: Any,
    prefix: str,
    workspace_id: UUID,
    definition: "object_sets.ObjectSet",
) -> tuple[tuple[Any, ...], bool]:
    """Turn a set's `via` hop into the filters that express it.

    Returns `(filters, empty)`. **`empty` is not "no filters"** - it means the
    set below linked to nothing, so this set has no members and the caller must
    stop rather than read the type unfiltered.

    **The link decides which end is near**, read from the base set's own type
    (`links_for_type` returns a link once per end it occupies), so a definition
    cannot name the wrong direction - it does not name one at all. A link that
    does not join these two types is refused here rather than quietly
    returning nothing, because "your definition is wrong" and "there are no
    matches" look identical in an empty table.

    Recursive, bounded by `MAX_TRAVERSALS` at parse time.
    """
    if definition.via is None:
        return definition.filters, False

    base = definition.via.base
    await ontology_service.get_type(conn, workspace_id, base.object_type_id)
    base_filters, base_empty = await _resolve_traversal(
        conn, store, prefix, workspace_id, base
    )
    if base_empty:
        return definition.filters, True

    links = await ontology_service.links_for_type(conn, workspace_id, base.object_type_id)
    link = next(
        (row for row in links if str(row["id"]) == str(definition.via.link_type_id)), None
    )
    if link is None:
        raise ValueError(
            "that link type does not connect the set being traversed from - a link "
            "joins two named object types, and this one does not touch that type"
        )
    if str(link["far_type_id"]) != str(definition.object_type_id):
        raise ValueError(
            "this traversal lands on a different object type than the set declares - "
            f"following that link from there reaches {link['far_type_display_name']!r}"
        )

    # The near side's join values. Read at the cap plus one, so "too many" is a
    # refusal with a number rather than a page silently missing its tail.
    members, _ = await store.evaluate_object_set(
        search_prefix=prefix,
        object_type_id=base.object_type_id,
        filters=base_filters,
        limit=object_sets.MAX_JOIN_VALUES + 1,
        offset=0,
        sort="key_asc",
    )
    near = str(link["near_property"])
    values = [
        row["primary_key"]
        if near == ontology_service.PRIMARY_KEY_REF
        else _jsonb(row["properties"]).get(near)
        for row in members
    ]
    joined = object_sets.join_filter(far_property=str(link["far_property"]), values=values)
    if joined is None:
        return definition.filters, True
    return (joined, *definition.filters), False


def _empty_for(aggregate: str | None) -> Any:
    """What a derivation that reached nothing answers - see `_derive_property`.

    `exact_cardinality` counts, so it is 0 for `count`'s reason: "how many
    distinct" has an honest numeric answer over nothing.
    """
    if aggregate in ("count", "exact_cardinality"):
        return 0
    if aggregate in ("collect_list", "collect_set"):
        return []
    return None


async def _derive_property(
    conn: Any,
    store: Any,
    prefix: str,
    workspace_id: UUID,
    *,
    start_type_id: UUID,
    instance_key: str,
    derivation: dict[str, Any],
) -> Any:
    """Answer one derived property for one object (`object-link-types` p.143).

    **The chain is an object set rooted at this one object.** A derived
    property asks "follow these links from *me*, then reduce what you find",
    and §155 already expresses exactly that: a set of the starting type
    filtered to this instance's key, wrapped in one `Traversal` per hop. So
    there is no traversal code here - the hops become the same nested
    `ObjectSet` a Workshop variable would build, and `_resolve_traversal`
    answers it. That is why filtering on `$primary_key` had to exist (§155),
    and it is what makes a three-hop derivation cost nothing new.

    **Each aggregation answers an empty chain with its own empty**: `count`
    returns 0, a collection returns `[]`, and a single value returns `None`.
    Written first with one shared sentinel, which made an empty *base* answer
    `None` where an empty *far side* answered `[]` - the same question, two
    shapes, depending on which end of the chain ran out. A reader cannot be
    expected to know which.
    """
    definition = object_sets.ObjectSet(
        object_type_id=start_type_id,
        filters=(
            object_sets.Filter(
                property=object_sets.PRIMARY_KEY_FILTER, op="eq", value=instance_key
            ),
        ),
    )
    for hop in derivation["links"]:
        definition = object_sets.ObjectSet(
            object_type_id=UUID(str(hop["far_type_id"])),
            via=object_sets.Traversal(
                link_type_id=UUID(str(hop["link_type_id"])), base=definition
            ),
        )

    filters, empty = await _resolve_traversal(conn, store, prefix, workspace_id, definition)
    aggregate = derivation.get("aggregate")
    if empty:
        return _empty_for(aggregate)

    if aggregate in ("count", "exact_cardinality"):
        # `AGGREGATIONS`' two, which are the two both stores answer the same
        # way over untyped properties. The rest were refused at save time
        # (`derived_properties.UNSUPPORTED_AGGREGATES`), so reaching here with
        # one would mean a row that predates that rule.
        return await store.aggregate_object_set(
            search_prefix=prefix,
            object_type_id=definition.object_type_id,
            filters=filters,
            aggregation="count" if aggregate == "count" else "count_distinct",
            property_name=None if aggregate == "count" else derivation.get("property"),
        )

    # Everything else reads the far objects and takes the property off them:
    # a collection (p.146, bounded by its own limit) or the single value a
    # one-to-one chain reaches.
    limit = int(derivation.get("limit") or 1)
    rows, _ = await store.evaluate_object_set(
        search_prefix=prefix,
        object_type_id=definition.object_type_id,
        filters=filters,
        limit=limit,
        offset=0,
        sort="key_asc",
    )
    name = str(derivation["property"])
    values = [
        row["primary_key"]
        if name == ontology_service.PRIMARY_KEY_REF
        else _jsonb(row["properties"]).get(name)
        for row in rows
    ]
    if aggregate == "collect_set":
        # Unordered and unique (p.145), but returned in a stable order anyway:
        # a set that came back differently on each read would make an object
        # view flicker for no reason a reader could name.
        seen = {v for v in values if v is not None}
        return sorted(seen, key=lambda v: str(v))
    if aggregate == "collect_list":
        return values
    return values[0] if values else None


async def _with_derived(
    conn: Any,
    store: Any,
    prefix: str,
    workspace_id: UUID,
    type_id: UUID,
    row: dict[str, Any],
) -> dict[str, Any]:
    """One instance, with its derived properties filled in (p.143).

    **Single reads only, and that is a deliberate line.** Each derived property
    costs a query per hop, so doing this for a page of a table would be a
    silent N+1 on every list in the product. p.143's own examples are all
    object-shaped - "this department's average salary", "this project's lead
    engineer" - so the object view is where the answer is worth paying for.
    A table showing a derived column needs the aggregation pushed into the
    index, which is the same typed-index work §87 is blocked on.
    """
    properties = await ontology_service.list_properties(conn, type_id)
    derived = [p for p in properties if p.get("derivation")]
    if not derived:
        return row
    values = dict(_jsonb(row["properties"]))
    for prop in derived:
        values[str(prop["api_name"])] = await _derive_property(
            conn, store, prefix, workspace_id,
            start_type_id=type_id,
            instance_key=str(row["primary_key"]),
            derivation=_jsonb(prop["derivation"]),
        )
    return {**row, "properties": values}


@router.post("/object-sets/evaluate", response_model=ObjectSetOut)
async def evaluate_object_set(
    body: ObjectSetIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> ObjectSetOut:
    """Evaluate an object-set variable (roadmap 1.2).

    A read, at the same floor as every other instance read. Filtering happens
    here rather than in the browser because a page of at most 200 rows cannot
    answer "how many match" or "show me the next page of the filtered set" -
    which is the whole reason object sets are a server concept.
    """
    definition = object_sets.parse(body.definition)
    sort = object_sets.parse_sort(body.sort)
    async with user_connection(access.auth.user_id) as conn:
        # Confirms the type is in this workspace before it is used as a filter
        # - an id from a request body is never trusted to be in scope (§10).
        await ontology_service.get_type(conn, access.workspace_id, definition.object_type_id)
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        store = instance_store.store_for(conn)
        filters, empty = await _resolve_traversal(
            conn, store, prefix, access.workspace_id, definition
        )
        if empty:
            # The set below linked to nothing, so this set has no members. An
            # unfiltered read here would be the silent widening decision 0002
            # exists to remove - see `object_sets.join_filter`.
            return ObjectSetOut(
                instances=[], total=0, limit=body.limit, offset=body.offset
            )
        rows, total = await store.evaluate_object_set(
            search_prefix=prefix,
            object_type_id=definition.object_type_id,
            filters=filters,
            limit=body.limit,
            offset=body.offset,
            sort=sort,
        )
    return ObjectSetOut(
        instances=[InstanceOut(**{**r, "properties": _jsonb(r["properties"])}) for r in rows],
        total=total,
        limit=body.limit,
        offset=body.offset,
    )
