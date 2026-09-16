"""Which datasets a proposal changes (§364; `code-repositories` p.52-55).

> "The Impact analysis tab provides information on datasets affected by the
>  pull request. By default, it will only show **directly affected** datasets…
>  In Java transforms, datasets are considered directly affected if their
>  source file is changed by the pull request." (p.53)

`code-repositories.md` §4.1 calls this the largest single gap in that file, and
says why: "Ours reviews text; Foundry reviews the consequences of text."

**p.53's Java rule is the one that translates**, and it is directly computable
here: a model's output dataset is `models.output_dataset_id`, so the datasets a
proposal directly affects are the outputs of the models whose files it changes.
Python's rule (Transforms Level Logic Versioning) is a Foundry build-system
artefact with nothing on this side to derive it from.

**The file list comes from `code.proposal_files` and not from either table.**
That function is the one place that knows a proposal has two shapes (db 0039),
and reading `code_proposal_files` directly here would make a commit-backed
proposal report no impact at all - which reads as "this changes nothing"
rather than as "this was not implemented".
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: A file in a proposal is in exactly one of these states, and the three are
#: different answers rather than degrees of one (§357's lesson, on a different
#: resource): a dataset to compare against, a transform that has never produced
#: one, or a file that would create a transform that does not exist yet.
AFFECTED = "affected"
NEVER_BUILT = "never_built"
NEW_TRANSFORM = "new_transform"


async def affected_datasets(
    conn: AsyncConnection,
    project_id: UUID,
    proposal_id: UUID,
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """p.53's list, one row per file the proposal changes.

    `files` is passed in rather than fetched because the caller has already
    resolved them - `proposal_files` is not free for a commit-backed proposal,
    and resolving them twice would let the impact list and the review surface
    disagree about what is being proposed.

    **Every file appears, including the ones with no dataset behind them.**
    Dropping them would make the list shorter than the diff and leave a reader
    to work out which files were silently not considered; p.53's own tab is a
    list of datasets, but a list that omits "this file has no dataset yet"
    answers a question nobody asked.
    """
    model_ids = [str(f["model_id"]) for f in files if f.get("model_id")]
    outputs: dict[str, dict[str, Any]] = {}
    if model_ids:
        rows = await fetch_all(
            conn,
            """
            -- An inner join, and the missing row *is* the "never built" answer.
            -- This was a LEFT JOIN with a second `dataset_id IS NULL` branch
            -- below, and the sweep could not tell the two apart: both paths
            -- produced the same row, so one of them was decoration. One way of
            -- saying it, and the branch that remains is reachable.
            --
            -- `m.project_id` is redundant and kept: RLS scopes `models` to
            -- projects the caller can reach, and the ids come from a proposal
            -- that is already project-scoped, so no test can make this clause
            -- matter. It is the house pattern for every scoped read here, and
            -- a scoped read that quietly stopped being scoped is not a thing
            -- to find out later (§213 — unfalsifiable, and said so).
            SELECT m.id AS model_id, m.name AS model_name,
                   d.id AS dataset_id, d.name AS dataset_name, d.slug AS dataset_slug,
                   d.row_count, d.current_version
              FROM models m
              JOIN datasets d ON d.id = m.output_dataset_id
             WHERE m.project_id = :pid AND m.id = ANY(CAST(:ids AS uuid[]))
            """,
            {"pid": str(project_id), "ids": "{" + ",".join(model_ids) + "}"},
        )
        outputs = {str(r["model_id"]): dict(r) for r in rows}

    out: list[dict[str, Any]] = []
    for entry in files:
        model_id = entry.get("model_id")
        if not model_id:
            # A commit-backed proposal may publish a file that creates a
            # transform which does not exist yet (db 0039 says so in its
            # header). There is no dataset to affect, and there is no missing
            # one either — saying "never built" here would describe a model
            # that is not there.
            out.append({
                "state": NEW_TRANSFORM,
                "model_id": None,
                "model_name": None,
                "path": entry.get("path"),
                "dataset": None,
            })
            continue
        row = outputs.get(str(model_id))
        if row is None:
            out.append({
                "state": NEVER_BUILT,
                "model_id": str(model_id),
                # From the file entry, because the row that would have carried
                # the model's name is the one that is not there.
                "model_name": entry.get("model_name"),
                "path": entry.get("path"),
                "dataset": None,
            })
            continue
        out.append({
            "state": AFFECTED,
            "model_id": str(model_id),
            "model_name": str(row["model_name"]),
            "path": entry.get("path"),
            "dataset": {
                "id": str(row["dataset_id"]),
                "name": str(row["dataset_name"]),
                "slug": str(row["dataset_slug"]),
                "row_count": int(row["row_count"]),
                "current_version": int(row["current_version"]),
            },
        })
    return out



async def schema_inputs(
    conn: AsyncConnection, project_id: UUID, model_id: UUID
) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    """What is needed to preview a proposed transform: the output dataset and
    the inputs it reads (§365; `code-repositories` p.54).

    Returns None when there is nothing to compare against — the same condition
    `affected_datasets` reports as `never_built`, asked here so the caller does
    not have to re-derive it from a list it may not be holding.
    """
    model = await fetch_one(
        conn,
        """
        SELECT m.id, m.output_dataset_id,
               d.id AS dataset_id, d.table_schema
          FROM models m
          JOIN datasets d ON d.id = m.output_dataset_id
         WHERE m.project_id = :pid AND m.id = :mid
        """,
        {"pid": str(project_id), "mid": str(model_id)},
    )
    if model is None:
        return None
    inputs = await fetch_all(
        conn,
        """
        SELECT mi.input_alias, d.id AS dataset_id, d.s3_location
          FROM model_inputs mi
          JOIN datasets d ON d.id = mi.dataset_id
         WHERE mi.model_id = :mid
         ORDER BY mi.input_alias
        """,
        {"mid": str(model_id)},
    )
    return dict(model), [dict(r) for r in inputs]
