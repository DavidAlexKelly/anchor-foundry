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

import json
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
#: `action-types` p.130's "Number of objects you can edit in a single action
#: submission": what an edit function may return (§773).
MAX_EDITS = 10_000

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


class UserFacingError(FunctionError):
    """p.166's "threw an error intended to be displayed to the user" (§773):
    the SQL's own `error('…')`, its message said as written."""


#: DuckDB's `error(message)`, which is how a query refuses on purpose.
_ERROR_CALL_RE = re.compile(r"\berror\s*\(", re.I)


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
        except duckdb.InvalidInputException as exc:
            # Raised by `error()` and by a few built-ins on bad input; the
            # query's own call is told apart by the query having one.
            message = _clean(exc)
            if _ERROR_CALL_RE.search(sql):
                raise UserFacingError(message.removeprefix("Invalid Input Error: ")) from exc
            raise FunctionError(message) from exc
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


def _aggregation(con: duckdb.DuckDBPyConnection, names: list[str]) -> dict[str, Any]:
    """Workshop p.284's two- and three-dimensional aggregations (§771): each
    row a bucket and its value, or a bucket, a segment and its value. The
    buckets and segments are labels, and the value a number."""
    if len(names) not in (2, 3):
        raise FunctionError("an aggregation's query gives a bucket and a value, or a "
                            f"bucket, a segment and a value; this one gives {len(names)} "
                            "columns")
    quoted = ['"' + n.replace('"', '""') + '"' for n in names]
    labels = ", ".join(f"CAST({q} AS VARCHAR)" for q in quoted[:-1])
    try:
        rows = con.execute(
            f"SELECT {labels}, CAST({quoted[-1]} AS DOUBLE) FROM __function_output "
            f"LIMIT {MAX_ARRAY_ITEMS + 1}").fetchall()
    except duckdb.Error as exc:
        raise FunctionError(f"an aggregation's last column is its value, and "
                            f"{names[-1]!r} is not a number: {_clean(exc)}") from exc
    if len(rows) > MAX_ARRAY_ITEMS:
        raise FunctionError(f"the function returned more than {MAX_ARRAY_ITEMS:,} buckets")
    if len(names) == 2:
        buckets = [{"key": r[0], "value": r[1]} for r in rows]
    else:
        buckets = [{"key": r[0], "segment": r[1], "value": r[2]} for r in rows]
    return {"kind": "aggregation", "dimensions": len(names), "buckets": buckets}


#: The columns of an edit function's typed shape (§783), in order: whose row
#: it is, which object, what becomes of it, and the properties to set.
TYPED_EDIT_COLUMNS = ("__object_type", "__primary_key", "__edit", "__properties")
#: p.75's verbs, "create, modify, and delete objects", and its "set up links
#: between them" on a join table (§784).
EDIT_VERBS = ("create", "modify", "delete", "link", "unlink")
LINK_VERBS = ("link", "unlink")


def typed_edits(names: list[str]) -> bool:
    """Whether a query's columns are §783's typed shape."""
    return bool(names) and names[0] == TYPED_EDIT_COLUMNS[0]


def _edits(con: duckdb.DuckDBPyConnection, names: list[str], described: list[Any]) -> dict[str, Any]:
    """`action-types` p.75's Ontology edit function (§773): each row an object
    of the output's type by its primary key, and the properties to set on it.
    What the action does with each - modify one that exists, create one that
    does not - is the executor's (`action_functions.edit_rules`).

    A query whose first column is `__object_type` is §783's typed shape, for
    p.75's edits across types: each row names its type, its object, its verb
    and a JSON object of the properties to set (`_typed_edits`)."""
    if typed_edits(names):
        return _typed_edits(con, names)
    if len(names) < 2:
        raise FunctionError("an edit function's query gives each object's primary key and "
                            "then at least one property to set")
    rows = con.execute(f"SELECT * FROM __function_output LIMIT {MAX_EDITS + 1}").fetchall()
    if len(rows) > MAX_EDITS:
        raise FunctionError(f"the function returned more than {MAX_EDITS:,} edits, the most "
                            "one action may make")
    edits: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row[0] is None:
            continue  # names no object, so it is no edit; as a map's row is
        key = str(row[0])
        if key in seen:
            raise FunctionError(f"the function edits {key!r} twice; one row says what "
                                "becomes of one object")
        seen.add(key)
        edits.append({"primary_key": key, "properties": {
            name: json_value(value) for name, value in zip(names[1:], row[1:])}})
    return {"kind": "edits", "columns": [{"name": r[0], "data_type": r[1]} for r in described[1:]],
            "edits": edits}


def _typed_edits(con: duckdb.DuckDBPyConnection, names: list[str]) -> dict[str, Any]:
    """§783's shape. Its properties are JSON rather than a column each, because
    two types may share a property name and a column cannot say "leave this
    one alone" for one type and "set it to nothing" for the other. A JSON
    value is coerced to the property's type as a parameter's is."""
    if tuple(names) != TYPED_EDIT_COLUMNS:
        raise FunctionError(TYPED_SHAPE)
    rows = con.execute(f"SELECT * FROM __function_output LIMIT {MAX_EDITS + 1}").fetchall()
    if len(rows) > MAX_EDITS:
        raise FunctionError(f"the function returned more than {MAX_EDITS:,} edits, the most "
                            "one action may make")
    edits: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for type_name, key, verb, raw in rows:
        if key is None:
            continue  # names no object, as §773's shape skips it
        key, type_name = str(key), str(type_name)
        if verb not in EDIT_VERBS:
            raise FunctionError(f"{verb!r} is not an edit; __edit is create, modify, delete, "
                                "link or unlink")
        properties = json.loads(raw) if isinstance(raw, str) else raw
        if properties is None:
            properties = {}
        if not isinstance(properties, dict):
            raise FunctionError(f"__properties is a JSON object of the properties to set, "
                                f"and {key}'s is not")
        if verb in LINK_VERBS:
            # §784: each property names a link type and the key, or keys, at
            # its other end. One object may link and unlink in several rows.
            if not properties:
                raise FunctionError(f"the function says nothing to {verb} {key} to")
            for name, value in properties.items():
                # A NULL key names nothing, as a row's does.
                keys = [k for k in (value if isinstance(value, list) else [value])
                        if k is not None]
                if not all(isinstance(k, (str, int)) and not isinstance(k, bool)
                           for k in keys):
                    raise FunctionError(f"{name} in {key}'s __properties is a key or a list "
                                        "of keys")
                properties[name] = [str(k) for k in keys]
            edits.append({"object_type": type_name, "primary_key": key, "edit": verb,
                          "properties": properties})
            continue
        if verb == "delete" and properties:
            raise FunctionError(f"the function deletes {key} and sets properties on it")
        if verb == "modify" and not properties:
            raise FunctionError(f"the function says nothing to set on {key}, which it modifies")
        if (type_name, key) in seen:
            raise FunctionError(f"the function edits {type_name} {key} twice; one row says "
                                "what becomes of one object")
        seen.add((type_name, key))
        edits.append({"object_type": type_name, "primary_key": key, "edit": verb,
                      "properties": properties})
    return {"kind": "edits", "columns": [{"name": n, "data_type": "VARCHAR"} for n in names],
            "edits": edits}


TYPED_SHAPE = ("an edit function over several object types says each row's type: its query "
               "gives " + ", ".join(TYPED_EDIT_COLUMNS) + ", in that order (action-types p.75)")


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
    if kind == "aggregation":
        return _aggregation(con, names)
    if kind == "edits":
        return _edits(con, names, described)
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
