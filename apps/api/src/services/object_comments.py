"""Comments on an object (§322; db 0078; `object-views` p.137).

    "Multiple users often work with a particular object. To facilitate this
     cooperation, Object Explorer allows users to comment on an object, mention
     other users, and attach files and images." (p.137)

    "Object Explorer comments on an object are not related to the Comment
     widget in Workshop." (p.137)

That last line is the one to keep in view. Workshop's Comment widget is
something a builder drops into a module; a comment here belongs to the
**object** and follows it onto every screen that shows it — which is why this
is keyed on (type, instance) and not on anything about a view.

**Mentions are resolved here, once, against the workspace's own members.** The
alternative — letting the client send a list of user ids alongside the text —
is the version that leaks: anybody could then have a comment delivered to
somebody who cannot see the object it is about. Deriving the mentions from what
was actually written means the notification can only name people the text
names.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: What one comment may say. Long enough for a paragraph of reasoning about an
#: object, short enough that the thread is still a thread.
MAX_BODY = 10_000

#: How many files one comment may carry (p.137's "attach files and images").
#: A cap rather than none, because each is a 25 MB upload and a comment with
#: forty of them is a folder somebody has put in the wrong place.
MAX_ATTACHMENTS = 10

#: A mention starts with `@` and runs to the end of the name it matched. The
#: **candidate** is what follows the `@`; which of the candidates is a real
#: person is decided by `find_mentions` against the member list, not by this.
_AT = re.compile(r"@")


class CommentRefused(Exception):
    """The comment cannot be stored, and the message says why."""


def find_mentions(
    body: str, members: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """p.137's "mention other users", resolved against who is actually here.

    Returns `{"user_id", "label", "start", "end"}` per mention, in the order
    they appear.

    **Longest match wins, and that is the whole algorithm.** Display names have
    spaces in them, so there is no token boundary to split on: `@Ada` and
    `@Ada Lovelace` are both plausible readings of the same eight characters,
    and the longer one is what the writer typed. Sorting the candidates by
    length and taking the first that fits is therefore not an optimisation — it
    is the rule.

    **An `@` that matches nobody stays literal text.** An email address in a
    comment is not a mention, and neither is `@here` unless somebody is called
    that. Guessing would mean notifying a person whose name merely starts the
    same way.

    Matching is case-insensitive on both the display name and the email,
    because somebody typing a name at speed is not choosing between them —
    the same argument `ontology_search` makes about casefolding.
    """
    if not members:
        return []
    # Every name and email that could be mentioned, longest first so a longer
    # name is preferred over a shorter one that prefixes it.
    candidates: list[tuple[str, str, str]] = []
    for member in members:
        user_id = member.get("user_id")
        if not user_id:
            continue  # a group, which p.137 does not mention
        for field in ("display_name", "email"):
            value = (member.get(field) or "").strip()
            if value:
                candidates.append((value.casefold(), value, str(user_id)))
    candidates.sort(key=lambda c: len(c[0]), reverse=True)

    folded = body.casefold()
    found: list[dict[str, Any]] = []
    for at in _AT.finditer(body):
        start = at.start()
        after = start + 1
        for needle, label, user_id in candidates:
            if folded.startswith(needle, after):
                found.append({
                    "user_id": user_id,
                    "label": label,
                    "start": start,
                    "end": after + len(needle),
                })
                break
    return found


def check_attachments(attachments: list[dict[str, Any]]) -> None:
    """Refuse a list this table will not usefully hold.

    The shape itself is the upload route's `AttachmentOut`, and it is not
    re-validated here: a key that names nothing is caught by the download
    route, which is the only place that can honestly answer whether the caller
    may have those bytes.
    """
    if len(attachments) > MAX_ATTACHMENTS:
        raise CommentRefused(
            f"A comment carries at most {MAX_ATTACHMENTS} files "
            f"(this one has {len(attachments)}). Post them across a few "
            "comments, or attach them to the object itself."
        )
    for item in attachments:
        if not isinstance(item, dict) or not item.get("key"):
            raise CommentRefused(
                "Every attachment needs the key the upload returned."
            )


async def post(
    conn: AsyncConnection,
    *,
    workspace_id: UUID,
    object_type_id: UUID,
    instance_id: UUID,
    author_id: UUID,
    body: str,
    members: list[dict[str, Any]],
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Say something about this object.

    The mentions are found here rather than taken from the caller — see the
    module docstring for why that distinction is a security one and not a
    tidiness one.
    """
    said = body.strip()
    if not said:
        raise CommentRefused("A comment needs something in it.")
    if len(said) > MAX_BODY:
        raise CommentRefused(
            f"A comment is at most {MAX_BODY} characters (this one is "
            f"{len(said)}). "
        )
    files = list(attachments or [])
    check_attachments(files)
    mentions = find_mentions(said, members)

    row = await fetch_one(
        conn,
        """
        INSERT INTO object_comments
               (workspace_id, object_type_id, instance_id, author_id, body,
                mentions, attachments)
        VALUES (:wid, :tid, :iid, :uid, :body,
                CAST(:mentions AS jsonb), CAST(:files AS jsonb))
        RETURNING id, object_type_id, instance_id, author_id, body,
                  mentions, attachments, created_at
        """,
        {
            "wid": str(workspace_id), "tid": str(object_type_id),
            "iid": str(instance_id), "uid": str(author_id), "body": said,
            "mentions": json.dumps(mentions), "files": json.dumps(files),
        },
    )
    assert row is not None
    return dict(row)


async def thread(
    conn: AsyncConnection, *, object_type_id: UUID, instance_id: UUID
) -> list[dict[str, Any]]:
    """This object's comments, **oldest first**.

    The opposite of every other listing in this codebase — favourites (db 0074)
    and the scratchpad's history (db 0073) both come back newest first — and
    for a reason that is not a matter of taste. Those are lists of *your*
    things, where the most recent is the one you want. This is a conversation,
    and a conversation read backwards is a different conversation.

    The author's name is joined so a comment can say who said it without the
    thread paying a read per row for the same handful of people.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT c.id, c.object_type_id, c.instance_id, c.author_id, c.body,
               c.mentions, c.attachments, c.created_at,
               u.display_name AS author_name, u.email AS author_email
          FROM object_comments c
          LEFT JOIN users u ON u.id = c.author_id
         WHERE c.object_type_id = :tid AND c.instance_id = :iid
         ORDER BY c.created_at, c.id
        """,
        {"tid": str(object_type_id), "iid": str(instance_id)},
    )
    return [dict(r) for r in rows]


async def count_for(
    conn: AsyncConnection, *, object_type_id: UUID, instance_id: UUID
) -> int:
    """How many comments this object has.

    p.137 puts a **View comments** button in the header of every Object View,
    and a button that says nothing about whether there is anything behind it is
    a button people stop pressing. Its own query rather than `len(thread(...))`
    — the header is drawn on a screen that has no reason to have fetched the
    conversation.
    """
    row = await fetch_one(
        conn,
        """
        SELECT count(*) AS n FROM object_comments
         WHERE object_type_id = :tid AND instance_id = :iid
        """,
        {"tid": str(object_type_id), "iid": str(instance_id)},
    )
    assert row is not None
    return int(row["n"])
