"""Workspace service (spec §4 "Workspaces", §8 isolation, §16 workspaces /
workspace_members).

Isolation anchors are generated here at creation time — s3 prefix, pg schema,
search prefix — and are immutable afterwards (db trigger 0002). The dedicated
``ws_*`` PostgreSQL schema is provisioned in the same transaction via
``provision_workspace_schema`` so a workspace can never exist half-isolated.
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


def isolation_anchors(workspace_id: UUID, slug: str) -> tuple[str, str, str]:
    """Spec §8 formats. Keyed on the immutable id (not slug) so a future
    rename feature can't collide anchors; slug kept in the s3 prefix for
    human-readable bucket listings."""
    short = workspace_id.hex[:12]
    return (
        f"workspaces/{slug}-{short}/",       # s3_prefix
        f"ws_{short}",                        # pg_schema (matches ^ws_[a-z0-9_]+$)
        f"ws-{short}-",                       # search_prefix (indexes ws-{id}-*)
    )


async def list_for_user(conn: AsyncConnection, user_id: UUID) -> list[dict[str, Any]]:
    """Home screen grid (§5): only workspaces the user can access, with their
    effective role — straight from the v_user_workspaces view (db 0005)."""
    return await fetch_all(
        conn,
        """
        SELECT v.workspace_id AS id, w.name, w.slug, w.description, v.role AS effective_role,
               w.created_at,
               (SELECT count(*) FROM projects p WHERE p.workspace_id = w.id) AS project_count
          FROM v_user_workspaces v
          JOIN workspaces w ON w.id = v.workspace_id
         WHERE v.user_id = :uid
         ORDER BY w.name
        """,
        {"uid": str(user_id)},
    )


async def get(conn: AsyncConnection, workspace_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT id, organisation_id, name, slug, description, s3_prefix, pg_schema,
               search_prefix, created_by, created_at, updated_at
          FROM workspaces WHERE id = :wid
        """,
        {"wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("workspace")
    return row


async def create(
    conn: AsyncConnection,
    *,
    organisation_id: UUID,
    name: str,
    description: str,
    created_by: UUID,
) -> dict[str, Any]:
    import uuid as uuid_mod

    slug = slugify(name)
    workspace_id = uuid_mod.uuid4()
    s3_prefix, pg_schema, search_prefix = isolation_anchors(workspace_id, slug)

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM workspaces WHERE organisation_id=:org AND slug=:slug",
        {"org": str(organisation_id), "slug": slug},
    )
    if existing is not None:
        raise ConflictError(f"a workspace with slug '{slug}' already exists")

    # INSERT and read-back are separate commands deliberately: RETURNING would
    # require the new row to pass the SELECT policy, whose helper re-queries
    # workspaces — and rows from the current command aren't visible to it yet
    # (PostgreSQL command-id visibility). The follow-up SELECT runs as a later
    # command in the same transaction, where the row is visible and the policy
    # evaluates correctly.
    await conn.execute(
        text(
            """
            INSERT INTO workspaces (id, organisation_id, name, slug, description,
                                    s3_prefix, pg_schema, search_prefix, created_by)
            VALUES (:id, :org, :name, :slug, :descr, :s3, :pg, :search, :by)
            """
        ),
        {
            "id": str(workspace_id),
            "org": str(organisation_id),
            "name": name,
            "slug": slug,
            "descr": description,
            "s3": s3_prefix,
            "pg": pg_schema,
            "search": search_prefix,
            "by": str(created_by),
        },
    )
    row = await fetch_one(
        conn,
        """
        SELECT id, organisation_id, name, slug, description, s3_prefix,
               pg_schema, search_prefix, created_by, created_at, updated_at
          FROM workspaces WHERE id = :id
        """,
        {"id": str(workspace_id)},
    )
    assert row is not None  # visible to this later command in the same txn
    # Same transaction: workspace row + its isolated pg schema are atomic.
    await fetch_one(conn, "SELECT provision_workspace_schema(:wid) AS s", {"wid": str(workspace_id)})
    return row


