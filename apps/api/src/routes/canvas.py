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

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..lib.db import user_connection
from ..lib.errors import ForbiddenError, NotFoundError
from ..middleware.permissions import ProjectAccess, WorkspaceAccess, require_project_role, require_workspace_role
from ..services import actions as actions_service
from ..services import audit
from ..services import canvas as canvas_service
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


class EvaluateVariablesOut(BaseModel):
    values: dict[str, Any]
    order: list[str]


def _out(row: dict[str, Any]) -> CanvasAppDetail:
    return CanvasAppDetail(**{**row, "definition": _parse_json(row["definition"])})


def _summary(row: dict[str, Any]) -> CanvasAppOut:
    return CanvasAppOut(**row)


# ---- project-scoped CRUD ------------------------------------------------------
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
        if target.kind != "single_object":
            raise variables_service.VariableError(
                f"a loop gives {child_name!r} one object at a time, so "
                f"{embed.item_external_id!r} has to be a single_object and it is a "
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
            variables_service.validate_module(body.definition, actions=known)
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
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(document)
    except variables_service.VariableError as exc:
        # A saved app whose document no longer validates. Reachable: the module
        # could have been written before a rule existed, or by something other
        # than this API. Reported rather than swallowed, because the viewer
        # otherwise sees widgets quietly bound to nothing.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    try:
        resolved = variables_service.evaluate(
            variables, body.values, bound=frozenset(body.bound)
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
        values=resolved, order=variables_service.evaluation_order(variables)
    )


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


# ---- workspace-wide read path for published apps ------------------------------
@published_router.get("/published-canvas-apps", response_model=list[CanvasAppOut])
async def list_published_apps(
    access: WorkspaceAccess = Depends(require_workspace_role("viewer")),
) -> list[CanvasAppOut]:
    async with user_connection(access.auth.user_id) as conn:
        rows = await canvas_service.list_published(conn, access.workspace_id)
    return [_summary(r) for r in rows]


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
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(document)
    except variables_service.VariableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    try:
        resolved = variables_service.evaluate(
            variables, body.values, bound=frozenset(body.bound)
        )
    except variables_service.VariableError as exc:
        # The values, not the document - see the note on the project-scoped one.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return EvaluateVariablesOut(
        values=resolved, order=variables_service.evaluation_order(variables)
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


def _module_variables(row: dict[str, Any]) -> dict[str, Any]:
    """This module's variables, and a refusal if it does not save state.

    Checked on every path rather than only on the write: a state saved while
    the feature was on, and opened after it was turned off, is a view the
    module no longer offers - and restoring it silently would be the module
    disagreeing with its own settings.
    """
    document = _parse_json(row["definition"])
    try:
        variables = variables_service.validate_module(document)
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
