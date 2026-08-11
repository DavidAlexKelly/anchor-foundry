"""Dataset compute (spec §"Models" execution: "DuckDB for small-medium
datasets ... Athena over S3/Iceberg for large datasets").

This module is the DuckDB half. Files above the interactive size cap get a
clear message pointing at export instead of a hung request - the Athena path
arrives with the production data plane. All functions are synchronous; routes
run them on a worker thread.

Query sandboxing: user SQL runs only after the dataset is materialised into
an in-memory table and `enable_external_access` is switched off, so
read_csv('/etc/passwd'), COPY TO, httpfs and every other filesystem/network
door is closed. Writes to the ephemeral in-memory database are harmless.
"""
from __future__ import annotations

import datetime as dt
import decimal
import os
from dataclasses import dataclass
from typing import Any

import duckdb

MAX_INTERACTIVE_BYTES = 200 * 1024 * 1024  # flag: Athena beyond this in prod
MAX_RESULT_ROWS = 500
PREVIEW_ROWS = 100
QUERY_MEMORY_LIMIT = "512MB"

_READERS: dict[str, str] = {
    ".csv": "read_csv_auto({path!r})",
    ".tsv": "read_csv_auto({path!r}, delim='\\t')",
    ".parquet": "read_parquet({path!r})",
    ".json": "read_json_auto({path!r})",
    ".jsonl": "read_json_auto({path!r}, format='newline_delimited')",
}

SUPPORTED_EXTENSIONS = tuple(_READERS)


class DatasetEngineError(RuntimeError):
    """User-safe failure (bad file, bad SQL, too large)."""


@dataclass(frozen=True)
class ColumnSchema:
    name: str
    data_type: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "data_type": self.data_type}


@dataclass(frozen=True)
class TabularResult:
    columns: list[ColumnSchema]
    rows: list[list[Any]]
    total_rows: int
    truncated: bool


def _reader_expr(src_path: str, extension: str) -> str:
    template = _READERS.get(extension.lower())
    if template is None:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise DatasetEngineError(
            f"unsupported file type {extension!r} (supported: {supported})"
        )
    return template.format(path=src_path)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    return str(value)


def ingest_to_parquet(src_path: str, extension: str, dest_path: str) -> tuple[list[ColumnSchema], int]:
    """Convert an uploaded file to canonical Parquet; returns (schema, rows)."""
    reader = _reader_expr(src_path, extension)
    con = duckdb.connect()
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        try:
            con.execute(f"CREATE VIEW src AS SELECT * FROM {reader}")
            con.execute(f"COPY src TO '{dest_path}' (FORMAT parquet)")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        schema = [
            ColumnSchema(name=row[0], data_type=row[1])
            for row in con.execute("DESCRIBE src").fetchall()
        ]
        row_count = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        return schema, row_count
    finally:
        con.close()


def diff_schemas(
    previous: list[dict[str, str]] | None, current: list[ColumnSchema]
) -> dict[str, Any] | None:
    """Schema drift between the previous dataset version and the one about to
    be written (roadmap Connections item 6, migration 0018).

    `previous` is a stored `table_schema` jsonb array (or None for a dataset's
    first version). Returns None when there is nothing to report - no baseline,
    or no change - so a caller can store the result directly and
    `schema_changes IS NOT NULL` means "this run drifted".

    Column order is deliberately not drift: a source reordering its SELECT
    changes nothing about what downstream consumers can read, and reporting it
    would bury the changes that do matter.
    """
    if not previous:
        return None
    before = {c["name"]: c.get("data_type", "") for c in previous if c.get("name")}
    after = {c.name: c.data_type for c in current}

    added = [
        {"name": name, "data_type": after[name]} for name in after if name not in before
    ]
    removed = [
        {"name": name, "data_type": before[name]} for name in before if name not in after
    ]
    retyped = [
        {"name": name, "from": before[name], "to": after[name]}
        for name in after
        if name in before and before[name] != after[name]
    ]

    changes: dict[str, Any] = {}
    if added:
        changes["added"] = added
    if removed:
        changes["removed"] = removed
    if retyped:
        changes["retyped"] = retyped
    return changes or None


