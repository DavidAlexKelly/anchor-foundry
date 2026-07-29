"""Dataset compute - worker's copy of the DuckDB primitives apps/api's
dataset_engine.py already has, trimmed to what scheduled jobs need: running
a SQL transform (cron-triggered models the API isn't the one to execute)
and merging incremental sync rows into an existing dataset. Duplicated for
the same reason as storage.py - api and worker are independently deployable
images with no shared Python package in this build.
"""
from __future__ import annotations

import datetime as dt
import decimal
import os
from dataclasses import dataclass
from typing import Any

import duckdb

QUERY_MEMORY_LIMIT = "512MB"
MAX_TRANSFORM_OUTPUT_ROWS = 5_000_000  # matches the API's day-one cap


def json_safe(value: Any) -> Any:
    """Matches apps/api's services/dataset_engine.py exactly - values read
    back out of DuckDB must serialise the same way regardless of which side
    (API interactive sync, or worker scheduled sync) ran the extraction."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return str(value)


class DatasetEngineError(RuntimeError):
    """User-safe failure (bad SQL, bad file, too large)."""


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "data_type": self.data_type}


# Migration 0023 enforces a dataset's schema policy in a BEFORE INSERT
# trigger on dataset_versions and raises with this SQLSTATE. The worker has
# to translate it into a DatasetEngineError so the per-run/per-connection
# isolation records it as that item's failure instead of crashing the batch -
# the same bug STATUS §16 fixed for StorageKeyError. Kept in step with
# apps/api's services/datasets.py, which names the same constant.
SCHEMA_POLICY_SQLSTATE = "AF001"


def schema_policy_error(exc: Exception) -> "DatasetEngineError | None":
    """The user-safe error for a schema-policy refusal, or None if this
    database error is something else and must not be swallowed."""
    if getattr(exc, "sqlstate", None) != SCHEMA_POLICY_SQLSTATE:
        return None
    diag = getattr(exc, "diag", None)
    message = getattr(diag, "message_primary", None) or str(exc).splitlines()[0]
    hint = getattr(diag, "message_hint", None)
    return DatasetEngineError(message if not hint else f"{message} - {hint}")


def _clean(exc: duckdb.Error) -> str:
    text = str(exc).strip()
    first = text.splitlines()[0] if text else "query failed"
    return first[:500]


# Scheduled instance sync's row cap - the whole reason it runs in the worker
# rather than the interactive request/response cycle apps/api's
# services/instances.py's MAX_INSTANCE_SYNC_ROWS (20,000) is bounded by.
MAX_SCHEDULED_INSTANCE_SYNC_ROWS = 2_000_000


def extract_instance_rows(
    parquet_path: str,
    primary_key_column: str,
    column_mappings: dict[str, str],
    max_rows: int = MAX_SCHEDULED_INSTANCE_SYNC_ROWS,
) -> list[tuple[str, dict[str, Any]]]:
    """Worker copy of services/instances.py's extract_rows - same primary-key
    + mapped-column extraction, just with the worker's much larger row cap
    instead of the API's interactive one. Rows with a null primary key are
    skipped; they can't identify an instance."""
    source_columns = [primary_key_column] + list(column_mappings.keys())
    property_names = list(column_mappings.values())
    select_list = ", ".join(_quote(c) for c in source_columns)

    con = duckdb.connect()
    try:
        try:
            rows = con.execute(
                f"SELECT {select_list} FROM read_parquet({parquet_path!r}) LIMIT {max_rows + 1}"
            ).fetchall()
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()

    if len(rows) > max_rows:
        raise DatasetEngineError(f"dataset exceeds the {max_rows:,} row scheduled-sync limit")

    out: list[tuple[str, dict[str, Any]]] = []
    for row in rows:
        pk = row[0]
        if pk is None:
            continue
        properties = {property_names[i]: json_safe(row[i + 1]) for i in range(len(property_names))}
        out.append((str(pk), properties))
    return out


def diff_schemas(previous, current) -> dict | None:
    """Schema drift between the previous dataset version and the one about to
    be written (migration 0018). Mirrors the API's dataset_engine.diff_schemas;
    see its docstring and the migration for why the comparison is
    version-to-version rather than against a setup-time baseline."""
    if not previous:
        return None
    before = {c["name"]: c.get("data_type", "") for c in previous if c.get("name")}
    after = {c.name: c.data_type for c in current}

    added = [{"name": n, "data_type": after[n]} for n in after if n not in before]
    removed = [{"name": n, "data_type": before[n]} for n in before if n not in after]
    retyped = [
        {"name": n, "from": before[n], "to": after[n]}
        for n in after
        if n in before and before[n] != after[n]
    ]

    changes = {}
    if added:
        changes["added"] = added
    if removed:
        changes["removed"] = removed
    if retyped:
        changes["retyped"] = retyped
    return changes or None


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