async def update(
    conn: AsyncConnection, workspace_id: UUID, *, name: str | None, description: str | None
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        UPDATE workspaces
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description)
         WHERE id = :wid
        RETURNING id, organisation_id, name, slug, description, created_at, updated_at
        """,
        {"name": name, "descr": description, "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("workspace")
    return row


async def delete(conn: AsyncConnection, workspace_id: UUID) -> None:
    # FK cascades remove members/projects/resources. The ws_* pg schema and
    # S3 prefix are cleaned up by an async worker job, not inline — dropping
    # customer data synchronously in a request is deliberately avoided.
    # Flagged for review: spec is silent on deletion semantics; conservative
    # choice is soft-latency cleanup with the row removal as the commit point.
    result = await fetch_one(
        conn, "DELETE FROM workspaces WHERE id = :wid RETURNING id", {"wid": str(workspace_id)}
    )
    if result is None:
        raise NotFoundError("workspace")


# ---- members ----------------------------------------------------------------
async def list_members(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT wm.id, wm.role, wm.added_at AS created_at,
               u.id AS user_id, u.email, u.display_name,
               g.id AS group_id, g.name AS group_name
          FROM workspace_members wm
          LEFT JOIN users u  ON u.id = wm.user_id
          LEFT JOIN groups g ON g.id = wm.group_id
         WHERE wm.workspace_id = :wid
         ORDER BY wm.added_at
        """,
        {"wid": str(workspace_id)},
    )


async def add_member(
    conn: AsyncConnection,
    workspace_id: UUID,
    *,
    organisation_id: UUID,
    user_id: UUID | None,
    group_id: UUID | None,
    role: str,
) -> dict[str, Any]:
    if (user_id is None) == (group_id is None):
        raise ValueError("exactly one of user_id or group_id is required")
    if role not in ("admin", "editor", "viewer"):
        raise ValueError(f"invalid workspace role {role!r}")

    # The principal must belong to the same organisation — cross-org grants
    # are impossible by construction (§10 tenant isolation).
    if user_id is not None:
        principal = await fetch_one(
            conn,
            "SELECT 1 AS x FROM users WHERE id=:id AND organisation_id=:org",
            {"id": str(user_id), "org": str(organisation_id)},
        )
    else:
        principal = await fetch_one(
            conn,
            "SELECT 1 AS x FROM groups WHERE id=:id AND organisation_id=:org",
            {"id": str(group_id), "org": str(organisation_id)},
        )
    if principal is None:
        raise NotFoundError("user or group")

    row = await fetch_one(
        conn,
        """
        INSERT INTO workspace_members (workspace_id, user_id, group_id, role)
        VALUES (:wid, :uid, :gid, :role)
        ON CONFLICT DO NOTHING
        RETURNING id, workspace_id, user_id, group_id, role, added_at AS created_at
        """,
        {
            "wid": str(workspace_id),
            "uid": str(user_id) if user_id else None,
            "gid": str(group_id) if group_id else None,
            "role": role,
        },
    )
    if row is None:
        raise ConflictError("principal is already a member of this workspace")
    return row


async def update_member_role(
    conn: AsyncConnection, workspace_id: UUID, member_id: UUID, role: str
) -> dict[str, Any]:
    if role not in ("admin", "editor", "viewer"):
        raise ValueError(f"invalid workspace role {role!r}")
    row = await fetch_one(
        conn,
        """
        UPDATE workspace_members SET role = :role
         WHERE id = :mid AND workspace_id = :wid
        RETURNING id, workspace_id, user_id, group_id, role, added_at AS created_at
        """,
        {"role": role, "mid": str(member_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("workspace member")
    return row


async def remove_member(conn: AsyncConnection, workspace_id: UUID, member_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM workspace_members WHERE id=:mid AND workspace_id=:wid RETURNING id",
        {"mid": str(member_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("workspace member")
