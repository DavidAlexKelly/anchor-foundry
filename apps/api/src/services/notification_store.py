"""Reading and writing delivered notifications (db 0066; `action-types` p.91).

Separate from `services/notifications.py`, which is the pure half — what a rule
means and what its content renders to. This is the half that touches the
database, and the split is the one every service pair here uses: a wrong answer
in the other file is a line, and a wrong answer in this one needs a row to see.

> "they may still view their notifications when logged into Foundry by going to
> 'Notifications' and then 'See All' in the Workspace." (p.91)

That sentence is the whole read surface: a list of what you were sent, and a
way to stop it being new. There is no admin view, because db 0066's policy is
`user_id = rls_current_user_id()` — a workspace admin reading other people's
messages is not a feature anybody asked for, and RLS is where that is decided
rather than here.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: One page of somebody's notifications. Fifty for `INSTANCE_PAGE_SIZE`'s
#: reason and §256's: a list that grows without bound is a list that eventually
#: takes seconds to draw, and this one grows every time anybody runs an action.
PAGE = 50


async def deliver(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    user_id: str,
    actor_id: UUID | None,
    action_run_id: UUID | None,
    content: dict[str, Any],
) -> None:
    """Store one notification for one person.

    **Not batched, deliberately.** p.90's "notifications will be sent to each
    recipient individually" is a statement about what a recipient receives, and
    it happens to also be what makes the content correct: `{{{recipient}}}`
    renders differently per person, so there is no one row to write for many.

    A user id that names nobody is skipped rather than refused — p.100 says a
    recipient value that is not a Foundry user ID means "no notifications will
    be sent", not that the action fails. The insert is guarded by a subselect
    rather than by a lookup here, so the check and the write are one statement
    and cannot disagree.
    """
    await conn.execute(
        text(
            """
            INSERT INTO notifications
                (workspace_id, user_id, actor_id, action_run_id,
                 subject, body, link_url, link_text)
            SELECT :wid, u.id, :actor, :run, :subject, :body, :url, :text
              FROM users u WHERE u.id = CAST(:uid AS uuid)
            """
        ),
        {
            "wid": str(workspace_id),
            "uid": user_id,
            "actor": str(actor_id) if actor_id else None,
            "run": str(action_run_id) if action_run_id else None,
            "subject": content.get("subject") or "",
            "body": content.get("body") or "",
            "url": content.get("link_url") or None,
            "text": content.get("link_text") or None,
        },
    )


async def permitted(
    conn: AsyncConnection, *, workspace_id: UUID, user_ids: list[str]
) -> set[str]:
    """Which of these ids may see this workspace's data (p.96).

    > "Users may only receive notifications containing data which they are
    > allowed to view." (p.96)

    Membership *is* the answer here: this platform's read model is that a
    workspace member can see the workspace's ontology and a non-member cannot
    (db 0003, 0006). There is no per-object grant to consult, so checking one
    would be inventing a rule to enforce.

    An id that is not a uuid at all is not in the answer, which is p.100's
    "if this property contains something else such as string email addresses,
    no notifications will be sent" — filtered in SQL rather than by a `try`
    around a parse, so a malformed value cannot raise on the way in.
    """
    if not user_ids:
        return set()
    rows = await fetch_all(
        conn,
        """
        SELECT m.user_id FROM workspace_members m
         WHERE m.workspace_id = :wid
           AND m.user_id::text = ANY(CAST(:ids AS text[]))
        """,
        {"wid": str(workspace_id), "ids": user_ids},
    )
    return {str(r["user_id"]) for r in rows}


async def list_for_user(
    conn: AsyncConnection, *, limit: int = PAGE, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    """This connection's user's notifications, newest first, and how many.

    **No `user_id` argument**, and that is the point: db 0066's policy answers
    "whose" from the connection, so a caller cannot ask for somebody else's by
    passing the wrong id. A parameter here would be a second answer to a
    question RLS has already settled, and the kind that is wrong silently.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT count(*) OVER () AS match_count,
               n.id, n.subject, n.body, n.link_url, n.link_text,
               n.read_at, n.created_at, n.action_run_id,
               a.display_name AS actor_name
          FROM notifications n
          LEFT JOIN users a ON a.id = n.actor_id
         ORDER BY n.created_at DESC, n.id
         LIMIT :limit OFFSET :offset
        """,
        {"limit": max(1, min(limit, PAGE)), "offset": max(0, offset)},
    )
    out = [dict(r) for r in rows]
    total = int(out[0]["match_count"]) if out else 0
    for row in out:
        row.pop("match_count", None)
    return out, total


async def unread_count(conn: AsyncConnection) -> int:
    """How many are new, for the badge that asks on every page load.

    Its own query rather than a field on the listing, because the badge is
    drawn on every screen and the listing is drawn on one — and a badge that
    had to fetch a page of notifications to show a number would be reading
    fifty rows to answer with one.
    """
    row = await fetch_one(
        conn,
        "SELECT count(*) AS n FROM notifications WHERE read_at IS NULL",
        {},
    )
    return int(row["n"]) if row else 0


async def mark_read(conn: AsyncConnection, notification_id: UUID) -> bool:
    """Mark one as read. Returns whether there was one to mark.

    **Idempotent, and the timestamp does not move.** `read_at IS NULL` in the
    predicate means opening a notification twice records when it was first
    read, which is the only reading of "when did you see this" that is a fact
    about the person rather than about their scrolling.
    """
    result = await conn.execute(
        text(
            "UPDATE notifications SET read_at = now() "
            " WHERE id = :nid AND read_at IS NULL"
        ),
        {"nid": str(notification_id)},
    )
    return bool(result.rowcount)


async def exists(conn: AsyncConnection, notification_id: UUID) -> bool:
    """Whether this connection's user has such a notification at all.

    Separate from `mark_read` because the two answer different questions and
    only together tell "already read" apart from "not yours". RLS makes the
    second indistinguishable from "does not exist", which is the intended
    answer: telling them apart would say whether somebody else received one.
    """
    row = await fetch_one(
        conn, "SELECT 1 AS ok FROM notifications WHERE id = :nid",
        {"nid": str(notification_id)},
    )
    return row is not None


async def mark_all_read(conn: AsyncConnection) -> int:
    """p.91's "See All", which is where somebody clears the badge."""
    result = await conn.execute(
        text("UPDATE notifications SET read_at = now() WHERE read_at IS NULL"),
        {},
    )
    return int(result.rowcount or 0)
