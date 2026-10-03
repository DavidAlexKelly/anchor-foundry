"""Proposals to promote an object type (§767; db 0152; Foundry
`object-link-types` p.255).

> "Only users with the `Ontology Owner` role on the ontology level can
> directly apply the `promoted` status. Other users must submit a proposal for
> review and approval by an `Ontology Owner`." (p.255)

`ontology_status.check_promotion` is the first sentence, and this is the
second. The owner is a workspace admin, for `PROMOTION_ROLE`'s reason.

**Approving is the admin's own edit, made later.** It goes through
`ontology.set_type_statuses` with the admin's role, so p.255's visibility,
p.256's propagation, p.257's link re-cap and the version snapshot all run, as
they would had the admin chosen `promoted` themselves. A second path that
wrote the status directly would be a way round every one of them.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, ForbiddenError, NotFoundError
from . import ontology, ontology_status

_SELECT = """
    SELECT r.id, r.object_type_id, ot.api_name AS object_type_api_name,
           ot.display_name AS object_type_name, ot.status AS object_type_status,
           r.requested_by, coalesce(nullif(req.display_name, ''), req.email::text, '')
               AS requested_by_name,
           r.reason, r.state, r.decided_by,
           coalesce(nullif(dec.display_name, ''), dec.email::text, '') AS decided_by_name,
           r.decision_note, r.decided_at, r.created_at
      FROM promotion_requests r
      JOIN object_types ot ON ot.id = r.object_type_id
      LEFT JOIN users req ON req.id = r.requested_by
      LEFT JOIN users dec ON dec.id = r.decided_by
"""


class PromotionRequestError(ValueError):
    """A proposal that cannot be made or decided as asked."""


def _out(row: Any, caller: UUID) -> dict[str, Any]:
    out = dict(row)
    # Whether the caller may withdraw it: the screen offers Withdraw only to
    # the person who asked, as the server allows.
    out["mine"] = str(out.get("requested_by")) == str(caller)
    return out


async def list_requests(
    conn: AsyncConnection, workspace_id: UUID, caller: UUID, *, pending_only: bool
) -> list[dict[str, Any]]:
    rows = await fetch_all(
        conn,
        _SELECT + " WHERE r.workspace_id = :wid"
        + (" AND r.state = 'pending'" if pending_only else "")
        + " ORDER BY r.created_at DESC",
        {"wid": str(workspace_id)},
    )
    return [_out(r, caller) for r in rows]


async def _get(
    conn: AsyncConnection, workspace_id: UUID, request_id: UUID, caller: UUID
) -> dict[str, Any]:
    row = await fetch_one(
        conn, _SELECT + " WHERE r.workspace_id = :wid AND r.id = :rid",
        {"wid": str(workspace_id), "rid": str(request_id)},
    )
    if row is None:
        raise NotFoundError("promotion request")
    return _out(row, caller)


async def submit(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    type_id: UUID,
    requested_by: UUID,
    workspace_role: str,
    reason: str,
) -> dict[str, Any]:
    """p.255's proposal. Refused where it would ask nothing: from somebody who
    may promote directly, for a type already promoted, or beside a proposal
    still waiting for an answer."""
    existing = await ontology.get_type(conn, workspace_id, type_id)
    if workspace_role == ontology_status.PROMOTION_ROLE:
        raise PromotionRequestError(
            "a workspace admin promotes an object type directly (p.255)")
    if str(existing["status"]) == "promoted":
        raise PromotionRequestError(f"{existing['api_name']} is already promoted")
    waiting = await fetch_one(
        conn,
        "SELECT 1 AS x FROM promotion_requests "
        " WHERE object_type_id = :tid AND state = 'pending'",
        {"tid": str(type_id)},
    )
    if waiting is not None:
        raise ConflictError(
            f"{existing['api_name']} already has a promotion request waiting for an admin")
    row = await fetch_one(
        conn,
        """
        INSERT INTO promotion_requests (workspace_id, object_type_id, requested_by, reason)
        VALUES (:wid, :tid, :by, :reason)
        RETURNING id
        """,
        {"wid": str(workspace_id), "tid": str(type_id), "by": str(requested_by),
         "reason": reason.strip()},
    )
    assert row is not None
    return await _get(conn, workspace_id, UUID(str(row["id"])), requested_by)


async def _pending(
    conn: AsyncConnection, workspace_id: UUID, request_id: UUID, caller: UUID
) -> dict[str, Any]:
    found = await _get(conn, workspace_id, request_id, caller)
    if found["state"] != "pending":
        raise ConflictError(f"this request was already {found['state']}")
    return found


async def _close(
    conn: AsyncConnection, request_id: UUID, *, state: str, by: UUID, note: str
) -> None:
    await conn.execute(
        text(
            """
            UPDATE promotion_requests
               SET state = :state, decided_by = :by, decision_note = :note,
                   decided_at = now()
             WHERE id = :rid
            """
        ),
        {"state": state, "by": str(by), "note": note.strip(), "rid": str(request_id)},
    )


async def approve(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    request_id: UUID,
    decided_by: UUID,
    workspace_role: str,
    note: str = "",
) -> dict[str, Any]:
    """The owner's approval, applied as the owner's own edit (module note)."""
    found = await _pending(conn, workspace_id, request_id, decided_by)
    await ontology.set_type_statuses(
        conn,
        workspace_id=workspace_id,
        type_ids=[UUID(str(found["object_type_id"]))],
        status="promoted",
        updated_by=decided_by,
        workspace_role=workspace_role,
    )
    await _close(conn, request_id, state="approved", by=decided_by, note=note)
    return await _get(conn, workspace_id, request_id, decided_by)


async def reject(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    request_id: UUID,
    decided_by: UUID,
    note: str = "",
) -> dict[str, Any]:
    await _pending(conn, workspace_id, request_id, decided_by)
    await _close(conn, request_id, state="rejected", by=decided_by, note=note)
    return await _get(conn, workspace_id, request_id, decided_by)


async def withdraw(
    conn: AsyncConnection, *, workspace_id: UUID, request_id: UUID, caller: UUID
) -> dict[str, Any]:
    """Only by whoever asked: somebody else's question is theirs to take back."""
    found = await _pending(conn, workspace_id, request_id, caller)
    if not found["mine"]:
        raise ForbiddenError("only the person who asked can withdraw a promotion request")
    await _close(conn, request_id, state="withdrawn", by=caller, note="")
    return await _get(conn, workspace_id, request_id, caller)
