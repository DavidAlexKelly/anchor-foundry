"""A source's egress policies in the database (db 0068; decision 0013).

Separate from `services/egress.py`, which decides what a set of policies
*means*: the split every service pair here uses.

**The only read that matters is `for_connection`**, and it is on the hot path —
every outbound call makes it. It is a single indexed lookup by connection id,
and the four call sites resolve their policies once per operation rather than
once per request, because a sync makes a thousand requests against one source.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: How many destinations one source may name. Ours, not the document's: a list
#: nobody can read is not an allowlist anybody is checking, and a source that
#: needs fifty destinations is a source whose policies have stopped meaning
#: anything.
MAX_POLICIES = 50


async def for_connection(
    conn: AsyncConnection, connection_id: UUID
) -> list[dict[str, Any]]:
    """This source's allowlist, or an empty list.

    **Empty is a real answer here** and `egress.check` is where it is
    interpreted — decision 0013 §2's "no policies means unrestricted" lives in
    one function, not at four call sites that could each forget it.
    """
    return await fetch_all(
        conn,
        "SELECT id, host, port, description, created_at FROM egress_policies"
        " WHERE connection_id = :cid ORDER BY host, port NULLS FIRST",
        {"cid": str(connection_id)},
    )


async def create(
    conn: AsyncConnection,
    *,
    connection_id: UUID,
    policy: dict[str, Any],
    created_by: UUID,
) -> dict[str, Any]:
    count = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM egress_policies WHERE connection_id = :cid",
        {"cid": str(connection_id)},
    )
    if count and int(count["n"]) >= MAX_POLICIES:
        raise ConflictError(
            f"a source may name at most {MAX_POLICIES} destinations"
        )
    existing = await fetch_one(
        conn,
        "SELECT 1 AS x FROM egress_policies"
        " WHERE connection_id = :cid AND host = :host"
        "   AND port IS NOT DISTINCT FROM :port",
        {"cid": str(connection_id), "host": policy["host"], "port": policy["port"]},
    )
    if existing is not None:
        # db 0068's unique constraint refuses it too; this turns that into a
        # sentence rather than a 500 quoting a constraint name — the same fix
        # §259 had to make for a connection a webhook was using.
        raise ConflictError(
            f"this source already allows {policy['host']}"
            + (f":{policy['port']}" if policy["port"] else "")
        )
    row = await fetch_one(
        conn,
        """
        INSERT INTO egress_policies (connection_id, host, port, description, created_by)
        VALUES (:cid, :host, :port, :descr, :by)
        RETURNING id, host, port, description, created_at
        """,
        {
            "cid": str(connection_id), "host": policy["host"], "port": policy["port"],
            "descr": policy["description"], "by": str(created_by),
        },
    )
    assert row is not None
    return row


async def delete(conn: AsyncConnection, policy_id: UUID) -> None:
    row = await fetch_one(
        conn, "DELETE FROM egress_policies WHERE id = :pid RETURNING id",
        {"pid": str(policy_id)},
    )
    if row is None:
        raise NotFoundError("egress policy")
