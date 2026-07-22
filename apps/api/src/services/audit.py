"""Audit logging (spec §16 audit_log). Called inside the same transaction as
the mutation it records, so an action and its audit entry commit atomically.

Hard rule inherited from spec §10: metadata must never contain credentials or
secret values. The service enforces a denylist of obviously-sensitive keys as
a tripwire; callers remain responsible for not passing secrets at all.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

_FORBIDDEN_KEYS = {"password", "secret", "token", "credential", "api_key", "apikey", "authorization"}


def _valid_ip(value: str | None) -> str | None:
    """The audit column is `inet`; proxies/test harnesses can hand us
    non-address hosts. Store NULL rather than fail the mutation or fabricate
    an address."""
    if value is None:
        return None
    import ipaddress

    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def _scrub(metadata: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(marker in key.lower() for marker in _FORBIDDEN_KEYS):
            clean[key] = "[redacted]"
        elif isinstance(value, dict):
            clean[key] = _scrub(value)
        else:
            clean[key] = value
    return clean


async def record(
    conn: AsyncConnection,
    *,
    organisation_id: UUID,
    user_id: UUID | None,
    action: str,
    resource_type: str = "",
    resource_id: UUID | None = None,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    import json

    await conn.execute(
        text(
            """
            INSERT INTO audit_log (organisation_id, user_id, action, resource_type,
                                   resource_id, workspace_id, project_id, metadata,
                                   ip_address, user_agent)
            VALUES (:org, :uid, :action, :rtype, :rid, :wid, :pid,
                    CAST(:meta AS jsonb), CAST(:ip AS inet), :ua)
            """
        ),
        {
            "org": str(organisation_id),
            "uid": str(user_id) if user_id else None,
            "action": action,
            "rtype": resource_type,
            "rid": str(resource_id) if resource_id else None,
            "wid": str(workspace_id) if workspace_id else None,
            "pid": str(project_id) if project_id else None,
            "meta": json.dumps(_scrub(metadata or {})),
            "ip": _valid_ip(ip_address),
            "ua": user_agent,
        },
    )
