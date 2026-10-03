"""Running a function's SQL (decision 0018, option B; §768).

Synchronous and free of the database, as `dataset_engine` is: the registry
(`functions.py`) reads the objects and the version, and hands this module
plain tables and values. Routes run it on a worker thread.

**The boundary is `dataset_engine.preview_transform`'s**, applied the same way:
the inputs are materialised into an in-memory connection, then
`enable_external_access` is switched off (one way: DuckDB refuses to turn it
back on), and only then does the author's SQL run. Three more guards, each
because a function is called on page loads rather than on a build:

* **One SELECT.** `extract_statements` must find exactly one statement, and
  it must be a query. A string of several would otherwise all run.
* **A timeout**, by interrupting the connection from a timer.
* **A memory limit**, the transform's.

Parameters are bound as `$name` and never put into the SQL text.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import Any

import duckdb

from .dataset_engine import QUERY_MEMORY_LIMIT, json_value

#: How long one call may run. A function-backed column is called as a table
#: page loads (`functions` p.80), so this is seconds, not a build's minutes.
TIMEOUT_SECONDS = 10.0
#: Rows a table output returns, as a preview's do.
MAX_TABLE_ROWS = 1000
#: What an array or object set output may hold.
MAX_ARRAY_ITEMS = 10_000

#: p.80's Workshop variable types, as DuckDB spells them.
SCALAR_TYPES: dict[str, str] = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMP",
}

_PARAM_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)")


class FunctionError(ValueError):
    """A function that cannot be saved, or a call that cannot complete."""


@dataclass(frozen=True)
class InputTable:
    """One object type the function reads, as a table named by its api_name."""

    name: str
    #: (column, DuckDB type), the properties after `__id` and `__primary_key`.
    columns: list[tuple[str, str]]
    rows: list[tuple[Any, ...]] = field(default_factory=list)


def duck_type(data_type: str) -> str:
    """A property's type as a column. Anything not scalar is its JSON text,
    which the SQL can read with DuckDB's JSON functions."""
    return SCALAR_TYPES.get(data_type, "VARCHAR")


def parameters_used(sql: str) -> set[str]:
    return set(_PARAM_RE.findall(sql))


def check_sql(sql: str, declared: list[str]) -> None:
    """One query, whose `$names` are exactly the declared parameters."""
    try:
        statements = duckdb.connect().extract_statements(sql)
    except duckdb.Error as exc:
        raise FunctionError(_clean(exc)) from exc
    if len(statements) != 1:
        raise FunctionError("a function is one query; this SQL has "
                            f"{len(statements)} statements")
    if statements[0].type != duckdb.StatementType.SELECT:
        raise FunctionError("a function is a query: its SQL must be a SELECT")
    used = parameters_used(sql)
    if undeclared := sorted(used - set(declared)):
        raise FunctionError(f"the SQL uses {', '.join('$' + n for n in undeclared)}, "
                            "which no parameter declares")
    if unused := sorted(set(declared) - used):
        raise FunctionError(f"{', '.join('$' + n for n in unused)} "
                            + ("is declared and the SQL never uses it" if len(unused) == 1
                               else "are declared and the SQL never uses them"))


def _clean(exc: duckdb.Error) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else "the query failed"


