"""Saved time series analyses (§662; `workshop` p.397, migration 0131).

> "Enable analysis saving: Save and share analyses for future reference.
>  Analyses can be saved as either Private or Public." (p.397)

A saved analysis is the Time Series Analysis widget's view - its plots,
canvases, event sets and axes - and never its readings, for db 0089's reason:
the readings are a live question. Who may see one is RLS's (db 0131): a
private analysis is its author's, a public one the project's. Only the author
saves over or deletes one; that is checked here as well as by RLS, so the
refusal says why rather than reading as "not found".
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, ForbiddenError, NotFoundError

VISIBILITIES = ("private", "public")
#: A saved view is plots and settings; this is room for a full analysis many
#: times over, and a bound on what one request may store.
MAX_STATE_BYTES = 256_000
#: The widget holds 24 plots; a saved view with more was not saved by it.
MAX_PLOTS = 24

_COLUMNS = """a.id, a.project_id, a.name, a.visibility, a.state, a.created_by, a.created_at,
              a.updated_at, u.display_name AS created_by_name"""


class AnalysisError(ValueError):
    """Refusal, phrased for whoever saved the analysis."""


def parse(state: Any) -> dict[str, Any]:
    """The view as it may be stored: an object, of a bounded size, whose plots
    are a list of plots with an id and a label each."""
    if not isinstance(state, dict):
        raise AnalysisError("an analysis is saved as an object")
    if len(json.dumps(state)) > MAX_STATE_BYTES:
        raise AnalysisError(f"an analysis is at most {MAX_STATE_BYTES:,} bytes saved")
    plots = state.get("plots", [])
    if not isinstance(plots, list):
        raise AnalysisError("an analysis's plots are a list")
    if len(plots) > MAX_PLOTS:
        raise AnalysisError(f"an analysis has at most {MAX_PLOTS} plots")
    for plot in plots:
        if not isinstance(plot, dict) or not isinstance(plot.get("id"), str) \
                or not isinstance(plot.get("label"), str):
            raise AnalysisError("each plot has an id and a label")
    return state


def _visibility(value: str) -> str:
    if value not in VISIBILITIES:
        raise AnalysisError(f"an analysis is {' or '.join(VISIBILITIES)}")
    return value


def _out(row: Any) -> dict[str, Any]:
    out = dict(row)
    if isinstance(out.get("state"), str):
        out["state"] = json.loads(out["state"])
    return out


async def list_analyses(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    """Every analysis this reader may open in the project: their own, and the
    public ones - RLS's rule, not a filter here."""
    rows = await fetch_all(
        conn,
        f"""SELECT {_COLUMNS} FROM series_analyses a LEFT JOIN users u ON u.id = a.created_by
            WHERE a.project_id = :pid ORDER BY a.name, a.created_at""",
        {"pid": str(project_id)},
    )
    return [_out(r) for r in rows]


async def get(conn: AsyncConnection, project_id: UUID, analysis_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""SELECT {_COLUMNS} FROM series_analyses a LEFT JOIN users u ON u.id = a.created_by
            WHERE a.project_id = :pid AND a.id = :id""",
        {"pid": str(project_id), "id": str(analysis_id)},
    )
    if row is None:
        raise NotFoundError("time series analysis")
    return _out(row)


async def by_id(conn: AsyncConnection, workspace_id: UUID, analysis_id: UUID) -> dict[str, Any]:
    """One analysis by its id alone, p.397's RID (§663), in whichever of the
    workspace's projects it is; whether the reader may see it is RLS's, as it
    is for the list."""
    row = await fetch_one(
        conn,
        f"""SELECT {_COLUMNS} FROM series_analyses a
              JOIN projects p ON p.id = a.project_id AND p.workspace_id = :wid
              LEFT JOIN users u ON u.id = a.created_by
            WHERE a.id = :id""",
        {"wid": str(workspace_id), "id": str(analysis_id)},
    )
    if row is None:
        raise NotFoundError("time series analysis")
    return _out(row)


async def create(
    conn: AsyncConnection, *, project_id: UUID, name: str, visibility: str, state: Any,
    created_by: UUID,
) -> dict[str, Any]:
    parsed = parse(state)
    clash = await fetch_one(
        conn,
        """SELECT 1 AS x FROM series_analyses
           WHERE project_id = :pid AND created_by = :by AND name = :name""",
        {"pid": str(project_id), "by": str(created_by), "name": name},
    )
    if clash is not None:
        raise ConflictError(f"you already have an analysis called '{name}' in this project")
    row = await fetch_one(
        conn,
        """INSERT INTO series_analyses (project_id, name, visibility, state, created_by)
           VALUES (:pid, :name, :vis, CAST(:state AS jsonb), :by) RETURNING id""",
        {"pid": str(project_id), "name": name, "vis": _visibility(visibility),
         "state": json.dumps(parsed), "by": str(created_by)},
    )
    assert row is not None
    return await get(conn, project_id, row["id"])


async def _own(conn: AsyncConnection, project_id: UUID, analysis_id: UUID, user_id: UUID) -> dict[str, Any]:
    found = await get(conn, project_id, analysis_id)
    if str(found["created_by"]) != str(user_id):
        raise ForbiddenError("only its author saves over or deletes an analysis - save your own copy")
    return found


async def replace(
    conn: AsyncConnection, project_id: UUID, analysis_id: UUID, *, state: Any, visibility: str,
    user_id: UUID,
) -> dict[str, Any]:
    """Save over one's own analysis: the view and whether it is shared. The
    name stays, as a saved graph's does (§512)."""
    await _own(conn, project_id, analysis_id, user_id)
    await fetch_one(
        conn,
        """UPDATE series_analyses SET state = CAST(:state AS jsonb), visibility = :vis
           WHERE project_id = :pid AND id = :id RETURNING id""",
        {"pid": str(project_id), "id": str(analysis_id), "vis": _visibility(visibility),
         "state": json.dumps(parse(state))},
    )
    return await get(conn, project_id, analysis_id)


async def remove(conn: AsyncConnection, project_id: UUID, analysis_id: UUID, user_id: UUID) -> None:
    await _own(conn, project_id, analysis_id, user_id)
    await fetch_one(
        conn,
        "DELETE FROM series_analyses WHERE project_id = :pid AND id = :id RETURNING id",
        {"pid": str(project_id), "id": str(analysis_id)},
    )
