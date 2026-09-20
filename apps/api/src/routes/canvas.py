"""Canvas app routes (spec §11 "Canvas", §5 "Publishing").

Definitions and editing are project-scoped, same floor as models/datasets/
connections: read = viewer, create/edit/save/delete = editor. Publishing to
the whole workspace or to specific groups additionally requires the
workspace admin role - same conservative bar routes/connections.py already
applies to workspace-scoped connections, since both expose project data
beyond the project's own membership. A project editor can always keep an
app private.

A second, workspace-scoped router (``published_router``) is the read path
for a workspace member who isn't a member of the app's own project: listing
and viewing apps that have actually been published. It never accepts writes.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ForbiddenError, NotFoundError
from ..middleware.permissions import (
    ProjectAccess,
    WorkspaceAccess,
    require_project_role,
    require_workspace_role,
    resolve_project_role,
    resolve_workspace_role,
)
from ..services import actions as actions_service
from ..services import audit
from ..services import module_access
from ..services import ontology as ontology_service
from ..services import orgs as org_service
from ..services import canvas as canvas_service
from ..services import workshop_metrics
from ..services import module_states as states_service
from ..services import workshop_format
from ..services import workshop_variables as variables_service
from ..services.workshop_variables import MAX_EMBED_DEPTH

router = APIRouter(
    prefix="/workspaces/{workspace_id}/projects/{project_id}/canvas-apps", tags=["canvas"]
)
published_router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["canvas"])


def _parse_json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class CanvasAppOut(BaseModel):
    id: UUID
    project_id: UUID
    name: str
    slug: str
    description: str
    current_version: int
    publish_scope: str
    published_at: datetime | None
    # The version viewers of a published app see (roadmap 1.7). Reported
    # alongside `current_version` rather than instead of it: "published v3,
    # editing v7" is the sentence an author needs, and it cannot be said with
    # one number.
    published_version: int | None
    # The two Versions-dialog settings (p.192).
    auto_publish_on_save: bool
    prompt_for_description: bool
    # Where this app opens as an application (`/r/{id}`). The registry has held
    # the mapping since it landed; not reporting it here meant every caller
    # that wanted to link to a module built a slug path instead, and a slug
    # path is a link that breaks on a rename - the one thing resource ids exist
    # to prevent.
    resource_id: UUID
    created_at: datetime
    updated_at: datetime


class CanvasAppDetail(CanvasAppOut):
    definition: dict[str, Any]


class CanvasAppCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class CanvasAppUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DefinitionIn(BaseModel):
    definition: dict[str, Any] = Field(default_factory=dict)
    # Optional note on what changed (p.191). Never required by the server, even
    # when the module asks for one: "always prompt" is a prompt, not a
    # validation rule, and a save refused for want of a sentence is a save
    # somebody loses.
    version_description: str = Field(default="", max_length=500)


class VersionOut(BaseModel):
    id: UUID
    version_number: int
    created_by: UUID | None
    # The editor's name, which is what p.191 puts in the dialog. Optional
    # because `created_by` is ON DELETE SET NULL - a version outlives the
    # account that made it.
    created_by_name: str | None = None
    created_at: datetime
    description: str = ""


class VersionDetail(VersionOut):
    definition: dict[str, Any]


class DescribeVersionIn(BaseModel):
    description: str = Field(default="", max_length=500)


class VersionSettingsIn(BaseModel):
    auto_publish_on_save: bool | None = None
    prompt_for_description: bool | None = None


class UsageTrackingIn(BaseModel):
    on: bool


class PublishIn(BaseModel):
    scope: str = Field(pattern="^(private|workspace|groups)$")
    group_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ShareOut(BaseModel):
    group_id: UUID
    group_name: str


class EvaluateVariablesIn(BaseModel):
    """What the viewer has set. Values for derived variables are ignored - a
    derived variable is a function of its inputs (see the service)."""

    values: dict[str, Any] = Field(default_factory=dict)
    # Variable ids the *host* module is backing, when this module is embedded.
    # Foundry's rule is that the parent's definition wins and the child's is
    # ignored (p.122, p.127), and that cannot be read off the child's document -
    # only the host knows which of the child's interface variables it mapped.
    #
    # Trusting the client with this is a smaller thing than it looks: a caller
    # could already send any value it liked for any non-derived variable, and
    # object sets are still definitions here, resolved against RLS by
    # `/object-sets/evaluate` afterwards. What `bound` buys a hostile caller is
    # the ability to change what its own browser draws, which it has anyway.
    bound: list[str] = Field(default_factory=list)
    # p.76's two non-automatic recompute behaviours: the value a variable last
    # computed, sent back so it does not recompute this time. Client-supplied
    # for the same reason `bound` is - only the browser knows what it last saw
    # - and trusting it costs the same: a caller can change what its own
    # browser draws, which it could already do by sending any value it liked.
    #
    # Ignored for any variable that is not configured to hold one; the
    # evaluator branches on the *document's* behaviour, not on what arrived.
    held: dict[str, Any] = Field(default_factory=dict)
    # p.85's Recompute event arriving: ids to recompute this time regardless of
    # what `held` carries for them. Separate from an absence in `held` because
    # an absence cannot say it - for `only_on_event`, "never computed" and
    # "recompute now" are both spelled "nothing held", and the event has to be
    # able to mean the second one.
    recompute: list[str] = Field(default_factory=list)
    #: p.75's lazy rule (§392): the layout node ids currently on screen. The
    #: server expands these into the variables they need, inputs included, and
    #: computes nothing else.
    #:
    #: **`None` means "compute everything", and that is not the same as `[]`.**
    #: An empty list is a real answer - a module showing no widgets at all -
    #: and a caller that has not been taught to send this must not be read as
    #: giving it. The builder sends nothing, because in this build's editor
    #: every page is on screen at once and the question has no answer there.
    #:
    #: Trusting the client is the same size of thing as `bound` and `held`
    #: above: what it buys a caller is a smaller answer about its own browser.
    visible: list[str] | None = None
    #: Whether to measure (§394). Off by default: every caller but the
    #: Performance Profiler wants the values and nothing else.
    profile: bool = False


class EvaluateVariablesOut(BaseModel):
    values: dict[str, Any]
    order: list[str]
    #: p.178's "breakdown of load time by widgets and variables", the variable
    #: half (§394). Milliseconds each variable took *this* resolve, and only
    #: when the caller asked - `None` rather than `{}` for a resolve that was
    #: not measured, because an empty breakdown is a real answer (a module
    #: showing nothing) and "not measured" is not an answer at all.
    timings: dict[str, float] | None = None


def _out(row: dict[str, Any]) -> CanvasAppDetail:
    return CanvasAppDetail(**{**row, "definition": _parse_json(row["definition"])})


def _summary(row: dict[str, Any]) -> CanvasAppOut:
    return CanvasAppOut(**row)


# ---- project-scoped CRUD ------------------------------------------------------
async def _workspace_property_types(conn, workspace_id) -> dict[str, dict[str, str]]:
    """`{object_type_id: {api_name: data_type}}` for a whole workspace (§221).

    **One query, not one per object type**, which is why
    `list_properties_for_workspace` exists at all: a document can hold sets
    over any number of types, and the per-type version made a workspace with
    226 of them do 226 round trips.

    Passed on **both** the write and the read path, unlike `actions`. An action
    deleted after an app was saved must not stop the app opening, because the
    record of what somebody built stays valid; a property whose declared type
    changed is different in kind - the ordered comparison saved against it can
    no longer be evaluated by either store, so an app that opened anyway would
    be showing a set narrowed by a filter that silently did nothing, which is
    decision 0002's failure exactly.
    """
    return {
        str(type_id): {
            str(row["api_name"]): str(row["data_type"])
            for row in rows
            if row.get("api_name") and row.get("data_type")
        }
        for type_id, rows in (
            await ontology_service.list_properties_for_workspace(conn, workspace_id)
        ).items()
    }


@router.get("", response_model=list[CanvasAppOut])
async def list_apps(
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[CanvasAppOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_for_project(conn, access.project_id)
    return [_summary(r) for r in rows]


@router.post("", response_model=CanvasAppDetail, status_code=status.HTTP_201_CREATED)
async def create_app(
    body: CanvasAppCreate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.create(
            conn,
            project_id=access.project_id,
            name=body.name,
            description=body.description,
            created_by=access.auth.user_id,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.create",
            resource_type="canvas_app",
            resource_id=row["id"],
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": body.name},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{app_id}", response_model=CanvasAppDetail)
async def get_app(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
    return _out(row)


@router.patch("/{app_id}", response_model=CanvasAppDetail)
async def update_app(
    app_id: UUID,
    body: CanvasAppUpdate,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.update_metadata(
            conn, access.project_id, app_id, name=body.name, description=body.description
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.update",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"name": body.name},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.delete("/{app_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_app(
    app_id: UUID,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.delete(conn, access.project_id, app_id)
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.delete",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )


# ---- definition versioning ----------------------------------------------------
async def _check_embeds(conn, project_id: UUID, app_id: UUID, document: Any) -> None:
    """Refuse an embed that cannot be drawn: a missing module, a cycle, or a
    stack deeper than `MAX_EMBED_DEPTH`.

    **Checked when the document is saved, not when it is opened.** A cycle
    found at render time is a browser that hangs or a request storm, and the
    person who sees it is a viewer who did not build the thing. The author is
    the one who can fix it, so the author is the one who is told.

    The walk is over *stored* definitions, which means it is a snapshot: A can
    be saved embedding B today and B edited to embed A tomorrow, because saving
    B checks B's own embeds and reaches A the same way. The cycle is refused
    whichever side completes it - which is the property that matters, and is
    why this does not need to lock anything.
    """
    direct = variables_service.embedded_modules(document)
    if not direct:
        return
    if str(app_id) in direct:
        raise variables_service.VariableError(
            "a module cannot embed itself - it would draw itself drawing itself. "
            "Embed one of its parts, or link to it."
        )

    # The interface mapping's child half, checked here because it is the only
    # place that has the child's document. Each embed is checked against the
    # module it actually names, so two nodes embedding two different modules
    # get two different answers.
    host_variables = variables_service.parse((document or {}).get("variables"))
    for embed in variables_service.embeds(document):
        try:
            child = await canvas_service.get(conn, project_id, UUID(embed.module_id))
        except (NotFoundError, ValueError):
            continue  # reported by the walk below, which says it better
        await _check_interface(embed, child, host_variables)

    seen: set[str] = {str(app_id)}
    frontier = [(module_id, 1, [str(module_id)]) for module_id in sorted(direct)]
    while frontier:
        module_id, depth, path = frontier.pop()
        try:
            embedded = await canvas_service.get(conn, project_id, UUID(module_id))
        except (NotFoundError, ValueError) as exc:
            raise variables_service.VariableError(
                f"embedded module {module_id} is not in this project, so nothing would "
                "be drawn where it is placed"
            ) from exc
        if depth > MAX_EMBED_DEPTH:
            raise variables_service.VariableError(
                f"embedding is {depth} deep at {' -> '.join(path)}, past the limit of "
                f"{MAX_EMBED_DEPTH}. Every level is another definition to fetch before "
                "anything appears, and the wait is paid by a viewer who cannot see why."
            )
        for nested in sorted(variables_service.embedded_modules(embedded.get("definition") or {})):
            if nested == str(app_id):
                raise variables_service.VariableError(
                    f"this would embed itself through {' -> '.join(path)}, and the loop "
                    "has no end. Break the chain at one of those modules."
                )
            if nested in seen:
                continue
            seen.add(nested)
            frontier.append((nested, depth + 1, [*path, nested]))


async def _check_interface(
    embed: variables_service.Embed,
    child: dict[str, Any],
    host_variables: dict[str, variables_service.Variable],
) -> None:
    """The four refusals an interface mapping earns (`docs/parity/workshop.md` §3.4).

    All four are the same failure wearing different clothes: a mapping that
    looks configured and passes nothing. Foundry's precedence rule makes that
    worse rather than better - the child's own definition is *ignored* for a
    mapped variable (p.122, p.127), so a mapping that silently does not apply
    leaves the child reading a default the parent thought it had replaced.
    """
    child_name = child.get("name") or embed.module_id
    try:
        child_variables = variables_service.parse((child.get("definition") or {}).get("variables"))
    except variables_service.VariableError:
        # The child does not parse. That is the child's problem to fix and its
        # own save already refused it; saying so here would blame this document
        # for a fault in another one.
        return
    interface = variables_service.interface_variables(child_variables)

    for external_id, host_vid in sorted(embed.mapping.items()):
        target = interface.get(external_id)
        if target is None:
            offered = ", ".join(sorted(interface)) or "nothing"
            raise variables_service.VariableError(
                f"{child_name!r} has no interface variable called {external_id!r}. "
                f"Its interface offers: {offered}. A variable joins the interface by "
                "being given an external ID with the interface toggle on"
            )
        host = host_variables[host_vid]  # validate_module proved it exists
        if host.kind != target.kind:
            raise variables_service.VariableError(
                f"{external_id!r} on {child_name!r} is a {target.kind} and "
                f"{host.label!r} is a {host.kind}. The mapped variable is backed by "
                "this module's definition, so the two have to be the same kind"
            )

    # A Loop layout's item variable (p.135). Same failure as an unknown mapping
    # - a loop that looks configured and passes no object - but it needs its own
    # check because it is not in `mapping`: nothing on the host backs it, the
    # set being looped does.
    if embed.item_external_id is not None:
        target = interface.get(embed.item_external_id)
        if target is None:
            offered = ", ".join(sorted(interface)) or "nothing"
            raise variables_service.VariableError(
                f"{child_name!r} has no interface variable called "
                f"{embed.item_external_id!r} to receive each object. Its interface "
                f"offers: {offered}"
            )
        # p.134: the child must have "a module interface object set variable if
        # configured to loop over an object set, or a variable typed to the
        # array type if configured to loop over an array". `item_kind` is that
        # requirement, computed from what the loop is looping - see `Embed`.
        #
        # `None` means the loop is misconfigured in a way the layout check
        # already refuses with a sharper message (an array arm naming nothing,
        # or an untyped array). Checking it again here would report the child's
        # variable as wrong when the fault is on the host.
        if embed.item_kind is not None and target.kind != embed.item_kind:
            one_of = (
                "one object at a time" if embed.item_kind == "single_object"
                else "one array entry at a time"
            )
            raise variables_service.VariableError(
                f"a loop gives {child_name!r} {one_of}, so "
                f"{embed.item_external_id!r} has to be a {embed.item_kind} and it is a "
                f"{target.kind}"
            )

    missing = sorted(
        external_id
        for external_id, variable in interface.items()
        if variable.interface is not None
        and variable.interface.required
        and external_id not in embed.mapping
        # The loop's item variable *is* supplied - by the set being looped -
        # so a required one is satisfied rather than missing.
        and external_id != embed.item_external_id
    )
    if missing:
        raise variables_service.VariableError(
            f"{child_name!r} requires {', '.join(missing)} to be mapped, and "
            f"{'they are' if len(missing) > 1 else 'it is'} not. A required interface "
            "variable is one the module cannot render without"
        )


@router.put("/{app_id}/definition", response_model=CanvasAppDetail)
async def save_definition(
    app_id: UUID,
    body: DefinitionIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    # Validated here rather than in `canvas_service`, which stores an opaque
    # blob and does not interpret it - a property decision 0002 records as
    # worth keeping. The API refuses the document; the storage layer stays
    # uninterested in what is inside it.
    #
    # **A v1 document is refused on the way in** (roadmap 1.8). Migration 0034
    # converted every stored app, and the migration container runs before this
    # code does, so an "unconverted app" cannot reach here - the only things
    # that can still produce a v1 document are a script or a client older than
    # the conversion, and what they would produce is an app that silently has
    # no variables, no events and no pages. Reading v1 is untouched: historical
    # version rows are deliberately left in the format they were written in
    # (0034), and the browser still renders them.
    if workshop_format.is_v1(body.definition):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "this is a pre-Workshop (v1) layout, and saving one would create an app "
                "with no variables, events or pages. Every stored app was converted by "
                "migration 0034; a client sending this one is older than that conversion."
            ),
        )
    async with user_connection(access.auth.user_id) as conn:
        # The workspace's actions, so a `run_action` naming one that is not
        # here - or writing a property it does not make editable - is refused
        # by the person who wrote it rather than by whoever clicks it later.
        # Only on the way in: see `validate_module` for why reading a document
        # does not re-check it against live state.
        known = {
            str(a["id"]): actions_service.editable_properties_of(a["rules"])
            for a in await actions_service.list_action_types(conn, access.workspace_id)
        }
        try:
            variables_service.validate_module(
                body.definition, actions=known,
                property_types=await _workspace_property_types(
                    conn, access.workspace_id
                ),
            )
        except variables_service.VariableError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        try:
            await _check_embeds(conn, access.project_id, app_id, body.definition)
        except variables_service.VariableError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

        row = await canvas_service.save_definition(
            conn, access.project_id, app_id,
            definition=body.definition, created_by=access.auth.user_id,
            version_description=body.version_description,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.save",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"version": row["current_version"]},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{app_id}/versions", response_model=list[VersionOut])
async def list_versions(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[VersionOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_versions(conn, access.project_id, app_id)
    return [VersionOut(**r) for r in rows]


@router.get("/{app_id}/versions/{version_number}", response_model=VersionDetail)
async def get_version(
    app_id: UUID,
    version_number: int,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> VersionDetail:
    """"View this version" (p.191). Viewer, not editor: looking at what an app
    used to be is reading, and a reviewer who cannot open a version cannot
    review a revert."""
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get_version(conn, access.project_id, app_id, version_number)
    return VersionDetail(**{**row, "definition": _parse_json(row["definition"])})


@router.patch("/{app_id}/versions/{version_number}", response_model=VersionOut)
async def describe_version(
    app_id: UUID,
    version_number: int,
    body: DescribeVersionIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> VersionOut:
    """p.192: descriptions "can be viewed, added, and edited"."""
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.describe_version(
            conn, access.project_id, app_id, version_number, body.description
        )
    return VersionOut(**row)


@router.post("/{app_id}/versions/{version_number}/publish", response_model=CanvasAppDetail)
async def publish_version(
    app_id: UUID,
    version_number: int,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    """"Publish this version" (p.191) - move viewers to a version somebody
    chose, rather than to whatever is newest.

    **Editor, not workspace admin**, and the distinction is deliberate: this
    changes *which* version an existing audience sees, not *who* the audience
    is. Widening the audience is `set_publish_scope` and still needs an admin,
    so choosing a version cannot be a way round that check.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.publish_version(
            conn, access.project_id, app_id, version_number
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.publish_version",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"version": version_number},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.post("/{app_id}/versions/{version_number}/revert", response_model=CanvasAppDetail)
async def revert_to_version(
    app_id: UUID,
    version_number: int,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    """p.192: save the historic version as the newest one, with a generated
    description. A new version, not a rewind - the history in between stays."""
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.revert_to_version(
            conn, access.project_id, app_id, version_number, access.auth.user_id
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.revert",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"reverted_to": version_number},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.put("/{app_id}/version-settings", response_model=CanvasAppDetail)
async def set_version_settings(
    app_id: UUID,
    body: VersionSettingsIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    """The two toggles in the Versions dialog (p.192)."""
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.set_version_settings(
            conn, access.project_id, app_id,
            auto_publish_on_save=body.auto_publish_on_save,
            prompt_for_description=body.prompt_for_description,
        )
    return _out(row)


@router.put("/{app_id}/usage-tracking", response_model=CanvasAppDetail)
async def set_usage_tracking(
    app_id: UUID,
    body: UsageTrackingIn,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    """p.187's Usage Metrics Tracking (§397).

    **Editor**, unlike everything else about metrics. Reading counts is
    reading; deciding that a module starts recording what people look at is a
    change to the module, and p.187 puts it behind "Open the module in Edit
    mode" for the same reason.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.set_usage_tracking(
            conn, access.project_id, app_id, on=body.on
        )
    return _out(row)


def _only_visible(
    body: EvaluateVariablesIn, document: Any, variables: Any
) -> "frozenset[str] | None":
    """p.75's lazy rule, or None when the caller did not ask for it (§392).

    **The `None` check is the whole function.** `body.visible` defaults to
    `None` and an empty list is a real answer, so `if not body.visible` would
    quietly turn "this module is showing nothing" into "compute everything" -
    which is the one case where the lazy rule saves the most work and the one
    where it would be silently switched off.
    """
    if body.visible is None:
        return None
    layout = document.get("layout") if isinstance(document, dict) else None
    return frozenset(
        variables_service.displayed(
            layout, variables, set(body.visible),
            # What the host mapped, which the evaluator is about to honour by
            # skipping these variables' own derivations (p.127). The closure
            # stops there for the same reason.
            bound=frozenset(body.bound),
        )
    )


# ---- variables (roadmap phase 2, item 1.2) -----------------------------------
@router.post("/{app_id}/variables/evaluate", response_model=EvaluateVariablesOut)
async def evaluate_variables(
    app_id: UUID,
    body: EvaluateVariablesIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> EvaluateVariablesOut:
    """Resolve every variable in the app, computing derived ones in dependency
    order.

    **Why the server does this rather than the browser**, since the transforms
    are pure functions and the browser is where the values are shown. This
    repo already carries five files mirrored between two runtimes and a
    standing note that a sixth should become a shared package instead
    (`STATUS.md`, rough edges). A TypeScript copy of `if_else`'s truthiness or
    `cast`'s refusals would be the sixth, and those are exactly the semantics
    two implementations get subtly and invisibly different.

    The round trip is close to free where it matters: derived values change
    when their *inputs* change - a filter selection, a row click - which is the
    same moment the app is already asking the server to re-evaluate an object
    set. It rides along with a call that was happening anyway. The honest cost
    is a text input, where every debounced keystroke now costs a request that a
    local computation would not.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
        # Read inside the connection that fetched the row, because validating a
        # saved ordered comparison needs the declared types (§221) - and the
        # *store* needs them too, to know what to cast.
        property_types = await _workspace_property_types(conn, access.workspace_id)
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(
            document, property_types=property_types
        )
    except variables_service.VariableError as exc:
        # A saved app whose document no longer validates. Reachable: the module
        # could have been written before a rule existed, or by something other
        # than this API. Reported rather than swallowed, because the viewer
        # otherwise sees widgets quietly bound to nothing.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    try:
        measured: dict[str, float] | None = {} if body.profile else None
        resolved = variables_service.evaluate(
            variables,
            body.values,
            bound=frozenset(body.bound),
            held=body.held,
            recompute_now=frozenset(body.recompute),
            # A `narrow_set` derivation combines the widget's clauses with the
            # base set and re-validates the result, so an ordered clause needs
            # the declared types here too (§221) - not only where the document
            # was checked.
            property_types=property_types,
            # p.75's lazy rule (§392). Expanded here rather than in the
            # browser: the closure - a chart needs its set, the set needs its
            # filter - is over a graph this service already understands, and a
            # second walker of it would be the copy that disagrees.
            only=_only_visible(body, document, variables),
            timings=measured,
        )
    except variables_service.VariableError as exc:
        # Not the same failure, and not the same fault. The document is fine;
        # what arrived with the request is not - a Filter List can send filter
        # clauses, and `narrow_set` refuses ones it cannot mean rather than
        # dropping them. Blaming the saved app for a bad request would send
        # whoever reads this to the wrong place entirely.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return EvaluateVariablesOut(
        values=resolved,
        order=variables_service.evaluation_order(variables),
        timings=measured,
    )


# ---- usage metrics (§396; `workshop` p.185-188) ------------------------------
class ActionUsageOut(BaseModel):
    action_type_id: str
    display_name: str
    api_name: str
    #: Successful submissions in the chosen period. **Of this action**, not of
    #: this module - p.186's "available by default for all modules and do not
    #: require any additional configuration" is what settles that, and the
    #: service says so at length.
    submissions: int
    #: The same count over the equivalent period immediately before (p.188).
    previous: int
    #: Where in the module this action is used, for p.185's "select an action
    #: to view which widgets in the module use that action".
    used_by: list[dict[str, str]]


class LayoutViewOut(BaseModel):
    node_id: str
    views: int
    previous: int


class UsageMetricsOut(BaseModel):
    days: int
    actions: list[ActionUsageOut]
    #: p.186's layout views. Empty when the module has not opted in *and* when
    #: it has but nobody has looked - **`tracking` is what tells those apart**,
    #: because "no views" and "we are not counting" are different answers and
    #: a panel showing the first for the second would report a module as unused
    #: when it was never watched.
    layouts: list[LayoutViewOut] = []
    tracking: bool = False


@router.get("/{app_id}/metrics", response_model=UsageMetricsOut)
async def usage_metrics(
    app_id: UUID,
    days: int = Query(default=workshop_metrics.DEFAULT_PERIOD),
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> UsageMetricsOut:
    """p.185's Metrics tab, the action half.

    **Viewer, though the panel is a builder's.** Reading how a module is used
    is reading counts about actions the caller can already see; p.185 calls
    every number here "aggregate counts… not attributable to any specific
    user", so there is nothing to protect that the action list does not already
    expose. Putting an editor floor on it would be a rule with no reason behind
    it, which is the kind that gets copied.
    """
    if days not in workshop_metrics.PERIODS:
        # p.188 offers three windows and no others. Refused rather than
        # clamped: a panel that asked for 45 days and was quietly given 30
        # would label the answer with the number it asked for.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "usage metrics are reported over "
                + ", ".join(f"{d} days" for d in workshop_metrics.PERIODS)
            ),
        )
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
        used = workshop_metrics.module_actions(_parse_json(row["definition"]))
        counts = await workshop_metrics.action_counts(
            conn, list(used), days=days
        )
        views = await workshop_metrics.layout_views(conn, app_id=app_id, days=days)
    return UsageMetricsOut(
        days=days,
        tracking=bool(row["track_usage"]),
        layouts=[LayoutViewOut(**v) for v in views],
        actions=[
            ActionUsageOut(**c, used_by=used.get(c["action_type_id"], []))
            for c in counts
        ],
    )


class LayoutViewIn(BaseModel):
    node_id: str


@router.post("/{app_id}/views", status_code=status.HTTP_204_NO_CONTENT,
             response_model=None)
async def record_layout_view(
    app_id: UUID,
    body: LayoutViewIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> None:
    """One layout was looked at (p.186; §397).

    **204 whether or not it was counted**, and the silence is the point. A
    module with tracking off is the ordinary case, not an error, and a browser
    that got a 4xx for reporting a page view would be a browser logging errors
    on every navigation of every module nobody opted in. The service decides;
    the caller is told nothing because there is nothing it should do
    differently.

    **Viewer, because viewing is what this records.** p.185's numbers are
    aggregate and carry no user, so there is nothing here that a reader of the
    module could not already do by reading it.
    """
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.get(conn, access.project_id, app_id)
        await workshop_metrics.record_view(conn, app_id=app_id, node_id=body.node_id)


# ---- publishing ---------------------------------------------------------------
@router.put("/{app_id}/publish", response_model=CanvasAppDetail)
async def set_publish_scope(
    app_id: UUID,
    body: PublishIn,
    request: Request,
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> CanvasAppDetail:
    if body.scope != "private" and access.workspace_role != "admin":
        raise ForbiddenError("publishing beyond the project requires the workspace admin role")
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.set_publish_scope(
            conn, access.project_id, app_id,
            organisation_id=access.auth.organisation_id,
            scope=body.scope, group_ids=body.group_ids,
        )
        await audit.record(
            conn,
            organisation_id=access.auth.organisation_id,
            user_id=access.auth.user_id,
            action="canvas_app.publish",
            resource_type="canvas_app",
            resource_id=app_id,
            workspace_id=access.workspace_id,
            project_id=access.project_id,
            metadata={"scope": body.scope, "groups": len(body.group_ids)},
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    return _out(row)


@router.get("/{app_id}/shares", response_model=list[ShareOut])
async def list_shares(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[ShareOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_shares(conn, access.project_id, app_id)
    return [ShareOut(**r) for r in rows]


class AccessUser(BaseModel):
    id: UUID
    email: str
    display_name: str
    #: Whether the account can sign in at all. Carried because every role a
    #: disabled account holds is a role it cannot use, and a panel that read
    #: those roles out as access would be confidently wrong about the one
    #: person a builder is least likely to think of.
    active: bool


class AccessResource(BaseModel):
    kind: str
    id: str
    name: str | None
    status: str  # 'visible' | 'unusable' | 'hidden' | 'unknown'


class ModuleAccessOut(BaseModel):
    user: AccessUser
    workspace_role: str | None
    project_role: str | None
    can_open: bool
    can_edit: bool
    resources: list[AccessResource]


@router.get("/{app_id}/access", response_model=ModuleAccessOut)
async def check_access(
    app_id: UUID,
    user_id: UUID = Query(...),
    access: ProjectAccess = Depends(require_project_role("editor")),
) -> ModuleAccessOut:
    """The Check access panel (`workshop` p.92).

        "You can use the Check access panel in the sidebar to easily check a
         user's access on a Workshop module. This will show if they meet the
         access requirement on the Workshop module, as well as additional data
         requirements to see object types, link types, action types, and
         functions."

    **Every answer is asked as the named user**, on a connection opened for
    them, through the same reads their own requests make. p.92's value is
    entirely in being right about somebody else's access, and a re-derivation
    of the rules here would be free to disagree with the rules (§146) in
    exactly the cases a builder opens this panel to understand.

    **Editor, not viewer.** The panel reports one person's access to another,
    which is a builder's question about a module they maintain; a reader of the
    module has no use for it. The bar is the same one that can change what the
    module requires.

    Functions are p.92's fourth kind and are absent: this platform has none.
    """
    async with user_connection(access.auth.user_id) as caller:
        subject = await org_service.get_user(caller, access.auth.organisation_id, user_id)
        row = await canvas_service.get(caller, access.project_id, app_id)
        definition = _parse_json(row["definition"])

        # `get_current_user` refuses a non-active account before any route
        # runs, so a disabled user reaches nothing whatever `effective_*_role`
        # still says - and those functions check `status` only on their org
        # admin branch, so they go on reporting a membership role for an
        # account that cannot authenticate.
        active = subject["status"] == "active"

        async with user_connection(user_id) as theirs:
            project_role = await resolve_project_role(theirs, user_id, access.project_id)
            workspace_role = await resolve_workspace_role(theirs, user_id, access.workspace_id)
            can_open = active and await module_access.opens(
                theirs, workspace_id=access.workspace_id, app_id=app_id,
                project_role=project_role,
            )
            found = await module_access.resources(
                theirs, caller, workspace_id=access.workspace_id, definition=definition,
                # Running an action is a project editor's right on the module's
                # own project (`actions.execute_action`), and it is the one
                # requirement p.92's sentence separates that this platform can
                # actually have come apart: a published module's reader can
                # read every action type in the workspace and run none of them.
                may_run_actions=project_role in ("editor", "owner"),
            )

    return ModuleAccessOut(
        user=AccessUser(
            id=subject["id"], email=subject["email"],
            display_name=subject["display_name"], active=active,
        ),
        workspace_role=workspace_role,
        project_role=project_role,
        can_open=can_open,
        # An editor of the project may change the module; p.92's "open or edit"
        # is one sentence and two different answers, which is why both are here.
        can_edit=active and project_role in ("editor", "owner"),
        resources=[AccessResource(**r) for r in found],
    )


# ---- workspace-wide read path for published apps ------------------------------
@published_router.get("/published-canvas-apps", response_model=list[CanvasAppOut])
async def list_published_apps(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[CanvasAppOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_published(conn, access.workspace_id)
    return [_summary(r) for r in rows]


@published_router.get("/saved-canvas-apps/{app_id}", response_model=CanvasAppDetail)
async def get_saved_app(
    app_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> CanvasAppDetail:
    """p.166's `/dev/`: the app as its author last **saved** it (§314).

        "For testing purposes, you can change the `/latest/` to `/dev/` in the
         URL, and the link will now redirect to the last saved version of the
         Workshop application instead of the last published version."

    **The refusal p.166 leaves implicit is the point of this route.** "For
    testing purposes" means unpublished work, and unpublished work is exactly
    what publishing being an act rather than a checkbox exists to keep from
    viewers — so a workspace viewer following a hand-edited link must get the
    same answer as somebody who guessed the URL: nothing. The floor here is
    workspace viewer only so the request reaches this function; who may
    actually see a draft is settled below, against the *project*.

    404 rather than 403, and that matters. A 403 would confirm the app exists
    and has unpublished changes, which is the very thing being withheld.
    """
    async with user_connection(access.auth.user_id) as conn:
        # Read first, so a nonexistent app and an app somebody may not preview
        # give the same answer — `get_saved` raises `NotFoundError` for the
        # first, and the check below produces the same for the second.
        row = await canvas_service.get_saved(conn, access.workspace_id, app_id)
        role = await resolve_project_role(
            conn, access.auth.user_id, row["project_id"]
        )
        if role not in ("editor", "admin", "owner"):
            raise NotFoundError("canvas app")
    return _out(row)


@published_router.get("/published-canvas-apps/{app_id}", response_model=CanvasAppDetail)
async def get_published_app(
    app_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> CanvasAppDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get_published(conn, access.workspace_id, app_id)
    return _out(row)


@published_router.post(
    "/published-canvas-apps/{app_id}/variables/evaluate", response_model=EvaluateVariablesOut
)
async def evaluate_published_variables(
    app_id: UUID,
    body: EvaluateVariablesIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> EvaluateVariablesOut:
    """The same resolve, reached the way a published app is reached.

    Needed because the project-scoped one requires project membership, and a
    published app exists precisely for a workspace member who is *not* in its
    project (`STATUS.md` §15). Without this, every published Workshop app would
    resolve no variables for exactly the audience it was published to - and the
    symptom would be widgets showing nothing, which reads as no data rather
    than as no permission.

    `get_published` is what enforces the scope, exactly as the read path does:
    an app that is not published to this caller is not found.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get_published(conn, access.workspace_id, app_id)
        property_types = await _workspace_property_types(conn, access.workspace_id)
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(
            document, property_types=property_types
        )
    except variables_service.VariableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    try:
        measured: dict[str, float] | None = {} if body.profile else None
        resolved = variables_service.evaluate(
            variables,
            body.values,
            bound=frozenset(body.bound),
            held=body.held,
            recompute_now=frozenset(body.recompute),
            # A `narrow_set` derivation combines the widget's clauses with the
            # base set and re-validates the result, so an ordered clause needs
            # the declared types here too (§221) - not only where the document
            # was checked.
            property_types=property_types,
            # p.75's lazy rule (§392). Expanded here rather than in the
            # browser: the closure - a chart needs its set, the set needs its
            # filter - is over a graph this service already understands, and a
            # second walker of it would be the copy that disagrees.
            only=_only_visible(body, document, variables),
            timings=measured,
        )
    except variables_service.VariableError as exc:
        # The values, not the document - see the note on the project-scoped one.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return EvaluateVariablesOut(
        values=resolved,
        order=variables_service.evaluation_order(variables),
        timings=measured,
    )


# ---- saved module states (p.200-206; db 0048) --------------------------------
class StateIn(BaseModel):
    """A state as the viewer's browser has it: values keyed by **variable id**.

    Translated to external IDs on the way in (`module_states.savable_values`)
    rather than by the browser, so the one rule about what a state contains has
    one implementation - the same argument that keeps variable evaluation on
    the server.
    """

    name: str = Field(min_length=1, max_length=200)
    values: dict[str, Any] = Field(default_factory=dict)
    page_id: str | None = Field(default=None, max_length=200)


class StateOut(BaseModel):
    id: UUID
    name: str
    page_id: str | None
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime


class StateDetail(StateOut):
    """One state, opened: values keyed back to **variable id** for the module.

    `missing` names the external IDs the state carries that this module no
    longer has a savable variable for. p.203 warns that changing an external ID
    "may cause previously configured states to reload unsuccessfully" - saying
    *which* part failed is the difference between a known gap and a view that
    is quietly wrong.
    """

    values: dict[str, Any]
    missing: list[str]


def _state_summary(row: dict[str, Any]) -> StateOut:
    return StateOut(
        id=row["id"], name=row["name"], page_id=row["page_id"],
        created_by_name=row.get("created_by_name"),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _module_variables(
    row: dict[str, Any], property_types: dict[str, dict[str, str]] | None = None
) -> dict[str, Any]:
    """This module's variables, and a refusal if it does not save state.

    Checked on every path rather than only on the write: a state saved while
    the feature was on, and opened after it was turned off, is a view the
    module no longer offers - and restoring it silently would be the module
    disagreeing with its own settings.
    """
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(
            document, property_types=property_types
        )
        settings = variables_service.state_saving(document)
    except variables_service.VariableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this module does not save state - turn it on in the module's "
                   "settings first",
        )
    return variables


async def _save(conn, row, body: StateIn, user_id: UUID) -> StateOut:
    variables = _module_variables(row)
    saved = await states_service.save_state(
        conn,
        canvas_app_id=row["id"],
        name=body.name,
        values=states_service.savable_values(variables, body.values),
        # p.200: "optionally, the current page". Honoured only when the module
        # asked for it, so turning the option off stops states carrying a page
        # rather than merely stopping them writing one.
        page_id=body.page_id
        if variables_service.state_saving(_parse_json(row["definition"])).include_page
        else None,
        user_id=user_id,
    )
    return _state_summary(saved)


async def _open(conn, row, state_id: UUID) -> StateDetail:
    variables = _module_variables(row)
    state = await states_service.get_state(conn, state_id)
    if str(state["canvas_app_id"]) != str(row["id"]):
        # A state id from another module would otherwise open here and restore
        # values that mean nothing - keyed by external ID, some of them might
        # even match.
        raise NotFoundError("module state")
    values, missing = states_service.restore(variables, state["values"])
    return StateDetail(**_state_summary(state).model_dump(), values=values, missing=missing)


@router.get("/{app_id}/states", response_model=list[StateOut])
async def list_states(
    app_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> list[StateOut]:
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.get(conn, access.project_id, app_id)
        rows = await states_service.list_states(conn, app_id)
    return [_state_summary(r) for r in rows]


@router.post("/{app_id}/states", response_model=StateOut, status_code=status.HTTP_201_CREATED)
async def save_state(
    app_id: UUID,
    body: StateIn,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> StateOut:
    """Saving a state is a **viewer** action, not an editor one.

    p.200 calls this a feature for "module consumers", and it writes nothing
    about the module: a state is a note about how somebody was looking at it.
    Requiring the editor role would put it behind exactly the permission its
    audience does not have.
    """
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
        return await _save(conn, row, body, access.auth.user_id)


@router.get("/{app_id}/states/{state_id}", response_model=StateDetail)
async def open_state(
    app_id: UUID,
    state_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> StateDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get(conn, access.project_id, app_id)
        return await _open(conn, row, state_id)


@router.delete(
    "/{app_id}/states/{state_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_state(
    app_id: UUID,
    state_id: UUID,
    access: ProjectAccess = Depends(require_project_role("viewer")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.get(conn, access.project_id, app_id)
        await states_service.delete_state(conn, state_id, access.auth.user_id)


# The same four, reached the way a published app is reached - the audience
# state saving exists for is precisely the workspace member who is not in the
# app's project (`STATUS.md` §15, and the note on the published evaluate).
@published_router.get("/published-canvas-apps/{app_id}/states", response_model=list[StateOut])
async def list_published_states(
    app_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[StateOut]:
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.get_published(conn, access.workspace_id, app_id)
        rows = await states_service.list_states(conn, app_id)
    return [_state_summary(r) for r in rows]


@published_router.post(
    "/published-canvas-apps/{app_id}/states",
    response_model=StateOut,
    status_code=status.HTTP_201_CREATED,
)
async def save_published_state(
    app_id: UUID,
    body: StateIn,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> StateOut:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get_published(conn, access.workspace_id, app_id)
        return await _save(conn, row, body, access.auth.user_id)


@published_router.get(
    "/published-canvas-apps/{app_id}/states/{state_id}", response_model=StateDetail
)
async def open_published_state(
    app_id: UUID,
    state_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> StateDetail:
    async with user_connection(access.auth.user_id) as conn:
        row = await canvas_service.get_published(conn, access.workspace_id, app_id)
        return await _open(conn, row, state_id)


@published_router.delete(
    "/published-canvas-apps/{app_id}/states/{state_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_published_state(
    app_id: UUID,
    state_id: UUID,
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> None:
    async with user_connection(access.auth.user_id) as conn:
        await canvas_service.get_published(conn, access.workspace_id, app_id)
        await states_service.delete_state(conn, state_id, access.auth.user_id)
