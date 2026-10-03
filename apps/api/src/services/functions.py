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
PARAMETER_TYPES = (*engine.SCALAR_TYPES, "object", "object_set", "batch")
#: `action-types` p.84-85's batched execution (§779): "the function must
#: receive a single input parameter containing a list of structs". A `batch`
#: parameter declares its struct's `fields`, each a scalar or an object, and
#: the SQL reads it with `unnest($name)`.
BATCH_FIELD_TYPES = (*engine.SCALAR_TYPES, "object")
#: `map` is p.221's "map from the object type to a value or custom type"
#: (§770): a key column, then one column per field. `aggregation` is Chart
#: XY's "TwoDimensionalAggregation or ThreeDimensionalAggregation" (workshop
#: p.284; §771): a bucket and a value, or a bucket, a segment and a value.
#: `edits` is `action-types` p.75's Ontology edit function (§773): a key
#: column, then one column per property to set, for an action's Function rule.
#: Over several types (§783) it declares `object_type_ids` and its query gives
#: `function_engine.TYPED_EDIT_COLUMNS`.
OUTPUT_KINDS = ("value", "array", "object_set", "table", "map", "aggregation", "edits")
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
        if data_type == "batch":
            parsed["fields"] = _parse_fields(name, item.get("fields"))
        out.append(parsed)
    if any(p["data_type"] == "batch" for p in out) and len(out) != 1:
        raise FunctionError("a batched function receives a single input parameter "
                            "containing a list of structs (action-types p.85)")
    return out


def _parse_fields(name: str, raw: Any) -> list[dict[str, Any]]:
    """A batch parameter's struct fields (§779)."""
    if not isinstance(raw, list) or not raw:
        raise FunctionError(f"{name}: a batch parameter declares its fields")
    fields: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise FunctionError(f"{name}: each field must be an object")
        field = str(item.get("api_name") or "")
        if not _API_RE.match(field):
            raise FunctionError(f"{name}: invalid field name {field!r}")
        if field in {f["api_name"] for f in fields}:
            raise FunctionError(f"{name}: two fields are called {field}")
        data_type = str(item.get("data_type") or "")
        if data_type not in BATCH_FIELD_TYPES:
            raise FunctionError(f"{name}.{field}: {data_type!r} is not a field type; expected "
                                f"one of {', '.join(BATCH_FIELD_TYPES)}")
        parsed: dict[str, Any] = {"api_name": field, "data_type": data_type}
        if data_type == "object":
            if not item.get("object_type_id"):
                raise FunctionError(f"{name}.{field}: an object field names its object type")
            parsed["object_type_id"] = str(item["object_type_id"])
        fields.append(parsed)
    return fields


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
    if kind == "edits" and "object_type_ids" in raw:
        # p.75's "Create several different types of objects" (§783): the
        # types it may edit, which is p.83's provenance.
        listed = raw["object_type_ids"]
        if not isinstance(listed, list) or not listed \
                or not all(isinstance(t, str) and t for t in listed):
            raise FunctionError("an edit output names its object types")
        if len(set(listed)) != len(listed):
            raise FunctionError("an edit output names an object type twice")
        if len(listed) > MAX_INPUTS:
            raise FunctionError(f"an edit function edits at most {MAX_INPUTS} object types")
        return {"kind": kind, "object_type_ids": [str(t) for t in listed]}
    if kind in ("object_set", "map", "edits"):
        if not raw.get("object_type_id"):
            said = {"object_set": "an object set", "map": "an object map",
                    "edits": "an edit"}[kind]
            raise FunctionError(f"{said} output names its object type")
        return {"kind": kind, "object_type_id": str(raw["object_type_id"])}
    return {"kind": kind}


async def _link_types(conn: AsyncConnection, workspace_id: UUID) -> list[dict[str, Any]]:
    rows = await fetch_all(conn, """
        SELECT l.id, l.api_name, l.from_object_type_id, l.to_object_type_id,
               l.from_property, l.join_dataset_id, l.join_from_column, l.join_to_column,
               f.api_name AS from_name, t.api_name AS to_name
          FROM link_types l
          JOIN object_types f ON f.id = l.from_object_type_id
          JOIN object_types t ON t.id = l.to_object_type_id
         WHERE l.workspace_id = :wid
    """, {"wid": str(workspace_id)})
    return [dict(r) for r in rows]