def describe_file(src_path: str, extension: str) -> list[ColumnSchema]:
    """Column names/types of a source file without converting it.

    Same readers as ingest_to_parquet, so what a connector reports at
    discovery time is what the file will actually land with - but DESCRIBE
    only, since discovery inspects files it has no intention of ingesting."""
    reader = _reader_expr(src_path, extension)
    con = duckdb.connect()
    try:
        try:
            con.execute(f"CREATE VIEW src AS SELECT * FROM {reader}")
            return [
                ColumnSchema(name=row[0], data_type=row[1])
                for row in con.execute("DESCRIBE src").fetchall()
            ]
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def profile_columns(parquet_path: str) -> list[dict[str, Any]]:
    """Per-column statistics for a dataset version (migration 0019).

    One pass over the file computing every column's aggregates at once, rather
    than a query per column: DuckDB reads the Parquet once and the whole thing
    stays a single scan even on a wide table.

    min/max come back as text because the result has to hold whatever each
    column's type is in one JSON array, and this is display metadata - nothing
    computes against it. Types DuckDB cannot order (structs, lists, maps -
    ordinary in a JSON source) get NULL min/max rather than failing the whole
    profile; the null rate and distinct count are still meaningful for them.
    """
    con = duckdb.connect()
    try:
        try:
            con.execute(
                f"CREATE VIEW src AS SELECT * FROM read_parquet('{parquet_path}')"
            )
            described = con.execute("DESCRIBE src").fetchall()
            total = int(con.execute("SELECT count(*) FROM src").fetchone()[0])
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        if not described:
            return []

        selects: list[str] = []
        for name, data_type, *_ in described:
            quoted = '"' + str(name).replace('"', '""') + '"'
            selects.append(f"count({quoted})")
            selects.append(f"count(DISTINCT {quoted})")
            if _is_orderable(str(data_type)):
                selects.append(f"CAST(min({quoted}) AS VARCHAR)")
                selects.append(f"CAST(max({quoted}) AS VARCHAR)")
            else:
                # Kept in the projection so the row stays a fixed 4-per-column
                # stride and the unpacking below doesn't need to branch.
                selects.append("NULL")
                selects.append("NULL")

        try:
            row = con.execute(f"SELECT {', '.join(selects)} FROM src").fetchone()
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        profile: list[dict[str, Any]] = []
        for index, (name, data_type, *_) in enumerate(described):
            non_null, distinct, minimum, maximum = row[index * 4 : index * 4 + 4]
            non_null = int(non_null or 0)
            null_count = total - non_null
            profile.append(
                {
                    "name": str(name),
                    "data_type": str(data_type),
                    "null_count": null_count,
                    # Rounded rather than raw: this is rendered as a percentage
                    # and a full float would put 17 digits on screen.
                    "null_rate": round(null_count / total, 6) if total else 0.0,
                    "distinct_count": int(distinct or 0),
                    "min": None if minimum is None else str(minimum),
                    "max": None if maximum is None else str(maximum),
                }
            )
        return profile
    finally:
        con.close()


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


def _is_orderable(data_type: str) -> bool:
    """Whether min()/max() mean anything for this DuckDB type. Nested types
    (STRUCT, LIST/[], MAP, UNION) either error or produce something useless."""
    upper = data_type.upper()
    return not (
        upper.endswith("[]")
        or upper.startswith("STRUCT")
        or upper.startswith("MAP")
        or upper.startswith("UNION")
        or upper == "JSON"
    )


