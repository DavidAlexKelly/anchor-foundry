"""Save and share a lineage graph (§360; `data-lineage` p.12).

> "You can save and share your lineage graph with other Foundry users in the
>  following ways: **Save / Open**: Save your Data Lineage graph and re-open it
>  by clicking on Open graph. **Get quick share link**: Generates a shareable
>  link that provides read-only access to your graph." (p.12)

Stored in migration 0089, which follows db 0040's saved searches rather than
inventing a second convention for a saved thing. A saved graph holds the
*view* - what a person chose to look at - and never the nodes: §355 settled
that this platform draws the whole project, so the node list is not a choice,
and a stored one would be a screenshot with a date on it.

**`parse` is used twice, which is the whole reason it is here** and is db
0040's own lesson: the graph route already refuses a malformed `focus`, and if
saving validated separately - or not at all - it would be possible to save a
view that cannot open, and the person who found out would not be the person who
made the mistake. The `focus` grammar now lives here and `routes/models.py`
reads it from here too.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: The kinds a graph draws, and therefore the only ones a filter can name or a
#: focus can be. **One list**, because §420 found the cost of three: adding the
#: data source node meant a regex here, a tuple here, and the same sentence
#: written out by hand in two refusals, and the two refusals were still naming
#: three kinds after the graph drew four. They are derived now, so the next
#: kind is one line (§292).
KINDS = ("dataset", "model", "object_type", "connection")

#: A node id as the graph builds them (`services/pipeline.py`).
NODE_ID = re.compile(rf"({'|'.join(KINDS)}):[0-9a-fA-F-]{{36}}")

#: What a refusal says a focus may be, in the caller's words. `routes/models.py`
#: reads this rather than writing its own, for the reason `parse` is shared:
#: two refusals that disagree are one of them being wrong.
FOCUS_HINT = (
    "focus must be "
    + ", ".join(f"'{kind}:<uuid>'" for kind in KINDS[:-1])
    + f" or '{KINDS[-1]}:<uuid>'"
)

#: p.38's node colourings, as the browser offers them (§419). Mirrored from
#: `apps/web/src/lib/node-colouring.ts` rather than shared, because there is no
#: shared language between them - and mirrored lists drift, so
#: `test_saved_graphs.py` reads that file and asserts the two say the same
#: thing. That test is the reason this is safe to write twice.
COLOURINGS = ("status", "out_of_date", "health", "kind", "origin", "none")

#: A selection is a view, not a bulk operation. Forty nodes is a large graph;
#: four hundred is somebody's script, and storing it would make opening the
#: saved graph slower than drawing it.
MAX_SELECTED = 500

MAX_QUERY = 200


class GraphViewError(ValueError):
    """Refusal, phrased for whoever saved the view."""


def parse(view: Any) -> dict[str, Any]:
    """The view parameters a saved graph may hold, or a refusal.

    **Unknown keys are refused rather than dropped.** A view saved with a
    misspelled key would open silently missing whatever it was for, and the
    reader would see a graph that looked deliberate. The set is small and
    grows by a migration-free line here, so there is no cost to naming it.
    """
    if not isinstance(view, dict):
        raise GraphViewError("a saved graph's view must be an object")

    known = {"focus", "column", "selected", "query", "kinds", "colouring"}
    unknown = sorted(set(view) - known)
    if unknown:
        raise GraphViewError(
            f"a saved graph has no {', '.join(unknown)} — it holds "
            f"{', '.join(sorted(known))}"
        )

    out: dict[str, Any] = {}

    focus = view.get("focus")
    if focus is not None:
        if not isinstance(focus, str) or not NODE_ID.fullmatch(focus):
            raise GraphViewError(FOCUS_HINT)
        out["focus"] = focus

    column = view.get("column")
    if column is not None:
        if not isinstance(column, str) or not column.strip():
            raise GraphViewError("column must be a column name")
        out["column"] = column

    selected = view.get("selected")
    if selected is not None:
        if not isinstance(selected, list):
            raise GraphViewError("selected must be a list of node ids")
        if len(selected) > MAX_SELECTED:
            raise GraphViewError(
                f"a saved graph holds at most {MAX_SELECTED} selected nodes"
            )
        for node in selected:
            if not isinstance(node, str) or not NODE_ID.fullmatch(node):
                raise GraphViewError(f"{node!r} is not a node id")
        # De-duplicated, keeping the order it was saved in: the same node twice
        # is not a different view, and a count drawn from this would be wrong.
        out["selected"] = list(dict.fromkeys(selected))

    query = view.get("query")
    if query is not None:
        if not isinstance(query, str):
            raise GraphViewError("query must be text")
        if len(query) > MAX_QUERY:
            raise GraphViewError(f"a search is at most {MAX_QUERY} characters")
        # Stored only when it says something. A saved graph carrying `query:
        # ""` would reopen with the search box focused on nothing.
        if query.strip():
            out["query"] = query

    kinds = view.get("kinds")
    if kinds is not None:
        if not isinstance(kinds, list):
            raise GraphViewError("kinds must be a list")
        for kind in kinds:
            if kind not in KINDS:
                raise GraphViewError(
                    f"{kind!r} is not a kind this graph draws ({', '.join(KINDS)})"
                )
        if kinds:
            # Every kind chosen is the same view as none chosen, and saving it
            # as a filter would have a reader believe one is applied.
            out["kinds"] = (
                [] if set(kinds) == set(KINDS) else list(dict.fromkeys(kinds))
            )
            if not out["kinds"]:
                del out["kinds"]

    colouring = view.get("colouring")
    if colouring is not None:
        if colouring not in COLOURINGS:
            raise GraphViewError(
                f"{colouring!r} is not a node colouring "
                f"({', '.join(COLOURINGS)})"
            )
        # Stored as given, including "none" - p.38's first option is somebody
        # deciding the colours were in the way, which is a view rather than the
        # absence of one. Only the default is dropped, and the browser drops
        # that before it gets here (`viewOf`); a client that sends it anyway
        # gets it back, because refusing it would make an honest view a
        # refusal.
        out["colouring"] = colouring

    return out


_COLUMNS = "id, project_id, name, description, view::text AS view, created_by, created_at, updated_at"


def _out(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["view"] = json.loads(data["view"]) if isinstance(data["view"], str) else data["view"]
    return data


async def list_graphs(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM saved_graphs WHERE project_id = :pid ORDER BY name",
        {"pid": str(project_id)},
    )
    return [_out(row) for row in rows]


async def create(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    name: str,
    description: str,
    view: Any,
    created_by: UUID,
) -> dict[str, Any]:
    parsed = parse(view)
    clash = await fetch_one(
        conn,
        "SELECT 1 AS x FROM saved_graphs WHERE project_id = :pid AND name = :name",
        {"pid": str(project_id), "name": name},
    )
    if clash is not None:
        raise ConflictError(f"a saved graph called '{name}' already exists in this project")
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO saved_graphs (project_id, name, description, view, created_by)
        VALUES (:pid, :name, :descr, CAST(:view AS jsonb), :by)
        RETURNING {_COLUMNS}
        """,
        {
            "pid": str(project_id), "name": name, "descr": description,
            "view": json.dumps(parsed), "by": str(created_by),
        },
    )
    assert row is not None
    return _out(row)


async def remove(conn: AsyncConnection, project_id: UUID, graph_id: UUID) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM saved_graphs WHERE id = :gid AND project_id = :pid RETURNING id",
        {"gid": str(graph_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("saved graph")
