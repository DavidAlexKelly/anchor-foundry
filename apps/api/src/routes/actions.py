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
from datetime import datetime, timezone
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
from ..lib.errors import NotFoundError
from ..services import instance_store
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


class ActionParameterOut(BaseModel):
    """An input the action declares (Foundry `action-types` p.25)."""

    id: UUID
    api_name: str
    display_name: str
    data_type: str
    required: bool
    default_value: Any | None
    hidden: bool
    sort_order: int


class ActionRuleOut(BaseModel):
    """What the action does with them (p.75)."""

    id: UUID
    kind: str
    config: dict[str, Any]
    sort_order: int


class ActionCriterionOut(BaseModel):
    """A condition that must hold for the action to be submitted (p.49-56)."""

    id: UUID
    message: str
    config: dict[str, Any]
    sort_order: int


class ActionTypeOut(BaseModel):
    id: UUID
    object_type_id: UUID
    object_type_name: str
    api_name: str
    display_name: str
    description: str
    parameters: list[ActionParameterOut]
    rules: list[ActionRuleOut]
    criteria: list[ActionCriterionOut]
    # **Derived from the rules, not stored** - migration 0044 dropped the
    # column. Kept on the wire because the object-type screens and the
    # Workshop `run_action` editor both ask "which properties does this action
    # write", and that question still has this exact answer while
    # `modify_object` is the only rule kind. It goes when the action form
    # itself moves to parameters (decision 0007, "the form gets harder before
    # it gets better").
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
    rules = [{**r, "config": _parse_json(r["config"])} for r in row["rules"]]
    # `default_value` is deliberately not run through `_parse_json` - see
    # `bind_parameters`: a jsonb scalar comes back already decoded, and parsing
    # it again raises.
    parameters = list(row["parameters"])
    return ActionTypeOut(
        **{
            **row,
            "parameters": parameters,
            "rules": rules,
            "criteria": [{**c, "config": _parse_json(c["config"])} for c in row["criteria"]],
            "editable_properties": actions_service.editable_properties_of(rules),
        }
    )


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


class ActionParameterIn(BaseModel):
    api_name: str = Field(min_length=1, max_length=100, pattern="^[a-z][a-z0-9_]{0,99}$")
    display_name: str = Field(min_length=1, max_length=200)
    data_type: str = Field(min_length=1, max_length=40)
    required: bool = False
    default_value: Any | None = None
    hidden: bool = False


