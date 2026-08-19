"""Object type groups (Foundry ``object-link-types`` p.261-263).

> "Object type groups are a classification primitive that help users better
> search and explore their ontology." (p.261)

**A group is a way of finding object types, and nothing else.** It carries no
properties, no datasource and no behaviour; p.262 lists its whole purpose as
three places it shows up - the search bar, a filterable column in the Ontology
Manager's table of object types, and the Object Explorer home page. So there
is no validation here about what may be grouped with what, because there is no
statement being made about the members beyond "somebody filed these together".

The one rule with teeth, and it is a rule about *not* looking
------------------------------------------------------------
> "Previously, if all object types inside a group were non-discoverable to a
> certain user … the group was also non-discoverable to the user … all groups
> will now be discoverable to any user that can view the ontology. This change
> aligns group visibility with other ontology primitives to increase clarity
> and transparency in governance." (p.263)

A group's visibility is a fact about the group. It is not derived from its
members, not even when it has none. That sounds like the absence of a feature
until you notice that the natural way to write `list_groups` - join the
membership table, group by - implements the behaviour p.263 describes having
deliberately removed: an empty group vanishes from its own listing, and the
person who just created one is told nothing happened. Every read here counts
members with a scalar subquery for that reason, and `test_object_type_groups`
has a test named after the empty case.

Two ways in, one write path
---------------------------
p.261 offers both directions - a groups menu in the sidebar, and "Edit groups"
on the object type page - so `set_members` and `set_groups_for_type` both
exist. They are two orderings of the same pair of ids and delegate to one
`_replace` so a membership written from one screen cannot mean something
different from a membership written on the other.
"""
from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


class ObjectTypeGroupError(ValueError):
    """A group, or a membership, that cannot be saved."""


# ---- reading ----------------------------------------------------------------
async def list_groups(
    conn: AsyncConnection, workspace_id: UUID
) -> list[dict[str, Any]]:
    """Every group in the workspace, with how many object types are in it.

    **The count is a scalar subquery and not a join**, so a group with no
    members is a row saying `0` rather than no row at all. p.263 makes a
    group's discoverability independent of its members; zero is the sharpest
    case of that, and it is the one somebody hits within a minute of creating
    their first group.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT g.id, g.api_name, g.display_name, g.description,
               g.created_at, g.updated_at,
               (SELECT count(*) FROM object_type_group_members m
                 WHERE m.group_id = g.id) AS member_count
          FROM object_type_groups g
         WHERE g.workspace_id = :wid
         ORDER BY g.display_name
        """,
        {"wid": str(workspace_id)},
    )
    return [_out(r) for r in rows]


