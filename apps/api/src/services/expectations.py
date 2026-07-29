"""Dataset expectations - data quality rules and the health they produce
(roadmap Datasets item 2, migration 0020).

Two halves:

  * CRUD over the rules themselves, which is ordinary.
  * `health()`, the single read path every consumer goes through. It returns
    the cached evaluation for a dataset's current version, computing it first
    if there isn't one. That "compute if absent" is what lets seven different
    version-creating paths - upload, two sync paths, two model paths, action
    write-back, and the worker's mirrors - stay untouched: none of them has to
    know expectations exist. See migration 0020 for the full argument, and for
    the one case (alerting on failure) that would need real eager evaluation.

Any change to a dataset's rules clears the cached results for that dataset,
because a result computed against the old rule set is not an answer to the
new question.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text as _text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError
from . import dataset_engine as engine
from . import datasets as ds_service

class ExpectationConfigError(ValueError):
    """A rule the platform will not store. A ValueError so main.py's existing
    handler turns it into a 422 with the message intact, same as the
    connectors' own config error."""


_COLUMNS = "id, dataset_id, rule_type, column_name, config, severity, created_at"


def validate_rule(rule_type: str, column_name: str, config: dict[str, Any]) -> dict[str, Any]:
    """Re-derive the stored config for a rule type, so nothing a client
    smuggles in persists - the same shape connectors' validate_config takes."""
    if rule_type not in engine.RULE_TYPES:
        supported = ", ".join(engine.RULE_TYPES)
        raise ExpectationConfigError(f"unknown rule type '{rule_type}' (supported: {supported})")
    if not column_name.strip():
        raise ExpectationConfigError("column_name is required")

    if rule_type == "value_in_range":
        minimum, maximum = config.get("min"), config.get("max")
        for bound in (minimum, maximum):
            if bound is not None and (
                isinstance(bound, bool) or not isinstance(bound, (int, float))
            ):
                raise ExpectationConfigError("value_in_range bounds must be numbers")
        if minimum is None and maximum is None:
            raise ExpectationConfigError("value_in_range needs a min, a max, or both")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ExpectationConfigError("value_in_range min must not exceed max")
        return {k: v for k, v in (("min", minimum), ("max", maximum)) if v is not None}

    if rule_type == "regex_match":
        pattern = config.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ExpectationConfigError("regex_match needs a pattern")
        import re

        try:
            re.compile(pattern)
        except re.error as exc:
            # Caught here rather than at evaluation time so a typo is a 422 on
            # the form the user is looking at, not a mystery on a later read.
            raise ExpectationConfigError(f"regex_match pattern is invalid: {exc}") from exc
        return {"pattern": pattern}

    return {}


async def list_rules(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID
) -> list[dict[str, Any]]:
    await ds_service.get(conn, project_id, dataset_id)
    return await fetch_all(
        conn,
        f"SELECT {_COLUMNS} FROM dataset_expectations WHERE dataset_id = :did "
        "ORDER BY column_name, rule_type",
        {"did": str(dataset_id)},
    )


async def create_rule(
    conn: AsyncConnection,
    project_id: UUID,
    dataset_id: UUID,
    *,
    rule_type: str,
    column_name: str,
    config: dict[str, Any],
    severity: str,
    created_by: UUID,
) -> dict[str, Any]:
    await ds_service.get(conn, project_id, dataset_id)
    clean = validate_rule(rule_type, column_name, config)
    if severity not in ("error", "warn"):
        raise ExpectationConfigError("severity must be 'error' or 'warn'")

    existing = await fetch_one(
        conn,
        "SELECT id FROM dataset_expectations WHERE dataset_id = :did "
        "AND rule_type = :rt AND column_name = :col",
        {"did": str(dataset_id), "rt": rule_type, "col": column_name},
    )
    if existing is not None:
        raise ConflictError(
            f"a {rule_type} rule already exists for column '{column_name}'"
        )

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO dataset_expectations
               (dataset_id, rule_type, column_name, config, severity, created_by)
        VALUES (:did, :rt, :col, CAST(:cfg AS jsonb), :sev, :by)
        RETURNING {_COLUMNS}
        """,
        {
            "did": str(dataset_id), "rt": rule_type, "col": column_name,
            "cfg": json.dumps(clean), "sev": severity, "by": str(created_by),
        },
    )
    assert row is not None
    await invalidate(conn, dataset_id)
    return row


async def delete_rule(
    conn: AsyncConnection, project_id: UUID, dataset_id: UUID, rule_id: UUID
) -> None:
    await ds_service.get(conn, project_id, dataset_id)
    row = await fetch_one(
        conn,
        "DELETE FROM dataset_expectations WHERE id = :rid AND dataset_id = :did "
        "RETURNING id",
        {"rid": str(rule_id), "did": str(dataset_id)},
    )
    if row is None:
        raise NotFoundError("expectation")
    await invalidate(conn, dataset_id)


async def invalidate(conn: AsyncConnection, dataset_id: UUID) -> None:
    """Drop cached results for every version of a dataset. Called on any rule
    change: a result computed against the old rules does not answer the new
    question, and a health badge that lags a rule edit is worse than one that
    takes a moment to recompute."""
    await conn.execute(
        _text(
            "UPDATE dataset_versions SET expectation_results = NULL "
            "WHERE dataset_id = :did AND expectation_results IS NOT NULL"
        ),
        {"did": str(dataset_id)},
    )


def _decode(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


async def cached_health(
    conn: AsyncConnection, dataset_id: UUID, version_number: int
) -> dict[str, Any] | None:
    row = await fetch_one(
        conn,
        "SELECT expectation_results FROM dataset_versions "
        "WHERE dataset_id = :did AND version_number = :v",
        {"did": str(dataset_id), "v": version_number},
    )
    return None if row is None else _decode(row["expectation_results"])


async def store_health(
    conn: AsyncConnection, dataset_id: UUID, version_number: int, health: dict[str, Any]
) -> None:
    await conn.execute(
        _text(
            "UPDATE dataset_versions SET expectation_results = CAST(:h AS jsonb) "
            "WHERE dataset_id = :did AND version_number = :v"
        ),
        {"h": json.dumps(health), "did": str(dataset_id), "v": version_number},
    )


def failing_summary(health: dict[str, Any]) -> list[str]:
    """One short line per rule that actually failed, for a caller that has to
    explain a health verdict in a sentence (a blocked model run, migration
    0022). `error`-status rules are left out: a rule that could not be
    evaluated has not proven the data bad."""
    return [
        f"{r.get('column_name')}: {r.get('message') or r.get('rule_type')}"
        for r in health.get("results", [])
        if r.get("status") == "fail"
    ]


def evaluate(parquet_path: str, rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Run the rules and shape the stored/returned health object. Synchronous;
    callers run it in a worker thread."""
    from datetime import datetime, timezone

    results = engine.evaluate_expectations(parquet_path, rules)
    return {
        "status": engine.overall_status(results),
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "results": results,
    }
