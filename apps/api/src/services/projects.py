"""Project service (spec §4 "Projects", §16 projects / project_members).

Permission modes (§4): 'inherited' (workspace roles map through) or 'custom'
(explicit project_members entries, where role 'none' actively revokes).
Resolution itself always goes through effective_project_role (db 0005) — this
service only manages the rows that function reads.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_SLUG_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:63].strip("-")
    if not _SLUG_RE.match(slug):
        raise ValueError(f"cannot derive a valid slug from {name!r}")
    return slug


async def list_for_user(
    conn: AsyncConnection, user_id: UUID, workspace_id: UUID
) -> list[dict[str, Any]]:
    """Workspace view project grid (§5): visible projects with effective role
    from v_user_projects (db 0005) — a project with no effective role simply
    isn't in the list."""
    return await fetch_all(
        conn,
        """
        SELECT p.id, p.name, p.slug, p.description, p.permission_mode,
               v.role AS effective_role, p.created_at, p.updated_at
          FROM v_user_projects v
          JOIN projects p ON p.id = v.project_id
         WHERE v.user_id = :uid AND p.workspace_id = :wid
         ORDER BY p.name
        """,
        {"uid": str(user_id), "wid": str(workspace_id)},
    )


async def get(conn: AsyncConnection, project_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT id, workspace_id, name, slug, description, permission_mode,
               created_by, created_at, updated_at
          FROM projects WHERE id = :pid
        """,
        {"pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("project")
    return row


async def resource_counts(conn: AsyncConnection, project_id: UUID) -> dict[str, int]:
    """Sidebar badge counts (§5 project sidebar). object_types is a
    workspace-level table (the ontology is shared across a workspace), so the
    Objects badge counts the workspace ontology visible from this project —
    Flagged for review: spec shows a per-project count but defines object
    types per workspace."""
    row = await fetch_one(
        conn,
        """
        SELECT
          (SELECT count(*) FROM connections   WHERE project_id = :pid) AS connections,
          (SELECT count(*) FROM datasets      WHERE project_id = :pid) AS datasets,
          (SELECT count(*) FROM models        WHERE project_id = :pid) AS models,
          (SELECT count(*) FROM object_types ot
            WHERE ot.workspace_id = (SELECT workspace_id FROM projects WHERE id = :pid)
          ) AS objects,
          (SELECT count(*) FROM canvas_apps   WHERE project_id = :pid) AS canvas,
          (SELECT count(*) FROM code_repos    WHERE project_id = :pid) AS code
        """,
        {"pid": str(project_id)},
    )
    assert row is not None
    return {k: int(v) for k, v in row.items()}


async def create(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    name: str,
    description: str,
    created_by: UUID,
) -> dict[str, Any]:
    slug = slugify(name)
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM projects WHERE workspace_id=:wid AND slug=:slug",
        {"wid": str(workspace_id), "slug": slug},
    )
    if existing is not None:
        raise ConflictError(f"a project with slug '{slug}' already exists in this workspace")
    # Same RLS/RETURNING split as workspaces.create: the project SELECT policy
    # helper re-queries projects, which can't see rows from the current
    # command. INSERT first, read back as a later command in the same txn.
    import uuid as uuid_mod

    project_id = uuid_mod.uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO projects (id, workspace_id, name, slug, description, created_by)
            VALUES (:id, :wid, :name, :slug, :descr, :by)
            """
        ),
        {
            "id": str(project_id),
            "wid": str(workspace_id),
            "name": name,
            "slug": slug,
            "descr": description,
            "by": str(created_by),
        },
    )
    row = await fetch_one(
        conn,
        """
        SELECT id, workspace_id, name, slug, description, permission_mode,
               created_by, created_at, updated_at
          FROM projects WHERE id = :id
        """,
        {"id": str(project_id)},
    )
    assert row is not None
    return row


