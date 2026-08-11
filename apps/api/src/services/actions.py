"""Actions - write-back (spec: "Canvas buttons/forms writing back to object
instances → source datasets").

Scope, flagged for review: write-back targets this platform's own Parquet
copy of the mapped dataset (the same dataset the object type source points
at), not the customer's original external system reached through a
connection. Connectors in this build only support test/discover, not
write - true write-through to a live external table needs its own connector
capability and is out of scope here. Every write-back still creates a new
dataset_versions row (produced_by_kind='action'), exactly like
uploads/syncs/model runs - nothing is silently overwritten.

An action type is **parameters and rules** (decision 0007; Foundry
`action-types` p.25 and p.75): parameters are what the caller supplies,
rules are what the action does with them. Until migration 0044 it was one
list of property names playing both parts, which left nowhere to put an
input that is not literally a property being overwritten - and every
remaining feature in `docs/parity/ontology.md` §5 needs one.

Executing one (routes/actions.py orchestrates; this module holds the
DB-only primitives) still requires the property a rule writes to appear in
its source's column_mappings - only properties with a known dataset column
can be written back.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

_API_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,99}$")


def bind_parameters(
    values: dict[str, Any], *, parameters: list[dict[str, Any]]
) -> dict[str, Any]:
    """What the caller supplied, checked against what the action declares.

    The *first* half of executing an action, and the half that knows nothing
    about objects: p.25's parameters "are treated like variables that contain
    external values", so this asks only whether each value was asked for and
    whether everything required is present. What any of it *does* is the
    rules' business, below.

    **Missing is not the same as absent.** An unsupplied parameter with a
    default takes the default (p.27); one without a default is simply not
    bound, and a rule reading it does nothing - which is how a partial submit
    kept working across migration 0044. Required parameters are the exception
    and are refused by name.
    """
    declared = {str(p["api_name"]): p for p in parameters}
    bound: dict[str, Any] = {}
    for name, value in values.items():
        if name not in declared:
            raise ValueError(f"{name!r} is not a parameter of this action")
        bound[name] = value
    for name, parameter in declared.items():
        if name in bound:
            continue
        default = parameter.get("default_value")
        if default is not None:
            # **Used as it comes back, not re-parsed.** The repo's defensive
            # `json.loads(x) if isinstance(x, str)` is a no-op for a jsonb
            # object or array and *wrong* for a jsonb scalar: the driver
            # decodes `"triaged"` to the Python string `triaged`, and parsing
            # that again fails with "Expecting value: line 1 column 1". A
            # default is the only jsonb in this codebase that is routinely a
            # scalar, which is why the convention held everywhere until here.
            bound[name] = default
        elif parameter.get("required"):
            raise ValueError(f"{name!r} is required by this action")
    return bound


def apply_rules(
    bound: dict[str, Any],
    *,
    rules: list[dict[str, Any]],
    property_types: dict[str, str],
    mapped_properties: set[str],
) -> dict[str, Any]:
    """What the rules write, given the bound parameters.

    The second half. p.75: "rules define the ways objects should change when
    the action is applied" - so this is the only place that turns an input
    into a property write, and the only place that has to care whether the
    property has a dataset column behind it.

    Returns the values *normalised* (roadmap Objects item 4): the type check
    is `ontology.coerce_property_value`, shared with the sync path, so a
    geopoint submitted as "51.5,-0.12" is stored in the same shape as one
    that arrived from a Parquet struct.

    An unknown property still defaults to "string" rather than raising: the
    caller resolved these names from the type moments ago, so a miss means
    the type changed underneath (§38 makes that possible), and refusing the
    *write* is a worse answer than checking it loosely.
    """
    from . import ontology as ontology_service

    writes: dict[str, Any] = {}
    for rule in sorted(rules, key=lambda r: (r.get("sort_order") or 0)):
        kind = str(rule["kind"])
        config = _json(rule.get("config")) or {}
        if kind != "modify_object":
            # The schema admits four more kinds and nothing can create one
            # yet. Refusing loudly beats writing nothing and reporting success,
            # which is what a silent `continue` would do the day one appears.
            raise ValueError(f"this build cannot apply a {kind!r} rule yet")
        prop = str(config.get("property", ""))
        parameter = str(config.get("parameter", ""))
        if parameter not in bound:
            continue  # not supplied, no default - the rule has nothing to write
        if prop not in mapped_properties:
            raise ValueError(
                f"{prop!r} has no dataset column mapped on this instance's source"
            )
        writes[prop] = ontology_service.coerce_property_value(
            property_types.get(prop, "string"), bound[parameter]
        )
    if not writes:
        raise ValueError("submit at least one value to write")
    return writes


def _json(value: Any) -> Any:
    """psycopg hands jsonb back as a decoded object; some fetch paths hand back
    the text. Both shapes reach here."""
    return json.loads(value) if isinstance(value, str) else value


def editable_properties_of(rules: list[dict[str, Any]]) -> list[str]:
    """The properties this action's rules write.

    **A projection of the rules, not a stored field.** It replaces the
    `editable_properties` column that migration 0044 dropped, and keeps two
    callers working unchanged: the ontology change-impact report (which asks
    "does an action write this property") and the Workshop `run_action`
    validation (which refuses an effect that names a property the action does
    not write). Exact today, because `modify_object` is the only rule kind
    that exists; when `create_object` lands, a caller wanting "what does this
    action touch" will need the rules themselves, and this stays what its name
    says - the properties written on the action's own object.
    """
    return [
        str(_json(r.get("config")).get("property"))
        for r in sorted(rules, key=lambda r: (r.get("sort_order") or 0))
        if str(r["kind"]) == "modify_object" and _json(r.get("config")).get("property")
    ]


# ---- parameters and rules ----------------------------------------------------
_PARAMETER_COLUMNS = (
    "id, action_type_id, api_name, display_name, data_type, required, "
    "default_value, hidden, sort_order"
)


async def _parameters_for(
    conn: AsyncConnection, action_type_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    """Every action type's parameters in one query rather than one each - the
    list endpoint returns a workspace's actions and a per-row fetch would make
    it N+1 for a page nothing paginates."""
    if not action_type_ids:
        return {}
    rows = await fetch_all(
        conn,
        f"SELECT {_PARAMETER_COLUMNS} FROM action_parameters "
        "WHERE action_type_id = ANY(CAST(:ids AS uuid[])) ORDER BY sort_order, api_name",
        {"ids": action_type_ids},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["action_type_id"]), []).append(dict(row))
    return grouped


async def _rules_for(
    conn: AsyncConnection, action_type_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    if not action_type_ids:
        return {}
    rows = await fetch_all(
        conn,
        "SELECT id, action_type_id, kind, config, sort_order FROM action_rules "
        "WHERE action_type_id = ANY(CAST(:ids AS uuid[])) ORDER BY sort_order",
        {"ids": action_type_ids},
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["action_type_id"]), []).append(dict(row))
    return grouped


async def _with_definition(
    conn: AsyncConnection, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """An action type is not usable without its parameters and rules, so they
    are never a separate fetch a caller could forget to make."""
    ids = [str(r["id"]) for r in rows]
    parameters = await _parameters_for(conn, ids)
    rules = await _rules_for(conn, ids)
    return [
        {
            **row,
            "parameters": parameters.get(str(row["id"]), []),
            "rules": rules.get(str(row["id"]), []),
        }
        for row in rows
    ]


# ---- action types (workspace-scoped) ----------------------------------------
async def list_action_types(
    conn: AsyncConnection, workspace_id: UUID, *, object_type_id: UUID | None = None
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"wid": str(workspace_id)}
    where = "at.workspace_id = :wid"
    if object_type_id is not None:
        where += " AND at.object_type_id = :tid"
        params["tid"] = str(object_type_id)
    rows = await fetch_all(
        conn,
        f"""
        SELECT at.id, at.object_type_id, ot.display_name AS object_type_name,
               at.api_name, at.display_name, at.description,
               at.created_at, at.updated_at
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE {where}
         ORDER BY at.display_name
        """,
        params,
    )
    return await _with_definition(conn, [dict(r) for r in rows])


async def get_action_type(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT at.id, at.object_type_id, ot.display_name AS object_type_name,
               at.api_name, at.display_name, at.description,
               at.created_at, at.updated_at
          FROM action_types at
          JOIN object_types ot ON ot.id = at.object_type_id
         WHERE at.id = :aid AND at.workspace_id = :wid
        """,
        {"aid": str(action_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("action type")
    return (await _with_definition(conn, [dict(row)]))[0]


async def create_action_type(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    object_type_id: UUID,
    api_name: str,
    display_name: str,
    description: str,
    editable_properties: list[str],
    created_by: UUID,
) -> dict[str, Any]:
    if not _API_NAME_RE.match(api_name):
        raise ValueError(f"invalid action api_name {api_name!r}")
    if not editable_properties:
        raise ValueError("an action must make at least one property editable")

    from . import ontology as ontology_service

    await ontology_service.get_type(conn, workspace_id, object_type_id)  # 404 if invisible
    known = {p["api_name"] for p in await ontology_service.list_properties(conn, object_type_id)}
    unknown = [p for p in editable_properties if p not in known]
    if unknown:
        raise ValueError(f"not properties of this object type: {', '.join(unknown)}")

    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM action_types WHERE object_type_id=:tid AND api_name=:api",
        {"tid": str(object_type_id), "api": api_name},
    )
    if existing is not None:
        raise ConflictError(f"an action named {api_name!r} already exists on this object type")

    row = await fetch_one(
        conn,
        """
        INSERT INTO action_types (workspace_id, object_type_id, api_name, display_name,
                                  description, created_by)
        VALUES (:wid, :tid, :api, :name, :descr, :by)
        RETURNING id, object_type_id, api_name, display_name, description,
                  created_at, updated_at
        """,
        {
            "wid": str(workspace_id), "tid": str(object_type_id), "api": api_name,
            "name": display_name, "descr": description, "by": str(created_by),
        },
    )
    assert row is not None
    action_type_id = UUID(str(row["id"]))
    declared = await ontology_service.list_properties(conn, object_type_id)
    property_types = {p["api_name"]: p["data_type"] for p in declared}
    display_names = {p["api_name"]: p["display_name"] for p in declared}
    # **The same conversion migration 0044 ran**, in Python, and deliberately
    # so: one property per parameter, named after it, plus one `modify_object`
    # rule writing it back. Keeping the two in step is what makes
    # `{property: value}` and `{parameter: value}` the same wire shape, which
    # is what lets every saved Workshop `run_action` keep working. `required`
    # is false for the same reason it is false in the migration - submitting a
    # subset of an action's properties has always been legal.
    for order, prop in enumerate(dict.fromkeys(editable_properties)):
        await conn.execute(
            text(
                """
                INSERT INTO action_parameters
                    (action_type_id, api_name, display_name, data_type, required, sort_order)
                VALUES (:aid, :api, :name, CAST(:dtype AS action_parameter_type), false, :ord)
                """
            ),
            {
                "aid": str(action_type_id), "api": prop,
                "name": display_names.get(prop) or prop,
                "dtype": property_types.get(prop, "string"), "ord": order,
            },
        )
        await conn.execute(
            text(
                """
                INSERT INTO action_rules (action_type_id, kind, config, sort_order)
                VALUES (:aid, 'modify_object', CAST(:config AS jsonb), :ord)
                """
            ),
            {
                "aid": str(action_type_id),
                "config": json.dumps({"property": prop, "parameter": prop}),
                "ord": order,
            },
        )
    object_type = await ontology_service.get_type(conn, workspace_id, object_type_id)
    return {
        **(await _with_definition(conn, [dict(row)]))[0],
        "object_type_name": object_type["display_name"],
    }


async def delete_action_type(
    conn: AsyncConnection, workspace_id: UUID, action_type_id: UUID
) -> None:
    row = await fetch_one(
        conn,
        "DELETE FROM action_types WHERE id=:aid AND workspace_id=:wid RETURNING id",
        {"aid": str(action_type_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("action type")


# ---- action_runs bookkeeping --------------------------------------------------
async def open_run(
    conn: AsyncConnection,
    *,
    action_type_id: UUID,
    instance_id: UUID,
    dataset_id: UUID,
    requested_by: UUID,
    submitted_values: dict[str, Any],
) -> UUID:
    row = await fetch_one(
        conn,
        """
        INSERT INTO action_runs (action_type_id, instance_id, dataset_id,
                                 requested_by, submitted_values)
        VALUES (:atid, :iid, :did, :by, CAST(:vals AS jsonb))
        RETURNING id
        """,
        {
            "atid": str(action_type_id), "iid": str(instance_id), "did": str(dataset_id),
            "by": str(requested_by), "vals": json.dumps(submitted_values),
        },
    )
    assert row is not None
    return UUID(str(row["id"]))


async def close_run(
    conn: AsyncConnection,
    run_id: UUID,
    *,
    ok: bool,
    dataset_version: int | None,
    error: str | None,
) -> None:
    await conn.execute(
        text(
            """
            UPDATE action_runs
               SET status = :status, dataset_version = :version,
                   error = :error, finished_at = now()
             WHERE id = :id
            """
        ),
        {
            "status": "succeeded" if ok else "failed",
            "version": dataset_version,
            "error": error,
            "id": str(run_id),
        },
    )


async def list_runs(conn: AsyncConnection, action_type_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT id, instance_id, dataset_id, dataset_version, submitted_values,
               status, error, started_at, finished_at
          FROM action_runs
         WHERE action_type_id = :atid
         ORDER BY started_at DESC
         LIMIT 50
        """,
        {"atid": str(action_type_id)},
    )