def preview(parquet_path: str, limit: int = PREVIEW_ROWS) -> TabularResult:
    limit = max(1, min(limit, MAX_RESULT_ROWS))
    con = duckdb.connect()
    try:
        try:
            cursor = con.execute(
                f"SELECT * FROM read_parquet('{parquet_path}') LIMIT {limit}"
            )
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        columns = [ColumnSchema(name=d[0], data_type=str(d[1])) for d in cursor.description]
        rows = [[json_safe(v) for v in row] for row in cursor.fetchall()]
        total = int(
            con.execute(f"SELECT count(*) FROM read_parquet('{parquet_path}')").fetchone()[0]
        )
        return TabularResult(columns=columns, rows=rows, total_rows=total, truncated=total > len(rows))
    finally:
        con.close()


def query(parquet_path: str, sql: str, max_rows: int = MAX_RESULT_ROWS) -> TabularResult:
    """Run user SQL with the dataset available as the table `dataset`."""
    size = os.path.getsize(parquet_path)
    if size > MAX_INTERACTIVE_BYTES:
        raise DatasetEngineError(
            "this dataset is too large for interactive queries in this build - "
            "use export, or a model transform"
        )
    max_rows = max(1, min(max_rows, MAX_RESULT_ROWS))
    con = duckdb.connect()
    try:
        con.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        con.execute(f"CREATE TABLE dataset AS SELECT * FROM read_parquet('{parquet_path}')")
        # Sandbox boundary: from here on, no filesystem or network access.
        con.execute("SET enable_external_access=false")
        try:
            cursor = con.execute(sql)
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
        if cursor.description is None:
            raise DatasetEngineError("only queries that return rows are supported here")
        columns = [ColumnSchema(name=d[0], data_type=str(d[1])) for d in cursor.description]
        rows_raw = cursor.fetchmany(max_rows + 1)
        truncated = len(rows_raw) > max_rows
        rows = [[json_safe(v) for v in row] for row in rows_raw[:max_rows]]
        return TabularResult(columns=columns, rows=rows, total_rows=len(rows), truncated=truncated)
    finally:
        con.close()


def export_csv(parquet_path: str, dest_path: str) -> None:
    con = duckdb.connect()
    try:
        try:
            con.execute(
                f"COPY (SELECT * FROM read_parquet('{parquet_path}')) TO '{dest_path}' "
                "(FORMAT csv, HEADER true)"
            )
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def merge_incremental(
    existing_parquet: str | None,
    new_rows_parquet: str,
    primary_key_column: str,
    dest_parquet: str,
) -> tuple[list[ColumnSchema], int]:
    """Upsert an incremental sync's new/changed rows into the existing
    dataset by primary key, writing the merged result as a new version. No
    existing_parquet means this is the connection's first incremental run -
    the new rows are the whole dataset."""
    con = duckdb.connect()
    try:
        try:
            con.execute(
                f"CREATE TABLE new_rows AS SELECT * FROM read_parquet({new_rows_parquet!r})"
            )
            if existing_parquet is None:
                con.execute("CREATE TABLE merged AS SELECT * FROM new_rows")
            else:
                con.execute(
                    f"CREATE TABLE existing AS SELECT * FROM read_parquet({existing_parquet!r})"
                )
                pk = f'"{primary_key_column}"'
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
        schema = [
            ColumnSchema(name=row[0], data_type=row[1])
            for row in con.execute("DESCRIBE merged").fetchall()
        ]
        row_count = int(con.execute("SELECT count(*) FROM merged").fetchone()[0])
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        con.execute(f"COPY merged TO {dest_parquet!r} (FORMAT parquet)")
        return schema, row_count
    finally:
        con.close()


def _clean(exc: duckdb.Error) -> str:
    """First line of DuckDB's message: precise about the SQL/file problem,
    never contains paths beyond the one we passed in."""
    text = str(exc).strip()
    first = text.splitlines()[0] if text else "query failed"
    return first[:500]


