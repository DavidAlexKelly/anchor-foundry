"""Functions: named, versioned SQL over the ontology (decision 0018, option B;
§768; db 0153; Foundry `functions` p.49-50, p.79-81).

> "Functions enable code authors to write logic that can be executed quickly
> in operational contexts, such as dashboards and applications… This logic is
> executed on the server side in an isolated environment." (`functions` p.2)

This module is the registry and the call. `function_engine` runs the SQL.

**A version is immutable and chosen by its author** (p.49: "Versions for
function releases are chosen by their publishers and are immutable after
creation"), as a semantic version (p.50). A new version must be greater than
every earlier one, so "the latest" always means the one published last.

**A version is checked by running it** when it is saved: against empty input
tables, with every parameter null. That is what catches a misspelt column or
table, which parsing alone does not, before any consumer calls it.

**A call reads its inputs as the caller.** The objects come from the instance
store over the caller's connection, so a function sees what the person
calling it may see (p.77: a function has to work "for users with differing
access to individual objects").
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from uuid import UUID

import anyio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from . import function_engine as engine
from . import instance_store, instances as instances_service, ontology
from .function_engine import FunctionError

_API_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")
#: p.50: "versions take the form X.Y.Z … A version may also include a
#: prerelease identifier … by appending a hyphen".
_VERSION_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?$")
#: `object_set` is p.221's "ObjectSet<ObjectType> parameter", by which an
#: Object Table passes the objects it is showing (§770): their primary keys,
#: as a list the SQL reads with `list_contains($name, __primary_key)`.
PARAMETER_TYPES = (*engine.SCALAR_TYPES, "object", "object_set")
#: `map` is p.221's "map from the object type to a value or custom type"
#: (§770): a key column, then one column per field.
OUTPUT_KINDS = ("value", "array", "object_set", "table", "map")
MAX_PARAMETERS = 20
MAX_INPUTS = 10
#: The objects of one type a call reads. Above it a call is refused, by name:
#: a function that quietly read the first ten thousand would answer about a
#: different set than the one it was asked about.
MAX_INPUT_OBJECTS = 10_000


def version_key(version: str) -> tuple[int, int, int, int, str]:
    """Semantic version order (p.50), with a prerelease before its release.
    Prerelease identifiers compare as text, which is simpler than SemVer's
    dotted rule and agrees with it for the `rc1` / `rc2` cases p.50 shows."""
    found = _VERSION_RE.match(version)
    if found is None:
        raise FunctionError(f"{version!r} is not a semantic version such as 1.0.0 (p.50)")
    major, minor, patch, pre = found.groups()
    return int(major), int(minor), int(patch), 0 if pre else 1, pre or ""


def parse_parameters(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise FunctionError("parameters must be a list")
    if len(raw) > MAX_PARAMETERS:
        raise FunctionError(f"a function takes at most {MAX_PARAMETERS} parameters")
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise FunctionError("each parameter must be an object")
        name = str(item.get("api_name") or "")
        if not _API_RE.match(name):
            raise FunctionError(f"invalid parameter name {name!r}")
        if name in {p["api_name"] for p in out}:
            raise FunctionError(f"two parameters are called {name}")
        data_type = str(item.get("data_type") or "")
        if data_type not in PARAMETER_TYPES:
            raise FunctionError(f"{name}: {data_type!r} is not a parameter type; expected "
                                f"one of {', '.join(PARAMETER_TYPES)}")
        parsed: dict[str, Any] = {
            "api_name": name,
            "display_name": str(item.get("display_name") or name),
            "data_type": data_type,
            "required": item.get("required", True) is not False,
        }
        if data_type in ("object", "object_set"):
            if not item.get("object_type_id"):
                raise FunctionError(f"{name}: an object parameter names its object type")
            parsed["object_type_id"] = str(item["object_type_id"])
        out.append(parsed)
    return out


def parse_output(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FunctionError("the output must say what the function returns")
    kind = str(raw.get("kind") or "")
    if kind not in OUTPUT_KINDS:
        raise FunctionError(f"{kind!r} is not an output; expected one of "
                            f"{', '.join(OUTPUT_KINDS)}")
    if kind in ("value", "array"):
        data_type = str(raw.get("data_type") or "")
        if data_type not in engine.SCALAR_TYPES:
            raise FunctionError(f"a {kind} output is one of {', '.join(engine.SCALAR_TYPES)}")
        return {"kind": kind, "data_type": data_type}
    if kind in ("object_set", "map"):
        if not raw.get("object_type_id"):
            raise FunctionError(f"an {'object set' if kind == 'object_set' else 'object map'} "
                                "output names its object type")
        return {"kind": kind, "object_type_id": str(raw["object_type_id"])}
    return {"kind": kind}


async def _types(
    conn: AsyncConnection, workspace_id: UUID, ids: set[str]
) -> dict[str, dict[str, Any]]:
    """The named object types with their properties, refusing one that is not
    this workspace's."""
    found: dict[str, dict[str, Any]] = {}
    for type_id in ids:
        try:
            found[type_id] = await ontology.get_type(conn, workspace_id, UUID(type_id))
        except (NotFoundError, ValueError) as exc:
            raise FunctionError(f"no object type {type_id} in this workspace") from exc
        found[type_id]["properties"] = await ontology.list_properties(conn, UUID(type_id))
    return found


