"""Models service (spec §"Models - Optional Transform Layer", §16 models /
model_inputs / model_runs, §17 "Models: CRUD, code editor, trigger run, run
history, cancel").

Scope, each deviation flagged:
  * language='sql' runs execute inline in the request (the same sandboxed
    DuckDB path as queries) - an interactive result the caller waits for.
    language='python' needs a real process boundary DuckDB can't give it
    (see apps/worker's python_sandbox.py), so a python run is left
    'queued' by open_run() and the worker's scheduled_model_runs job picks
    it up; the route returns immediately rather than blocking on the
    worker's poll cycle.
  * trigger_mode='cron': the API only computes an initial next_run_at guess
    (lib/cron.py) when the schedule is set or changed; the worker
    recomputes it after every firing, since it's the process that actually
    observes "this just fired." trigger_mode='upstream' is the same shape
    with a different due-ness test - the worker polls
    models.upstream_watermark against the model's input dataset versions
    (migration 0021); the API only clears the watermark when the trigger
    mode changes, so switching a model to 'upstream' fires it once and then
    reacts to genuinely new data. The cancel endpoint remains out of scope:
    a synchronous SQL run has no meaningful cancel.
  * Run logs live in error_message/rows_produced; log_s3_key is written by
    the worker runtime for long runs.

Output semantics mirror connection sync: first successful run creates the
output dataset (origin='model_output', slug from the model name) and links
models.output_dataset_id; later runs append a dataset version and roll
current_version - model_runs.output_version points at the exact version each
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
    trigger_mode, cron_schedule, next_run_at, upstream_watermark,
    input_health_policy, created_by, created_at, updated_at
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


async def _insert_version(conn: AsyncConnection, sql: str, params: dict[str, Any]) -> Any:
    """Append a dataset_versions row, translating migration 0023's schema
    policy refusal into a DatasetEngineError. The callers here own a run
    record that has to be closed truthfully, so the refusal must land in
    their existing failure handling rather than escaping as a database error
    - see services/datasets.py `schema_policy_error`."""
    from sqlalchemy.exc import DBAPIError

    try:
        return await fetch_one(conn, sql, params)
    except DBAPIError as exc:
        raise (ds_service.schema_policy_error(exc) or exc) from exc


async def _refuse_cycles(
    conn: AsyncConnection,
    model_id: UUID,
    project_id: UUID,
    inputs: list[dict[str, Any]],
) -> None:
    """Refuse an input set that would make the model depend on its own output
    (roadmap Models item 7).

    The pipeline graph already *reports* cycles (services/pipeline.py); this
    is the other half. A cycle matters beyond being confusing: a model in one
    with trigger_mode='upstream' re-fires on every worker pass forever, since
    each run produces a version the loop is watching. Migration 0021's
    self-loop guard only covers a model reading its own output directly - it
    cannot see A -> B -> A, because it only ever looks at one model's inputs.

    Checked at edit time, and only here, because that is the only moment a
    cycle can appear. A model's output dataset is created by its first run
    and nothing points at a brand-new dataset yet, so running a model can
    never close a loop that saving it did not.

    **Existing cycles are grandfathered**, deliberately: this validates the
    proposed input set, so a loop created before this existed keeps working
    until someone edits one of its models, at which point the edit is refused
    until they break it. Force-breaking on next edit would mean silently
    deleting an input somebody configured on purpose; the Pipeline page names
    the loop instead, which is a better place to be told.
    """
    row = await fetch_one(
        conn,
        "SELECT output_dataset_id FROM models WHERE id = :mid",
        {"mid": str(model_id)},
    )
    output_dataset_id = None if row is None else row["output_dataset_id"]
    if output_dataset_id is None:
        return  # nothing downstream of a model that has never produced anything

    # Every dataset reachable downstream of this model's output. UNION, not
    # UNION ALL: a pre-existing cycle elsewhere in the project would
    # otherwise make this walk run forever.
    reachable = await fetch_all(
        conn,
        """
        WITH RECURSIVE downstream AS (
            SELECT CAST(:out AS uuid) AS dataset_id
            UNION
            SELECT m.output_dataset_id
              FROM downstream d
              JOIN model_inputs mi ON mi.dataset_id = d.dataset_id
              JOIN models m ON m.id = mi.model_id
             WHERE m.output_dataset_id IS NOT NULL
               AND m.project_id = :pid
        )
        SELECT d.dataset_id, ds.name
          FROM downstream d JOIN datasets ds ON ds.id = d.dataset_id
        """,
        {"out": str(output_dataset_id), "pid": str(project_id)},
    )
    downstream = {str(r["dataset_id"]): str(r["name"]) for r in reachable}

    offending = [
        downstream[str(item["dataset_id"])]
        for item in inputs
        if str(item["dataset_id"]) in downstream
    ]
    if offending:
        raise ValueError(
            f"this would create a dependency loop: {', '.join(sorted(set(offending)))} "
            "is produced downstream of this model, so it cannot also be an input"
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
    await _refuse_cycles(conn, model_id, project_id, inputs)
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


# ---- definition history (migration 0024) ------------------------------------
_VERSION_COLUMNS = "id, model_id, version_number, code, inputs, restored_from, created_by, created_at"


def _inputs_snapshot(inputs: list[dict[str, Any]]) -> str:
    """The stored form of an input set: dataset ids and aliases only, alias
    ordered so two saves of the same set compare equal regardless of the
    order they arrived in."""
    import json

    return json.dumps(
        sorted(
            (
                {"dataset_id": str(i["dataset_id"]), "input_alias": str(i["input_alias"])}
                for i in inputs
            ),
            key=lambda i: i["input_alias"],
        )
    )


async def _record_definition(
    conn: AsyncConnection,
    model_id: UUID,
    *,
    code: str,
    inputs: list[dict[str, Any]],
    created_by: UUID,
    restored_from: int | None = None,
    change_set_id: UUID | None = None,
) -> dict[str, Any]:
    """Append a definition version. Numbering is max+1 within the model, read
    in the caller's transaction - two concurrent edits to one model would
    collide on the (model_id, version_number) unique index rather than
    silently interleave, which is the failure we want."""
    row = await fetch_one(
        conn,
        f"""
        INSERT INTO model_versions (model_id, version_number, code, inputs,
                                    restored_from, created_by, change_set_id)
        VALUES (:mid,
                COALESCE((SELECT max(version_number) FROM model_versions
                           WHERE model_id = :mid), 0) + 1,
                :code, CAST(:inputs AS jsonb), :restored, :by, :cset)
        RETURNING {_VERSION_COLUMNS}
        """,
        {
            "mid": str(model_id), "code": code, "inputs": _inputs_snapshot(inputs),
            "restored": restored_from, "by": str(created_by),
            "cset": str(change_set_id) if change_set_id else None,
        },
    )
    assert row is not None
    return dict(row)


async def list_versions(
    conn: AsyncConnection, project_id: UUID, model_id: UUID
) -> list[dict[str, Any]]:
    await get(conn, project_id, model_id)
    return await fetch_all(
        conn,
        f"""
        SELECT {_VERSION_COLUMNS},
               (SELECT u.email FROM users u WHERE u.id = model_versions.created_by)
                   AS created_by_email
          FROM model_versions WHERE model_id = :mid
         ORDER BY version_number DESC
        """,
        {"mid": str(model_id)},
    )


async def restore_version(
    conn: AsyncConnection,
    project_id: UUID,
    model_id: UUID,
    version_number: int,
    *,
    restored_by: UUID,
) -> dict[str, Any]:
    """Set the model's code and inputs back to an earlier version, and record
    that as a *new* version rather than rewinding the pointer (migration
    0024). History stays a true record, and a run stamped with a version
    still resolves to exactly one piece of code however many times someone
    has rolled back.

    Restoring goes through the same input validation a normal edit does: the
    graph may have changed since, so an input set that was legal then can
    close a dependency loop now, and it must be refused the same way.
    """
    await get(conn, project_id, model_id)
    version = await fetch_one(
        conn,
        f"SELECT {_VERSION_COLUMNS} FROM model_versions "
        "WHERE model_id = :mid AND version_number = :v",
        {"mid": str(model_id), "v": version_number},
    )
    if version is None:
        raise NotFoundError("model version")

    stored = version["inputs"]
    if isinstance(stored, str):
        import json

        stored = json.loads(stored)
    inputs = [dict(i) for i in (stored or [])]

    await _validate_and_set_inputs(conn, model_id, project_id, inputs)
    row = await fetch_one(
        conn,
        f"UPDATE models SET code = :code WHERE id = :mid RETURNING {_COLUMNS}",
        {"code": version["code"], "mid": str(model_id)},
    )
    assert row is not None
    await _record_definition(
        conn, model_id, code=str(version["code"]), inputs=inputs,
        created_by=restored_by, restored_from=version_number,
    )
    return dict(row)


async def current_version_id(conn: AsyncConnection, model_id: UUID) -> UUID | None:
    row = await fetch_one(
        conn,
        "SELECT id FROM model_versions WHERE model_id = :mid "
        "ORDER BY version_number DESC LIMIT 1",
        {"mid": str(model_id)},
    )
    return None if row is None else UUID(str(row["id"]))


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
    model_id = UUID(str(row["id"]))
    await _validate_and_set_inputs(conn, model_id, project_id, inputs)
    # Version 1 exists from the moment the model does, so "every model has at
    # least one definition version" holds everywhere and no read path has to
    # special-case an empty history (migration 0024 backfilled the same
    # invariant onto every model that predates it).
    await _record_definition(
        conn, model_id, code=code, inputs=inputs, created_by=created_by
    )
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
    input_health_policy: str | None = None,
    updated_by: UUID,
    # Set only by the Code pillar's multi-model save (services/code.py), which
    # groups the versions one edit produced. Every other caller writes a
    # standalone version, and migration 0030 keeps that the honest default:
    # a single-model save was not part of a change set, rather than part of
    # an unknown one.
    change_set_id: UUID | None = None,
) -> dict[str, Any]:
    before = await get(conn, project_id, model_id)
    before_inputs = await list_inputs(conn, model_id)
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
                                  ELSE next_run_at END,
               -- Changing the trigger mode at all resets the upstream
               -- watermark: switching to 'upstream' should fire once
               -- promptly (0021's NULL = '-infinity' convention), and
               -- switching away should not leave a stale watermark that
               -- silently swallows the first version after switching back.
               upstream_watermark = CASE WHEN :trigger IS NOT NULL THEN NULL
                                         ELSE upstream_watermark END,
               input_health_policy = COALESCE(
                   CAST(:health_policy AS model_health_policy), input_health_policy)
         WHERE id = :mid
        RETURNING {_COLUMNS}
        """,
        {
            "name": name, "descr": description, "code": code,
            "trigger": trigger_mode, "cron": cron_schedule, "next_run_at": next_run_at,
            "health_policy": input_health_policy, "mid": str(model_id),
        },
    )
    assert row is not None
    if inputs is not None:
        await _validate_and_set_inputs(conn, model_id, project_id, inputs)

    # Only a change to what the model *computes* makes a new version. Trigger
    # mode, schedule, health policy, name and description are how and when it
    # runs, and versioning those would fill the history with entries nobody
    # would ever roll back to (migration 0024).
    effective_inputs = inputs if inputs is not None else [
        {"dataset_id": i["dataset_id"], "input_alias": i["input_alias"]}
        for i in before_inputs
    ]
    if str(row["code"]) != str(before["code"]) or (
        inputs is not None
        and _inputs_snapshot(effective_inputs) != _inputs_snapshot([
            {"dataset_id": i["dataset_id"], "input_alias": i["input_alias"]}
            for i in before_inputs
        ])
    ):
        await _record_definition(
            conn, model_id, code=str(row["code"]), inputs=effective_inputs,
            created_by=updated_by, change_set_id=change_set_id,
        )

    if row["trigger_mode"] == "upstream" and not await list_inputs(conn, model_id):
        # Checked after the input replacement above, so a single PATCH may set
        # the mode and the inputs together. An upstream model with no inputs
        # has nothing to watch and would never fire - the exact silent
        # no-op 0021 exists to remove, so it is refused rather than stored.
        raise ValueError(
            "trigger_mode 'upstream' needs at least one input dataset to watch"
        )
    return dict(row)