def _quote_column(name: str) -> str:
    """Dataset column names come from uploaded file headers, not a fixed
    identifier grammar - quote-and-escape rather than assume unquoted-safe."""
    return '"' + name.replace('"', '""') + '"'


def write_rows(
    parquet_path: str,
    primary_key_column: str,
    updates: list[tuple[str, dict[str, Any]]],
    appends: list[dict[str, Any]],
    dest_path: str,
    deletes: list[str] | None = None,
) -> tuple[list[ColumnSchema], int]:
    """Apply a set of row updates and row appends, and write **one** file.

    Decision 0008: an action is "a single transaction" (Foundry `action-types`
    p.2), and in a Parquet-backed dataset that means one output file and one
    version however many rows an action touched. Three versions with the same
    `produced_by_id` would be a history that has to be interpreted rather than
    read, and a failure between them would leave a dataset nobody asked for.

    Every write lands in one DuckDB table before anything is copied out, so a
    failure on the third row leaves the file on disk untouched - there is no
    half-written output to clean up, because the output is written last.

    **An append whose primary key already exists is refused.** Instance identity
    is `(source_id, primary_key)`, so a duplicate key would produce two objects
    that no query could tell apart - the same failure the STATUS note about two
    sources feeding one object type describes, arrived at from the other side.
    """
    con = duckdb.connect()
    try:
        try:
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({parquet_path!r})")
            pk_col = _quote_column(primary_key_column)

            for primary_key_value, column_updates in updates:
                (matched,) = con.execute(
                    f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?",
                    [primary_key_value],
                ).fetchone()
                if not matched:
                    raise DatasetEngineError(
                        f"no row with {primary_key_column} = {primary_key_value!r} in this dataset"
                    )
                if not column_updates:
                    continue
                set_clause = ", ".join(f"{_quote_column(c)} = ?" for c in column_updates)
                params = list(column_updates.values()) + [primary_key_value]
                con.execute(
                    f"UPDATE t SET {set_clause} WHERE CAST({pk_col} AS VARCHAR) = ?", params
                )

            for row in appends:
                key = row.get(primary_key_column)
                if key is None or str(key) == "":
                    raise DatasetEngineError(
                        f"a new row needs a value for {primary_key_column!r}"
                    )
                (clash,) = con.execute(
                    f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?", [str(key)]
                ).fetchone()
                if clash:
                    raise DatasetEngineError(
                        f"a row with {primary_key_column} = {str(key)!r} already exists"
                    )
                columns = ", ".join(_quote_column(c) for c in row)
                placeholders = ", ".join("?" for _ in row)
                # Columns the caller said nothing about are left NULL rather
                # than defaulted: a dataset column this platform knows nothing
                # about is not ours to invent a value for.
                try:
                    con.execute(
                        f"INSERT INTO t ({columns}) VALUES ({placeholders})", list(row.values())
                    )
                except duckdb.Error as exc:
                    # **DuckDB buries the reason under a sentence about
                    # internals.** A value that will not convert reports as
                    # "Attempting to execute an unsuccessful or closed pending
                    # query result", with `Conversion Error: Could not convert
                    # string 'T9' to INT32` on the *second* line - so `_clean`,
                    # which keeps the first line everywhere else, would hand the
                    # user the one sentence with nothing in it. This is the one
                    # place that reads further, because supplying a value of the
                    # wrong type for a column is a thing people will do.
                    detail = next(
                        (line.strip() for line in str(exc).splitlines()[1:] if line.strip()),
                        _clean(exc),
                    )
                    raise DatasetEngineError(f"could not add a row: {detail}") from exc

            for primary_key_value in deletes or []:
                (matched,) = con.execute(
                    f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?",
                    [primary_key_value],
                ).fetchone()
                if not matched:
                    # Refused rather than treated as already-done: an action
                    # that reports success for a row it could not find is one
                    # nobody can tell from one that deleted something.
                    raise DatasetEngineError(
                        f"no row with {primary_key_column} = {primary_key_value!r} to delete"
                    )
                con.execute(
                    f"DELETE FROM t WHERE CAST({pk_col} AS VARCHAR) = ?", [primary_key_value]
                )

            described = con.execute("DESCRIBE t").fetchall()
            schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
            row_count = int(con.execute("SELECT count(*) FROM t").fetchone()[0])
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            con.execute(f"COPY t TO '{dest_path}' (FORMAT parquet)")
            return schema, row_count
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc
    finally:
        con.close()