def run(
    inputs: list[InputTable],
    sql: str,
    params: dict[str, Any],
    output: dict[str, Any],
    *,
    timeout: float = TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the SQL over the inputs and shape the result as `output` says.

    Returns `{"kind": ..., "value" | "values" | "columns"/"rows"}`.
    """
    sandbox = duckdb.connect()
    timer = threading.Timer(timeout, sandbox.interrupt)
    try:
        sandbox.execute(f"SET memory_limit='{QUERY_MEMORY_LIMIT}'")
        for table in inputs:
            quoted = '"' + table.name.replace('"', '""') + '"'
            columns = [("__id", "VARCHAR"), ("__primary_key", "VARCHAR"), *table.columns]
            ddl = ", ".join('"' + c.replace('"', '""') + f'" {t}' for c, t in columns)
            sandbox.execute(f"CREATE TABLE {quoted} ({ddl})")
            if table.rows:
                marks = ", ".join("?" for _ in columns)
                try:
                    sandbox.executemany(f"INSERT INTO {quoted} VALUES ({marks})", table.rows)
                except duckdb.Error as exc:
                    # A stored value its declared type cannot hold: said, with
                    # the table, rather than a fault.
                    raise FunctionError(f"{table.name}: {_clean(exc)}") from exc
        # Sandbox boundary: from here the SQL sees only the tables above.
        sandbox.execute("SET enable_external_access=false")
        timer.start()
        try:
            sandbox.execute(f"CREATE TABLE __function_output AS ({sql})", params)
        except duckdb.InterruptException as exc:
            raise FunctionError(f"the function ran for more than {timeout:g} seconds "
                                "and was stopped") from exc
        except duckdb.Error as exc:
            raise FunctionError(_clean(exc)) from exc
        finally:
            timer.cancel()
        return _shape(sandbox, output)
    finally:
        timer.cancel()
        sandbox.close()


def _map(con: duckdb.DuckDBPyConnection, names: list[str], described: list[Any]) -> dict[str, Any]:
    """p.221's map from objects to a value or a custom type (§770): the first
    column is each object's primary key, and every other column a field."""
    if len(names) < 2:
        raise FunctionError("a map's query gives each object's primary key and then at "
                            "least one value")
    rows = con.execute(
        f"SELECT * FROM __function_output LIMIT {MAX_ARRAY_ITEMS + 1}").fetchall()
    if len(rows) > MAX_ARRAY_ITEMS:
        raise FunctionError(f"the function returned more than {MAX_ARRAY_ITEMS:,} items")
    entries: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row[0] is None:
            continue
        key = str(row[0])
        if key in entries:
            raise FunctionError(f"the function gave {key!r} two values; a map has one per object")
        entries[key] = {name: json_value(value) for name, value in zip(names[1:], row[1:])}
    return {"kind": "map", "columns": [{"name": r[0], "data_type": r[1]} for r in described[1:]],
            "entries": entries}


def _shape(con: duckdb.DuckDBPyConnection, output: dict[str, Any]) -> dict[str, Any]:
    described = con.execute("DESCRIBE __function_output").fetchall()
    names = [row[0] for row in described]
    kind = str(output["kind"])
    if kind == "table":
        rows = con.execute(
            f"SELECT * FROM __function_output LIMIT {MAX_TABLE_ROWS + 1}").fetchall()
        return {"kind": kind, "columns": [{"name": r[0], "data_type": r[1]} for r in described],
                "rows": [[json_value(v) for v in row] for row in rows[:MAX_TABLE_ROWS]],
                "truncated": len(rows) > MAX_TABLE_ROWS}
    first = '"' + names[0].replace('"', '""') + '"'
    if kind == "map":
        return _map(con, names, described)
    target = "VARCHAR" if kind == "object_set" else SCALAR_TYPES[str(output["data_type"])]
    try:
        values = [row[0] for row in con.execute(
            f"SELECT CAST({first} AS {target}) FROM __function_output "
            f"LIMIT {MAX_ARRAY_ITEMS + 1}").fetchall()]
    except duckdb.Error as exc:
        raise FunctionError(
            f"the function returned {names[0]!r}, which is not "
            f"{'a primary key' if kind == 'object_set' else 'a ' + str(output['data_type'])}: "
            f"{_clean(exc)}") from exc
    if kind == "value":
        if len(values) > 1:
            raise FunctionError("the function returns one value, and its query gave "
                                "more than one row")
        return {"kind": kind, "value": json_value(values[0]) if values else None}
    if len(values) > MAX_ARRAY_ITEMS:
        raise FunctionError(f"the function returned more than {MAX_ARRAY_ITEMS:,} items")
    if kind == "object_set":
        return {"kind": kind, "values": [str(v) for v in values if v is not None]}
    return {"kind": kind, "values": [json_value(v) for v in values]}