async def update(
    conn: AsyncConnection,
    project_id: UUID,
    *,
    name: str | None,
    description: str | None,
    permission_mode: str | None,
) -> dict[str, Any]:
    if permission_mode is not None and permission_mode not in ("inherited", "custom"):
        raise ValueError(f"invalid permission_mode {permission_mode!r}")
    row = await fetch_one(
        conn,
        """
        UPDATE projects
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description),
               permission_mode = COALESCE(CAST(:mode AS project_permission_mode), permission_mode)
         WHERE id = :pid
        RETURNING id, workspace_id, name, slug, description, permission_mode,
                  created_by, created_at, updated_at
        """,
        {"name": name, "descr": description, "mode": permission_mode, "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("project")
    return row


async def delete(conn: AsyncConnection, project_id: UUID) -> None:
    row = await fetch_one(
        conn, "DELETE FROM projects WHERE id=:pid RETURNING id", {"pid": str(project_id)}
    )
    if row is None:
        raise NotFoundError("project")


# ---- custom permissions -----------------------------------------------------
async def list_members(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT pm.id, pm.role, pm.added_at AS created_at,
               u.id AS user_id, u.email, u.display_name,
               g.id AS group_id, g.name AS group_name
          FROM project_members pm
          LEFT JOIN users u  ON u.id = pm.user_id
          LEFT JOIN groups g ON g.id = pm.group_id
         WHERE pm.project_id = :pid
         ORDER BY pm.added_at
        """,
        {"pid": str(project_id)},
    )


async def set_member(
    conn: AsyncConnection,
    project_id: UUID,
    *,
    workspace_id: UUID,
    user_id: UUID | None,
    group_id: UUID | None,
    role: str,
) -> dict[str, Any]:
    """Upsert a custom permission entry. Role 'none' is a real entry — it
    revokes access even when workspace roles or groups would grant it (§4)."""
    if (user_id is None) == (group_id is None):
        raise ValueError("exactly one of user_id or group_id is required")
    if role not in ("owner", "editor", "viewer", "none"):
        raise ValueError(f"invalid project role {role!r}")

    # Principal must share the organisation of the workspace this project
    # lives in (cross-org grants impossible; §10).
    org_row = await fetch_one(
        conn,
        "SELECT organisation_id FROM workspaces WHERE id = :wid",
        {"wid": str(workspace_id)},
    )
    if org_row is None:
        raise NotFoundError("workspace")
    org_id = org_row["organisation_id"]
    if user_id is not None:
        ok = await fetch_one(
            conn,
            "SELECT 1 AS x FROM users WHERE id=:id AND organisation_id=:org",
            {"id": str(user_id), "org": str(org_id)},
        )
    else:
        ok = await fetch_one(
            conn,
            "SELECT 1 AS x FROM groups WHERE id=:id AND organisation_id=:org",
            {"id": str(group_id), "org": str(org_id)},
        )
    if ok is None:
        raise NotFoundError("user or group")

    if user_id is not None:
        row = await fetch_one(
            conn,
            """
            INSERT INTO project_members (project_id, user_id, role)
            VALUES (:pid, :uid, :role)
            ON CONFLICT (project_id, user_id) WHERE user_id IS NOT NULL
            DO UPDATE SET role = EXCLUDED.role
            RETURNING id, project_id, user_id, group_id, role, added_at AS created_at
            """,
            {"pid": str(project_id), "uid": str(user_id), "role": role},
        )
    else:
        row = await fetch_one(
            conn,
            """
            INSERT INTO project_members (project_id, group_id, role)
            VALUES (:pid, :gid, :role)
            ON CONFLICT (project_id, group_id) WHERE group_id IS NOT NULL
            DO UPDATE SET role = EXCLUDED.role
            RETURNING id, project_id, user_id, group_id, role, added_at AS created_at
            """,
            {"pid": str(project_id), "gid": str(group_id), "role": role},
        )
    assert row is not None
    return row


async def remove_member(conn: AsyncConnection, project_id: UUID, member_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM project_members WHERE id=:mid AND project_id=:pid RETURNING id",
        {"mid": str(member_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("project member")