def write_back_row(
    parquet_path: str,
    primary_key_column: str,
    primary_key_value: str,
    column_updates: dict[str, Any],
    dest_path: str,
) -> tuple[list[ColumnSchema], int]:
    """One row updated, written as a new version. The single-write shape, kept
    because most callers have exactly one and `write_rows` reads oddly with a
    one-element list at every call site."""
    return write_rows(
        parquet_path, primary_key_column, [(primary_key_value, column_updates)], [], dest_path
    )


# ---- model transforms --------------------------------------------------------
TRANSFORM_BATCH_ROWS = 50_000
MAX_TRANSFORM_OUTPUT_ROWS = 5_000_000  # flag: worker/Athena path beyond this

_IDENT_RE_ENGINE = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_RESERVED_ALIASES = {"dataset", "__model_output", "src"}


def validate_alias(alias: str) -> str:
    if not _IDENT_RE_ENGINE.match(alias) or alias.lower() in _RESERVED_ALIASES:
        raise DatasetEngineError(f"invalid input alias {alias!r}")
    return alias


def run_transform(
    inputs: dict[str, str], sql: str, dest_parquet: str
) -> tuple[list[ColumnSchema], int]:
    """Execute a SQL transform over named input datasets; write the result as
    Parquet. Returns (schema, row_count).

    Sandboxing has a wrinkle here: DuckDB's enable_external_access switch is
    one-way per connection, and writing Parquet needs external access. So the
    user's SQL runs in a sandboxed connection (inputs pre-materialised, all
    filesystem/network doors closed), and the result streams out in batches
    through a second, trusted connection that only ever executes SQL this
    module composed itself.
    """
    total_bytes = 0
    for alias, path in inputs.items():
        validate_alias(alias)
        total_bytes += os.path.getsize(path)
    if total_bytes > MAX_INTERACTIVE_BYTES:
        raise DatasetEngineError(
            "combined inputs exceed the interactive transform limit in this build - "
            "scheduled worker runs handle larger models"
        )

    sandbox = duckdb.connect()
    writer = duckdb.connect()
    try:
        sandbox.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        for alias, path in inputs.items():
            sandbox.execute(
                f'CREATE TABLE "{alias}" AS SELECT * FROM read_parquet({path!r})'
            )
        # Sandbox boundary: user SQL sees only the input tables.
        sandbox.execute("SET enable_external_access=false")
        try:
            sandbox.execute(f"CREATE TABLE __model_output AS ({sql})")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        described = sandbox.execute("DESCRIBE __model_output").fetchall()
        if not described:
            raise DatasetEngineError("the transform produced no columns")
        schema = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
        row_count = int(sandbox.execute("SELECT count(*) FROM __model_output").fetchone()[0])
        if row_count > MAX_TRANSFORM_OUTPUT_ROWS:
            raise DatasetEngineError(
                f"the transform produced {row_count:,} rows - above this build's "
                f"{MAX_TRANSFORM_OUTPUT_ROWS:,} row limit"
            )

        columns_ddl = ", ".join(f'"{c.name}" {c.data_type}' for c in schema)
        writer.execute(f"CREATE TABLE __model_output ({columns_ddl})")
        placeholders = ", ".join("?" for _ in schema)
        cursor = sandbox.execute("SELECT * FROM __model_output")
        while True:
            batch = cursor.fetchmany(TRANSFORM_BATCH_ROWS)
            if not batch:
                break
            writer.executemany(
                f"INSERT INTO __model_output VALUES ({placeholders})", batch
            )
        os.makedirs(os.path.dirname(dest_parquet), exist_ok=True)
        writer.execute(f"COPY __model_output TO '{dest_parquet}' (FORMAT parquet)")
        return schema, row_count
    finally:
        sandbox.close()
        writer.close()


