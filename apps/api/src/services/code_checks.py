"""Checks that run on a proposal and block it (ROADMAP.md phase 2, item 2.8).

The item asks for "lint and schema-compatibility checks that run on a proposal
and block merge", reusing the existing quality-gate machinery. The point of it
is a sequencing problem, not a missing feature:

* migration 0023 gave a dataset a `schema_policy` enforced by a trigger on
  `dataset_versions`, so a transform that drops a column from a strict
  dataset **is already refused** - by the database, at run time, some hours
  after a reviewer approved it and somebody applied it;
* item 2.6 gave the API a way to run a transform over a sample of its inputs
  and report the schema it produces, writing nothing.

Putting the second in front of the first is the whole item: find out at review
time what the database would refuse at run time. There is deliberately no
second rule engine here - the policy that decides `fail` from `warn` is the
dataset's own `schema_policy`, read rather than reimplemented.

Two checks, and the second depends on the first:

  transform_runs      the proposed code runs against a sample of its inputs.
  schema_compatible   the schema it produces does not break the dataset it
                      writes, judged by that dataset's policy.

A check result is a claim about a *version* of the files (migration 0037, same
rule as 0036's comments): it records the `files_updated_at` it ran against, and
a result older than that is stale - it describes code nobody will apply. Stale
results are shown, marked, and do not gate.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from . import dataset_engine as engine
from . import models as model_service
from .dataset_engine import DatasetEngineError

CHECK_NAMES = ("transform_runs", "schema_compatible")
CHECK_STATUSES = ("pass", "warn", "fail", "error")

# Only a `fail` gates. `error` deliberately does not: it means the check could
# not run, and refusing to apply because *we* could not answer would make every
# outage a freeze on every project. It is shown, in its own words, and a
# reviewer decides.
BLOCKING_STATUSES = ("fail",)


def _stored_schema(table_schema: Any) -> list[dict[str, str]] | None:
    """`datasets.table_schema` as `diff_schemas` wants it. Same shape the sync
    path already normalises (services/sync.py), and None when the dataset has
    no version yet - which is "nothing to compare against", not "no columns"."""
    if not table_schema:
        return None
    if isinstance(table_schema, dict):
        columns = table_schema.get("columns")
        return columns if isinstance(columns, list) else None
    return table_schema if isinstance(table_schema, list) else None


async def _proposal(conn: AsyncConnection, project_id: UUID, proposal_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        "SELECT id, project_id, state, files_updated_at FROM code_proposals "
        "WHERE id = :id AND project_id = :pid",
        {"id": str(proposal_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("proposal")
    return dict(row)


async def _record(
    conn: AsyncConnection,
    *,
    proposal_id: UUID,
    model_id: UUID | None,
    source_path: str | None,
    name: str,
    status: str,
    summary: str,
    detail: dict[str, Any],
    ran_by: UUID | None,
    anchored_at: Any,
) -> None:
    """One current result per check per file: re-running replaces. A list of
    every time a check ran is a log, and what a reviewer needs is the answer."""
    import json

    await conn.exec_driver_sql(
        """
        INSERT INTO code_proposal_checks
            (proposal_id, model_id, source_path, name, status, summary, detail,
             ran_by, anchored_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (proposal_id, model_id, source_path, name) DO UPDATE
            SET status = EXCLUDED.status, summary = EXCLUDED.summary,
                detail = EXCLUDED.detail, ran_at = now(),
                ran_by = EXCLUDED.ran_by, anchored_at = EXCLUDED.anchored_at
        """,
        (
            str(proposal_id), str(model_id) if model_id else None, source_path,
            name, status,
            summary, json.dumps(detail), str(ran_by) if ran_by else None, anchored_at,
        ),
    )


async def run_checks(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    *,
    storage: Any,
    actor_id: UUID | None,
) -> list[dict[str, Any]]:
    """Run every check against the proposal's current files, and store what
    each one found.

    Storage is passed in rather than reached for, so this can be exercised
    against a real gateway pointed at a temp directory - the same shape the
    dataset routes already use.
    """
    proposal = await _proposal(conn, project_id, proposal_id)
    if proposal["state"] != "open":
        raise ValueError("this proposal is closed, so there is nothing to check")
    anchor = proposal["files_updated_at"]

    # Through the proposal's own file list rather than `code_proposal_files`:
    # a commit-backed proposal has no rows there (db 0039) and every check on
    # one would otherwise find nothing to do and report success by silence.
    from . import code as code_service

    files, unpublishable = await code_service.proposal_files(
        conn, project_id, proposal_id
    )
    if unpublishable:
        raise ValueError(unpublishable)
    if not files:
        raise ValueError("this proposal has no files to check")

    for entry in files:
        model_id = UUID(str(entry["model_id"])) if entry["model_id"] else None
        row = dict(entry)
        if model_id is not None:
            live = await fetch_one(
                conn, "SELECT output_dataset_id FROM models WHERE id = :mid",
                {"mid": str(model_id)},
            )
            row["output_dataset_id"] = live["output_dataset_id"] if live else None
        else:
            # A file that would create a transform writes a dataset nothing has
            # yet, so there is no schema to be incompatible with.
            row["output_dataset_id"] = None
        path = entry.get("path") if model_id is None else None
        schema, ran = await _check_transform_runs(
            conn, proposal_id, row, model_id=model_id, source_path=path,
            storage=storage, actor_id=actor_id, anchor=anchor,
        )
        await _check_schema_compatible(
            conn, proposal_id, row, model_id=model_id, source_path=path,
            produced=schema, transform_ran=ran, actor_id=actor_id, anchor=anchor,
        )

    return await list_checks(conn, proposal_id, anchor)


async def _check_transform_runs(
    conn: AsyncConnection,
    proposal_id: UUID,
    row: Any,
    *,
    model_id: UUID | None,
    source_path: str | None,
    storage: Any,
    actor_id: UUID | None,
    anchor: Any,
) -> tuple[list[Any] | None, bool]:
    """Does the proposed code run at all?

    Returns the schema it produced and whether it ran, because the schema check
    needs both - and "it did not run" is a different answer from "it produced
    nothing", which is what a bare `None` would collapse them into.
    """
    name = "transform_runs"
    if str(row["language"]) != "sql":
        # Decision 0004: customer Python runs in an isolated task, never in the
        # API. `error` rather than `pass` - nobody has been told anything about
        # this code, and saying "pass" would be a claim we have not earned.
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="error",
            summary=(
                "Python transforms run in an isolated task rather than in the API, so "
                "this check cannot run on them here. It has not passed - it has not run."
            ),
            detail={"language": str(row["language"])}, ran_by=actor_id, anchored_at=anchor,
        )
        return None, False

    inputs = (
        await model_service.list_inputs(conn, model_id)
        if model_id is not None
        # A file that would create a transform has no `model_inputs` rows yet.
        # The plan already resolved its declared inputs to datasets, so they
        # arrive on the entry - which is also what makes this checkable at all.
        else [
            {"dataset_id": i["dataset_id"], "input_alias": i["input_alias"],
             "dataset_name": i.get("dataset", "")}
            for i in (row.get("inputs") or [])
        ]
    )
    paths: dict[str, str] = {}
    for item in inputs:
        location = await fetch_one(
            conn, "SELECT s3_location FROM datasets WHERE id = :did",
            {"did": str(item["dataset_id"])},
        )
        if location is None or not location["s3_location"]:
            await _record(
                conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="error",
                summary=(
                    f"{item['dataset_name']} has no stored data yet, so there is nothing "
                    "to run this against."
                ),
                detail={"alias": str(item["input_alias"])},
                ran_by=actor_id, anchored_at=anchor,
            )
            return None, False
        try:
            paths[str(item["input_alias"])] = await anyio.to_thread.run_sync(
                storage.local_path, str(location["s3_location"])
            )
        except FileNotFoundError:
            await _record(
                conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="error",
                summary=(
                    f"{item['dataset_name']} has a version recorded but no bytes behind "
                    "it, so this check could not read it."
                ),
                detail={"alias": str(item["input_alias"])},
                ran_by=actor_id, anchored_at=anchor,
            )
            return None, False

    try:
        result, previewed = await anyio.to_thread.run_sync(
            engine.preview_transform, paths, str(row["code"])
        )
    except DatasetEngineError as exc:
        # The code is wrong, and this is the check that exists to say so before
        # anybody approves it. `fail`, and the engine's own message - it is
        # already phrased for whoever wrote the SQL.
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="fail",
            summary=str(exc), detail={}, ran_by=actor_id, anchored_at=anchor,
        )
        return None, False

    sampled = any(p.sampled for p in previewed)
    await _record(
        conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="pass",
        summary=(
            f"Runs, and produces {len(result.columns)} column"
            f"{'' if len(result.columns) == 1 else 's'}"
            # Said here as well as in the preview panel: a check that ran on a
            # sample and did not say so is a check somebody will over-believe.
            + (" (over a sample of its inputs)." if sampled else ".")
        ),
        detail={
            "columns": [c.as_dict() for c in result.columns],
            "sampled": sampled,
        },
        ran_by=actor_id, anchored_at=anchor,
    )
    return result.columns, True


async def _check_schema_compatible(
    conn: AsyncConnection,
    proposal_id: UUID,
    row: Any,
    *,
    model_id: UUID | None,
    source_path: str | None,
    produced: list[Any] | None,
    transform_ran: bool,
    actor_id: UUID | None,
    anchor: Any,
) -> None:
    """Would applying this break the dataset the transform writes?

    The verdict is the dataset's own `schema_policy` (migration 0023), read
    rather than reimplemented. A strict dataset's trigger will refuse a version
    that removes or retypes a column, so predicting anything else here would be
    a second opinion that the database is about to overrule.
    """
    name = "schema_compatible"
    if not transform_ran or produced is None:
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="error",
            summary="The transform did not run, so there is no schema to compare.",
            detail={}, ran_by=actor_id, anchored_at=anchor,
        )
        return

    output_id = row["output_dataset_id"]
    if output_id is None:
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="pass",
            summary="This transform has not written a dataset yet, so nothing can break.",
            detail={}, ran_by=actor_id, anchored_at=anchor,
        )
        return

    dataset = await fetch_one(
        conn,
        "SELECT name, table_schema, CAST(schema_policy AS text) AS schema_policy "
        "FROM datasets WHERE id = :did",
        {"did": str(output_id)},
    )
    previous = _stored_schema(dataset["table_schema"]) if dataset else None
    changes = engine.diff_schemas(previous, produced)
    if not changes:
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="pass",
            summary=(
                f"Leaves {dataset['name']}'s schema as it is."
                if previous
                else f"{dataset['name']} has no schema recorded yet, so nothing can break."
            ),
            detail={}, ran_by=actor_id, anchored_at=anchor,
        )
        return

    removed = changes.get("removed", [])
    retyped = changes.get("retyped", [])
    added = changes.get("added", [])
    strict = (dataset or {}).get("schema_policy") == "strict"

    if not removed and not retyped:
        # Adding a column is not a breaking change, and 0023's strict policy
        # allows it for the reason written there: a policy people keep
        # switching off is a policy nobody leaves on.
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="pass",
            summary=(
                f"Adds {', '.join(c['name'] for c in added)} to {dataset['name']}. "
                "Adding a column does not break a reader."
            ),
            detail=changes, ran_by=actor_id, anchored_at=anchor,
        )
        return

    what = ", ".join(
        [f"drops {c['name']}" for c in removed]
        + [f"retypes {c['name']} ({c['from']} → {c['to']})" for c in retyped]
    )
    if strict:
        await _record(
            conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="fail",
            summary=(
                f"This {what} on {dataset['name']}, which is strict - the write would be "
                "refused when the transform ran. Applying this would produce a failed "
                "run, not a changed dataset."
            ),
            detail={**changes, "dataset": dataset["name"], "schema_policy": "strict"},
            ran_by=actor_id, anchored_at=anchor,
        )
        return
    await _record(
        conn, proposal_id=proposal_id, model_id=model_id,
            source_path=source_path, name=name, status="warn",
        summary=(
            f"This {what} on {dataset['name']}. The dataset is permissive so the write "
            "would be allowed, but anything reading those columns breaks."
        ),
        detail={**changes, "dataset": dataset["name"], "schema_policy": "permissive"},
        ran_by=actor_id, anchored_at=anchor,
    )


async def list_checks(
    conn: AsyncConnection, proposal_id: UUID, files_updated_at: Any
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        """
        SELECT c.id, c.model_id, c.source_path, c.name,
               CAST(c.status AS text) AS status,
               c.summary, c.detail, c.ran_at, c.ran_by, c.anchored_at,
               (SELECT u.email FROM users u WHERE u.id = c.ran_by) AS ran_by_email
          FROM code_proposal_checks c
         WHERE c.proposal_id = :pid
         ORDER BY c.name, c.ran_at DESC
        """,
        {"pid": str(proposal_id)},
    )
    return [
        {**dict(r), "stale": r["anchored_at"] < files_updated_at}
        for r in rows
    ]


def blockers(checks: list[dict[str, Any]]) -> list[str]:
    """The reasons a check gives for not applying this.

    Only current results, and only failures. A stale result describes code
    nobody will apply, and blocking on it would mean an edit made to *fix* a
    failure keeps the failure in place until somebody re-runs.
    """
    return [
        f"a check failed: {c['summary']}"
        for c in checks
        if not c["stale"] and c["status"] in BLOCKING_STATUSES
    ]
