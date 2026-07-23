"""Canvas apps — the low-code app builder (spec §11 "Canvas": widgets bound
to objects — tables, charts, forms with write-back; spec §5 "Publishing":
private / workspace / specific groups).

An app's ``definition`` is an opaque JSON blob to this layer — a Craft.js
node tree (per db 0003's comment) the frontend builder produces and
interprets; this service only stores, versions, and gates visibility on it,
the same "backend doesn't understand widget semantics" split routes/actions.py
already takes with ``submitted_values``. Rendering (tables, object instances,
write-back forms) reuses the datasets/objects/actions endpoints already
built — no new data-access surface is needed for a widget to read or write
through; Canvas only needs to remember which widgets exist and how they're
arranged.

Publishing to the workspace or to specific groups requires the workspace
admin role (enforced at the route layer, mirroring routes/connections.py's
workspace-scoped connections) — both expose project data beyond the
project's own membership, so both get the same conservative bar. A plain
project editor can always keep an app private and edit it freely.

Schema (migration 0003, already applied — this session only starts using
it): canvas_apps, canvas_app_versions (one row per save), canvas_app_shares
(group targets when publish_scope='groups'). RLS (0006, recursion-fixed in
0009) additionally allows a workspace member to see a published app without
project membership; ``get_published``/``list_published`` below are the
counterpart read paths for that case, filtering to publish_scope <> 'private'
explicitly rather than trusting RLS alone (RLS also lets the app's own
project members through the same query).
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
MAX_DEFINITION_BYTES = 2 * 1024 * 1024  # flag: conservative day-one cap on a saved layout

_COLUMNS = """
    id, project_id, name, slug, description, current_version,
    publish_scope, published_at, created_at, updated_at
"""


def slugify(name: str) -> str:
    """canvas_apps.slug allows only [a-z0-9-] — no underscore, unlike
    datasets' slug — so this can't reuse services/datasets.py's slugify."""
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


# ---- project-scoped CRUD -----------------------------------------------------
async def list_for_project(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM canvas_apps WHERE project_id = :pid ORDER BY name",
        {"pid": str(project_id)},
    )
    return [dict(r) for r in rows]


