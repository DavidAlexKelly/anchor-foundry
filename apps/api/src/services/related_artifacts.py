"""What links to the lineage graph's selection from off the graph (§614;
`data-lineage` p.10, p.30).

> "The related artifacts helper displays artifacts directly linked to the
> nodes selected on the graph. Deleted and automatically saved files are
> excluded from the list unless chosen otherwise." (p.10)

**An artifact is what the graph does not draw.** Datasets, transforms, object
types and sources are its nodes, so the things that link to one of them from
elsewhere are two:

- a **Workshop module** whose document names a selected dataset or object
  type - a dataset widget, an object set variable, a table's type. "Directly
  linked" is read literally: the module holds the id. A module that reads an
  object type only through another module's interface does not;
- the **code repository** a selected transform is authored in (B.1's
  adoption, `models.source_repo_id`).

**Read through the caller's own connection**, so row-level security decides
which modules and repositories are listed: a module in a project this person
cannot open is not an artifact they can follow, and naming it would say that
it exists. Modules are looked for across the workspace, because an object type
is read from other projects' modules too.

p.10's exclusions need nothing: nothing here is deleted into a trash, and a
module is saved when somebody saves it, never automatically.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from ..lib.db import fetch_all

#: How many nodes one question may name. A selection is a person's clicks, and
#: two hundred is a graph's worth of them.
MAX_NODES = 200

#: The node kinds a module can name. A transform is linked to its repository
#: instead, and a source to nothing off the graph.
MODULE_KINDS = ("dataset", "object_type")


def _strings(value: Any, into: set[str]) -> set[str]:
    """Every string *value* in a document. Keys are a module's own names for
    things (variable ids, prop names), never a resource's id."""
    if isinstance(value, str):
        into.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _strings(item, into)
    elif isinstance(value, list):
        for item in value:
            _strings(item, into)
    return into


async def for_nodes(conn: Any, *, workspace_id: UUID, nodes: list[str]) -> list[dict[str, Any]]:
    """The artifacts linked to any of `nodes` (`kind:uuid`), each with the
    nodes it links to in the order they were asked about."""
    by_id: dict[str, str] = {}
    models: list[str] = []
    for node in nodes:
        kind, _, bare = node.partition(":")
        if kind in MODULE_KINDS:
            by_id[bare] = node
        elif kind == "model":
            models.append(bare)

    found: list[dict[str, Any]] = []
    if by_id:
        # `position` is a filter that avoids *fetching* a module that cannot
        # match, as `actions.parameter_usages` explains; the walk decides.
        rows = await fetch_all(
            conn,
            """
            SELECT ca.id, ca.name, ca.resource_id, ca.project_id, p.name AS project_name,
                   ca.created_at, ca.updated_at, ca.definition
              FROM canvas_apps ca
              JOIN projects p ON p.id = ca.project_id
             WHERE ca.workspace_id = :wid
               AND EXISTS (SELECT 1 FROM unnest(CAST(:needles AS text[])) AS n(needle)
                            WHERE position(n.needle in ca.definition::text) > 0)
            """,
            {"wid": str(workspace_id), "needles": list(by_id)},
        )
        for row in rows:
            document = row["definition"]
            if isinstance(document, str):
                document = json.loads(document)
            named = _strings(document, set())
            linked = [node for bare, node in by_id.items() if bare in named]
            if linked:
                found.append({
                    "kind": "workshop_module", "id": row["id"], "name": row["name"],
                    "resource_id": row["resource_id"], "project_id": row["project_id"],
                    "project_name": row["project_name"], "created_at": row["created_at"],
                    "updated_at": row["updated_at"], "nodes": linked,
                })

    if models:
        rows = await fetch_all(
            conn,
            """
            SELECT m.id AS model_id, r.id, r.name, r.resource_id, r.project_id,
                   p.name AS project_name, r.created_at, r.updated_at
              FROM models m
              JOIN code_repos r ON r.id = m.source_repo_id
              JOIN projects p ON p.id = r.project_id
             WHERE m.id = ANY(CAST(:ids AS uuid[]))
            """,
            {"ids": models},
        )
        repos: dict[str, dict[str, Any]] = {}
        for bare in models:
            for row in rows:
                if str(row["model_id"]) != bare:
                    continue
                repo = repos.setdefault(str(row["id"]), {
                    "kind": "code_repository", "id": row["id"], "name": row["name"],
                    "resource_id": row["resource_id"], "project_id": row["project_id"],
                    "project_name": row["project_name"], "created_at": row["created_at"],
                    "updated_at": row["updated_at"], "nodes": [],
                })
                repo["nodes"].append(f"model:{bare}")
        found.extend(repos.values())
    return found
