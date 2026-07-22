"""Organisation-level administration (spec §4 "Organisation", §5 "Org
settings", §16 organisations / users / groups / group_members / audit_log).

User provisioning note (§9 "No self-registration"): creating a platform user
here also creates the Cognito identity via AdminCreateUser in production
(CognitoAdminGateway). The DB row is authoritative; cognito_sub is linked on
first login when the middleware sees a matching email claim — Flagged for
review: spec doesn't define the linking moment; conservative choice is to
store the sub returned by AdminCreateUser immediately, which is what the
production gateway does. The gateway is injected so the service is testable
without AWS.
"""
from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError


class CognitoAdminGateway(Protocol):
    def admin_create_user(self, email: str, display_name: str) -> str:
        """Create the Cognito identity (sends invite email); returns sub."""
        ...

    def admin_disable_user(self, cognito_sub: str) -> None: ...


class NullCognitoGateway:
    """Local/dev/test gateway: mints deterministic fake subs, no AWS calls."""

    def admin_create_user(self, email: str, display_name: str) -> str:
        import hashlib

        return "local-" + hashlib.sha256(email.lower().encode()).hexdigest()[:32]

    def admin_disable_user(self, cognito_sub: str) -> None:
        return None


async def get_org(conn: AsyncConnection, organisation_id: UUID) -> dict[str, Any]:
    row = await fetch_one(
        conn,
        """
        SELECT id, name, slug, plan, aws_region, stack_status, created_at
          FROM organisations WHERE id = :org
        """,
        {"org": str(organisation_id)},
    )
    if row is None:
        raise NotFoundError("organisation")
    return row


