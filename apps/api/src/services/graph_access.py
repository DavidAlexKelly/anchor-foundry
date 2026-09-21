"""Whose access the lineage graph is drawn for (§422; `data-lineage` p.80-84).

> "You can use Data Lineage to check users' permissions to view datasets or
>  artifacts using the 'Permissions' coloring option." (p.80)

> "Select the user's name from the **View as** dropdown. This will allow you to
>  see the user's permissions to each of the nodes on the graph." (p.82)

**p.83 names two permission types and this is one of them.** *Resource access*
is "the role (such as Editor, Viewer, etc.) that is set for the selected user
on the selected resource", which is exactly what `effective_project_role` and
`effective_workspace_role` answer. *Data access in datasets* is Markings
propagated down the lineage, and this platform has no Markings - the parity
row carries that rather than a colouring that would paint one colour and mean
nothing.

**The graph is worth colouring by this only because its nodes are not all
scoped the same way**, which is the fact that made the row buildable at all:
datasets and models are project-scoped (db 0003), object types are
*workspace*-scoped, and a connection is either, by its own `scope` column. So
"Alice can edit everything on this page except the object type it feeds" is a
real answer here, and it is p.84's own warning said in this platform's terms:
"Roles do not correspond to data lineage the same way that data access does."

**Two queries whatever the graph's size.** A role is per scope, not per node,
so the per-node map is built by looking up two roles and each connection's
scope - never one query per card.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: Which scope decides access to each kind of node the graph draws. A
#: connection is absent because it is the one kind that answers for itself
#: (db 0003's `connection_scope`), and `for_nodes` reads that per node.
SCOPE_OF_KIND = {
    "dataset": "project",
    "model": "project",
    "object_type": "workspace",
}


async def viewers(conn: AsyncConnection, *, workspace_id: UUID) -> list[dict[str, Any]]:
    """Who p.82's *View as* dropdown may name.

    **`notification_store.notifiable`'s predicate, and deliberately the same
    one.** §258 learned this the expensive way one surface over: a picker built
    from the `workspace_members` table is empty for the workspace's creator,
    who has access by a route that writes no membership row. Offering a set
    that is not the set the server answers for is wrong in either direction -
    narrower hides people whose access somebody is trying to debug, wider
    offers a name the colouring cannot answer about (§214).
    """
    return await fetch_all(
        conn,
        """
        SELECT u.id, u.email, u.display_name
          FROM users u
         WHERE effective_workspace_role(u.id, CAST(:wid AS uuid)) IS NOT NULL
         ORDER BY u.display_name, u.email
        """,
        {"wid": str(workspace_id)},
    )


async def for_nodes(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    project_id: UUID,
    user_id: UUID,
    nodes: list[dict[str, Any]],
) -> dict[str, Any]:
    """One person's access to each node on this graph.

    `via` travels beside the role because the role alone does not explain
    itself: "viewer" on a dataset and "viewer" on an object type are answers
    from two different scopes, and somebody debugging why one card is red and
    its neighbour is not needs to know which door they are being refused at.

    A node whose kind this does not know is **absent from the map rather than
    reported as no access** (§210): the honest answer for a kind added later
    is "this build cannot say", and colouring it the same as a refusal would
    report a permissions problem nobody has.
    """
    roles = await fetch_one(
        conn,
        """
        SELECT effective_project_role(CAST(:uid AS uuid), CAST(:pid AS uuid)) AS project,
               effective_workspace_role(CAST(:uid AS uuid), CAST(:wid AS uuid)) AS workspace
        """,
        {"uid": str(user_id), "pid": str(project_id), "wid": str(workspace_id)},
    )
    assert roles is not None
    by_scope = {"project": roles["project"], "workspace": roles["workspace"]}

    # A connection is scoped by its own row, so the ones actually on the graph
    # are looked up together - one query, not one per card.
    connection_ids = [
        node["resource_id"] for node in nodes if node["kind"] == "connection"
    ]
    scopes: dict[str, str] = {}
    if connection_ids:
        for row in await fetch_all(
            conn,
            """
            SELECT id, scope::text AS scope FROM connections
             WHERE id = ANY(CAST(:ids AS uuid[]))
            """,
            {"ids": connection_ids},
        ):
            scopes[str(row["id"])] = str(row["scope"])

    out: dict[str, Any] = {}
    for node in nodes:
        # A connection on the graph always has a scope here, and there is no
        # branch for one that does not. The graph's own `sources` query joins
        # `connections`, and both queries run on the same caller's connection
        # - so a connection node exists on the graph exactly when this caller
        # can read its row. A guard for the other case was written first and a
        # sweep could not make it fail; it is gone rather than covered by a
        # test that would pass either way (§223), and this paragraph is in its
        # place because the reasoning is the thing worth keeping.
        scope = (
            scopes.get(node["resource_id"])
            if node["kind"] == "connection"
            else SCOPE_OF_KIND.get(node["kind"])
        )
        if scope is None:
            continue
        out[node["id"]] = {"role": by_scope[scope], "via": scope}
    return out
