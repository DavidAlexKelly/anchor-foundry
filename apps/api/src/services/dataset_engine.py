"""Dataset compute (spec §"Models" execution: "DuckDB for small-medium
datasets ... Athena over S3/Iceberg for large datasets").

This module is the DuckDB half. Files above the interactive size cap get a
clear message pointing at export instead of a hung request — the Athena path
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
            "this dataset is too large for interactive queries in this build — "
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


def _clean(exc: duckdb.Error) -> str:
    """First line of DuckDB's message: precise about the SQL/file problem,
    never contains paths beyond the one we passed in."""
    text = str(exc).strip()
    first = text.splitlines()[0] if text else "query failed"
    return first[:500]


def _quote_column(name: str) -> str:
    """Dataset column names come from uploaded file headers, not a fixed
    identifier grammar — quote-and-escape rather than assume unquoted-safe."""
    return '"' + name.replace('"', '""') + '"'


def write_back_row(
    parquet_path: str,
    primary_key_column: str,
    primary_key_value: str,
    column_updates: dict[str, Any],
    dest_path: str,
) -> tuple[list[ColumnSchema], int]:
    """Update one row (matched by primary key) in a dataset's Parquet file
    and write the result to dest_path as a new version. Used by Actions
    write-back — every mutation still produces a new dataset_versions row
    rather than silently overwriting data, matching the rest of the
    platform's dataset model."""
    con = duckdb.connect()
    try:
        try:
            con.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({parquet_path!r})")
            pk_col = _quote_column(primary_key_column)
            (matched,) = con.execute(
                f"SELECT count(*) FROM t WHERE CAST({pk_col} AS VARCHAR) = ?",
                [primary_key_value],
            ).fetchone()
            if not matched:
                raise DatasetEngineError(
                    f"no row with {primary_key_column} = {primary_key_value!r} in this dataset"
                )
            set_clause = ", ".join(f"{_quote_column(c)} = ?" for c in column_updates)
            params = list(column_updates.values()) + [primary_key_value]
            con.execute(f"UPDATE t SET {set_clause} WHERE CAST({pk_col} AS VARCHAR) = ?", params)
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
            "combined inputs exceed the interactive transform limit in this build — "
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
                f"the transform produced {row_count:,} rows — above this build's "
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