def _tables(inputs: list[str], types: dict[str, dict[str, Any]]) -> list[engine.InputTable]:
    return [
        engine.InputTable(
            name=str(types[t]["api_name"]),
            columns=[(str(p["api_name"]), engine.duck_type(str(p["data_type"])))
                     for p in types[t]["properties"]],
        )
        for t in inputs
    ]


async def check_version(
    conn: AsyncConnection, workspace_id: UUID, raw: dict[str, Any]
) -> dict[str, Any]:
    """A version's definition, parsed, its references resolved, and its SQL
    run once against empty inputs (module note)."""
    version = str(raw.get("version") or "")
    version_key(version)
    parameters = parse_parameters(raw.get("parameters") or [])
    output = parse_output(raw.get("output"))
    inputs = [str(i) for i in dict.fromkeys(raw.get("inputs") or [])]
    if len(inputs) > MAX_INPUTS:
        raise FunctionError(f"a function reads at most {MAX_INPUTS} object types")
    sql = str(raw.get("sql") or "").strip()
    if not sql:
        raise FunctionError("a function needs its SQL")
    referenced = {*inputs, *(p["object_type_id"] for p in parameters
                             if p["data_type"] in ("object", "object_set"))}
    if output["kind"] in ("object_set", "map"):
        referenced.add(output["object_type_id"])
    types = await _types(conn, workspace_id, referenced)
    engine.check_sql(sql, [p["api_name"] for p in parameters])
    tables = _tables(inputs, types)
    params: dict[str, Any] = {p["api_name"]: None for p in parameters}
    await anyio.to_thread.run_sync(lambda: engine.run(tables, sql, params, output))
    return {"version": version, "parameters": parameters, "inputs": inputs,
            "output": output, "sql": sql}


_FN_SELECT = """
    SELECT f.id, f.api_name, f.display_name, f.description, f.created_at, f.updated_at,
           (SELECT v.version FROM function_versions v WHERE v.function_id = f.id
             ORDER BY v.created_at DESC LIMIT 1) AS latest_version
      FROM functions f
"""


def _version_out(row: Any) -> dict[str, Any]:
    out = dict(row)
    for key in ("parameters", "output"):
        if isinstance(out.get(key), str):
            out[key] = json.loads(out[key])
    out["inputs"] = [str(i) for i in (out.get("inputs") or [])]
    return out