TRANSFORM_BATCH_ROWS = 50_000


def run_sql_transform(
    inputs: dict[str, str], sql: str, dest_parquet: str
) -> tuple[list[ColumnSchema], int]:
    """Same sandboxed-input / trusted-output-writer split as the API's
    run_transform: user SQL only ever executes in the sandbox connection
    (inputs pre-materialised, external access switched off before it runs);
    the trusted writer connection never executes user SQL at all - it only
    receives already-computed rows via parameterised INSERT and writes them
    out, so a malicious transform can't reach the filesystem or network
    through the write path either."""
    sandbox = duckdb.connect()
    writer = duckdb.connect()
    try:
        sandbox.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        for alias, path in inputs.items():
            sandbox.execute(f'CREATE TABLE "{alias}" AS SELECT * FROM read_parquet({path!r})')
        sandbox.execute("SET enable_external_access=false")
        try:
            sandbox.execute(f"CREATE TABLE __output AS ({sql})")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        described = sandbox.execute("DESCRIBE __output").fetchall()
        if not described:
            raise DatasetEngineError("the transform produced no columns")
        schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
        row_count = int(sandbox.execute("SELECT count(*) FROM __output").fetchone()[0])
        if row_count > MAX_TRANSFORM_OUTPUT_ROWS:
            raise DatasetEngineError(
                f"the transform produced {row_count:,} rows - above this build's "
                f"{MAX_TRANSFORM_OUTPUT_ROWS:,} row limit"
            )

        columns_ddl = ", ".join(f'"{c.name}" {c.data_type}' for c in schema)
        writer.execute(f"CREATE TABLE __output ({columns_ddl})")
        placeholders = ", ".join("?" for _ in schema)
        cursor = sandbox.execute("SELECT * FROM __output")
        while True:
            batch = cursor.fetchmany(TRANSFORM_BATCH_ROWS)
            if not batch:
                break
            writer.executemany(f"INSERT INTO __output VALUES ({placeholders})", batch)
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        writer.execute(f"COPY __output TO {dest_parquet!r} (FORMAT parquet)")
        return schema, row_count
    finally:
        sandbox.close()
        writer.close()


def merge_incremental(
    existing_parquet: str | None,
    new_rows_parquet: str,
    primary_key_column: str,
    dest_parquet: str,
) -> tuple[list[ColumnSchema], int]:
    """Upsert new_rows into existing (by primary key) and write the merged
    result as a new version. No existing_parquet means this is the first
    sync - the new rows are the whole dataset."""
    con = duckdb.connect()
    try:
        try:
            con.execute(f"CREATE TABLE new_rows AS SELECT * FROM read_parquet({new_rows_parquet!r})")
            if existing_parquet is None:
                con.execute("CREATE TABLE merged AS SELECT * FROM new_rows")
            else:
                con.execute(
                    f"CREATE TABLE existing AS SELECT * FROM read_parquet({existing_parquet!r})"
                )
                pk = _quote(primary_key_column)
                con.execute(
                    f"""
                    CREATE TABLE merged AS
                    SELECT * FROM existing WHERE {pk} NOT IN (SELECT {pk} FROM new_rows)
                    UNION ALL
                    SELECT * FROM new_rows
                    """
                )
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        described = con.execute("DESCRIBE merged").fetchall()
        schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
        row_count = int(con.execute("SELECT count(*) FROM merged").fetchone()[0])
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        con.execute(f"COPY merged TO {dest_parquet!r} (FORMAT parquet)")
        return schema, row_count
    finally:
        con.close()


# ---- data quality expectations (migration 0020/0022) ------------------------
# An exact mirror of apps/api's services/dataset_engine.py evaluator, for the
# same reason as everything else in this file: api and worker are separately
# deployed images with no shared package. The worker needs it because
# migration 0022's input-health gate has to hold on *every* path a model run
# can start from - and the automated ones (cron, upstream triggers, queued
# Python) all start here. A gate that only held on the interactive API path
# would be the same silently-does-nothing promise 0021 existed to remove.
#
# tests/test_model_runs.py asserts RULE_TYPES is identical on both sides, the
# same parity check test_mysql_sync_configs.py makes for the connector
# registry. Any rule added to the API's evaluator must be added here too.

RULE_TYPES = ("not_null", "unique", "value_in_range", "regex_match", "column_exists")


