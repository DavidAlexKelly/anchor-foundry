"""Tags, and the resources that carry them (§511; db 0105).

    "About: Information including … tags, and more." (`dataset-preview` p.3)

    "You can create and manage tags from the Tags section of Platform
     Settings. Once they are created, they can be added … in the filesystem."
     (`app-building` p.35)

A tag is made once for the workspace and applied to many resources. Who may
make one and who may apply one is the route's (it knows the role); what is
visible is the database's (db 0105's policies).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_COLUMNS = "t.id, t.category, t.name, t.created_at"


def _clean(value: str) -> str:
    """Inner runs of space are one space and the ends are trimmed, so " PII "
    and "PII" are the same tag rather than two that look alike."""
    return " ".join(value.split())


def _taken(category: str, name: str) -> ConflictError:
    where = f" in {category!r}" if category else ""
    return ConflictError(f"there is already a tag called {name!r}{where}")


async def list_tags(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    """Every tag in the workspace, grouped by category, with how many
    resources the caller can see carry it."""
    return await fetch_all(conn, f"""
        SELECT {_COLUMNS}, count(l.resource_id)::int AS uses
          FROM resource_tags t
          LEFT JOIN resource_tag_links l ON l.tag_id = t.id
         WHERE t.workspace_id = :wid
         GROUP BY t.id
         ORDER BY lower(t.category), lower(t.name)
    """, {"wid": str(workspace_id)})


async def create_tag(
    conn: AsyncConnection, workspace_id: UUID, *, category: str, name: str, by: UUID,
) -> dict[str, Any]:
    category, name = _clean(category), _clean(name)
    try:
        async with conn.begin_nested():
            row = await fetch_one(conn, """
                INSERT INTO resource_tags (workspace_id, category, name, created_by)
                VALUES (:wid, :cat, :name, :by)
                RETURNING id, category, name, created_at
            """, {"wid": str(workspace_id), "cat": category, "name": name, "by": str(by)})
    except IntegrityError as exc:
        raise _taken(category, name) from exc
    return {**row, "uses": 0}


async def update_tag(
    conn: AsyncConnection, workspace_id: UUID, tag_id: UUID, *, category: str, name: str,
) -> dict[str, Any]:
    """Renaming a tag renames it everywhere, which is why a tag is a row."""
    category, name = _clean(category), _clean(name)
    try:
        async with conn.begin_nested():
            row = await fetch_one(conn, """
                UPDATE resource_tags SET category = :cat, name = :name
                 WHERE id = :id AND workspace_id = :wid
                RETURNING id
            """, {"id": str(tag_id), "wid": str(workspace_id), "cat": category, "name": name})
    except IntegrityError as exc:
        raise _taken(category, name) from exc
    if row is None:
        raise NotFoundError("tag")
    return next(t for t in await list_tags(conn, workspace_id) if t["id"] == row["id"])


async def delete_tag(conn: AsyncConnection, workspace_id: UUID, tag_id: UUID) -> None:
    row = await fetch_one(conn, """
        DELETE FROM resource_tags WHERE id = :id AND workspace_id = :wid RETURNING id
    """, {"id": str(tag_id), "wid": str(workspace_id)})
    if row is None:
        raise NotFoundError("tag")


async def tags_on(conn: AsyncConnection, resource_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(conn, f"""
        SELECT {_COLUMNS}
          FROM resource_tag_links l JOIN resource_tags t ON t.id = l.tag_id
         WHERE l.resource_id = :rid
         ORDER BY lower(t.category), lower(t.name)
    """, {"rid": str(resource_id)})


async def add(conn: AsyncConnection, resource_id: UUID, tag_id: UUID, *, by: UUID) -> None:
    """Idempotent: a tag already on the resource stays on, once."""
    tag = await fetch_one(conn, """
        SELECT 1 FROM resource_tags t JOIN resources r ON r.workspace_id = t.workspace_id
         WHERE t.id = :tid AND r.id = :rid
    """, {"tid": str(tag_id), "rid": str(resource_id)})
    # A tag from another workspace is as absent as one that does not exist.
    if tag is None:
        raise NotFoundError("tag")
    await conn.execute(text(
        "INSERT INTO resource_tag_links (resource_id, tag_id, added_by) VALUES (:rid, :tid, :by)"
        " ON CONFLICT DO NOTHING"), {"rid": str(resource_id), "tid": str(tag_id), "by": str(by)})


async def remove(conn: AsyncConnection, resource_id: UUID, tag_id: UUID) -> None:
    await conn.execute(text(
        "DELETE FROM resource_tag_links WHERE resource_id = :rid AND tag_id = :tid"),
        {"rid": str(resource_id), "tid": str(tag_id)})
