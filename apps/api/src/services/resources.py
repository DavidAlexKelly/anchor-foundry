"""The resource registry - one list of everything in a project, regardless of
kind (ROADMAP.md phase 2, section 0 item 1).

This service reads migration 0032's `resources` table and nothing else. It is
deliberately thin: the registry holds only what is true of every resource
(identity, location, name, lifecycle), so there is nothing here to interpret.
A caller who wants to know a dataset's row count asks the datasets service;
what this answers is "what is in this project, and what kind is each thing".

Why it is a table read and not six
----------------------------------
The obvious alternative - UNION the six kind tables at query time - avoids the
mirrored name in 0032 and cannot answer the browser's actual questions. Sorting
by name across a UNION cannot use an index; neither can a substring search;
paginating one means materialising all of them. The registry exists so that the
query which runs on every project open is a single indexed scan.

Ordering and paging are the API's, not the caller's
---------------------------------------------------
`sort` and `direction` are matched against an allowlist and interpolated only
after matching. That is not paranoia about this caller: it is that an ORDER BY
built from a query string is the exact shape of the bug that is invisible in
tests written by the person who added it.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

# Every kind the registry knows. Mirrors the `resource_kind` enum; a kind that
# is in the database and not here would be silently unfilterable.
KINDS = ("connection", "dataset", "model", "object_type", "canvas_app", "code_repo")

# The browser caps at 200 for the same reason the object explorer does
# (STATUS.md §37): a page nobody scrolls is a query nobody should have run.
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

_SORTS = {
    "updated_at": "updated_at",
    "created_at": "created_at",
    "name": "lower(name)",
    "kind": "kind",
}

_COLUMNS = """
    id, workspace_id, project_id, kind::text AS kind, name, description,
    created_by, created_at, updated_at
"""


def _escape_like(term: str) -> str:
    """A search for "a_b" means "a_b", not "a<anything>b"."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def list_for_project(
    conn: AsyncConnection,
    workspace_id: UUID,
    project_id: UUID,
    *,
    kinds: list[str] | None = None,
    search: str | None = None,
    sort: str = "updated_at",
    direction: str = "desc",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    include_workspace_level: bool = False,
) -> dict[str, Any]:
    """Resources in a project, newest first by default.

    `include_workspace_level` additionally returns the resources that do not
    live in any project - object types, and connections shared across the
    workspace. They are off by default because a project browser that silently
    mixes in things belonging to a different scope is how the first-run
    checklist came to tick a step in an empty project (STATUS.md §44). A caller
    that wants them has to say so, and the rows carry `project_id: null` so the
    UI can say so too.
    """
    if sort not in _SORTS:
        raise ValueError(f"cannot sort by {sort!r} (try one of: {', '.join(sorted(_SORTS))})")
    if direction not in ("asc", "desc"):
        raise ValueError(f"sort direction must be 'asc' or 'desc', not {direction!r}")
    if kinds:
        unknown = [k for k in kinds if k not in KINDS]
        if unknown:
            raise ValueError(f"unknown resource kind(s): {', '.join(unknown)}")
    limit = max(1, min(limit, MAX_LIMIT))
    offset = max(0, offset)

    where = ["trashed_at IS NULL"]
    params: dict[str, Any] = {"pid": str(project_id), "wid": str(workspace_id)}
    if include_workspace_level:
        where.append("(project_id = :pid OR (project_id IS NULL AND workspace_id = :wid))")
    else:
        where.append("project_id = :pid")
    if kinds:
        # Cast rather than bind an enum array: the same AmbiguousParameter that
        # bit the code proposal filter (STATUS.md §46) is one step away here.
        where.append("kind::text = ANY(:kinds)")
        params["kinds"] = list(kinds)
    if search and search.strip():
        where.append("name ILIKE :q ESCAPE '\\'")
        params["q"] = f"%{_escape_like(search.strip())}%"

    clause = " AND ".join(where)
    total = await fetch_one(conn, f"SELECT count(*) AS n FROM resources WHERE {clause}", params)
    rows = await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM resources WHERE {clause} "
        # id is the tiebreak so paging is stable when many rows share a
        # timestamp - without it, page 2 can repeat a row from page 1.
        f"ORDER BY {_SORTS[sort]} {direction.upper()}, id "
        "LIMIT :limit OFFSET :offset",
        {**params, "limit": limit, "offset": offset},
    )
    return {
        "resources": [dict(r) for r in rows],
        "total": int(total["n"]) if total else 0,
        "limit": limit,
        "offset": offset,
    }


async def get(conn: AsyncConnection, resource_id: UUID) -> dict[str, Any] | None:
    """One resource by id, or None. RLS decides visibility, so a resource in a
    project the caller cannot reach is indistinguishable from one that does not
    exist - which is the intended answer, not a limitation."""
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS}, trashed_at FROM resources WHERE id = :rid",
        {"rid": str(resource_id)},
    )
    return dict(row) if row else None


async def resolve(conn: AsyncConnection, resource_id: UUID) -> dict[str, Any] | None:
    """One resource by id, with enough of its location to draw a breadcrumb.

    This is what `/r/{id}` resolves against, and the reason resource ids exist
    at all: a link built from a workspace and project slug stops working the
    moment somebody renames either, which is precisely when a shared link is
    most likely to be clicked.

    A trashed resource resolves rather than 404s, and says it is trashed. A
    link to something that has been deleted should say so - answering "no such
    thing" for a resource that demonstrably existed sends the person who
    followed the link looking for a typo.
    """
    row = await fetch_one(
        conn,
        """
        SELECT r.id, r.workspace_id, r.project_id, r.kind::text AS kind,
               r.name, r.description, r.created_by, r.created_at, r.updated_at,
               r.trashed_at IS NOT NULL AS trashed,
               w.slug AS workspace_slug, w.name AS workspace_name,
               p.slug AS project_slug, p.name AS project_name
          FROM resources r
          JOIN workspaces w ON w.id = r.workspace_id
          LEFT JOIN projects p ON p.id = r.project_id
         WHERE r.id = :rid
        """,
        {"rid": str(resource_id)},
    )
    return dict(row) if row else None


async def counts_for_project(
    conn: AsyncConnection, project_id: UUID
) -> dict[str, int]:
    """Per-kind counts, for the browser's filter chips. Every kind is present
    with a zero rather than absent, so the UI does not have to distinguish
    "none of these" from "this kind does not exist"."""
    rows = await fetch_all(
        conn,
        "SELECT kind::text AS kind, count(*) AS n FROM resources "
        "WHERE project_id = :pid AND trashed_at IS NULL GROUP BY kind",
        {"pid": str(project_id)},
    )
    counts = {kind: 0 for kind in KINDS}
    counts.update({r["kind"]: int(r["n"]) for r in rows})
    return counts
