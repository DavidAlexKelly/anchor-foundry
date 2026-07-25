"""Dataset compute — worker's copy of the DuckDB primitives apps/api's
dataset_engine.py already has, trimmed to what scheduled jobs need: running
a SQL transform (cron-triggered models the API isn't the one to execute)
and merging incremental sync rows into an existing dataset. Duplicated for
the same reason as storage.py — api and worker are independently deployable
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
    """Matches apps/api's services/dataset_engine.py exactly — values read
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


def _clean(exc: duckdb.Error) -> str:
    text = str(exc).strip()
    first = text.splitlines()[0] if text else "query failed"
    return first[:500]


# Scheduled instance sync's row cap — the whole reason it runs in the worker
# rather than the interactive request/response cycle apps/api's
# services/instances.py's MAX_INSTANCE_SYNC_ROWS (20,000) is bounded by.
MAX_SCHEDULED_INSTANCE_SYNC_ROWS = 2_000_000


def extract_instance_rows(
    parquet_path: str,
    primary_key_column: str,
    column_mappings: dict[str, str],
    max_rows: int = MAX_SCHEDULED_INSTANCE_SYNC_ROWS,
) -> list[tuple[str, dict[str, Any]]]:
    """Worker copy of services/instances.py's extract_rows — same primary-key
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


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


TRANSFORM_BATCH_ROWS = 50_000


def run_sql_transform(
    inputs: dict[str, str], sql: str, dest_parquet: str
) -> tuple[list[ColumnSchema], int]:
    """Same sandboxed-input / trusted-output-writer split as the API's
    run_transform: user SQL only ever executes in the sandbox connection
    (inputs pre-materialised, external access switched off before it runs);
    the trusted writer connection never executes user SQL at all — it only
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
                f"the transform produced {row_count:,} rows — above this build's "
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
    sync — the new rows are the whole dataset."""
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
