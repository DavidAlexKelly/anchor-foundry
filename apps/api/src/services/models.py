"""Models service (spec §"Models — Optional Transform Layer", §16 models /
model_inputs / model_runs, §17 "Models: CRUD, code editor, trigger run, run
history, cancel").

Scope, each deviation flagged:
  * language='sql' runs execute inline in the request (the same sandboxed
    DuckDB path as queries) — an interactive result the caller waits for.
    language='python' needs a real process boundary DuckDB can't give it
    (see apps/worker's python_sandbox.py), so a python run is left
    'queued' by open_run() and the worker's scheduled_model_runs job picks
    it up; the route returns immediately rather than blocking on the
    worker's poll cycle.
  * trigger_mode='cron': the API only computes an initial next_run_at guess
    (lib/cron.py) when the schedule is set or changed; the worker
    recomputes it after every firing, since it's the process that actually
    observes "this just fired." trigger_mode='upstream' and the cancel
    endpoint remain out of scope — a synchronous SQL run has no meaningful
    cancel, and 'upstream' triggers belong with a real dependency graph,
    neither built here.
  * Run logs live in error_message/rows_produced; log_s3_key is written by
    the worker runtime for long runs.

Output semantics mirror connection sync: first successful run creates the
output dataset (origin='model_output', slug from the model name) and links
models.output_dataset_id; later runs append a dataset version and roll
current_version — model_runs.output_version points at the exact version each
run produced, which is what makes run history auditable against data.

Lineage (§"Models" lineage): model_inputs (dataset → model) plus
models.output_dataset_id (model → dataset) form the edges; walk() follows
them both ways from any dataset.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.cron import next_run_after
from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from . import dataset_engine as engine
from . import datasets as ds_service
from .storage import StorageGateway

_COLUMNS = """
    id, project_id, name, description, language, code, output_dataset_id,
    trigger_mode, cron_schedule, next_run_at, created_by, created_at, updated_at
"""


async def list_for_project(conn: AsyncConnection, project_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        f"""
        SELECT {_COLUMNS},
               (SELECT status FROM model_runs r WHERE r.model_id = models.id
                 ORDER BY r.queued_at DESC LIMIT 1) AS last_run_status,
               (SELECT r.finished_at FROM model_runs r WHERE r.model_id = models.id
                 ORDER BY r.queued_at DESC LIMIT 1) AS last_run_at
          FROM models WHERE project_id = :pid ORDER BY name
        """,
        {"pid": str(project_id)},
    )


async def get(conn: AsyncConnection, project_id: UUID, model_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"SELECT {_COLUMNS} FROM models WHERE id = :mid AND project_id = :pid",
        {"mid": str(model_id), "pid": str(project_id)},
    )
    if row is None:
        raise NotFoundError("model")
    return row


async def list_inputs(conn: AsyncConnection, model_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT mi.dataset_id, mi.input_alias, d.name AS dataset_name
          FROM model_inputs mi
          JOIN datasets d ON d.id = mi.dataset_id
         WHERE mi.model_id = :mid
         ORDER BY mi.input_alias
        """,
        {"mid": str(model_id)},
    )


async def _validate_and_set_inputs(
    conn: AsyncConnection,
    model_id: UUID,
    project_id: UUID,
    inputs: list[dict[str, Any]],
) -> None:
    """Replace the model's input set. Aliases are validated by the engine's
    rules; every dataset must live in the same project (cross-project reads
    would be a permission bypass)."""
    seen: set[str] = set()
    for item in inputs:
        alias = engine.validate_alias(str(item["input_alias"]))
        if alias in seen:
            raise ValueError(f"duplicate input alias {alias!r}")
        seen.add(alias)
        ds = await fetch_one(
            conn,
            "SELECT 1 AS x FROM datasets WHERE id = :did AND project_id = :pid",
            {"did": str(item["dataset_id"]), "pid": str(project_id)},
        )
        if ds is None:
            raise NotFoundError("input dataset")
    from sqlalchemy import text

    await conn.execute(
        text("DELETE FROM model_inputs WHERE model_id = :mid"), {"mid": str(model_id)}
    )
    for item in inputs:
        await conn.execute(
            text(
                """INSERT INTO model_inputs (model_id, dataset_id, input_alias)
                   VALUES (:mid, :did, :alias)"""
            ),
            {
                "mid": str(model_id),
                "did": str(item["dataset_id"]),
                "alias": str(item["input_alias"]),
            },
        )


