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
from uuid import UUID, uuid4

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
    # Why this action cannot back an Object Table's inline edits, empty if it
    # can (`workshop` p.240-241, `action-types` p.136-137). **Derived on the
    # server and sent**, rather than left for the panel to work out: the panel
    # has to offer only eligible actions (§214's rule - a setting the platform
    # refuses must not be offered), and a browser deciding eligibility from its
    # own copy of the rules is the seventh copy of a constraint this session has
    # spent four units collapsing.
    inline_edit_refusals: list[str]
    # p.242: "Users can stage edits for up to … 200 rows at a time for actions
    # that are not function-backed." **Sent rather than known by the browser**,
    # for the same reason as the refusals above: the table has to stop a reader
    # staging the two hundred and first row *before* Submit, and a number typed
    # into the widget would be an eighth copy of a constraint this session has
    # spent four units collapsing. One place says 200, and it is the place that
    # enforces it.
    inline_edit_row_limit: int
    # p.253: "every object type, property, link type, action, or interface in
    # the Ontology has a status". p.255 excludes `promoted` from action types
    # by name.
    status: str = "experimental"
    deprecation: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class ActionTypeCreate(BaseModel):
    object_type_id: UUID
    api_name: str = Field(min_length=1, max_length=100, pattern="^[a-z][a-z0-9_]{0,99}$")
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    editable_properties: list[str] = Field(min_length=1, max_length=50)
    status: str = "experimental"
    deprecation: dict[str, Any] | None = None


class ActionStatusUpdate(BaseModel):
    """p.256's status dropdown, for an action type.

    **Both fields optional, and omitted means unchanged** - §170's rule. This
    is the only endpoint that writes an action's status, so treating a missing
    field as the documented default for a *new* resource would demote an
    action every time a client that predates statuses touched it.
    """

    status: str | None = None
    deprecation: dict[str, Any] | None = None


class ActionRunOut(BaseModel):
    id: UUID
    instance_id: UUID | None
    dataset_id: UUID | None
    dataset_version: int | None
    submitted_values: dict[str, Any]
    status: str
    error: str | None
    # The inline-edit submission this run belonged to, or null for an action
    # submitted on its own (db 0063). On the wire because the action log's
    # question is "what happened to this object", and "as one of forty edits
    # somebody submitted together" is part of the answer.
    batch_id: UUID | None = None
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
            # Handed the row as it came back. `inline_edit_refusals` reads every
            # config through `_json` itself, so pre-parsing here would be a
            # second parse of the same value - which is what a mutant said when
            # it swapped the parsed rules for the raw ones and nothing failed.
            "inline_edit_refusals": actions_service.inline_edit_refusals(row),
            "inline_edit_row_limit": actions_service.INLINE_EDIT_ROW_LIMIT,
            # jsonb, so it may arrive as text depending on the driver path -
            # the same treatment `config` gets two lines up.
            "deprecation": _parse_json(row.get("deprecation")),
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
            status=body.status,
            deprecation=body.deprecation,
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


