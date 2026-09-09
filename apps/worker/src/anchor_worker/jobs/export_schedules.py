"""Scheduled exports (decision 0016; `data-connection` p.205).

§265 built the export, the runner and the manual button and left the schedule
owed; `data-connection.md`'s row named it as the one piece of build-order item
3 still missing. p.205:

    "Exports should be scheduled to run regularly, exporting recent data to
     the external destination."

One op, on its own schedule: for every export whose cron is due (db
`list_due_exports`), write the dataset's current version to the destination and
record a run. Same discover-then-verify pattern as the other jobs — the
SECURITY DEFINER function enumerates candidates across every workspace, and the
actual read and write happen through a workspace-scoped connection that
re-checks the export is still due and still allowed.

**Two things here are not decoration and both come from earlier findings.**

`list_due_exports()` joins `connections.exports_enabled` rather than trusting
that a scheduled export could not exist without it — decision 0013 §3's
send-time-versus-save-time argument, which exists because two of its four
original outbound paths had been reasoned about the same way and were wrong.
Turning p.202's switch off stops the schedule without touching it.

And every export is run inside its own `try`, with `EgressRefused` listed
*separately* from `ConnectorError`. §263 found that exact bug in
`sync_configs`: a refused destination is deliberately not a `ConnectorError`,
so it escaped an enumerated `except` and took every other candidate down with
it. A scheduled export is the one path with no caller to notice.

Note: deliberately no `from __future__ import annotations` here - see
jobs/model_runs.py's docstring for why (breaks Dagster's `@op` context
validation under PEP 563).
"""

import json
from datetime import datetime, timezone

from croniter import croniter
from dagster import OpExecutionContext, job, op

from .. import export_runs
from ..resources import PlatformDatabase
from ..storage import StorageKeyError, gateway_from_env


def _json(value):
    """A jsonb column as a Python object whichever way the driver returned it.

    The API's `export_store._clean` makes the same normalisation and gives the
    reason: a caller that forgot would get `"{}".get("table")`, an
    AttributeError a long way from its cause.
    """
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            return json.loads(value or "{}")
        except ValueError:
            return {}
    return value


def _schema_list(value):
    parsed = _json(value)
    return parsed if isinstance(parsed, list) else []


@op
def run_due_exports(context: OpExecutionContext, platform_db: PlatformDatabase) -> int:
    with platform_db.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT export_id, workspace_id FROM list_due_exports()")
            candidates = cur.fetchall()

    ran = 0
    for export_id, workspace_id in candidates:
        try:
            if _run_one(context, platform_db, export_id, workspace_id):
                ran += 1
        except Exception as exc:  # pragma: no cover - one export must not end the op
            # **The §263 lesson, one level up.** `perform` already returns a
            # result rather than raising, so reaching here means something
            # outside the export itself went wrong - a missing dataset file, a
            # storage error. Whatever it is, the next candidate still runs.
            context.log.warning("scheduled export %s could not run: %s", export_id, exc)
    return ran