async def get_group(
    conn: AsyncConnection, workspace_id: UUID, group_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT g.id, g.api_name, g.display_name, g.description,
               g.created_at, g.updated_at,
               (SELECT count(*) FROM object_type_group_members m
                 WHERE m.group_id = g.id) AS member_count
          FROM object_type_groups g
         WHERE g.id = :gid AND g.workspace_id = :wid
        """,
        {"gid": str(group_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("object type group")
    return _out(row)


async def members(
    conn: AsyncConnection, workspace_id: UUID, group_id: UUID
) -> list[dict[str, Any]]:
    """The object types in this group, in the order a listing wants them."""
    await get_group(conn, workspace_id, group_id)
    rows = await fetch_all(
        conn,
        """
        SELECT ot.id, ot.api_name, ot.display_name, ot.status
          FROM object_type_group_members m
          JOIN object_types ot ON ot.id = m.object_type_id
         WHERE m.group_id = :gid AND m.workspace_id = :wid
         ORDER BY ot.display_name
        """,
        {"gid": str(group_id), "wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def groups_for_type(
    conn: AsyncConnection, workspace_id: UUID, type_id: UUID
) -> list[dict[str, Any]]:
    """p.261's "Edit groups in the object type overview page", read side."""
    rows = await fetch_all(
        conn,
        """
        SELECT g.id, g.api_name, g.display_name
          FROM object_type_group_members m
          JOIN object_type_groups g ON g.id = m.group_id
         WHERE m.object_type_id = :tid AND m.workspace_id = :wid
         ORDER BY g.display_name
        """,
        {"tid": str(type_id), "wid": str(workspace_id)},
    )
    return [dict(r) for r in rows]


async def groups_by_type(
    conn: AsyncConnection, workspace_id: UUID
) -> dict[str, list[dict[str, Any]]]:
    """Every membership in the workspace, keyed by object type id.

    **One query for the whole listing**, because p.262's table shows a group
    column on every row and the per-type version of this call inside that loop
    is §169's N+1 in its next costume - the one that took ontology search from
    2 seconds to over 120.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT m.object_type_id, g.id, g.api_name, g.display_name
          FROM object_type_group_members m
          JOIN object_type_groups g ON g.id = m.group_id
         WHERE m.workspace_id = :wid
         ORDER BY g.display_name
        """,
        {"wid": str(workspace_id)},
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        entry = dict(row)
        out.setdefault(str(entry.pop("object_type_id")), []).append(entry)
    return out


# ---- writing ----------------------------------------------------------------
async def create_group(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    created_by: UUID,
) -> dict[str, Any]:
    if not _API_RE.match(api_name):
        raise ObjectTypeGroupError(f"invalid group api_name {api_name!r}")
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM object_type_groups WHERE workspace_id=:wid AND api_name=:api",
        {"wid": str(workspace_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"a group named {api_name!r} already exists")
    row = await fetch_one(
        conn,
        """
        INSERT INTO object_type_groups
            (workspace_id, api_name, display_name, description, created_by)
        VALUES (:wid, :api, :name, :descr, :by)
        RETURNING id, api_name, display_name, description, created_at, updated_at,
                  0 AS member_count
        """,
        {
            "wid": str(workspace_id),
            "api": api_name,
            "name": display_name,
            "descr": description,
            "by": str(created_by),
        },
    )
    assert row is not None
    return _out(row)


async def update_group(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    group_id: UUID,
    display_name: str,
    description: str,
) -> dict[str, Any]:
    """Rename a group, or change what it says it is for.

    No `api_name`, for `object_types.api_name`'s reason (db 0003): it is the
    stable machine name, and here it is also what p.262's search matches on,
    so renaming it would move a group out from under a saved query with
    nothing to say so.
    """
    await get_group(conn, workspace_id, group_id)
    await conn.execute(
        text(
            """
            UPDATE object_type_groups
               SET display_name = :name, description = :descr
             WHERE id = :gid AND workspace_id = :wid
            """
        ),
        {
            "name": display_name,
            "descr": description,
            "gid": str(group_id),
            "wid": str(workspace_id),
        },
    )
    return await get_group(conn, workspace_id, group_id)


async def delete_group(
    conn: AsyncConnection, workspace_id: UUID, group_id: UUID
) -> None:
    """Delete the classification. The object types in it are untouched.

    **Not refused when the group has members**, and that is the whole
    difference between a group and the things this codebase does refuse to
    delete: a group makes no claim its members depend on. Nothing downstream
    breaks, because nothing downstream was told anything by the grouping - the
    membership rows go with it (db 0056's cascade) and every object type keeps
    every property it had.
    """
    await get_group(conn, workspace_id, group_id)
    await conn.execute(
        text("DELETE FROM object_type_groups WHERE id = :gid AND workspace_id = :wid"),
        {"gid": str(group_id), "wid": str(workspace_id)},
    )


async def set_members(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    group_id: UUID,
    object_type_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Replace this group's membership (p.261's groups menu)."""
    await get_group(conn, workspace_id, group_id)
    await _check_types_exist(conn, workspace_id, object_type_ids)
    await _replace(
        conn,
        workspace_id=workspace_id,
        pairs=[(group_id, tid) for tid in object_type_ids],
        clear_column="group_id",
        clear_value=group_id,
    )
    return await members(conn, workspace_id, group_id)


async def set_groups_for_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    type_id: UUID,
    group_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Replace which groups an object type is in (p.261's "Edit groups").

    The other ordering of the same pair, and it goes through the same
    `_replace` - two write paths that could disagree about what a membership
    is would be two chances for the group page and the object type page to
    show different answers about the same fact.
    """
    await _check_types_exist(conn, workspace_id, [type_id])
    for gid in set(group_ids):
        await get_group(conn, workspace_id, gid)
    await _replace(
        conn,
        workspace_id=workspace_id,
        pairs=[(gid, type_id) for gid in group_ids],
        clear_column="object_type_id",
        clear_value=type_id,
    )
    return await groups_for_type(conn, workspace_id, type_id)


async def _replace(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    pairs: list[tuple[UUID, UUID]],
    clear_column: str,
    clear_value: UUID,
) -> None:
    """Delete one side's memberships and write the given ones back.

    `clear_column` is an identifier chosen from two literals by the two
    callers above, never from a request - the values are still bound.
    """
    assert clear_column in ("group_id", "object_type_id")
    await conn.execute(
        text(
            f"""
            DELETE FROM object_type_group_members
             WHERE {clear_column} = :val AND workspace_id = :wid
            """
        ),
        {"val": str(clear_value), "wid": str(workspace_id)},
    )
    seen: set[tuple[str, str]] = set()
    for group_id, type_id in pairs:
        key = (str(group_id), str(type_id))
        if key in seen:
            # A list naming the same member twice is a client bug, not a
            # conflict worth a 409: the requested state is unambiguous.
            continue
        seen.add(key)
        await conn.execute(
            text(
                """
                INSERT INTO object_type_group_members
                    (group_id, object_type_id, workspace_id)
                VALUES (:gid, :tid, :wid)
                """
            ),
            {"gid": key[0], "tid": key[1], "wid": str(workspace_id)},
        )


async def _check_types_exist(
    conn: AsyncConnection, workspace_id: UUID, type_ids: list[UUID]
) -> None:
    """Refuse an object type this workspace cannot see, by name.

    db 0056's composite foreign key already makes a cross-workspace membership
    impossible; this exists so the refusal is a 404 naming the object type
    rather than an integrity error naming a constraint.
    """
    for type_id in set(type_ids):
        row = await fetch_one(
            conn,
            "SELECT 1 AS x FROM object_types WHERE id = :tid AND workspace_id = :wid",
            {"tid": str(type_id), "wid": str(workspace_id)},
        )
        if row is None:
            raise NotFoundError("object type")


def _out(row: Any) -> dict[str, Any]:
    out = dict(row)
    if "member_count" in out:
        out["member_count"] = int(out["member_count"])
    return out