@router.patch("/action-types/{action_type_id}", response_model=ActionTypeOut)
async def set_action_status(
    action_type_id: UUID,
    body: ActionStatusUpdate,
    request: Request,
    access: WorkspaceAccess = Depends(require_workspace_role("editor")),
) -> ActionTypeOut:
    """p.256's status dropdown (`object-link-types` p.253-256).

    Separate from the definition PUT because that body is what the action
    *does*; a status is a statement about how much anyone should rely on it,
    and folding one into the other would make every rule edit a status write.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await actions_service.set_action_status(
            conn,
            access.workspace_id,
            action_type_id,
            status=body.status,
            deprecation=body.deprecation,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="action_type.status",
            resource_type="action_type",
            resource_id=action_type_id,
            workspace_id=access.workspace_id,
            metadata={"status": row["status"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
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
class CheckRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict, max_length=50)


class CheckResult(BaseModel):
    """Whether these parameter values would pass submission criteria.

    `ok` and a message, never a refusal: asking is not submitting, and a 4xx
    here would make "this action is not available" indistinguishable from "the
    question could not be asked".
    """

    ok: bool
    error: str | None


@project_router.post("/{action_type_id}/check", response_model=CheckResult)
async def check_action(
    action_type_id: UUID,
    body: CheckRequest,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CheckResult:
    """Would this submission be refused? (Workshop p.513.)

    Workshop's Inline Action widget can be configured to disable or hide a form
    "when submission criteria are not met", which needs the answer *before*
    anything is written. **The point of this endpoint is that it runs the same
    `check_criteria` the executor runs** - the alternative is the browser
    evaluating p.54-55's operators in another language, free to disagree with
    the one that governs writes, which `CanvasActionForm` has refused to do
    since §130 and is right to.

    Requires the same role as executing: a caller who may not run the action
    has no business learning which criterion would stop them, and p.140 makes
    criteria a permissions mechanism.
    """
    async with user_connection(access.auth.user_id) as conn:
        action_type = await actions_service.get_action_type(
            conn, access.workspace_id, action_type_id
        )
        user = await actions_service.criteria_user(conn, access.auth.user_id)
    try:
        bound = actions_service.bind_parameters(
            body.values, parameters=action_type["parameters"]
        )
        actions_service.check_criteria(
            bound, criteria=action_type["criteria"], user=user
        )
    except actions_service.CriteriaRefusal as refusal:
        return CheckResult(ok=False, error=str(refusal))
    except ValueError as invalid:
        # A binding failure - an unknown parameter name, a required one absent
        # - is also a reason this submission would not go through, and saying
        # so here is more use than saying nothing until Submit.
        return CheckResult(ok=False, error=str(invalid))
    return CheckResult(ok=True, error=None)


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
        # The subject's properties with no dataset column (p.113). Only the
        # subject's: a rule writing another object's property is checked
        # against *that* type's source, and edit-only there is not built.
        edit_only = ontology_service.edit_only_properties(properties)
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
        deletions = actions_service.object_deletions(
            bound, rules=action_type["rules"], default_object_type_id=object_type_id
        )
        # Read once and handed to everything that needs it: a far-side link
        # rule names the object type it writes *through its link type*, so the
        # lookup that resolves the named instance needs this as much as the
        # one that coerces the value.
        link_types = await actions_service.link_types_for(conn, access.workspace_id)

        # **A named object is looked up before it is written**, and its own
        # source decides which columns exist - two instances of one type can
        # come from different mappings, so the type is not enough to answer
        # "is this property stored anywhere". `get_source` 404s for a source
        # this project does not map, which is the refusal that stops an action
        # reaching into a project the caller is not in.
        modification_contexts: dict[tuple[str, str], dict[str, Any]] = {}
        modification_rows: dict[tuple[str, str], dict[str, Any]] = {}
        for target in actions_service.modification_targets(
            bound,
            rules=action_type["rules"],
            default_object_type_id=object_type_id,
            link_types=link_types,
        ):
            key = (target["object_type_id"], target["instance_id"])
            named = await instance_store.store_for(conn).get_instance(
                search_prefix=prefix,
                object_type_id=UUID(target["object_type_id"]),
                instance_id=target["instance_id"],
            )
            if named is None:
                raise NotFoundError("object to change")
            named_source = await ontology_service.get_source(
                conn, access.project_id, UUID(str(named["source_id"]))
            )
            named_mappings: dict[str, str] = _parse_json(named_source["column_mappings"])
            modification_contexts[key] = {
                "property_types": {
                    p["api_name"]: p["data_type"]
                    for p in await ontology_service.list_properties(
                        conn, UUID(target["object_type_id"])
                    )
                },
                "mapped_properties": set(named_mappings.values()),
            }
            modification_rows[key] = {
                "source": named_source,
                "primary_key": str(named["primary_key"]),
                "mappings": named_mappings,
            }

        # **One context per object type this action creates into.** A rule
        # creating another type's object has to be checked and coerced against
        # *that* type and written into *its* dataset - which is the lookup that
        # kept cross-type creates out of §135, and the first thing to put two
        # datasets inside one action.
        sources_by_type: dict[str, dict[str, Any]] = {str(object_type_id): dict(source)}
        contexts: dict[str, dict[str, Any]] = {
            str(object_type_id): {
                "property_types": property_types,
                "mapped_properties": set(column_mappings.values()),
            }
        }
        needed = list(actions_service.creation_targets(
            action_type["rules"], default_object_type_id=object_type_id
        ))
        for deletion in deletions:
            if deletion["object_type_id"] not in needed:
                needed.append(deletion["object_type_id"])
        for target in needed:
            if target in contexts:
                continue
            candidates = [
                row for row in await ontology_service.list_sources(
                    conn, access.project_id, access.workspace_id
                )
                if str(row["object_type_id"]) == target
            ]
            if len(candidates) != 1:
                # None: nothing in this project says where that type's rows
                # live. Several: nothing says *which* of them a new object
                # belongs to, and picking one would be a guess written into
                # somebody's data.
                raise ValueError(
                    "this action creates an object of a type with "
                    f"{'no' if not candidates else 'more than one'} dataset mapped in "
                    "this project"
                )
            target_source = await ontology_service.get_source(
                conn, access.project_id, UUID(str(candidates[0]["id"]))
            )
            target_mappings: dict[str, str] = _parse_json(target_source["column_mappings"])
            sources_by_type[target] = target_source
            contexts[target] = {
                "property_types": {
                    p["api_name"]: p["data_type"]
                    for p in await ontology_service.list_properties(conn, UUID(target))
                },
                "mapped_properties": set(target_mappings.values()),
            }

        # A named object has to be found before it can be removed: the rule
        # supplies an instance id, and what a dataset needs is a primary key
        # and the source it belongs to.
        removals: list[dict[str, Any]] = []
        for deletion in deletions:
            if deletion["instance_id"] is None:
                removals.append({
                    "object_type_id": str(object_type_id),
                    "source": dict(source),
                    "primary_key": str(instance["primary_key"]),
                })
                continue
            named = await instance_store.store_for(conn).get_instance(
                search_prefix=prefix,
                object_type_id=UUID(deletion["object_type_id"]),
                instance_id=deletion["instance_id"],
            )
            if named is None:
                # Refused rather than skipped: an action that reports success
                # for an object it could not find is one nobody can tell from
                # an action that deleted something.
                raise NotFoundError("object to delete")
            named_source = await ontology_service.get_source(
                conn, access.project_id, UUID(str(named["source_id"]))
            )
            removals.append({
                "object_type_id": deletion["object_type_id"],
                "source": named_source,
                "primary_key": str(named["primary_key"]),
                "instance_id": deletion["instance_id"],
            })
            sources_by_type.setdefault(deletion["object_type_id"], named_source)

        creations = actions_service.object_creations(
            bound,
            rules=action_type["rules"],
            contexts=contexts,
            default_object_type_id=object_type_id,
        )
        values = actions_service.apply_rules(
            bound,
            rules=action_type["rules"],
            property_types=property_types,
            mapped_properties=set(column_mappings.values()),
            edit_only=edit_only,
            link_types=link_types,
        )
        # p.116, at apply time and before anything is written. Only what this
        # action *writes* is checked on the subject: a required property that
        # was already empty is indexing's business (it reports), and refusing
        # here as well would make an object that predates the rule uneditable
        # by the one action that could fix it.
        required_by_type = {
            str(object_type_id): ontology_service.required_properties(properties)
        }

        async def _required_for(type_id: str) -> set[str]:
            """Cached per object type: an action can touch several, and each
            has its own list."""
            if type_id not in required_by_type:
                required_by_type[type_id] = ontology_service.required_properties(
                    await ontology_service.list_properties(conn, UUID(type_id))
                )
            return required_by_type[type_id]

        actions_service.check_required(values, required=required_by_type[str(object_type_id)])
        # p.222's constraints, at the same moment and for the same reason.
        # `constrained_properties` reads the value type's *current* version
        # (p.230), so an action refused today is refused against the rule in
        # force today rather than the one that applied when the type was saved.
        constrained_by_type = {
            str(object_type_id): ontology_service.constrained_properties(properties)
        }

        async def _constrained_for(type_id: str):
            if type_id not in constrained_by_type:
                constrained_by_type[type_id] = ontology_service.constrained_properties(
                    await ontology_service.list_properties(conn, UUID(type_id))
                )
            return constrained_by_type[type_id]

        actions_service.check_constraints(
            values, constrained_by_type[str(object_type_id)]
        )
        # **A create is checked whole.** There is no "already" for a new
        # object, so a required property absent from the rule is a row born
        # non-compliant - which is the one case where absence and emptiness
        # are the same failure.
        for creation in creations:
            actions_service.check_required(
                creation["properties"],
                required=await _required_for(creation["object_type_id"]),
                creating=True,
            )
            actions_service.check_constraints(
                creation["properties"],
                await _constrained_for(creation["object_type_id"]),
            )
        modifications = actions_service.object_modifications(
            bound,
            rules=action_type["rules"],
            contexts=modification_contexts,
            default_object_type_id=object_type_id,
            link_types=link_types,
            # A far-side link points the other object at *this* one, so the
            # value it writes comes from the subject rather than from any
            # parameter - **as this action leaves it**, which is why `values`
            # is computed first and laid over the stored properties. An action
            # that changes the property a link joins on and links on it in the
            # same submit would otherwise write the old value and create a link
            # that does not hold the moment the action finishes.
            subject={
                "primary_key": str(instance["primary_key"]),
                "properties": {**_parse_json(instance["properties"]), **values},
            },
        )
        # A named object is checked like the subject: only what this action
        # writes to it. After `object_modifications`, because that is where the
        # writes exist.
        for modification in modifications:
            actions_service.check_required(
                modification["properties"],
                required=await _required_for(modification["object_type_id"]),
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
        # **Edit-only properties are not in this dict, by definition** (p.113):
        # they have no column, so there is nothing to append. They are still in
        # `values`, which is what reaches the instance store below - that split
        # is the whole of what "edit-only" means in the write path.
        column_updates = {
            reverse_map[prop]: ontology_service.column_value(
                property_types.get(prop, "string"), value
            )
            for prop, value in values.items()
            if prop not in edit_only
        }
        local_path = await anyio.to_thread.run_sync(
            storage.local_path, str(source["s3_location"])
        )
        # Every row this action writes, in one file (decision 0008). A modify
        # and a create are two writes and must land as **one** version: three
        # versions carrying the same `produced_by_id` would be a history that
        # has to be interpreted, and a failure between them would leave a
        # dataset nobody asked for.
        def rows_for(type_id: str) -> list[dict[str, Any]]:
            """The rows to append to one type's dataset, in its own columns."""
            target_source = sources_by_type[type_id]
            mappings: dict[str, str] = _parse_json(target_source["column_mappings"])
            columns = {prop: col for col, prop in mappings.items()}
            types = contexts[type_id]["property_types"]
            return [
                {
                    str(target_source["primary_key_column"]): creation["primary_key"],
                    **{
                        columns[prop]: ontology_service.column_value(
                            types.get(prop, "string"), value
                        )
                        for prop, value in creation["properties"].items()
                    },
                }
                for creation in creations
                if creation["object_type_id"] == type_id
            ]

        # **One entry per dataset, not per rule.** Two rules touching the same
        # dataset - a modify and a delete of a different row, say - have to
        # land in one file, or the second staging would collide with the
        # version the first one just claimed.
        plan: dict[str, dict[str, Any]] = {}

        def entry(target_source: dict[str, Any]) -> dict[str, Any]:
            return plan.setdefault(
                str(target_source["dataset_id"]),
                {"source": target_source, "updates": [], "appends": [], "deletes": []},
            )

        if column_updates:
            entry(dict(source))["updates"].append(
                (str(instance["primary_key"]), column_updates)
            )
        for modification in modifications:
            row = modification_rows[
                (modification["object_type_id"], modification["instance_id"])
            ]
            columns = {prop: col for col, prop in row["mappings"].items()}
            types = modification_contexts[
                (modification["object_type_id"], modification["instance_id"])
            ]["property_types"]
            entry(row["source"])["updates"].append((
                row["primary_key"],
                {
                    columns[prop]: ontology_service.column_value(
                        types.get(prop, "string"), value
                    )
                    for prop, value in modification["properties"].items()
                },
            ))
        for type_id in sources_by_type:
            rows = rows_for(type_id)
            if rows:
                entry(sources_by_type[type_id])["appends"].extend(rows)
        for removal in removals:
            entry(removal["source"])["deletes"].append(removal["primary_key"])

        staged_all = []
        async with user_connection(access.auth.user_id) as conn:
            for dataset_key, work in plan.items():
                work_source = work["source"]
                work_path = await anyio.to_thread.run_sync(
                    storage.local_path, str(work_source["s3_location"])
                )
                with tempfile.TemporaryDirectory() as tmp:
                    dest = os.path.join(tmp, "out.parquet")
                    work_schema, work_rows = await anyio.to_thread.run_sync(
                        engine.write_rows,
                        work_path,
                        str(work_source["primary_key_column"]),
                        work["updates"],
                        work["appends"],
                        dest,
                        work["deletes"],
                    )
                    with open(dest, "rb") as handle:
                        work_bytes = handle.read()
                staged_all.append(
                    await dataset_service.stage_version(
                        conn, storage,
                        dataset_id=UUID(dataset_key),
                        workspace_id=access.workspace_id,
                        parquet_bytes=work_bytes,
                        schema=work_schema,
                        row_count=work_rows,
                        produced_by_kind="action",
                        produced_by_id=run_id,
                        created_by=access.auth.user_id,
                    )
                )
            committed = await dataset_service.commit_versions(conn, staged_all)
            dataset_version = int(
                committed.get(str(source["dataset_id"]), {"current_version": 0})[
                    "current_version"
                ]
            ) or None
            if values:
                await instance_store.store_for(conn).update_properties(
                    search_prefix=prefix,
                    object_type_id=UUID(str(action_type["object_type_id"])),
                    instance_id=str(body.instance_id),
                    properties=values,
                )
            for modification in modifications:
                # Same order and same reasoning as the subject's write above:
                # the dataset is the record, the index is a projection
                # (decision 0008), so a failure here leaves an object whose
                # stored properties are stale until the next sync rather than a
                # dataset that disagrees with itself.
                await instance_store.store_for(conn).update_properties(
                    search_prefix=prefix,
                    object_type_id=UUID(modification["object_type_id"]),
                    instance_id=modification["instance_id"],
                    properties=modification["properties"],
                )
            if removals:
                # The dataset is the record and the index is a projection
                # (decision 0008), so the row goes first and the projection
                # follows. A failure here leaves a findable object whose row is
                # gone - visible, wrong, and repairable by a re-sync; the
                # reverse order would lose the object while the row survived.
                for removal in removals:
                    await instance_store.store_for(conn).delete_instances(
                        search_prefix=prefix,
                        object_type_id=UUID(removal["object_type_id"]),
                        source_id=UUID(str(removal["source"]["id"])),
                        primary_keys=[removal["primary_key"]],
                    )
            if creations:
                # The index is a projection (decision 0008) - the dataset above
                # is the record. Upserted here so a created object is findable
                # immediately rather than at the next sync; a failure here is
                # repairable by re-syncing the source, which a half-written
                # dataset would not be.
                for type_id, target_source in sources_by_type.items():
                    rows = [
                        (creation["primary_key"], creation["properties"])
                        for creation in creations
                        if creation["object_type_id"] == type_id
                    ]
                    if not rows:
                        continue
                    await instance_store.store_for(conn).upsert_instances(
                        search_prefix=prefix,
                        object_type_id=UUID(type_id),
                        source_id=UUID(str(target_source["id"])),
                        rows=rows,
                        synced_at=datetime.now(timezone.utc),
                        # An action creating the *first* object of a type is
                        # the one path that reaches the store before any sync
                        # has, so the index it creates has to carry the
                        # mapping - otherwise `dynamic: "strict"` refuses the
                        # document that asked for it.
                        declared=await ontology_service.list_properties(
                            conn, UUID(type_id)
                        ),
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


# ---- inline edits (Workshop p.240-243, action-types p.135-138) ---------------
class InlineEdit(BaseModel):
    """One row's worth of an inline-edit submission."""

    instance_id: UUID
    values: dict[str, Any] = Field(default_factory=dict, max_length=50)


class BatchRequest(BaseModel):
    # p.242's cap, enforced by the schema rather than by a check inside the
    # handler: a request of a thousand rows should be refused before anything
    # reads a thousand instances out of the store.
    edits: list[InlineEdit] = Field(
        min_length=1, max_length=actions_service.INLINE_EDIT_ROW_LIMIT
    )


class BatchResult(BaseModel):
    """What one inline-edit submission did.

    **No per-row outcome**, because there is no such thing: p.138 makes the
    batch succeed or fail whole, so a list of results would be a list of the
    same word repeated. What varies, and is therefore reported, is which
    dataset versions the submission produced - a table's rows can come from
    more than one mapping of one object type.
    """

    ok: bool
    error: str | None
    batch_id: UUID
    rows: int
    dataset_versions: dict[str, int]


@project_router.post("/{action_type_id}/execute-batch", response_model=BatchResult)
async def execute_batch(
    action_type_id: UUID,
    body: BatchRequest,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> BatchResult:
    """Submit an Object Table's staged inline edits (`workshop` p.242-243).

    > "Inline edits differ in that they are validated and submitted in bulk."
    > (`action-types` p.137)

    > "At final submission, the edits will be submitted all at once and will
    > succeed if they all pass parameter and global submission criteria for the
    > corresponding object." (p.138)

    **The two halves of that sentence are two loops here, and the order between
    them is the whole guarantee**: every row is bound, seeded, checked against
    p.49-56's criteria and validated against the ontology *before* the first
    row is written. A per-row write-as-you-go would leave a submission that
    half-happened, which is precisely the state p.138 says must not exist and
    which nothing on the reader's screen could describe.

    This is `execute_action` with the shapes eligibility rules out: no creates,
    no deletes, no links, no far-side modifies. That is not a simplification
    somebody chose - it is what `inline_edit_refusals` guarantees, and it is why
    a hundred rows can share one dataset version.
    """
    storage = _dataset_storage()
    batch_id = uuid4()
    async with user_connection(access.auth.user_id) as conn:
        action_type = await actions_service.get_action_type(
            conn, access.workspace_id, action_type_id
        )
        # Parsed once, here, because three things below read a rule's config -
        # the eligibility check does its own, but `apply_rules` and
        # `seed_from_instance` are handed this list per row and would otherwise
        # parse the same configs two hundred times.
        rules = [{**r, "config": _parse_json(r["config"])} for r in action_type["rules"]]
        refusals = actions_service.inline_edit_refusals(action_type)
        if refusals:
            # Refused here as well as hidden in the panel. A builder can point
            # a table at an action and then change the action, and the widget
            # that was configured while it was eligible would go on submitting.
            raise ValueError(
                "this action cannot back inline edits: " + "; ".join(refusals)
            )
        seen: set[UUID] = set()
        for edit in body.edits:
            if edit.instance_id in seen:
                # p.138: "Actions will return an error if an inline edit
                # attempts to edit the same object twice." Refused rather than
                # merged, because two edits of one cell are two answers and
                # nothing here can say which the reader meant last.
                raise ValueError(
                    "this submission edits the same object twice, which an inline "
                    "edit cannot do"
                )
            seen.add(edit.instance_id)

        object_type_id = UUID(str(action_type["object_type_id"]))
        prefix = await instances_service.workspace_search_prefix(conn, access.workspace_id)
        properties = await ontology_service.list_properties(conn, object_type_id)
        property_types = {p["api_name"]: p["data_type"] for p in properties}
        edit_only = ontology_service.edit_only_properties(properties)
        required = ontology_service.required_properties(properties)
        constrained = ontology_service.constrained_properties(properties)
        user = await actions_service.criteria_user(conn, access.auth.user_id)
        link_types = await actions_service.link_types_for(conn, access.workspace_id)

        # Two instances of one type can come from different mappings, so the
        # source is a per-row lookup - cached, because a table's rows usually
        # share one and re-reading it two hundred times is two hundred queries
        # for one answer.
        sources: dict[str, dict[str, Any]] = {}

        async def source_for(source_id: str) -> dict[str, Any]:
            if source_id not in sources:
                # 404s for a source this project does not map, which is the
                # refusal that stops a batch reaching into a project the caller
                # is not in - the same one `execute_action` relies on.
                sources[source_id] = dict(
                    await ontology_service.get_source(
                        conn, access.project_id, UUID(source_id)
                    )
                )
            return sources[source_id]

        planned: list[dict[str, Any]] = []
        for edit in body.edits:
            instance = await instance_store.store_for(conn).get_instance(
                search_prefix=prefix, object_type_id=object_type_id,
                instance_id=str(edit.instance_id),
            )
            if instance is None:
                raise NotFoundError("object instance")
            source = await source_for(str(instance["source_id"]))
            mappings: dict[str, str] = _parse_json(source["column_mappings"])
            stored: dict[str, Any] = _parse_json(instance["properties"])
            bound = actions_service.bind_parameters(
                actions_service.seed_from_instance(
                    edit.values,
                    parameters=action_type["parameters"],
                    properties=stored,
                    rules=rules,
                ),
                parameters=action_type["parameters"],
            )
            actions_service.check_criteria(
                bound, criteria=action_type["criteria"], user=user
            )
            values = actions_service.apply_rules(
                bound,
                rules=rules,
                property_types=property_types,
                mapped_properties=set(mappings.values()),
                edit_only=edit_only,
                link_types=link_types,
            )
            actions_service.check_required(values, required=required)
            actions_service.check_constraints(values, constrained)
            columns = {prop: col for col, prop in mappings.items()}
            planned.append({
                "instance_id": edit.instance_id,
                "primary_key": str(instance["primary_key"]),
                "source": source,
                "values": values,
                # Edit-only properties have no column by definition (p.113), so
                # they reach the instance store below and nothing else.
                "column_updates": {
                    columns[prop]: ontology_service.column_value(
                        property_types.get(prop, "string"), value
                    )
                    for prop, value in values.items()
                    if prop not in edit_only
                },
            })

        # Every row validated, so the runs can be opened: a run that exists is
        # a submission that was accepted, and one opened before the checks
        # would record a hundred attempts for a batch refused on its first row.
        for row in planned:
            row["run_id"] = await actions_service.open_run(
                conn,
                action_type_id=action_type_id,
                instance_id=row["instance_id"],
                dataset_id=UUID(str(row["source"]["dataset_id"])),
                requested_by=access.auth.user_id,
                submitted_values=row["values"],
                batch_id=batch_id,
            )

    ok, error = True, None
    dataset_versions: dict[str, int] = {}
    try:
        # **One entry per dataset**, for the reason `execute_action` states: two
        # staged versions of one dataset collide on the version the first
        # claimed. Here it is the common case rather than the odd one - a table
        # of two hundred rows is one dataset two hundred times.
        plan: dict[str, dict[str, Any]] = {}
        for row in planned:
            entry = plan.setdefault(
                str(row["source"]["dataset_id"]),
                {"source": row["source"], "updates": []},
            )
            if row["column_updates"]:
                entry["updates"].append((row["primary_key"], row["column_updates"]))

        staged_all = []
        async with user_connection(access.auth.user_id) as conn:
            for dataset_key, work in plan.items():
                if not work["updates"]:
                    # Every row this dataset carries wrote edit-only properties
                    # only (p.113). Staging a version identical to the one
                    # before it would be a lineage entry for a file that did
                    # not change.
                    continue
                work_source = work["source"]
                work_path = await anyio.to_thread.run_sync(
                    storage.local_path, str(work_source["s3_location"])
                )
                with tempfile.TemporaryDirectory() as tmp:
                    dest = os.path.join(tmp, "out.parquet")
                    work_schema, work_rows = await anyio.to_thread.run_sync(
                        engine.write_rows,
                        work_path,
                        str(work_source["primary_key_column"]),
                        work["updates"],
                        [],
                        dest,
                        [],
                    )
                    with open(dest, "rb") as handle:
                        work_bytes = handle.read()
                staged_all.append(
                    await dataset_service.stage_version(
                        conn, storage,
                        dataset_id=UUID(dataset_key),
                        workspace_id=access.workspace_id,
                        parquet_bytes=work_bytes,
                        schema=work_schema,
                        row_count=work_rows,
                        # The submission produced this version, not any one of
                        # its runs (db 0063). Naming the first run would be a
                        # lineage entry that is wrong for every other row.
                        produced_by_kind="action_batch",
                        produced_by_id=batch_id,
                        created_by=access.auth.user_id,
                    )
                )
            committed = await dataset_service.commit_versions(conn, staged_all)
            for dataset_key, record in committed.items():
                dataset_versions[str(dataset_key)] = int(record["current_version"])
            for row in planned:
                if not row["values"]:
                    continue
                # The dataset is the record and the index is a projection
                # (decision 0008), so this follows the commit above - a failure
                # here leaves objects stale until the next sync rather than a
                # dataset that disagrees with itself.
                await instance_store.store_for(conn).update_properties(
                    search_prefix=prefix,
                    object_type_id=object_type_id,
                    instance_id=str(row["instance_id"]),
                    properties=row["values"],
                )
    except DatasetEngineError as exc:
        ok, error = False, str(exc)

    async with user_connection(access.auth.user_id) as conn:
        for row in planned:
            await actions_service.close_run(
                conn, row["run_id"], ok=ok,
                dataset_version=dataset_versions.get(str(row["source"]["dataset_id"])),
                error=error,
            )
        # **One audit entry for the submission**, matching what the reader did:
        # they pressed Submit once. The per-object record is the runs, which is
        # what `batch_id` exists to let somebody read back.
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="action.execute_batch",
            resource_type="action_type",
            resource_id=action_type_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={
                "batch_id": str(batch_id), "rows": len(planned), "ok": ok,
            },
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return BatchResult(
        ok=ok, error=error, batch_id=batch_id, rows=len(planned),
        dataset_versions=dataset_versions,
    )