# ---- preview (ROADMAP.md phase 2, item 2.6) ----------------------------------
PREVIEW_SAMPLE_ROWS = 1000


@dataclass(frozen=True)
class PreviewedInput:
    alias: str
    rows_available: int
    rows_used: int

    @property
    def sampled(self) -> bool:
        return self.rows_used < self.rows_available


def preview_transform(
    inputs: dict[str, str],
    sql: str,
    *,
    sample_rows: int = PREVIEW_SAMPLE_ROWS,
    limit: int = PREVIEW_ROWS,
) -> tuple[TabularResult, list[PreviewedInput]]:
    """Run a transform over a *sample* of its inputs and return the rows,
    writing nothing (roadmap item 2.6).

    Lives here, beside `run_transform`, because it needs the same sandbox
    discipline and a second almost-identical one would eventually drift from
    it. It is simpler in one respect: nothing is written, so there is no
    trusted writer connection and the user's SQL never leaves the sandbox
    where `enable_external_access` is off.

    **The row count returned is the count over the sample, and the caller must
    say so.** A transform with a join or a `group by` over the first thousand
    rows of each input produces an answer that is not the answer - one where
    the join found fewer matches than it will and the groups are smaller than
    they will be. That is inherent to previewing rather than running, which is
    why `PreviewedInput.sampled` exists: it is the difference between a screen
    a person can trust and one that quietly misleads them.
    """
    sample_rows = max(1, sample_rows)
    limit = max(1, min(limit, MAX_RESULT_ROWS))

    sandbox = duckdb.connect()
    try:
        sandbox.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        previewed: list[PreviewedInput] = []
        for alias, path in inputs.items():
            validate_alias(alias)
            available = int(
                sandbox.execute(
                    f"SELECT count(*) FROM read_parquet({path!r})"
                ).fetchone()[0]
            )
            sandbox.execute(
                f'CREATE TABLE "{alias}" AS '
                f"SELECT * FROM read_parquet({path!r}) LIMIT {sample_rows}"
            )
            used = int(sandbox.execute(f'SELECT count(*) FROM "{alias}"').fetchone()[0])
            previewed.append(
                PreviewedInput(alias=alias, rows_available=available, rows_used=used)
            )

        # Sandbox boundary: user SQL sees only the sampled input tables, and
        # unlike run_transform nothing after this point needs it reopened.
        sandbox.execute("SET enable_external_access=false")
        try:
            sandbox.execute(f"CREATE TABLE __model_output AS ({sql})")
        except duckdb.Error as exc:
            raise DatasetEngineError(_clean(exc)) from exc

        described = sandbox.execute("DESCRIBE __model_output").fetchall()
        if not described:
            raise DatasetEngineError("the transform produced no columns")
        columns = [ColumnSchema(name=row[0], data_type=row[1]) for row in described]
        produced = int(sandbox.execute("SELECT count(*) FROM __model_output").fetchone()[0])
        rows = sandbox.execute(
            f"SELECT * FROM __model_output LIMIT {limit}"
        ).fetchall()
        return (
            TabularResult(
                columns=columns,
                rows=[[json_safe(value) for value in row] for row in rows],
                # Rows the transform produced *from the sample*, not from the
                # datasets. Named total_rows only because every other tabular
                # response is; the caller has to make the difference visible.
                total_rows=produced,
                truncated=len(rows) < produced,
            ),
            previewed,
        )
    finally:
        sandbox.close()