def _link_edit(
    links: list[dict[str, Any]], edit: dict[str, Any], type_id: str, name: str,
    keys: list[str], allowed: list[str],
) -> dict[str, Any]:
    """A link edit's link type, resolved (§784): one of this object's type's,
    to a type the output declares (p.83), and kept in a join table. Which end
    the object is; a link from a type to itself is from its `from` end, as an
    action's link rule reads one."""
    link = next((lt for lt in links if lt["api_name"] == name and type_id in (
        str(lt["from_object_type_id"]), str(lt["to_object_type_id"]))), None)
    if link is None:
        raise FunctionError(f"the function links through {name!r}, which is not a link type "
                            f"of {edit['object_type']}")
    end = "from" if str(link["from_object_type_id"]) == type_id else "to"
    other = str(link["to_object_type_id" if end == "from" else "from_object_type_id"])
    if other not in allowed:
        raise FunctionError(
            f"the function links {edit['object_type']} to "
            f"{link['to_name' if end == 'from' else 'from_name']}, which is not an object type "
            "it declares (action-types p.83)")
    if not link["join_dataset_id"] and link["from_property"]:
        raise FunctionError(
            f"{name} matches a property rather than keeping a join table; set "
            f"{link['from_property']} on {link['from_name']} instead")
    if not link["join_dataset_id"]:
        raise FunctionError(f"{name} is not kept in a join table, so a function cannot "
                            "link through it")
    return {"link_type_id": str(link["id"]), "dataset_id": str(link["join_dataset_id"]),
            "from_column": str(link["join_from_column"]),
            "to_column": str(link["join_to_column"]), "end": end, "other_type_id": other,
            "keys": keys}


def edited_types(output: dict[str, Any]) -> list[str]:
    """The object types an edit output may edit, one or several (§783)."""
    if "object_type_ids" in output:
        return [str(t) for t in output["object_type_ids"]]
    return [str(output["object_type_id"])]


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
                             if p["data_type"] in ("object", "object_set")),
                  *(f["object_type_id"] for p in parameters for f in p.get("fields", [])
                    if f["data_type"] == "object")}
    if output["kind"] in ("object_set", "map"):
        referenced.add(output["object_type_id"])
    if output["kind"] == "edits":
        referenced.update(edited_types(output))
    types = await _types(conn, workspace_id, referenced)
    engine.check_sql(sql, [p["api_name"] for p in parameters])
    tables = _tables(inputs, types)
    # A batch is run as one entry of nothing, so its fields have names to read.
    params: dict[str, Any] = {
        p["api_name"]: [{f["api_name"]: None for f in p["fields"]}]
        if p["data_type"] == "batch" else None
        for p in parameters
    }
    dry = await anyio.to_thread.run_sync(lambda: engine.run(tables, sql, params, output))
    typed = output["kind"] == "edits" and engine.typed_edits([c["name"] for c in dry["columns"]])
    if output["kind"] == "edits" and len(edited_types(output)) > 1 and not typed:
        raise FunctionError(engine.TYPED_SHAPE)
    if output["kind"] == "edits" and not typed:
        # What an edit sets has to be somewhere to set it: a property of the
        # type it edits, said at publish rather than by an action's click. A
        # typed edit's properties are its rows', checked when it runs.
        edited = types[edited_types(output)[0]]
        declared = {str(p["api_name"]) for p in edited["properties"]}
        for column in dry["columns"]:
            if column["name"] not in declared:
                raise FunctionError(
                    f"the query sets {column['name']!r}, which is not a property of "
                    f"{edited['api_name']}")
    return {"version": version, "parameters": parameters, "inputs": inputs,
            "output": output, "sql": sql}


