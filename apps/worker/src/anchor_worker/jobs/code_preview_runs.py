"""Previewing a queued Python transform (§390; db 0092).

**This job exists because the API must not do this**, which is the same
sentence `code_test_runs` opens with and the same decision behind it:
`docs/decisions/0004-running-customer-code.md` confines customer Python to a
process that cannot obtain the platform's credentials. A SQL preview stays a
plain request — DuckDB in the API's own sandbox with external access off — and
a Python one cannot be, so it becomes a row somebody watches. db 0071's header
quotes the refusal this closes; this is that sentence's other half.

**What the job does *not* do is read the declaration.** The API resolves
`{alias: dataset_id}` when it queues the run, because `transform_declarations`
lives there and a second parser for a syntax with one writer is §292's failure
waiting to happen. So a file naming a dataset the project does not have is
refused at the button with the name in the message, and this job's inputs are
already ids.

**The sample is the point and the warning travels with it.** Each input is cut
to `PREVIEW_SAMPLE_ROWS` before the transform sees it, and both numbers — what
was there and what was read — are stored, because a join or a `group by` over
a sample finds fewer matches and smaller groups than the real run will. A
preview that reported a row count without saying it was sampled would be
confidently wrong, which is worse than slow.

Note: deliberately no `from __future__ import annotations` here — see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
import os
import tempfile
from datetime import datetime, timezone

from dagster import OpExecutionContext, job, op

from .. import dataset_engine as engine
from ..storage import gateway_from_env
from ..transform_dispatch import run_python_transform
from ..resources import PlatformDatabase


def _json(value):
    """The stored JSON as a dict whichever way the driver returned it —
    `code_test_runs._files`' normalisation, for the reason it gives."""
    if isinstance(value, str):
        return json.loads(value or "{}")
    return value or {}


@op
def run_queued_preview_runs(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT run_id, workspace_id FROM list_queued_preview_runs()")
            candidates = cur.fetchall()

    ran = 0
    for run_id, workspace_id in candidates:
        try:
            if _run_one(context, platform_db, run_id, workspace_id):
                ran += 1
        except Exception as exc:  # pragma: no cover - one run must not end the op
            # §263: whatever went wrong outside the run itself, the next
            # candidate still gets its turn.
            context.log.warning("preview %s could not be processed: %s", run_id, exc)
    return ran


def _run_one(context, platform_db, run_id, workspace_id) -> bool:
    """One preview, start to finish. Returns whether it ran at all."""
    storage = gateway_from_env()
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            # **Claimed, not just read** — `code_test_runs._run_one`'s reason:
            # two workers polling the same minute would otherwise both run the
            # same buffer and both write an answer.
            cur.execute(
                """
                UPDATE code_preview_runs
                   SET status = 'running', started_at = now()
                 WHERE id = %s AND status = 'queued'
             RETURNING content, input_datasets
                """,
                (str(run_id),),
            )
            claimed = cur.fetchone()
            if claimed is None:
                return False
            content, raw_inputs = claimed

            wanted = _json(raw_inputs)
            located = {}
            if wanted:
                cur.execute(
                    "SELECT id, s3_location FROM datasets WHERE id = ANY(%s)",
                    ([str(v) for v in wanted.values()],),
                )
                located = {str(i): loc for i, loc in cur.fetchall()}
        conn.commit()

        missing = sorted(a for a, d in wanted.items() if str(d) not in located)
        if missing:
            # Resolved when the run was queued and gone by the time it ran —
            # rare, and an answer about the platform's state rather than about
            # the author's code, so `errored`.
            _finish(
                conn, run_id, status="errored", result=None, inputs=None,
                error=(
                    "the datasets this transform reads are no longer here: "
                    + ", ".join(missing)
                ),
            )
            return True

        # The temp directory wraps the `except` for §358's reason, one step
        # over: the runner writes its log in here, and the run that most needs
        # one is the run that raised.
        with tempfile.TemporaryDirectory() as tmp:
            log_file = os.path.join(tmp, "preview.log")
            sampled = {}
            previewed = []
            try:
                for alias, dataset_id in sorted(wanted.items()):
                    src = storage.local_path(located[str(dataset_id)])
                    dest = os.path.join(tmp, f"in_{alias}.parquet")
                    available, used = engine.sample_parquet(src, dest)
                    sampled[alias] = dest
                    previewed.append(
                        {"alias": alias, "rows_available": available, "rows_used": used}
                    )

                out = os.path.join(tmp, "out.parquet")
                run_python_transform(sampled, content, out, log_path=log_file)
                result = engine.read_preview_rows(out)
            except engine.DatasetEngineError as exc:
                # **The author's transform raised, which is an answer about
                # their code on their data** — db 0092's `failed`, not
                # `errored`. `transform_dispatch` prefixes an infrastructure
                # failure, so the two survive in the text; the status says
                # which kind of problem it is and the message says whose.
                _finish(
                    conn, run_id, status="failed",
                    result={"columns": [], "rows": [], "error": str(exc)[:2000]},
                    inputs=previewed or None, error=None,
                )
                context.log.info("preview %s raised: %s", run_id, exc)
                return True
            except Exception as exc:  # pragma: no cover - defensive
                _finish(
                    conn, run_id, status="errored", result=None, inputs=None,
                    error=f"the platform could not preview this transform: {exc}"[:1000],
                )
                return True

            _finish(
                conn, run_id, status="succeeded", result=result,
                inputs=previewed, error=None,
            )
            context.log.info(
                "preview %s: %s rows over %s input(s)",
                run_id, len(result["rows"]), len(previewed),
            )
            return True


def _finish(conn, run_id, *, status, result, inputs, error) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE code_preview_runs
               SET status = %s,
                   result = CAST(%s AS jsonb),
                   inputs = CAST(%s AS jsonb),
                   error = %s,
                   finished_at = %s
             WHERE id = %s
            """,
            (
                status,
                None if result is None else json.dumps(result),
                None if inputs is None else json.dumps(inputs),
                error,
                datetime.now(timezone.utc),
                str(run_id),
            ),
        )
    conn.commit()


@job
def scheduled_preview_runs():
    run_queued_preview_runs()