def evaluate_expectations(
    parquet_path: str, rules: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Check each rule against a version's data (migration 0020).

    Returns one result per rule, in the order given, each with a status of
    `pass`, `fail`, or `error`. `error` is distinct from `fail` on purpose: a
    rule that cannot be evaluated (its column is gone, its regex is invalid)
    has not proven the data bad, and reporting that as a data failure would
    send someone looking in the wrong place.

    One rule failing never stops the others - a dataset's health is the whole
    picture, and the first broken rule is the least useful place to stop.
    """
    con = duckdb.connect()
    try:
        try:
            con.execute(
                f"CREATE VIEW src AS SELECT * FROM read_parquet('{parquet_path}')"
            )
            columns = {str(row[0]) for row in con.execute("DESCRIBE src").fetchall()}
            total = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        results: list[dict[str, Any]] = []
        for rule in rules:
            results.append(_evaluate_one(con, rule, columns, total))
        return results
    finally:
        con.close()


def _evaluate_one(
    con: "duckdb.DuckDBPyConnection",
    rule: dict[str, Any],
    columns: set[str],
    total: int,
) -> dict[str, Any]:
    rule_type = str(rule.get("rule_type"))
    column = str(rule.get("column_name") or "")
    config = rule.get("config") or {}
    if isinstance(config, str):
        import json

        try:
            config = json.loads(config)
        except ValueError:
            config = {}

    base = {
        "expectation_id": str(rule.get("id")) if rule.get("id") is not None else None,
        "rule_type": rule_type,
        "column_name": column,
        "severity": str(rule.get("severity") or "error"),
        "failing_rows": 0,
        "rows_checked": total,
    }

    if rule_type == "column_exists":
        present = column in columns
        return {
            **base,
            "status": "pass" if present else "fail",
            "message": None if present else f"column '{column}' is missing",
        }

    # Every other rule needs the column to be there to mean anything. Missing
    # is an `error`, not a `fail`: add a column_exists rule to assert presence.
    if column not in columns:
        return {
            **base,
            "status": "error",
            "message": f"column '{column}' is not in this version",
        }

    quoted = '"' + column.replace('"', '""') + '"'
    try:
        if rule_type == "not_null":
            failing = _scalar(con, f"SELECT count(*) FROM src WHERE {quoted} IS NULL")
            message = f"{failing} null value(s)" if failing else None
        elif rule_type == "unique":
            # Rows beyond the first occurrence of each value - nulls excluded,
            # since SQL uniqueness does not constrain them.
            failing = _scalar(
                con,
                f"SELECT count({quoted}) - count(DISTINCT {quoted}) FROM src",
            )
            message = f"{failing} duplicate value(s)" if failing else None
        elif rule_type == "value_in_range":
            minimum, maximum = config.get("min"), config.get("max")
            if minimum is None and maximum is None:
                return {
                    **base,
                    "status": "error",
                    "message": "value_in_range needs a min, a max, or both",
                }
            clauses = []
            if minimum is not None:
                clauses.append(f"{quoted} < {_number(minimum)}")
            if maximum is not None:
                clauses.append(f"{quoted} > {_number(maximum)}")
            predicate = " OR ".join(clauses)
            failing = _scalar(
                con,
                f"SELECT count(*) FROM src WHERE {quoted} IS NOT NULL AND ({predicate})",
            )
            message = f"{failing} value(s) outside the range" if failing else None
        elif rule_type == "regex_match":
            pattern = config.get("pattern")
            if not isinstance(pattern, str) or not pattern:
                return {**base, "status": "error", "message": "regex_match needs a pattern"}
            escaped = pattern.replace("'", "''")
            failing = _scalar(
                con,
                f"SELECT count(*) FROM src WHERE {quoted} IS NOT NULL "
                f"AND NOT regexp_matches(CAST({quoted} AS VARCHAR), '{escaped}')",
            )
            message = f"{failing} value(s) do not match" if failing else None
        else:
            return {**base, "status": "error", "message": f"unknown rule type '{rule_type}'"}
    except duckdb.Error as exc:
        # A rule that cannot run against this column's type (a range check on
        # text, a bad regex) is the rule's problem, not the data's.
        return {**base, "status": "error", "message": _clean(exc)}

    return {
        **base,
        "failing_rows": failing,
        "status": "pass" if failing == 0 else "fail",
        "message": message,
    }


def _scalar(con: "duckdb.DuckDBPyConnection", sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0] or 0) if row else 0


def _number(value: Any) -> str:
    """A numeric literal for a range bound. Anything non-numeric is refused
    rather than interpolated - this is the one place rule config reaches SQL."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DatasetEngineError("range bounds must be numbers")
    return repr(float(value))


def overall_status(results: list[dict[str, Any]]) -> str:
    """A dataset's health from its rule results.

    `fail` if any error-severity rule failed, `warn` if only warn-severity
    ones did or a rule could not be evaluated, `pass` otherwise, and `none`
    when there are no rules - which is different from passing, and shows
    differently.
    """
    if not results:
        return "none"
    statuses = {(r.get("status"), r.get("severity")) for r in results}
    if any(status == "fail" and severity == "error" for status, severity in statuses):
        return "fail"
    if any(status in ("fail", "error") for status, _ in statuses):
        return "warn"
    return "pass"