_FN_SELECT = """
    SELECT f.id, f.api_name, f.display_name, f.description, f.created_at, f.updated_at,
           (SELECT v.version FROM function_versions v WHERE v.function_id = f.id
             ORDER BY v.created_at DESC LIMIT 1) AS latest_version,
           (SELECT count(*) FROM function_versions v WHERE v.function_id = f.id)
             AS version_count
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


async def _keys_of_set(
    conn: AsyncConnection, workspace_id: UUID, parameter: dict[str, Any], raw: dict[str, Any]
) -> list[str]:
    from . import object_set_eval

    name = parameter["api_name"]
    if str(raw.get("object_type_id") or "") != str(parameter["object_type_id"]):
        raise FunctionError(f"{name}: the set is of another object type than "
                            f"{name} takes")
    try:
        return await object_set_eval.keys_of(conn, workspace_id, raw,
                                             limit=engine.MAX_ARRAY_ITEMS)
    except (ValueError, NotFoundError) as exc:
        raise FunctionError(f"{name}: {getattr(exc, 'detail', None) or exc}") from None


async def _bind_batch(
    parameter: dict[str, Any], raw: Any, *, store: Any, prefix: str
) -> list[dict[str, Any]]:
    """A batch's entries, each field as its type (§779): an object by its
    primary key, as an `object` parameter is."""
    name = parameter["api_name"]
    if not isinstance(raw, list) or len(raw) > engine.MAX_ARRAY_ITEMS:
        raise FunctionError(f"{name}: a batch is a list of at most "
                            f"{engine.MAX_ARRAY_ITEMS:,} entries")
    declared = {f["api_name"]: f for f in parameter["fields"]}
    entries: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise FunctionError(f"{name}: each entry is an object")
        if unknown := sorted(set(entry) - set(declared)):
            raise FunctionError(f"{name} has no field {unknown[0]}")
        bound: dict[str, Any] = {}
        for field, spec in declared.items():
            value = entry.get(field)
            if value is None or value == "":
                bound[field] = None
                continue
            value = _bind({**spec, "api_name": f"{name}.{field}"}, value)
            if spec["data_type"] == "object":
                found = await store.get_instance(
                    search_prefix=prefix, object_type_id=UUID(spec["object_type_id"]),
                    instance_id=value)
                if found is None:
                    raise FunctionError(f"{name}.{field}: no such object")
                value = str(found["primary_key"])
            bound[field] = value
        entries.append(bound)
    return entries


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
        if parameter["data_type"] == "batch":
            params[parameter["api_name"]] = await _bind_batch(
                parameter, raw, store=store, prefix=prefix)
            continue
        if parameter["data_type"] == "object_set" and isinstance(raw, dict):
            # A set variable's definition (§780; Workshop p.221's "Use a
            # variable"), read to the keys it holds - refused past the cap
            # rather than cut short, as a list of keys is.
            params[parameter["api_name"]] = await _keys_of_set(
                conn, workspace_id, parameter, raw)
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
    if result["kind"] == "edits":
        result["edits"] = await _edits_by_type(conn, workspace_id, chosen["output"],
                                               result["edits"])
    return {**result, "version": chosen["version"]}


async def _edits_by_type(
    conn: AsyncConnection, workspace_id: UUID, output: dict[str, Any],
    edits: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Each edit with the id of the type it edits. A typed edit (§783) names
    its type by api name, which has to be one the output declares (p.83's
    provenance), and each property it sets one of that type's."""
    allowed = edited_types(output)
    if not any("object_type" in e for e in edits):
        return [{**e, "object_type_id": allowed[0]} for e in edits]
    types = await _types(conn, workspace_id, set(allowed))
    by_name = {str(t["api_name"]): (type_id, {str(p["api_name"]) for p in t["properties"]})
               for type_id, t in types.items()}
    links = await _link_types(conn, workspace_id) \
        if any(e["edit"] in engine.LINK_VERBS for e in edits) else []
    out = []
    for edit in edits:
        found = by_name.get(str(edit["object_type"]))
        if found is None:
            raise FunctionError(
                f"the function edits {edit['object_type']}, which is not an object type it "
                "declares (action-types p.83)")
        type_id, declared = found
        if edit["edit"] in engine.LINK_VERBS:
            out.append({**edit, "object_type_id": type_id, "links": [
                _link_edit(links, edit, type_id, name, keys, allowed)
                for name, keys in edit["properties"].items()]})
            continue
        for name in edit["properties"]:
            if name not in declared:
                raise FunctionError(f"the function sets {name!r}, which is not a property of "
                                    f"{edit['object_type']}")
        out.append({**edit, "object_type_id": type_id})
    return out
