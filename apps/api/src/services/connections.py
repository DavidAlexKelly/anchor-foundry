"""Connections service (spec §16 connections, §17 "Connections: CRUD, test,
discover schema, trigger sync").

Scope rules (§980): a connection is project-scoped by default; workspace
scope shares it with every project in the workspace. Credentials go to the
SecretsGateway and only their ARN is stored; the config jsonb holds
non-secret fields exclusively — the connector's validate_config re-derives
the stored shape so nothing a client smuggles into config persists.

Trigger-sync ships with the Datasets layer, which owns the S3/Iceberg landing
zone a sync writes into; a sync endpoint with nowhere to land would be
decorative. Federated (the spec default) is fully served by test + discover.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import NotFoundError
from .connectors import get_connector
from .secrets import SecretsGateway

_LIST_COLUMNS = """
    id, workspace_id, project_id, scope, name, source_type, config, sync_mode,
    status, last_tested_at, last_synced_at, last_error, created_by,
    created_at, updated_at
"""


async def list_for_project(
    conn: AsyncConnection, workspace_id: UUID, project_id: UUID
) -> list[dict[str, Any]]:
    """Project view: its own connections plus workspace-shared ones."""
    return await fetch_all(
        conn,
        f"""
        SELECT {_LIST_COLUMNS}
          FROM connections
         WHERE (scope = 'project' AND project_id = :pid)
            OR (scope = 'workspace' AND workspace_id = :wid)
         ORDER BY name
        """,
        {"pid": str(project_id), "wid": str(workspace_id)},
    )


async def get(
    conn: AsyncConnection, workspace_id: UUID, project_id: UUID, connection_id: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""
        SELECT {_LIST_COLUMNS}, secret_arn
          FROM connections
         WHERE id = :cid
           AND ((scope = 'project' AND project_id = :pid)
             OR (scope = 'workspace' AND workspace_id = :wid))
        """,
        {"cid": str(connection_id), "pid": str(project_id), "wid": str(workspace_id)},
    )
    if row is None:
        raise NotFoundError("connection")
    return row


async def create(
    conn: AsyncConnection,
    secrets: SecretsGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    scope: str,
    name: str,
    source_type: str,
    config: dict[str, Any],
    secret_values: dict[str, str],
    created_by: UUID,
) -> dict[str, Any]:
    connector = get_connector(source_type)
    clean_config = connector.validate_config(config)

    import uuid as uuid_mod

    connection_id = uuid_mod.uuid4()
    # Secret first: if the gateway rejects the write the row never exists.
    # An orphaned secret from a failed INSERT is recoverable (7-day window,
    # name keyed by connection id); a row without its secret is a broken
    # connection — this ordering fails toward the harmless side.
    secret_arn: str | None = None
    if secret_values:
        secret_arn = secrets.put_secret(str(connection_id), secret_values)

    row = await fetch_one(
        conn,
        f"""
        INSERT INTO connections (id, workspace_id, project_id, scope, name,
                                 source_type, config, secret_arn, created_by)
        VALUES (:id, :wid, :pid, CAST(:scope AS connection_scope), :name,
                :stype, CAST(:config AS jsonb), :arn, :by)
        RETURNING {_LIST_COLUMNS}
        """,
        {
            "id": str(connection_id),
            "wid": str(workspace_id),
            "pid": str(project_id) if scope == "project" else None,
            "scope": scope,
            "name": name,
            "stype": source_type,
            "config": _json(clean_config),
            "arn": secret_arn,
            "by": str(created_by),
        },
    )
    assert row is not None  # parent-checking policy: RETURNING is safe here
    return row


async def update(
    conn: AsyncConnection,
    secrets: SecretsGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    connection_id: UUID,
    name: str | None,
    config: dict[str, Any] | None,
    secret_values: dict[str, str] | None,
) -> dict[str, Any]:
    existing = await get(conn, workspace_id, project_id, connection_id)

    clean_config: dict[str, Any] | None = None
    if config is not None:
        connector = get_connector(str(existing["source_type"]))
        clean_config = connector.validate_config(config)

    secret_arn = existing["secret_arn"]
    if secret_values:
        secret_arn = secrets.put_secret(str(connection_id), secret_values)

    row = await fetch_one(
        conn,
        f"""
        UPDATE connections
           SET name = COALESCE(:name, name),
               config = COALESCE(CAST(:config AS jsonb), config),
               secret_arn = :arn,
               status = 'unconfigured',
               last_error = NULL
         WHERE id = :cid
        RETURNING {_LIST_COLUMNS}
        """,
        {
            "name": name,
            "config": _json(clean_config) if clean_config is not None else None,
            "arn": secret_arn,
            "cid": str(connection_id),
        },
    )
    assert row is not None
    return row