class ActionRuleIn(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    config: dict[str, Any] = Field(default_factory=dict)


class ActionCriterionIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    config: dict[str, Any]


class ActionDefinitionIn(BaseModel):
    """The three lists as one document.

    Whole-document rather than per-row because they constrain each other: a
    rule names a parameter, a criterion names a parameter, so a per-row API
    would have orderings in which every individually valid edit passes through
    an invalid state. `order` is the position in the list - nothing carries a
    sort order the caller has to keep consistent with anything else.
    """

    parameters: list[ActionParameterIn] = Field(default_factory=list, max_length=50)
    rules: list[ActionRuleIn] = Field(default_factory=list, max_length=50)
    criteria: list[ActionCriterionIn] = Field(default_factory=list, max_length=50)


@router.put("/action-types/{action_type_id}/definition", response_model=ActionTypeOut)
async def set_action_definition(
    action_type_id: UUID,
    body: ActionDefinitionIn,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ActionTypeOut:
    """Edit an action's parameters, rules and criteria (decision 0007).

    Workspace editor, the same floor as creating the action type: this changes
    what an action *is*, not what it does to one project's data.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await actions_service.set_definition(
            conn,
            access.workspace_id,
            action_type_id,
            parameters=[p.model_dump() for p in body.parameters],
            rules=[r.model_dump() for r in body.rules],
            criteria=[c.model_dump() for c in body.criteria],
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="action_type.define",
            resource_type="action_type",
            resource_id=action_type_id,
            workspace_id=access.workspace_id,
            metadata={
                "parameters": len(body.parameters),
                "rules": len(body.rules),
                "criteria": len(body.criteria),
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _action_type_out(row)


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
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        instance = await instance_store.store_for(conn).get_instance(
            search_prefix=prefix, object_type_id=object_type_id,
            instance_id=str(body.instance_id),
        )
        if instance is None:
            raise NotFoundError("object instance")
        # 404s if this instance's source isn't a mapping in this project.
        source = await ontology_service.get_source(
            conn, access.project_id, UUID(str(instance["source_id"]))
        )
        properties = await ontology_service.list_properties(conn, object_type_id)
        property_types = {p["api_name"]: p["data_type"] for p in properties}
        column_mappings: dict[str, str] = _parse_json(source["column_mappings"])
        # Normalised, not just checked: a geopoint submitted as "51.5,-0.12"
        # is stored in the same shape as one that arrived from a sync.
        # Two steps, because they answer different questions: what did the
        # caller supply (against the declared parameters), and what do the
        # rules write with it (against the object type and its mapping).
        bound = actions_service.bind_parameters(
            body.values, parameters=action_type["parameters"]
        )
        # **Before the first rule runs, and before the run is even opened**
        # (p.49-50). "Refused" and "refused after writing half of it" look the
        # same to the caller and are very different in the dataset, and our
        # write-back appends a version per write - so the check has to come
        # before anything that could leave one behind.
        actions_service.check_criteria(
            bound,
            criteria=action_type["criteria"],
            user=await actions_service.criteria_user(conn, access.auth.user_id),
        )
        creations = actions_service.object_creations(
            bound,
            rules=action_type["rules"],
            property_types=property_types,
            mapped_properties=set(column_mappings.values()),
        )
        values = actions_service.apply_rules(
            bound,
            rules=action_type["rules"],
            property_types=property_types,
            mapped_properties=set(column_mappings.values()),
            link_types=await actions_service.link_types_for(conn, access.workspace_id),
        )
        run_id = await actions_service.open_run(
            conn,
            action_type_id=action_type_id,
            instance_id=body.instance_id,
            dataset_id=UUID(str(source["dataset_id"])),
            requested_by=access.auth.user_id,
            submitted_values=values,
        )

    ok, error = True, None
    dataset_version: int | None = None
    try:
        reverse_map = {prop: col for col, prop in column_mappings.items()}
        # The dataset copy gets the flat form - a Parquet column is a scalar
        # and a geopoint is not (ontology.column_value).
        column_updates = {
            reverse_map[prop]: ontology_service.column_value(
                property_types.get(prop, "string"), value
            )
            for prop, value in values.items()
        }
        local_path = await anyio.to_thread.run_sync(
            storage.local_path, str(source["s3_location"])
        )
        # Every row this action writes, in one file (decision 0008). A modify
        # and a create are two writes and must land as **one** version: three
        # versions carrying the same `produced_by_id` would be a history that
        # has to be interpreted, and a failure between them would leave a
        # dataset nobody asked for.
        appended = [
            {
                str(source["primary_key_column"]): creation["primary_key"],
                **{
                    reverse_map[prop]: ontology_service.column_value(
                        property_types.get(prop, "string"), value
                    )
                    for prop, value in creation["properties"].items()
                },
            }
            for creation in creations
        ]
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "out.parquet")
            schema, row_count = await anyio.to_thread.run_sync(
                engine.write_rows,
                local_path,
                str(source["primary_key_column"]),
                [(str(instance["primary_key"]), column_updates)] if column_updates else [],
                appended,
                dest,
            )
            with open(dest, "rb") as handle:
                parquet_bytes = handle.read()
        async with user_connection(access.auth.user_id) as conn:
            staged = await dataset_service.stage_version(
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
            committed = await dataset_service.commit_versions(conn, [staged])
            dataset_version = int(committed[str(source["dataset_id"])]["current_version"])
            if values:
                await instance_store.store_for(conn).update_properties(
                    search_prefix=prefix,
                    object_type_id=UUID(str(action_type["object_type_id"])),
                    instance_id=str(body.instance_id),
                    properties=values,
                )
            if creations:
                # The index is a projection (decision 0008) - the dataset above
                # is the record. Upserted here so a created object is findable
                # immediately rather than at the next sync; a failure here is
                # repairable by re-syncing the source, which a half-written
                # dataset would not be.
                await instance_store.store_for(conn).upsert_instances(
                    search_prefix=prefix,
                    object_type_id=UUID(str(action_type["object_type_id"])),
                    source_id=UUID(str(source["id"])),
                    rows=[
                        (creation["primary_key"], creation["properties"])
                        for creation in creations
                    ],
                    synced_at=datetime.now(timezone.utc),
                )
    except DatasetEngineError as exc:
        ok, error = False, str(exc)

    async with user_connection(access.auth.user_id) as conn:
        await actions_service.close_run(
            conn, run_id, ok=ok, dataset_version=dataset_version, error=error
        )
        updated_instance = await instance_store.store_for(conn).get_instance(
            search_prefix=prefix, object_type_id=object_type_id,
            instance_id=str(body.instance_id),
        ) or instance
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
