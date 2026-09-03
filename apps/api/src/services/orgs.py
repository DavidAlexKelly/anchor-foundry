"""Organisation-level administration (spec §4 "Organisation", §5 "Org
settings", §16 organisations / users / groups / group_members / audit_log).

User provisioning note (§9 "No self-registration"): creating a platform user
here also creates the Cognito identity via AdminCreateUser in production
(CognitoAdminGateway) - the sub it returns is stored immediately, not linked
later at first login (AdminCreateUser's response already carries it; there
is no earlier point where both facts are known together). The gateway is
injected so the service is testable without AWS.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError
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


class Boto3CognitoGateway:
    """Production gateway. AdminCreateUser sends the invite email with a
    Cognito-generated temporary password; the invited user sets a real one
    via the hosted UI's forced first-login flow. The CDK auth construct
    configures email as a sign-in alias, not the Username attribute
    (signInAliases: { email: true }) - Cognito auto-assigns the real,
    immutable Username as a UUID equal to the user's sub regardless of what
    string is passed as Username= here, so `cognito_sub` doubles as the
    identifier admin_disable_user needs."""

    def __init__(self, user_pool_id: str, region: str) -> None:
        import boto3

        self._client = boto3.client("cognito-idp", region_name=region)
        self._user_pool_id = user_pool_id

    def admin_create_user(self, email: str, display_name: str) -> str:
        resp = self._client.admin_create_user(
            UserPoolId=self._user_pool_id,
            Username=email,
            UserAttributes=[
                {"Name": "email", "Value": email},
                {"Name": "email_verified", "Value": "true"},
                {"Name": "name", "Value": display_name},
            ],
            DesiredDeliveryMediums=["EMAIL"],
        )
        attrs = {a["Name"]: a["Value"] for a in resp["User"]["Attributes"]}
        return attrs["sub"]

    def admin_disable_user(self, cognito_sub: str) -> None:
        self._client.admin_disable_user(UserPoolId=self._user_pool_id, Username=cognito_sub)


# ---- first-owner bootstrap ---------------------------------------------------
# Found missing during real deploy validation (STATUS.md §17): self-signup is
# disabled by spec, and invite_user below refuses to grant 'owner' - so a
# fresh customer stack had no path at all to create its first organisation or
# user. bootstrap_first_owner (db 0017) is a SECURITY DEFINER function rather
# than a privileged connection at this layer: the ordinary request connection
# has no RLS context at all pre-auth, and the one-time guard needs to be
# atomic against concurrent callers, which only the function itself can do.
async def platform_needs_setup(conn: AsyncConnection) -> bool:
    row = await fetch_one(conn, "SELECT platform_has_any_organisation() AS has_org", {})
    assert row is not None
    return not bool(row["has_org"])


async def bootstrap_first_owner(
    conn: AsyncConnection,
    cognito: CognitoAdminGateway,
    *,
    org_name: str,
    org_slug: str,
    owner_email: str,
    owner_display_name: str,
) -> UUID:
    # Cognito identity created before the DB call: if the DB call then finds
    # the platform already bootstrapped, this leaves one orphaned unused
    # Cognito user rather than a DB row with no matching identity - the
    # safer failure direction for something a human can clean up by hand.
    sub = cognito.admin_create_user(owner_email, owner_display_name)
    try:
        row = await fetch_one(
            conn,
            "SELECT bootstrap_first_owner(:name, :slug, :sub, :email, :disp) AS org_id",
            {
                "name": org_name,
                "slug": org_slug,
                "sub": sub,
                "email": owner_email,
                "disp": owner_display_name,
            },
        )
    except IntegrityError as exc:
        raise ConflictError("this platform has already been set up") from exc
    assert row is not None
    return UUID(str(row["org_id"]))


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
async def list_users(
    conn: AsyncConnection,
    organisation_id: UUID,
    *,
    group_ids: "Sequence[UUID] | None" = None,
) -> list[dict[str, Any]]:
    """Every user in the organisation, or only those in the named groups.

    **The filter is here rather than in the caller, and that is the point of it**
    (p.478's "Specify Multipass group IDs" for §234's User Select). Filtering in
    the browser would mean sending it every user *and* every group membership -
    a directory this platform deliberately keeps to the server, since group
    membership is what several permission decisions are made from. The narrowing
    is not a privacy boundary either way: `GET /org/members` has always been
    visible to every member of the org, on the reasoning that emails within one
    org are not sensitive to it. It is about not shipping a membership graph to
    answer a dropdown.

    **An empty list of groups is not "no filter".** `None` means nobody asked;
    `[]` means "the users in these zero groups", which is nobody. That is the
    honest reading of the argument, and it is kept even though **the route
    cannot currently send it**: a repeated query parameter has no empty form, so
    over HTTP the only two states are absent and non-empty. The case it exists
    for is a widget whose group ids come from a variable that has resolved to
    nothing - and the widget answers that by *not asking*, since a request it
    cannot express would come back as the whole directory. Kept rather than
    deleted because this is a service function with more callers than the one
    route, and a next caller passing `[]` should not silently get everybody.
    """
    if group_ids is None:
        return await fetch_all(
            conn,
            """
            SELECT id, email, display_name, org_role, status, created_at,
                   (cognito_sub IS NOT NULL) AS identity_linked
              FROM users WHERE organisation_id = :org ORDER BY display_name
            """,
            {"org": str(organisation_id)},
        )
    if not group_ids:
        return []
    return await fetch_all(
        conn,
        """
        SELECT u.id, u.email, u.display_name, u.org_role, u.status, u.created_at,
               (u.cognito_sub IS NOT NULL) AS identity_linked
          FROM users u
         WHERE u.organisation_id = :org
           AND EXISTS (
                 SELECT 1
                   FROM group_members gm
                   JOIN groups g ON g.id = gm.group_id
                  WHERE gm.user_id = u.id
                    AND g.organisation_id = :org
                    AND gm.group_id = ANY(CAST(:groups AS uuid[]))
               )
         ORDER BY u.display_name
        """,
        # **The group is re-checked against the organisation**, not trusted from
        # the id alone: the ids arrive from a document a builder wrote, and a
        # group id from another org would otherwise select its members here.
        {"org": str(organisation_id), "groups": [str(g) for g in group_ids]},
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
        # 'owner' is never grantable through invite - ownership transfer is a
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
