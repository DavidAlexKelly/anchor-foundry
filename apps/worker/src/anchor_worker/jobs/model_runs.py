"""Model run execution (spec: cron-triggered models, and the "isolated
worker runtime" Python transforms need).

Two ops, run in sequence:
  1. enqueue_due_cron_models — for every cron model due to fire, creates a
     queued model_runs row and advances the model's next_run_at to the next
     occurrence (croniter; this is the only place in the platform that
     parses cron expressions after the fact — the API only computes an
     initial guess when a schedule is first set).
  2. execute_queued_model_runs — for every queued run, whatever put it there
     (a cron firing above, or the API leaving a Python run 'queued' since it
     never executes those inline), runs the transform and records the
     result: SQL through the same sandboxed-DuckDB path the API uses
     in-process; Python through python_sandbox's subprocess isolation.

Both discover candidates via a SECURITY DEFINER function (workspace-blind
enumeration across every workspace) and re-verify/act on each one through a
workspace-scoped connection — the discovery bypass is never trusted for the
actual mutation, same pattern as workspace_cleanup.

Note: deliberately no `from __future__ import annotations` here — Dagster's
`@op` decorator validates the `context: OpExecutionContext` parameter by
identity, which breaks under PEP 563 postponed evaluation (the annotation
arrives as the string "OpExecutionContext" rather than the class). Every
other module in this codebase uses the future import; this file and
jobs/sync_configs.py are the deliberate exception.
"""

import json
import os
import tempfile
from datetime import datetime, timezone
from uuid import UUID, uuid4

from croniter import croniter
from dagster import OpExecutionContext, job, op

from .. import dataset_engine as engine
from ..python_sandbox import run_python_transform
from ..resources import PlatformDatabase
from ..storage import gateway_from_env, slugify, storage_prefix


def _workspace_s3_prefix(cur, workspace_id: UUID) -> str:
    cur.execute("SELECT s3_prefix FROM workspaces WHERE id = %s", (str(workspace_id),))
    row = cur.fetchone()
    if row is None:
        raise LookupError(f"workspace {workspace_id} not found")
    return row[0]


def _record_output(
    cur,
    storage,
    *,
    model_id: UUID,
    model_name: str,
    output_dataset_id: UUID | None,
    project_id: UUID,
    workspace_id: UUID,
    parquet_bytes: bytes,
    schema: list[engine.ColumnSchema],
    row_count: int,
) -> tuple[UUID, UUID]:
    """Create-or-version the model's output dataset. Mirrors apps/api's
    services/models.py record_output exactly (same columns, same
    produced_by_kind='model'), just via a synchronous psycopg cursor
    instead of an async SQLAlchemy connection."""
    schema_json = json.dumps([c.as_dict() for c in schema])
    ws_prefix = _workspace_s3_prefix(cur, workspace_id)

    if output_dataset_id is None:
        dataset_id = uuid4()
        slug = slugify(model_name)
        cur.execute(
            "SELECT 1 FROM datasets WHERE project_id = %s AND slug = %s",
            (str(project_id), slug),
        )
        if cur.fetchone() is not None:
            raise engine.DatasetEngineError(
                f"a dataset named '{slug}' already exists — rename the model or that dataset"
            )
        version = 1
        parquet_key = f"{storage_prefix(ws_prefix, dataset_id)}v1/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        cur.execute(
            """
            INSERT INTO datasets (id, project_id, workspace_id, name, slug, description,
                                  origin, s3_location, table_schema, row_count,
                                  current_version, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, 'model_output', %s, %s, %s, 1, NULL)
            """,
            (
                str(dataset_id), str(project_id), str(workspace_id), model_name, slug,
                f"Produced by the model '{model_name}'", parquet_key, schema_json, row_count,
            ),
        )
        cur.execute("UPDATE models SET output_dataset_id = %s WHERE id = %s", (str(dataset_id), str(model_id)))
    else:
        dataset_id = output_dataset_id
        cur.execute("SELECT current_version FROM datasets WHERE id = %s", (str(dataset_id),))
        row = cur.fetchone()
        if row is None:
            raise engine.DatasetEngineError("output dataset no longer exists")
        version = int(row[0]) + 1
        parquet_key = f"{storage_prefix(ws_prefix, dataset_id)}v{version}/data.parquet"
        storage.put(parquet_key, parquet_bytes)
        cur.execute(
            """
            UPDATE datasets
               SET s3_location = %s, table_schema = %s, row_count = %s, current_version = %s
             WHERE id = %s
            """,
            (parquet_key, schema_json, row_count, version, str(dataset_id)),
        )

    cur.execute(
        """
        INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                      table_schema, row_count, produced_by_kind, produced_by_id)
        VALUES (%s, %s, %s, %s, %s, 'model', %s)
        RETURNING id
        """,
        (str(dataset_id), version, parquet_key, schema_json, row_count, str(model_id)),
    )
    version_id = cur.fetchone()[0]
    return dataset_id, version_id