async def delete(conn: AsyncConnection, project_id: UUID, model_id: UUID) -> None:
    await get(conn, project_id, model_id)
    await fetch_one(
        conn, "DELETE FROM models WHERE id = :mid RETURNING id", {"mid": str(model_id)}
    )
    # The output dataset outlives the model deliberately: it holds real data
    # someone may depend on. models.output_dataset_id FK is SET NULL.


# ---- input health gating (migration 0022) -----------------------------------
async def check_input_health(
    conn: AsyncConnection,
    storage: StorageGateway,
    *,
    project_id: UUID,
    model_id: UUID,
    policy: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Evaluate every input dataset's health and decide whether the run may
    proceed. Returns (what the gate saw, refusal message or None).

    The gate is the "reader" migration 0020 said expectations were missing:
    it computes health when nothing has cached it, so `block` is enforced
    against data nobody has opened - the automated case that most needs it.
    That is also its cost: one DuckDB pass per input the first time each
    version is seen.

    `ignore` short-circuits before any of that, so an ungated model pays
    nothing.
    """
    import anyio

    from . import expectations

    if policy == "ignore":
        return [], None

    seen: list[dict[str, Any]] = []
    for item in await list_inputs(conn, model_id):
        dataset_id = UUID(str(item["dataset_id"]))
        ds_row = await ds_service.get(conn, project_id, dataset_id)
        version = int(ds_row["current_version"])
        health = await expectations.cached_health(conn, dataset_id, version)
        if health is None:
            rules = await expectations.list_rules(conn, project_id, dataset_id)
            path = await anyio.to_thread.run_sync(
                storage.local_path, str(ds_row["s3_location"])
            )
            health = await anyio.to_thread.run_sync(
                expectations.evaluate, path, [dict(r) for r in rules]
            )
            await expectations.store_health(conn, dataset_id, version, health)
        seen.append({
            "dataset_id": str(dataset_id),
            "name": str(ds_row["name"]),
            "version": version,
            "status": str(health.get("status", "none")),
            "failing": expectations.failing_summary(health),
        })

    return seen, gate_message(seen, policy)


def gate_message(seen: list[dict[str, Any]], policy: str) -> str | None:
    """The refusal, or None if the run may proceed. Only `fail` gates - see
    migration 0022 on why `warn` and `none` do not."""
    if policy != "block":
        return None
    bad = [s for s in seen if s["status"] == "fail"]
    if not bad:
        return None
    detail = "; ".join(f"{s['name']} ({', '.join(s['failing']) or 'failed its checks'})" for s in bad)
    return (
        f"blocked: {len(bad)} input dataset(s) failed their data quality checks - {detail}"
    )


# ---- runs -------------------------------------------------------------------
def _json_or_null(value: list[dict[str, Any]] | None) -> str | None:
    """An empty gate result is stored as NULL, not `[]`: migration 0022 reads
    NULL as "this run was not gated", and a model with no inputs under a
    `warn` policy has nothing to say either way."""
    import json

    return json.dumps(value) if value else None


async def open_run(
    conn: AsyncConnection,
    model_id: UUID,
    triggered_by: UUID,
    input_health: list[dict[str, Any]] | None = None,
) -> UUID:
    """SQL runs only - the route executes the transform immediately after
    this call, so 'running'/started_at=now() is accurate the instant it's
    written. Python runs use open_queued_run instead: nothing executes them
    until the worker's poll picks the row up."""
    row = await fetch_one(
        conn,
        """
        INSERT INTO model_runs (model_id, status, triggered_by, trigger_kind,
                                started_at, input_health, model_version)
        VALUES (:mid, 'running', :by, 'manual', now(), CAST(:health AS jsonb), :ver)
        RETURNING id
        """,
        {"mid": str(model_id), "by": str(triggered_by),
         "health": _json_or_null(input_health),
         "ver": str(await current_version_id(conn, model_id) or "") or None},
    )
    assert row is not None
    return UUID(str(row["id"]))


async def open_queued_run(
    conn: AsyncConnection,
    model_id: UUID,
    triggered_by: UUID,
    input_health: list[dict[str, Any]] | None = None,
) -> UUID:
    """Python runs: left at the table's default status='queued' with no
    started_at - that only gets set when the worker actually starts it."""
    row = await fetch_one(
        conn,
        """
        INSERT INTO model_runs (model_id, triggered_by, trigger_kind, input_health,
                                model_version)
        VALUES (:mid, :by, 'manual', CAST(:health AS jsonb), :ver)
        RETURNING id
        """,
        {"mid": str(model_id), "by": str(triggered_by),
         "health": _json_or_null(input_health),
         "ver": str(await current_version_id(conn, model_id) or "") or None},
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
               rows_produced, error_message, output_version, input_health,
               model_version
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
                f"a dataset named '{slug}' already exists - rename the model or that dataset"
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

    version_row = await _insert_version(
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