async def list_functions(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(conn, _FN_SELECT + " WHERE f.workspace_id = :wid ORDER BY f.api_name",
                           {"wid": str(workspace_id)})
    return [dict(r) for r in rows]


async def get_function(
    conn: AsyncConnection, workspace_id: UUID, function_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(conn, _FN_SELECT + " WHERE f.workspace_id = :wid AND f.id = :fid",
                          {"wid": str(workspace_id), "fid": str(function_id)})
    if row is None:
        raise NotFoundError("function")
    out = dict(row)
    versions = await fetch_all(
        conn,
        """
        SELECT id, version, parameters, inputs, output, sql, created_at
          FROM function_versions WHERE function_id = :fid
         ORDER BY created_at DESC
        """,
        {"fid": str(function_id)},
    )
    out["versions"] = [_version_out(v) for v in versions]
    return out


async def _insert_version(
    conn: AsyncConnection, function_id: UUID, parsed: dict[str, Any], created_by: UUID
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO function_versions (function_id, version, parameters, inputs,
                                           output, sql, created_by)
            VALUES (:fid, :version, CAST(:params AS jsonb), CAST(:inputs AS uuid[]),
                    CAST(:output AS jsonb), :sql, :by)
            """
        ),
        {"fid": str(function_id), "version": parsed["version"],
         "params": json.dumps(parsed["parameters"]),
         "inputs": "{" + ",".join(parsed["inputs"]) + "}",
         "output": json.dumps(parsed["output"]), "sql": parsed["sql"], "by": str(created_by)},
    )


async def create(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    version: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    if not _API_RE.match(api_name):
        raise FunctionError(f"invalid function api_name {api_name!r}")
    parsed = await check_version(conn, workspace_id, version)
    taken = await fetch_one(
        conn, "SELECT 1 AS x FROM functions WHERE workspace_id = :wid AND api_name = :api",
        {"wid": str(workspace_id), "api": api_name})
    if taken is not None:
        raise ConflictError(f"a function named {api_name!r} already exists")
    row = await fetch_one(
        conn,
        """
        INSERT INTO functions (workspace_id, api_name, display_name, description, created_by)
        VALUES (:wid, :api, :name, :descr, :by) RETURNING id
        """,
        {"wid": str(workspace_id), "api": api_name, "name": display_name,
         "descr": description, "by": str(created_by)},
    )
    assert row is not None
    function_id = UUID(str(row["id"]))
    await _insert_version(conn, function_id, parsed, created_by)
    return await get_function(conn, workspace_id, function_id)


async def add_version(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    function_id: UUID,
    version: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    """p.49's new release. Greater than every earlier one, so the order of
    publication and the order of versions agree."""
    current = await get_function(conn, workspace_id, function_id)
    parsed = await check_version(conn, workspace_id, version)
    newest = max((v["version"] for v in current["versions"]), key=version_key)
    if version_key(parsed["version"]) <= version_key(newest):
        raise FunctionError(f"{parsed['version']} is not after {newest}; versions are "
                            "immutable, so a change is a new, greater one (p.49)")
    await _insert_version(conn, function_id, parsed, created_by)
    await conn.execute(text("UPDATE functions SET updated_at = now() WHERE id = :fid"),
                       {"fid": str(function_id)})
    return await get_function(conn, workspace_id, function_id)


async def update_metadata(
    conn: AsyncConnection, *, workspace_id: UUID, function_id: UUID,
    display_name: str, description: str,
) -> dict[str, Any]:
    await get_function(conn, workspace_id, function_id)
    await conn.execute(
        text("UPDATE functions SET display_name = :name, description = :descr WHERE id = :fid"),
        {"name": display_name, "descr": description, "fid": str(function_id)})
    return await get_function(conn, workspace_id, function_id)


async def delete(conn: AsyncConnection, workspace_id: UUID, function_id: UUID) -> None:
    await get_function(conn, workspace_id, function_id)
    await conn.execute(text("DELETE FROM functions WHERE id = :fid"), {"fid": str(function_id)})


def _bind(parameter: dict[str, Any], value: Any) -> Any:
    """A submitted value as the parameter's type, or a refusal naming it."""
    name, data_type = parameter["api_name"], parameter["data_type"]
    try:
        if data_type == "object_set":
            # Primary keys, as the table holds them (`__primary_key`).
            if not isinstance(value, list) or len(value) > engine.MAX_ARRAY_ITEMS:
                raise TypeError
            return [str(v) for v in value]
        if data_type in ("string", "object"):
            return str(value)
        if data_type == "boolean":
            if not isinstance(value, bool):
                raise TypeError
            return value
        if data_type == "integer":
            if isinstance(value, bool) or (isinstance(value, float) and not value.is_integer()):
                raise TypeError
            return int(value)
        if data_type == "float":
            if isinstance(value, bool):
                raise TypeError
            return float(value)
        if data_type == "date":
            return date.fromisoformat(str(value)[:10])
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FunctionError(f"{name}: {value!r} is not a {data_type}") from exc


def _cell(value: Any, data_type: str) -> Any:
    if value is None or data_type in engine.SCALAR_TYPES:
        return value
    return json.dumps(value)


async def execute(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    function_id: UUID,
    version: str | None,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Call one version with `values`: the newest when none is named."""
    current = await get_function(conn, workspace_id, function_id)
    chosen = next((v for v in current["versions"] if v["version"] == version), None) \
        if version else max(current["versions"], key=lambda v: version_key(v["version"]))
    if chosen is None:
        raise NotFoundError(f"version {version} of {current['api_name']}")
    if unknown := sorted(set(values) - {p["api_name"] for p in chosen["parameters"]}):
        raise FunctionError(f"{current['api_name']} takes no parameter {unknown[0]}")
    prefix = await instances_service.workspace_search_prefix(conn, workspace_id)
    store = instance_store.store_for(conn)
    params: dict[str, Any] = {}
    for parameter in chosen["parameters"]:
        raw = values.get(parameter["api_name"])
        if raw is None or raw == "":
            if parameter["required"]:
                raise FunctionError(f"{parameter['api_name']} needs a value")
            params[parameter["api_name"]] = None
            continue
        bound = _bind(parameter, raw)
        if parameter["data_type"] == "object":
            # An object is passed by its id and read by its primary key,
            # which is what the input tables' `__primary_key` holds.
            found = await store.get_instance(
                search_prefix=prefix, object_type_id=UUID(parameter["object_type_id"]),
                instance_id=bound)
            if found is None:
                raise FunctionError(f"{parameter['api_name']}: no such object")
            bound = str(found["primary_key"])
        params[parameter["api_name"]] = bound
    types = await _types(conn, workspace_id, set(chosen["inputs"]))
    tables: list[engine.InputTable] = []
    for table, type_id in zip(_tables(chosen["inputs"], types), chosen["inputs"]):
        objects = await store.scan_for_type(
            search_prefix=prefix, object_type_id=UUID(type_id), limit=MAX_INPUT_OBJECTS + 1)
        if len(objects) > MAX_INPUT_OBJECTS:
            raise FunctionError(f"{table.name} has more than {MAX_INPUT_OBJECTS:,} objects, "
                                "which is more than a function reads in this build")
        declared = {str(p["api_name"]): str(p["data_type"])
                    for p in types[type_id]["properties"]}
        rows = []
        for obj in objects:
            props = obj["properties"]
            if isinstance(props, str):
                props = json.loads(props)
            rows.append((str(obj["id"]), str(obj["primary_key"]),
                         *(_cell(props.get(c), declared[c]) for c, _t in table.columns)))
        tables.append(engine.InputTable(name=table.name, columns=table.columns, rows=rows))
    result = await anyio.to_thread.run_sync(
        lambda: engine.run(tables, chosen["sql"], params, chosen["output"]))
    return {**result, "version": chosen["version"]}
