"""Somebody's notifications (Foundry `action-types` p.91; db 0066; §257).

> "they may still view their notifications when logged into Foundry by going to
> 'Notifications' and then 'See All' in the Workspace." (p.91)

**No workspace in the path, and that is p.91's shape rather than a shortcut.**
A notification is addressed to a *person*; the Workspace it is read in is
Foundry's app shell, not one ontology. Somebody who works in three workspaces
has one inbox, and scoping the URL would make them check it three times.

Access is decided by RLS rather than by a path-shaped permission dependency:
db 0066's policy is `user_id = rls_current_user_id()`, so a notification
belonging to somebody else is indistinguishable from one that does not exist.
That is the intended answer. It also means these handlers pass no user id
anywhere — a parameter would be a second answer to a question the connection
has already settled, and the kind that is wrong silently.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..lib.db import user_connection
from ..lib.errors import NotFoundError
from ..middleware.auth import AuthContext, get_current_user
from ..services import notification_store

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: UUID
    #: p.91's three content components, rendered at send time. Re-rendering at
    #: read time would show a different world each time it was opened — p.92
    #: fixes the content to "the state of the Ontology before edits of the
    #: current Action are applied", and that state is gone by now.
    subject: str
    body: str = ""
    link_url: str | None = None
    link_text: str | None = None
    #: Who ran the action. Named rather than identified, because a notification
    #: is read by a person and "Grace changed it" is the useful half.
    actor_name: str | None = None
    action_run_id: UUID | None = None
    read_at: datetime | None = None
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    #: The badge's number, on the listing too. One extra query on the one
    #: screen that has just made most of them read, which is cheaper than a
    #: second round trip from the browser to find out what it did.
    unread: int
    limit: int
    offset: int


@router.get("", response_model=NotificationPage)
async def list_notifications(
    limit: int = Query(default=notification_store.PAGE, ge=1, le=notification_store.PAGE),
    offset: int = Query(default=0, ge=0),
    auth: AuthContext = Depends(get_current_user),
) -> NotificationPage:
    async with user_connection(auth.user_id) as conn:
        rows, total = await notification_store.list_for_user(
            conn, limit=limit, offset=offset
        )
        unread = await notification_store.unread_count(conn)
    return NotificationPage(
        items=[NotificationOut(**r) for r in rows],
        total=total, unread=unread, limit=limit, offset=offset,
    )


class UnreadOut(BaseModel):
    unread: int


@router.get("/unread", response_model=UnreadOut)
async def unread(auth: AuthContext = Depends(get_current_user)) -> UnreadOut:
    """The badge. Its own endpoint because it is asked on every page load and
    the listing is asked on one — a badge that fetched a page of notifications
    to show a number would read fifty rows to answer with one."""
    async with user_connection(auth.user_id) as conn:
        return UnreadOut(unread=await notification_store.unread_count(conn))


@router.post("/{notification_id}/read", response_model=UnreadOut)
async def mark_read(
    notification_id: UUID, auth: AuthContext = Depends(get_current_user)
) -> UnreadOut:
    """404 for one that is not yours, which is the same answer as for one that
    does not exist — RLS makes them the same row count, and telling them apart
    would say whether somebody else received a notification."""
    async with user_connection(auth.user_id) as conn:
        if not await notification_store.mark_read(conn, notification_id):
            # **Only when there is nothing to mark *and* nothing to find.**
            # Marking an already-read notification is a no-op rather than a
            # failure: two tabs open on the same inbox is an ordinary thing,
            # and the second one should not report an error for agreeing.
            if not await notification_store.exists(conn, notification_id):
                raise NotFoundError("notification")
        return UnreadOut(unread=await notification_store.unread_count(conn))


@router.post("/read", response_model=UnreadOut)
async def mark_all_read(auth: AuthContext = Depends(get_current_user)) -> UnreadOut:
    """p.91's "See All", which is where somebody clears the badge."""
    async with user_connection(auth.user_id) as conn:
        await notification_store.mark_all_read(conn)
        return UnreadOut(unread=await notification_store.unread_count(conn))
