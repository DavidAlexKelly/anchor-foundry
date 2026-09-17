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


#: How far downstream `derived_chain` will walk (`code-repositories` p.54).
#:
#: p.54 says "all intermediate datasets between the selected dataset and the
#: affected datasets", which is unbounded in a document describing a product
#: with a build system behind it. Each hop here is a *preview*, so the work
#: grows with the depth and a pipeline twenty deep would make opening a review
#: cost twenty transform runs. Bounded, with the bound reported, because a
#: short answer presented as a whole one is the thing §364 refused.
MAX_DERIVED_DEPTH = 3


async def derived_chain(
    conn: AsyncConnection,
    project_id: UUID,
    dataset_id: UUID,
    *,
    max_depth: int = MAX_DERIVED_DEPTH,
) -> list[dict[str, Any]]:
    """The datasets built *from* an affected one, nearest first
    (`code-repositories` p.54; §372).

    > "Clicking on Add datasets to analysis will analyze the pull request's
    >  impact on derived datasets. All intermediate datasets between the
    >  selected dataset and the affected datasets will be added as well." (p.54)

    One row per derived dataset, carrying the model that builds it and that
    model's *other* inputs — everything a chained preview needs, so the caller
    makes one round trip rather than one per hop.

    **`UNION`, not `UNION ALL`**, which is `models._check_cycle`'s reason too: a
    cycle already in the project would otherwise make this walk run forever.
    The depth column is what makes "nearest first" meaningful, and it is also
    the bound — see `MAX_DERIVED_DEPTH`.
    """
    rows = await fetch_all(
        conn,
        """
        WITH RECURSIVE downstream(dataset_id, model_id, depth) AS (
            SELECT m.output_dataset_id, m.id, 1
              FROM model_inputs mi
              JOIN models m ON m.id = mi.model_id
             WHERE mi.dataset_id = CAST(:did AS uuid)
               AND m.project_id = :pid
               AND m.output_dataset_id IS NOT NULL
            UNION
            SELECT m.output_dataset_id, m.id, d.depth + 1
              FROM downstream d
              JOIN model_inputs mi ON mi.dataset_id = d.dataset_id
              JOIN models m ON m.id = mi.model_id
             WHERE m.project_id = :pid
               AND m.output_dataset_id IS NOT NULL
               AND d.depth < :depth
        )
        SELECT DISTINCT ON (ds.id)
               d.depth, d.model_id, m.name AS model_name, m.code,
               ds.id AS dataset_id, ds.name AS dataset_name, ds.table_schema
          FROM downstream d
          JOIN models m ON m.id = d.model_id
          JOIN datasets ds ON ds.id = d.dataset_id
         -- The dataset that started the walk can come back around through a
         -- cycle; it is the thing being analysed, not something derived from
         -- it, and listing it as its own consequence would be nonsense.
         --
         -- **Deliberately unfalsifiable, and said so** (§213, following §364's
         -- `m.project_id` clause). `models._check_cycle` refuses to create one,
         -- so no test here can build the state this excludes — but the `UNION`
         -- above exists for the same reason and this module is not the place
         -- that decides whether a cycle can pre-exist. A guard that is dead
         -- because something else holds is worth keeping when the cost of
         -- being wrong is a walk that reports a dataset as derived from itself.
         WHERE ds.id <> CAST(:did AS uuid)
         ORDER BY ds.id, d.depth
        """,
        {"did": str(dataset_id), "pid": str(project_id), "depth": max_depth},
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        inputs = await fetch_all(
            conn,
            """
            SELECT mi.input_alias, d.id AS dataset_id, d.s3_location
              FROM model_inputs mi
              JOIN datasets d ON d.id = mi.dataset_id
             WHERE mi.model_id = :mid
             ORDER BY mi.input_alias
            """,
            {"mid": str(row["model_id"])},
        )
        out.append({**dict(row), "inputs": [dict(i) for i in inputs]})
    # Nearest first, because p.54's "intermediate datasets between" is an order
    # a reader follows, and the whole point of the row is reading a change
    # outwards from where it lands.
    out.sort(key=lambda r: (int(r["depth"]), str(r["dataset_name"]).lower()))
    return out


async def unbuilt_consumers(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID
) -> list[dict[str, Any]]:
    """Transforms that read this dataset and have never produced one.

    **`derived_chain` cannot include them and must not hide them** — §364's
    rule, one layer further out. A transform with no output has nothing to
    chain a preview into and no stored schema to diff against, so there is no
    impact to report; but it is still something the change reaches, and a list
    that quietly dropped it would be shorter than the consequences and give a
    reader no way to know which were left out.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT DISTINCT m.id AS model_id, m.name AS model_name
          FROM model_inputs mi
          JOIN models m ON m.id = mi.model_id
         WHERE mi.dataset_id = CAST(:did AS uuid)
           AND m.project_id = :pid
           AND m.output_dataset_id IS NULL
         ORDER BY m.name
        """,
        {"did": str(dataset_id), "pid": str(project_id)},
    )
    return [dict(r) for r in rows]