# ---- users ------------------------------------------------------------------
async def list_users(conn: AsyncConnection, organisation_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT id, email, display_name, org_role, status, created_at,
               (cognito_sub IS NOT NULL) AS identity_linked
          FROM users WHERE organisation_id = :org ORDER BY display_name
        """,
        {"org": str(organisation_id)},
    )


async def invite_user(
    conn: AsyncConnection,
    cognito: CognitoAdminGateway,
    *,
    organisation_id: UUID,
    email: str,
    display_name: str,
    org_role: str,
) -> dict[str, Any]:
    if org_role not in ("admin", "member"):
        # 'owner' is never grantable through invite — ownership transfer is a
        # separate, deliberate operation. Flagged for review (spec silent).
        raise ValueError("invited users may be 'admin' or 'member'")
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM users WHERE organisation_id=:org AND email=:email",
        {"org": str(organisation_id), "email": email},
    )
    if existing is not None:
        raise ConflictError("a user with this email already exists")
    sub = cognito.admin_create_user(email, display_name)
    row = await fetch_one(
        conn,
        """
        INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
        VALUES (:org, :email, :name, CAST(:role AS org_role), :sub, 'active')
        RETURNING id, email, display_name, org_role, status, created_at
        """,
        {
            "org": str(organisation_id),
            "email": email,
            "name": display_name,
            "role": org_role,
            "sub": sub,
        },
    )
    assert row is not None
    return row


async def set_user_role(
    conn: AsyncConnection, organisation_id: UUID, user_id: UUID, org_role: str
) -> dict[str, Any]:
    if org_role not in ("admin", "member"):
        raise ValueError("role must be 'admin' or 'member'")
    target = await fetch_one(
        conn,
        "SELECT org_role FROM users WHERE id=:id AND organisation_id=:org",
        {"id": str(user_id), "org": str(organisation_id)},
    )
    if target is None:
        raise NotFoundError("user")
    if target["org_role"] == "owner":
        raise ValueError("the organisation owner's role cannot be changed here")
    row = await fetch_one(
        conn,
        """
        UPDATE users SET org_role = CAST(:role AS org_role)
         WHERE id=:id AND organisation_id=:org
        RETURNING id, email, display_name, org_role, status, created_at
        """,
        {"role": org_role, "id": str(user_id), "org": str(organisation_id)},
    )
    assert row is not None
    return row


async def disable_user(
    conn: AsyncConnection,
    cognito: CognitoAdminGateway,
    organisation_id: UUID,
    user_id: UUID,
) -> None:
    row = await fetch_one(
        conn,
        """
        UPDATE users SET status = 'disabled'
         WHERE id=:id AND organisation_id=:org AND org_role <> 'owner'
        RETURNING cognito_sub
        """,
        {"id": str(user_id), "org": str(organisation_id)},
    )
    if row is None:
        raise NotFoundError("user")
    if row["cognito_sub"]:
        cognito.admin_disable_user(str(row["cognito_sub"]))


# ---- groups -----------------------------------------------------------------
async def list_groups(conn: AsyncConnection, organisation_id: UUID) -> list[dict[str, Any]]:
    return await fetch_all(
        conn,
        """
        SELECT g.id, g.name, g.description, g.created_at,
               count(gm.user_id) AS member_count
          FROM groups g
          LEFT JOIN group_members gm ON gm.group_id = g.id
         WHERE g.organisation_id = :org
         GROUP BY g.id ORDER BY g.name
        """,
        {"org": str(organisation_id)},
    )


async def create_group(
    conn: AsyncConnection, organisation_id: UUID, name: str, description: str
) -> dict[str, Any]:
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM groups WHERE organisation_id=:org AND name=:name",
        {"org": str(organisation_id), "name": name},
    )
    if existing is not None:
        raise ConflictError("a group with this name already exists")
    row = await fetch_one(
        conn,
        """
        INSERT INTO groups (organisation_id, name, description)
        VALUES (:org, :name, :descr)
        RETURNING id, name, description, created_at
        """,
        {"org": str(organisation_id), "name": name, "descr": description},
    )
    assert row is not None
    return row


async def add_group_member(
    conn: AsyncConnection, organisation_id: UUID, group_id: UUID, user_id: UUID
) -> None:
    group = await fetch_one(
        conn,
        "SELECT 1 AS x FROM groups WHERE id=:gid AND organisation_id=:org",
        {"gid": str(group_id), "org": str(organisation_id)},
    )
    user = await fetch_one(
        conn,
        "SELECT 1 AS x FROM users WHERE id=:uid AND organisation_id=:org",
        {"uid": str(user_id), "org": str(organisation_id)},
    )
    if group is None or user is None:
        raise NotFoundError("group or user")
    row = await fetch_one(
        conn,
        """
        INSERT INTO group_members (group_id, user_id) VALUES (:gid, :uid)
        ON CONFLICT DO NOTHING RETURNING group_id
        """,
        {"gid": str(group_id), "uid": str(user_id)},
    )
    if row is None:
        raise ConflictError("user is already in this group")


async def remove_group_member(
    conn: AsyncConnection, organisation_id: UUID, group_id: UUID, user_id: UUID
) -> None:
    row = await fetch_one(
        conn,
        """
        DELETE FROM group_members gm USING groups g
         WHERE gm.group_id = g.id AND g.organisation_id = :org
           AND gm.group_id = :gid AND gm.user_id = :uid
        RETURNING gm.group_id
        """,
        {"org": str(organisation_id), "gid": str(group_id), "uid": str(user_id)},
    )
    if row is None:
        raise NotFoundError("group membership")


# ---- audit ------------------------------------------------------------------
async def list_audit(
    conn: AsyncConnection, organisation_id: UUID, *, limit: int, offset: int
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    return await fetch_all(
        conn,
        """
        SELECT a.id, a.action, a.resource_type, a.resource_id, a.workspace_id,
               a.project_id, a.metadata, a.created_at,
               u.email AS actor_email, u.display_name AS actor_name
          FROM audit_log a
          LEFT JOIN users u ON u.id = a.user_id
         WHERE a.organisation_id = :org
         ORDER BY a.id DESC
         LIMIT :limit OFFSET :offset
        """,
        {"org": str(organisation_id), "limit": limit, "offset": offset},
    )