async def get(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS}, definition FROM canvas_apps WHERE id = :aid AND project_id = :pid",
        {"aid": str(app_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")
    return dict(row)


async def create(
    conn: AsyncConnection, *, project_id: UUID, name: str, description: str, created_by: UUID
) -> dict[str, Any]:
    slug = slugify(name)
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM canvas_apps WHERE project_id=:pid AND slug=:slug",
        {"pid": str(project_id), "slug": slug},
    )
    if existing is not None:
        raise ConflictError(f"an app named {slug!r} already exists in this project")
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO canvas_apps (project_id, name, slug, description, created_by)
        VALUES (:pid, :name, :slug, :descr, :by)
        RETURNING {_COLUMNS}, definition
        """,
        {
            "pid": str(project_id), "name": name, "slug": slug,
            "descr": description, "by": str(created_by),
        },
    )
    assert row is not None
    return dict(row)


async def update_metadata(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    name: str | None,
    description: str | None,
) -> dict[str, Any]:
    await get(conn, project_id, app_id)  # 404 if invisible
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description)
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"name": name, "descr": description, "aid": str(app_id)},
    )
    assert row is not None
    return dict(row)


async def delete(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM canvas_apps WHERE id=:aid AND project_id=:pid RETURNING id",
        {"aid": str(app_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")


# ---- definition versioning ----------------------------------------------------
async def save_definition(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    definition: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    existing = await get(conn, project_id, app_id)
    payload = json.dumps(definition)
    if len(payload) > MAX_DEFINITION_BYTES:
        raise ValueError(f"layout exceeds the {MAX_DEFINITION_BYTES // (1024 * 1024)} MB size limit")
    version = int(existing["current_version"]) + 1
    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET definition = CAST(:def AS jsonb), current_version = :version
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"def": payload, "version": version, "aid": str(app_id)},
    )
    assert row is not None
    await fetch_one(
        conn,
        """
        INSERT INTO canvas_app_versions (canvas_app_id, version_number, definition, created_by)
        VALUES (:aid, :version, CAST(:def AS jsonb), :by)
        RETURNING id
        """,
        {"aid": str(app_id), "version": version, "def": payload, "by": str(created_by)},
    )
    return dict(row)


async def list_versions(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> list[dict[str, Any]]:
    await get(conn, project_id, app_id)
    return await fetch_all(
        conn,
        """
        SELECT id, version_number, created_by, created_at
          FROM canvas_app_versions
         WHERE canvas_app_id = :aid
         ORDER BY version_number DESC
        """,
        {"aid": str(app_id)},
    )


# ---- publishing ---------------------------------------------------------------
async def set_publish_scope(
    conn: AsyncConnection,
    project_id: UUID,
    app_id: UUID,
    *,
    organisation_id: UUID,
    scope: str,
    group_ids: list[UUID] | None,
) -> dict[str, Any]:
    await get(conn, project_id, app_id)  # 404 if invisible
    if scope == "groups":
        if not group_ids:
            raise ValueError("choose at least one group to publish to")
        rows = await fetch_all(
            conn,
            "SELECT id FROM groups WHERE organisation_id = :org AND id = ANY(:ids)",
            {"org": str(organisation_id), "ids": [str(g) for g in group_ids]},
        )
        found = {str(r["id"]) for r in rows}
        unknown = [str(g) for g in group_ids if str(g) not in found]
        if unknown:
            raise ValueError(f"unknown group(s): {', '.join(unknown)}")

    row = await fetch_one(
        conn,
        f"""
        UPDATE canvas_apps
           SET publish_scope = CAST(:scope AS app_publish_scope),
               published_at = CASE WHEN :scope = 'private' THEN NULL
                                    ELSE COALESCE(published_at, now()) END
         WHERE id = :aid
        RETURNING {_COLUMNS}, definition
        """,
        {"scope": scope, "aid": str(app_id)},
    )
    assert row is not None
    await conn.execute(
        text("DELETE FROM canvas_app_shares WHERE canvas_app_id = :aid"), {"aid": str(app_id)}
    )
    if scope == "groups":
        assert group_ids is not None
        for group_id in group_ids:
            await conn.execute(
                text(
                    "INSERT INTO canvas_app_shares (canvas_app_id, group_id) VALUES (:aid, :gid)"
                ),
                {"aid": str(app_id), "gid": str(group_id)},
            )
    return dict(row)


async def list_shares(conn: AsyncConnection, project_id: UUID, app_id: UUID) -> list[dict[str, Any]]:
    await get(conn, project_id, app_id)
    return await fetch_all(
        conn,
        """
        SELECT s.group_id, g.name AS group_name
          FROM canvas_app_shares s JOIN groups g ON g.id = s.group_id
         WHERE s.canvas_app_id = :aid
         ORDER BY g.name
        """,
        {"aid": str(app_id)},
    )


# ---- workspace-wide read path for published apps ------------------------------
async def list_published(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    """Apps visible to any workspace member regardless of project
    membership — the counterpart to list_for_project for a "gallery of apps
    shared with me" view. Scoped via rls_project_workspace_id (db 0015)
    rather than a subquery against `projects` directly: `projects` is
    itself RLS-protected, and a permission_mode='custom' project can
    legitimately hide its own row from a user this endpoint exists to
    serve — the SECURITY DEFINER helper resolves the workspace_id without
    depending on that visibility. RLS still independently enforces
    group-share membership for publish_scope='groups' rows."""
    rows = await fetch_all(
        conn,
        f"""
        SELECT {_COLUMNS} FROM canvas_apps
         WHERE publish_scope <> 'private'
           AND rls_project_workspace_id(project_id) = :wid
         ORDER BY name
        """,
        {"wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def get_published(conn: AsyncConnection, workspace_id: UUID, app_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""
        SELECT {_COLUMNS}, definition FROM canvas_apps
         WHERE id = :aid AND publish_scope <> 'private'
           AND rls_project_workspace_id(project_id) = :wid
        """,
        {"aid": str(app_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("canvas app")
    return dict(row)