def _enqueue_due_cron_models(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT model_id, workspace_id FROM list_due_cron_models()")
            candidates = cur.fetchall()

    enqueued = 0
    for model_id, workspace_id in candidates:
        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT trigger_mode, cron_schedule FROM models WHERE id = %s", (model_id,)
                )
                row = cur.fetchone()
                if row is None or row[0] != "cron" or not row[1]:
                    continue  # changed since discovery — re-verified, matches cleanup's pattern
                cron_schedule = row[1]
                try:
                    next_run = croniter(cron_schedule, datetime.now(timezone.utc)).get_next(datetime)
                except (ValueError, KeyError):
                    context.log.warning("model %s has an invalid cron_schedule %r", model_id, cron_schedule)
                    continue
                cur.execute(
                    "INSERT INTO model_runs (model_id, trigger_kind) VALUES (%s, 'cron')", (model_id,)
                )
                cur.execute("UPDATE models SET next_run_at = %s WHERE id = %s", (next_run, model_id))
            conn.commit()
        enqueued += 1
    context.log.info("enqueued %d cron model run(s)", enqueued)
    return enqueued


def _execute_queued_model_runs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    storage = gateway_from_env()
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT run_id, workspace_id FROM list_queued_model_runs()")
            candidates = cur.fetchall()

    executed = 0
    for run_id, workspace_id in candidates:
        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT mr.status, mr.model_id, m.project_id, m.language, m.code,
                           m.name, m.output_dataset_id
                      FROM model_runs mr
                      JOIN models m ON m.id = mr.model_id
                     WHERE mr.id = %s
                    """,
                    (run_id,),
                )
                row = cur.fetchone()
                if row is None or row[0] != "queued":
                    continue  # already handled or gone — re-verified
                (_, model_id, project_id, language, code, model_name, output_dataset_id) = row
                cur.execute(
                    "UPDATE model_runs SET status = 'running', started_at = now() WHERE id = %s",
                    (run_id,),
                )
                cur.execute(
                    """
                    SELECT mi.input_alias, d.s3_location
                      FROM model_inputs mi
                      JOIN datasets d ON d.id = mi.dataset_id
                     WHERE mi.model_id = %s
                    """,
                    (model_id,),
                )
                input_rows = cur.fetchall()
            conn.commit()

        ok, error, rows_produced, output_version_id = True, None, 0, None
        try:
            if not str(code).strip():
                raise engine.DatasetEngineError("the model has no code")
            if not input_rows:
                raise engine.DatasetEngineError("the model has no input datasets")
            input_paths = {alias: storage.local_path(loc) for alias, loc in input_rows}
            with tempfile.TemporaryDirectory() as tmp:
                dest = os.path.join(tmp, "out.parquet")
                if language == "sql":
                    schema, rows_produced = engine.run_sql_transform(input_paths, code, dest)
                else:
                    schema, rows_produced = run_python_transform(input_paths, code, dest)
                with open(dest, "rb") as handle:
                    parquet_bytes = handle.read()

            with platform_db.connect_scoped_to(workspace_id) as conn:
                with conn.cursor() as cur:
                    _, output_version_id = _record_output(
                        cur, storage,
                        model_id=UUID(str(model_id)), model_name=model_name,
                        output_dataset_id=UUID(str(output_dataset_id)) if output_dataset_id else None,
                        project_id=UUID(str(project_id)), workspace_id=UUID(str(workspace_id)),
                        parquet_bytes=parquet_bytes, schema=schema, row_count=rows_produced,
                    )
                conn.commit()
        except (engine.DatasetEngineError, FileNotFoundError) as exc:
            ok, error = False, str(exc)

        with platform_db.connect_scoped_to(workspace_id) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE model_runs
                       SET status = %s, finished_at = now(), rows_produced = %s,
                           error_message = %s, output_version = %s
                     WHERE id = %s
                    """,
                    (
                        "succeeded" if ok else "failed",
                        rows_produced if ok else None,
                        error,
                        str(output_version_id) if output_version_id else None,
                        run_id,
                    ),
                )
            conn.commit()
        context.log.info("model run %s: %s", run_id, "succeeded" if ok else f"failed ({error})")
        executed += 1
    return executed


@op
def run_model_runs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    """Enqueues due cron models, then executes every queued run (however it
    got there — a cron firing above, or the API leaving a Python run
    'queued' since it never executes those inline). One op, not two: the
    second step must always see the first's inserts in the same poll pass,
    and Dagster op-to-op data passing isn't needed for that — just calling
    both in sequence is simpler and equally correct."""
    _enqueue_due_cron_models(context, platform_db)
    return _execute_queued_model_runs(context, platform_db)


@job
def scheduled_model_runs():
    run_model_runs()
