"""Configured Object Views (parity `docs/parity/ontology.md` §4.2; Foundry
`object-views` p.2-4).

> "Configured Object Views are fully customizable representations of an object
> built using Workshop." (p.2)

**A view is a pointer at a module, not a document of its own** (migration
0046). The module already has a layout, variables, events, versions,
publishing and a changelog; a configured view that re-declared any of those
would be a second Workshop with one feature.

**The whole binding is one variable.** A standard view is generated from the
object type and takes no input. A configured view is a module, and a module
takes input through its variables, so this names the `single_object` variable
that receives the object being looked at. Checked here, at save time, against
the module's own document - the same place and for the same reason an action
rule's property is checked against its object type: the refusal belongs where
somebody can still fix it, not in front of a viewer who did not write it.

**Nothing here can hide the standard view.** p.2: standard views "remain
accessible even after a configured Object View is built". That is a rule about
the reader and it is enforced by there being no way to express the opposite -
no `replace` flag, no delete of the generated view, nothing to turn off.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError

FORM_FACTORS = ("full", "panel")

_COLUMNS = (
    "v.id, v.workspace_id, v.object_type_id, v.canvas_app_id, "
    "CAST(v.form_factor AS text) AS form_factor, v.subject_variable, "
    "v.created_at, v.updated_at"
)


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def subject_candidates(definition: Any) -> dict[str, str]:
    """The module variables that could receive the object, id -> label.

    `single_object` only: that is the kind that holds "the object somebody
    picked" (§84), and it is what every widget reading an object already
    expects. An object *set* variable would make the view about a collection,
    which is a different screen, and a string one would hold a primary key -
    which is not what the widgets look an instance up by.
    """
    document = _json(definition) or {}
    variables = document.get("variables") or {}
    if not isinstance(variables, dict):
        return {}
    return {
        str(variable["id"]): str(variable.get("label") or variable["id"])
        for variable in variables.values()
        if isinstance(variable, dict)
        and variable.get("id")
        and str(variable.get("kind")) == "single_object"
    }


async def get_view(
    conn: AsyncConnection,
    workspace_id: UUID,
    object_type_id: UUID,
    *,
    form_factor: str = "full",
) -> dict[str, Any] | None:
    """The configured view for a type, or None.

    None rather than a 404 on purpose: "does this type have a configured view"
    is a question every object screen asks on the way to rendering *something*,
    and the answer "no" is the common case, not an error.
    """
    row = await fetch_one(
        conn,
        f"""
        SELECT {_COLUMNS}, a.name AS canvas_app_name, a.publish_scope
          FROM object_type_views v
          JOIN canvas_apps a ON a.id = v.canvas_app_id
         WHERE v.workspace_id = :wid
           AND v.object_type_id = :tid
           AND v.form_factor = CAST(:ff AS object_view_form_factor)
        """,
        {"wid": str(workspace_id), "tid": str(object_type_id), "ff": form_factor},
    )
    return dict(row) if row else None


async def list_views(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    """Every configured view in the workspace, for the Ontology Manager's list."""
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_COLUMNS}, a.name AS canvas_app_name, a.publish_scope
          FROM object_type_views v
          JOIN canvas_apps a ON a.id = v.canvas_app_id
         WHERE v.workspace_id = :wid
         ORDER BY v.created_at
        """,
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def set_view(
    conn: AsyncConnection,
    workspace_id: UUID,
    object_type_id: UUID,
    *,
    canvas_app_id: UUID,
    subject_variable: str,
    form_factor: str = "full",
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Point an object type at a module, refusing every binding that could not render.

    Four refusals, and each one is a screen somebody would otherwise reach
    before finding out:

      * a form factor this build does not have;
      * a module this workspace cannot see - the trigger in 0046 would refuse
        it too, but as a database exception rather than a sentence;
      * a module that is not published, because an object view is read by
        whoever can read the object, and an unpublished module is readable only
        inside its own project. A view somebody cannot open is not a view;
      * a `subject_variable` that is not a `single_object` variable of *that*
        module, which is the binding itself.
    """
    if form_factor not in FORM_FACTORS:
        raise ValueError(f"unknown object view form factor {form_factor!r}")
    app = await fetch_one(
        conn,
        """
        SELECT id, name, definition, publish_scope
          FROM canvas_apps
         WHERE id = :aid AND rls_project_workspace_id(project_id) = :wid
        """,
        {"aid": str(canvas_app_id), "wid": str(workspace_id)},
    )
    if app is None:
        raise NotFoundError("canvas app")
    if str(app["publish_scope"]) == "private":
        raise ValueError(
            "publish this module before making it an object view - an object view is read "
            "by whoever can read the object, and an unpublished module is readable only "
            "inside its own project"
        )
    candidates = subject_candidates(app["definition"])
    if subject_variable not in candidates:
        raise ValueError(
            f"{subject_variable!r} is not a single-object variable of this module - "
            "an object view needs one to receive the object being viewed"
        )

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO object_type_views
            (workspace_id, object_type_id, canvas_app_id, form_factor,
             subject_variable, created_by)
        VALUES (:wid, :tid, :aid, CAST(:ff AS object_view_form_factor), :sv, :by)
        ON CONFLICT (object_type_id, form_factor) DO UPDATE
            SET canvas_app_id = EXCLUDED.canvas_app_id,
                subject_variable = EXCLUDED.subject_variable
        RETURNING {_COLUMNS.replace('v.', '')}
        """,
        {
            "wid": str(workspace_id), "tid": str(object_type_id),
            "aid": str(canvas_app_id), "ff": form_factor,
            "sv": subject_variable, "by": str(created_by) if created_by else None,
        },
    )
    assert row is not None
    return {**dict(row), "canvas_app_name": app["name"], "publish_scope": app["publish_scope"]}


async def clear_view(
    conn: AsyncConnection,
    workspace_id: UUID,
    object_type_id: UUID,
    *,
    form_factor: str = "full",
) -> None:
    """Stop using a module as this type's view.

    Not a deletion of anything a person made - the module is untouched and
    still opens as an app. What goes is the pointer, and what comes back is the
    standard view, which never went anywhere.
    """
    result = await conn.execute(
        text(
            """
            DELETE FROM object_type_views
             WHERE workspace_id = :wid AND object_type_id = :tid
               AND form_factor = CAST(:ff AS object_view_form_factor)
            """
        ),
        {"wid": str(workspace_id), "tid": str(object_type_id), "ff": form_factor},
    )
    if result.rowcount == 0:
        raise NotFoundError("object view")