async def create(
    conn: AsyncConnection,
    *,
    project_id: UUID,
    name: str,
    description: str,
    language: str,
    code: str,
    inputs: list[dict[str, Any]],
    created_by: UUID,
) -> dict[str, Any]:
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM models WHERE project_id = :pid AND name = :name",
        {"pid": str(project_id), "name": name},
    )
    if existing is not None:
        raise ConflictError("a model with this name already exists in this project")
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO models (project_id, name, description, language, code, created_by)
        VALUES (:pid, :name, :descr, CAST(:lang AS model_language), :code, :by)
        RETURNING {_COLUMNS}
        """,
        {
            "pid": str(project_id),
            "name": name,
            "descr": description,
            "lang": language,
            "code": code,
            "by": str(created_by),
        },
    )
    assert row is not None
    await _validate_and_set_inputs(conn, UUID(str(row["id"])), project_id, inputs)
    return dict(row)


async def update(
    conn: AsyncConnection,
    project_id: UUID,
    model_id: UUID,
    *,
    name: str | None,
    description: str | None,
    code: str | None,
    inputs: list[dict[str, Any]] | None,
    trigger_mode: str | None = None,
    cron_schedule: str | None = None,
) -> dict[str, Any]:
    await get(conn, project_id, model_id)
    if trigger_mode == "cron":
        if not cron_schedule:
            raise ValueError("cron_schedule is required when trigger_mode is 'cron'")
        next_run_at = next_run_after(cron_schedule)
    elif trigger_mode is not None:
        next_run_at = None  # switching away from cron clears any pending schedule
    else:
        next_run_at = None
    row = await fetch_one(
        conn,
        f"""
        UPDATE models
           SET name = COALESCE(:name, name),
               description = COALESCE(:descr, description),
               code = COALESCE(:code, code),
               trigger_mode = COALESCE(CAST(:trigger AS model_trigger), trigger_mode),
               cron_schedule = CASE WHEN :trigger = 'cron' THEN :cron
                                    WHEN :trigger IS NOT NULL THEN NULL
                                    ELSE cron_schedule END,
               next_run_at = CASE WHEN :trigger IS NOT NULL THEN :next_run_at
                                  ELSE next_run_at END
         WHERE id = :mid
        RETURNING {_COLUMNS}
        """,
        {
            "name": name, "descr": description, "code": code,
            "trigger": trigger_mode, "cron": cron_schedule, "next_run_at": next_run_at,
            "mid": str(model_id),
        },
    )
    assert row is not None
    if inputs is not None:
        await _validate_and_set_inputs(conn, model_id, project_id, inputs)
    return dict(row)


async def delete(conn: AsyncConnection, project_id: UUID, model_id: UUID) -> None:
    await get(conn, project_id, model_id)
    await fetch_one(
        conn, "DELETE FROM models WHERE id = :mid RETURNING id", {"mid": str(model_id)}
    )
    # The output dataset outlives the model deliberately: it holds real data
    # someone may depend on. models.output_dataset_id FK is SET NULL.


# ---- runs -------------------------------------------------------------------
async def open_run(
    conn: AsyncConnection, model_id: UUID, triggered_by: UUID
) -> UUID:
    """SQL runs only — the route executes the transform immediately after
    this call, so 'running'/started_at=now() is accurate the instant it's
    written. Python runs use open_queued_run instead: nothing executes them
    until the worker's poll picks the row up."""
    row = await fetch_one(
        conn,
        """
        INSERT INTO model_runs (model_id, status, triggered_by, trigger_kind, started_at)
        VALUES (:mid, 'running', :by, 'manual', now())
        RETURNING id
        """,
        {"mid": str(model_id), "by": str(triggered_by)},
    )
    assert row is not None
    return UUID(str(row["id"]))