def _run_one(context, platform_db, export_id, workspace_id) -> bool:
    """One export, start to finish. Returns whether it ran at all."""
    storage = gateway_from_env()

    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.name, e.kind, e.mode, e.destination, e.last_version,
                       e.schedule, e.connection_id,
                       c.source_type, c.config, c.secret_arn, c.exports_enabled,
                       d.current_version, d.id
                  FROM exports e
                  JOIN connections c ON c.id = e.connection_id
                  JOIN datasets d ON d.id = e.dataset_id
                 WHERE e.id = %s
                """,
                (str(export_id),),
            )
            row = cur.fetchone()
            if row is None:
                return False
            (name, kind, mode, destination, last_version, schedule, connection_id,
             source_type, config, secret_arn, exports_enabled,
             current_version, dataset_id) = row
            # Re-verified after discovery, both halves: the schedule may have
            # been cleared and the source's switch may have been turned off
            # between the enumeration and now.
            if schedule is None or not exports_enabled:
                return False
            if not current_version:
                # A dataset with no versions has nothing to export. Not a
                # failure and not a run — the API's route refuses it with a
                # sentence to somebody who pressed a button, and there is
                # nobody here to tell.
                return False

            # **The version's file and the version's schema, not the dataset's**
            # — the same two columns the API's run route reads. A schema taken
            # from anywhere else could disagree with the parquet in hand, and
            # p.197's 1:1 check is done against it.
            cur.execute(
                "SELECT table_schema, s3_manifest_key FROM dataset_versions"
                " WHERE dataset_id = %s AND version_number = %s",
                (str(dataset_id), current_version),
            )
            version_row = cur.fetchone()
            dataset_schema = _schema_list(version_row[0]) if version_row else []
            manifest_key = str(version_row[1] or "") if version_row else ""

            # §263: the source's egress policies, read in the same scoped
            # transaction as the row they belong to. A scheduled export has no
            # caller to inherit an ambient scope from.
            cur.execute(
                "SELECT host, port, description FROM egress_policies WHERE connection_id = %s",
                (connection_id,),
            )
            policies = [
                {"host": h, "port": p, "description": d} for h, p, d in cur.fetchall()
            ]
        conn.commit()

    export = {
        "name": name,
        "kind": kind,
        "mode": mode,
        "destination": _json(destination),
        "last_version": last_version,
    }
    connection = {"source_type": source_type, "config": _json(config)}
    secret = _read_secret(secret_arn)

    # Three ways this comes back empty and they end in the same place: no
    # version row, a version row with no recorded key, or a key whose bytes are
    # gone. All three are an export that could not read its input, which
    # `perform` turns into a **recorded failure** rather than an exception. The
    # exception list is enumerated rather than bare, for the reason §263
    # relearned in this worker: a broad `except` would also swallow a bug in
    # the lookup and report it as a missing file.
    parquet_path = None
    if manifest_key:
        try:
            parquet_path = storage.local_path(manifest_key)
        except (StorageKeyError, FileNotFoundError, OSError):
            parquet_path = None

    outcome = export_runs.perform(
        export, connection, secret,
        parquet_path=parquet_path,
        dataset_version=int(current_version or 0),
        dataset_schema=dataset_schema,
        policies=policies,
    )

    _record(platform_db, workspace_id, export_id, outcome)
    _advance(context, platform_db, workspace_id, export_id, schedule)
    context.log.info(
        "scheduled export %s (%s): %s", export_id, name,
        "skipped" if outcome["skipped"] else ("succeeded" if outcome["ok"] else f"failed ({outcome['error']})"),
    )
    return True


def _record(platform_db, workspace_id, export_id, outcome) -> None:
    """One row per run, including the one where nothing happened.

    p.192 makes "nothing new" a success, and a success that left no row would
    make a schedule's history read as gaps — "nothing happened" and "nothing
    ran" being exactly the two answers somebody reading that list is trying to
    tell apart. §267's screen says `nothing new (v7)` off this row.

    `last_version` moves only on a success, which is the API's rule and the
    reason a failed run leaves a retry with work to do.

    **`GREATEST` stopped being untestable with this unit.** The API's copy
    carries a note saying its harness cannot kill a mutant that removes it,
    because every test there makes one request at a time and the interleaving
    never occurs. A schedule changes that: a manual run and a scheduled one can
    now genuinely overlap, and the one that read v5 can commit after the one
    that read v6. The line is the same; what it guards against is now reachable.
    """
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            # **`run_by` is NULL, and that is the only column that differs from
            # a manual run.** Nobody pressed this. `duration_ms` and `detail`
            # are on the result and not in the table — the API's `record` drops
            # them too, and the two writers must produce the same row or the
            # history stops being one list.
            cur.execute(
                """
                INSERT INTO export_runs
                    (export_id, status, skipped, dataset_version, rows_written,
                     error, finished_at, run_by)
                VALUES (%s, %s, %s, %s, %s, %s, now(), NULL)
                """,
                (
                    str(export_id),
                    "succeeded" if outcome["ok"] else "failed",
                    outcome["skipped"],
                    outcome["dataset_version"],
                    outcome["rows_written"],
                    outcome["error"],
                ),
            )
            # The API's condition exactly, including why there is no
            # `not skipped` clause: `GREATEST` already makes a skip a no-op,
            # and a second copy of a rule is a second chance to state it
            # differently.
            if outcome["ok"] and outcome["dataset_version"]:
                cur.execute(
                    "UPDATE exports SET last_version = GREATEST(COALESCE(last_version, 0), %s)"
                    " WHERE id = %s",
                    (int(outcome["dataset_version"]), str(export_id)),
                )
        conn.commit()


def _advance(context, platform_db, workspace_id, export_id, schedule) -> None:
    """Move `next_run_at` on, whatever happened.

    Regardless of outcome, for `sync_configs`' reason: a failing destination
    should not be retried every poll cycle faster than its own cadence.
    """
    with platform_db.connect_scoped_to(workspace_id) as conn:
        with conn.cursor() as cur:
            try:
                next_run = croniter(schedule, datetime.now(timezone.utc)).get_next(datetime)
                cur.execute(
                    "UPDATE exports SET next_run_at = %s WHERE id = %s",
                    (next_run, str(export_id)),
                )
            except (ValueError, KeyError):
                context.log.warning(
                    "export %s has an invalid schedule %r", export_id, schedule
                )
        conn.commit()


def _read_secret(secret_arn):
    if not secret_arn:
        return {}
    import boto3

    client = boto3.client("secretsmanager")
    raw = client.get_secret_value(SecretId=secret_arn)["SecretString"]
    return json.loads(raw)


@job
def scheduled_exports():
    run_due_exports()