async def delete(
    conn: AsyncConnection,
    secrets: SecretsGateway,
    *,
    workspace_id: UUID,
    project_id: UUID,
    connection_id: UUID,
) -> None:
    existing = await get(conn, workspace_id, project_id, connection_id)
    await fetch_one(
        conn, "DELETE FROM connections WHERE id = :cid RETURNING id", {"cid": str(connection_id)}
    )
    if existing["secret_arn"]:
        # After the row delete in the same transaction; gateway delete is not
        # transactional, but the 7-day recovery window covers a crashed commit.
        secrets.delete_secret(str(existing["secret_arn"]))


_SCHEDULE_COLUMNS = """
    sync_mode, sync_schedule, sync_source_schema, sync_source_table, sync_dataset_name,
    sync_dataset_id, sync_primary_key_column, sync_cursor_column, sync_last_cursor_value,
    sync_next_run_at
"""


async def set_schedule(
    conn: AsyncConnection,
    workspace_id: UUID,
    project_id: UUID,
    connection_id: UUID,
    *,
    mode: str,
    source_schema: str,
    source_table: str,
    dataset_name: str | None,
    primary_key_column: str | None,
    cursor_column: str | None,
    cron_schedule: str | None,
    next_run_at,
) -> dict[str, Any]:
    """Define (or redefine) the one managed sync target a connection can
    carry — spec-shaped, flagged in migration 0014: a connection supports at
    most one scheduled/incremental sync target, not several independently
    scheduled tables."""
    await get(conn, workspace_id, project_id, connection_id)
    row = await fetch_one(
        conn,
        f"""
        UPDATE connections
           SET sync_mode = CAST(:mode AS sync_mode),
               sync_source_schema = :schema,
               sync_source_table = :table,
               sync_dataset_name = :dsname,
               sync_primary_key_column = :pk,
               sync_cursor_column = :cursor,
               sync_schedule = :cron,
               sync_next_run_at = :next_run
         WHERE id = :cid
        RETURNING id, {_SCHEDULE_COLUMNS}
        """,
        {
            "mode": mode, "schema": source_schema, "table": source_table,
            "dsname": dataset_name, "pk": primary_key_column, "cursor": cursor_column,
            "cron": cron_schedule, "next_run": next_run_at, "cid": str(connection_id),
        },
    )
    assert row is not None
    return row


async def clear_schedule(
    conn: AsyncConnection, workspace_id: UUID, project_id: UUID, connection_id: UUID
) -> dict[str, Any]:
    """Stops the cron firing (sync_schedule/sync_next_run_at cleared) but
    keeps the target/mode/cursor config so a manual 'run now' still works."""
    await get(conn, workspace_id, project_id, connection_id)
    row = await fetch_one(
        conn,
        f"""
        UPDATE connections SET sync_schedule = NULL, sync_next_run_at = NULL
         WHERE id = :cid
        RETURNING id, {_SCHEDULE_COLUMNS}
        """,
        {"cid": str(connection_id)},
    )
    assert row is not None
    return row


async def get_schedule(
    conn: AsyncConnection, workspace_id: UUID, project_id: UUID, connection_id: UUID
) -> dict[str, Any]:
    await get(conn, workspace_id, project_id, connection_id)
    row = await fetch_one(
        conn,
        f"SELECT id, {_SCHEDULE_COLUMNS} FROM connections WHERE id = :cid",
        {"cid": str(connection_id)},
    )
    assert row is not None
    return row


async def record_test_result(
    conn: AsyncConnection, connection_id: UUID, *, ok: bool, error: str | None
) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        f"""
        UPDATE connections
           SET status = CAST(:status AS connection_status),
               last_tested_at = now(),
               last_error = :error
         WHERE id = :cid
        RETURNING {_LIST_COLUMNS}
        """,
        {"status": "ok" if ok else "error", "error": error, "cid": str(connection_id)},
    )
    assert row is not None
    return row


def secret_values_for(
    secrets: SecretsGateway, row: dict[str, Any]
) -> dict[str, str]:
    """Resolve credentials for a driver call. Empty dict when the connection
    was created without credentials (e.g. trust-auth dev databases)."""
    if not row.get("secret_arn"):
        return {}
    return secrets.get_secret(str(row["secret_arn"]))


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)