async def open_queued_run(
    conn: AsyncConnection, model_id: UUID, triggered_by: UUID
) -> UUID:
    """Python runs: left at the table's default status='queued' with no
    started_at — that only gets set when the worker actually starts it."""
    row = await fetch_one(
        conn,
        """
        INSERT INTO model_runs (model_id, triggered_by, trigger_kind)
        VALUES (:mid, :by, 'manual')
        RETURNING id
        """,
        {"mid": str(model_id), "by": str(triggered_by)},
    )
    assert row is not None
    return UUID(str(row["id"]))


async def close_run(
    conn: AsyncConnection,
    run_id: UUID,
    *,
    ok: bool,
    rows_produced: int | None,
    output_version_id: UUID | None,
    error: str | None,
) -> None:
    await fetch_one(
        conn,
        """
        UPDATE model_runs
           SET status = :status, rows_produced = :rows, output_version = :ver,
               error_message = :error, finished_at = now()
         WHERE id = :id
        RETURNING id
        """,
        {
            "status": "succeeded" if ok else "failed",
            "rows": rows_produced,
            "ver": str(output_version_id) if output_version_id else None,
            "error": error,
            "id": str(run_id),
        },
    )


async def list_runs(conn: AsyncConnection, model_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT id, status, trigger_kind, queued_at, started_at, finished_at,
               rows_produced, error_message, output_version
          FROM model_runs
         WHERE model_id = :mid
         ORDER BY queued_at DESC
         LIMIT 50
        """,
        {"mid": str(model_id)},
    )


async def record_output(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    model: dict[str, Any],
    workspace_id: UUID,
    project_id: UUID,
    parquet_bytes: bytes,
    schema: list[engine.ColumnSchema],
    row_count: int,
    triggered_by: UUID,
) -> tuple[dict[str, Any], UUID]:
    """Create-or-version the model's output dataset; returns (dataset row,
    dataset_version id)."""
    import json

    schema_json = json.dumps([c.as_dict() for c in schema])
    ws_prefix = await ds_service.workspace_s3_prefix(conn, workspace_id)

    output_dataset_id = model.get("output_dataset_id")
    if output_dataset_id is None:
        dataset_id = uuid4()
        slug = ds_service.slugify(str(model["name"]))
        clash = await fetch_one(
            conn,
            "SELECT 1 AS x FROM datasets WHERE project_id = :pid AND slug = :slug",
            {"pid": str(project_id), "slug": slug},
        )
        if clash is not None:
            raise ConflictError(
                f"a dataset named '{slug}' already exists — rename the model or that dataset"
            )
        parquet_key = f"{ds_service.storage_prefix(ws_prefix, dataset_id)}v1/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        row = await fetch_one(
            conn,
            """
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                                  origin, s3_location, table_schema, row_count,
                                  current_version, created_by)
            VALUES (:id, :pid, :wid, :name, :slug, :descr, 'model_output', :loc,
                    CAST(:schema AS jsonb), :rows, 1, :by)
            RETURNING id, name, slug, row_count, current_version
            """,
            {
                "id": str(dataset_id),
                "pid": str(project_id),
                "wid": str(workspace_id),
                "name": str(model["name"]),
                "slug": slug,
                "descr": f"Produced by the model '{model['name']}'",
                "loc": parquet_key,
                "schema": schema_json,
                "rows": row_count,
                "by": str(triggered_by),
            },
        )
        assert row is not None
        version = 1
        from sqlalchemy import text

        await conn.execute(
            text("UPDATE models SET output_dataset_id = :did WHERE id = :mid"),
            {"did": str(dataset_id), "mid": str(model["id"])},
        )
    else:
        dataset_id = UUID(str(output_dataset_id))
        existing = await fetch_one(
            conn,
            "SELECT current_version FROM datasets WHERE id = :did",
            {"did": str(dataset_id)},
        )
        if existing is None:
            raise NotFoundError("output dataset")
        version = int(existing["current_version"]) + 1
        parquet_key = (
            f"{ds_service.storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
        )
        storage.put(parquet_key, parquet_bytes)
        row = await fetch_one(
            conn,
            """
            UPDATE datasets
               SET s3_location = :loc, table_schema = CAST(:schema AS jsonb),
                   row_count = :rows, current_version = :version
             WHERE id = :did
            RETURNING id, name, slug, row_count, current_version
            """,
            {
                "loc": parquet_key,
                "schema": schema_json,
                "rows": row_count,
                "version": version,
                "did": str(dataset_id),
            },
        )
        assert row is not None

    version_row = await fetch_one(
        conn,
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind,
                                      produced_by_id, created_by)
        VALUES (:did, :version, :key, CAST(:schema AS jsonb), :rows, 'model',
                :mid, :by)
        RETURNING id
        """,
        {
            "did": str(dataset_id),
            "version": version,
            "key": parquet_key,
            "schema": schema_json,
            "rows": row_count,
            "mid": str(model["id"]),
            "by": str(triggered_by),
        },
    )
    assert version_row is not None
    return dict(row), UUID(str(version_row["id"]))


# ---- lineage ----------------------------------------------------------------
async def lineage_for_dataset(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID
) -> dict[str, Any]:
    """Bidirectional walk over dataset↔model edges within the project.
    Returns nodes (datasets + models) and directed edges, plus a Mermaid
    rendering (§"Models": "Exportable as JSON or Mermaid diagram")."""
    await ds_service.get(conn, project_id, dataset_id)

    datasets_seen: dict[str, dict[str, Any]] = {}
    models_seen: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    frontier = [str(dataset_id)]

    while frontier:
        current = frontier.pop()
        if current in datasets_seen:
            continue
        row = await fetch_one(
            conn,
            "SELECT id, name, slug, origin FROM datasets WHERE id = :did",
            {"did": current},
        )
        if row is None:
            continue
        datasets_seen[current] = dict(row)

        # Upstream: the model that produces this dataset, and its inputs.
        producers = await fetch_all(
            conn,
            "SELECT id, name FROM models WHERE output_dataset_id = :did AND project_id = :pid",
            {"did": current, "pid": str(project_id)},
        )
        for m in producers:
            mid = str(m["id"])
            models_seen.setdefault(mid, dict(m))
            edges.append({"from": f"model:{mid}", "to": f"dataset:{current}"})
            for inp in await fetch_all(
                conn,
                "SELECT dataset_id, input_alias FROM model_inputs WHERE model_id = :mid",
                {"mid": mid},
            ):
                did = str(inp["dataset_id"])
                edges.append({"from": f"dataset:{did}", "to": f"model:{mid}"})
                frontier.append(did)

        # Downstream: models consuming this dataset, and their outputs.
        consumers = await fetch_all(
            conn,
            """
            SELECT m.id, m.name, m.output_dataset_id
              FROM model_inputs mi JOIN models m ON m.id = mi.model_id
             WHERE mi.dataset_id = :did AND m.project_id = :pid
            """,
            {"did": current, "pid": str(project_id)},
        )
        for m in consumers:
            mid = str(m["id"])
            models_seen.setdefault(mid, {"id": m["id"], "name": m["name"]})
            edges.append({"from": f"dataset:{current}", "to": f"model:{mid}"})
            if m["output_dataset_id"] is not None:
                out = str(m["output_dataset_id"])
                edges.append({"from": f"model:{mid}", "to": f"dataset:{out}"})
                frontier.append(out)

    unique_edges = [dict(t) for t in {tuple(sorted(e.items())) for e in edges}]

    def short(node_id: str) -> str:
        return node_id.replace("-", "")[:12]

    lines = ["graph LR"]
    for did, d in datasets_seen.items():
        lines.append(f'    D{short(did)}["{d["name"]}"]')
    for mid, m in models_seen.items():
        lines.append(f'    M{short(mid)}{{{{"{m["name"]}"}}}}')
    for e in sorted(unique_edges, key=lambda x: (x["from"], x["to"])):
        src_kind, src_id = e["from"].split(":", 1)
        dst_kind, dst_id = e["to"].split(":", 1)
        src = ("D" if src_kind == "dataset" else "M") + short(src_id)
        dst = ("D" if dst_kind == "dataset" else "M") + short(dst_id)
        lines.append(f"    {src} --> {dst}")

    return {
        "datasets": list(datasets_seen.values()),
        "models": list(models_seen.values()),
        "edges": unique_edges,
        "mermaid": "\n".join(lines),
    }
