"""Tags: a name pinned to a commit that never moves (§299; db 0072; p.17).

    "The branches tab also lets you access a list of tags, which are like
     immutable branches. A tag can be used to mark a significant version of the
     code for future reference by giving it a version number or name… A tag can
     be created from the current version of a branch, or from any arbitrary
     commit." (p.17)

**Immutability is the database's job, not this module's** (db 0072's trigger).
A rule that lives only here is a rule the next writer of an UPDATE — a
migration, a repair script — does not meet, and a tag whose commit moved is a
lie discovered by whoever resolves it, possibly a year later.

What lives here is the other half of p.17: **`repoSettings.json`**.
"""
from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one
from ..lib.errors import ConflictError, NotFoundError

#: Foundry's own settings file, at the root of the repository (p.17, p.20).
#: **The first thing in this platform to read it**, and the reason to start
#: here rather than to invent a settings table: the rule is about a repository's
#: contents and it travels with them — a branch that adds it, a commit that
#: relaxes it, and a `git log` that says who changed the convention and when. A
#: column in `code_repos` would have none of that.
SETTINGS_FILE = "repoSettings.json"

#: How long a regex from a customer's settings file may be. **A regex is code**,
#: and one assembled to be pathological is the ordinary way a validator becomes
#: a denial of service. Length is a blunt guard and it is not the only one — see
#: `_compiled`.
MAX_REGEX_LENGTH = 200


class TagNameRefused(Exception):
    """The name does not match this repository's convention.

    Carries the repository's *own* `errorMessage` when it set one, because p.17
    shows the field for exactly this: `"Tag name must have the format x.x.x or
    x.x.x-rcx."` is a sentence somebody wrote for their colleagues, and a
    platform that replaced it with "invalid tag name" would be throwing away the
    only part of the refusal that helps.
    """


def read_settings(files: dict[str, str]) -> dict[str, Any]:
    """`repoSettings.json` from a commit's files, or `{}`.

    **Absent and unreadable are the same answer here, deliberately.** A settings
    file with a syntax error would otherwise stop every tag in the repository
    until somebody fixed it, and the person blocked is rarely the person who
    broke it. The convention stops being enforced, which is visible in the next
    tag anybody makes; the alternative fails closed on a rule that is a
    convention rather than a permission.
    """
    raw = files.get(SETTINGS_FILE)
    if raw is None:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _compiled(settings: dict[str, Any]) -> tuple[re.Pattern[str] | None, str | None]:
    """The repository's tag-name rule, or `(None, None)`.

    p.17's shape:

        "tagNameValidation": {
            "regex": "^(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)\\\\.(0|[1-9]\\\\d*)(-rc\\\\d+)?$",
            "errorMessage": "Tag name must have the format x.x.x or x.x.x-rcx."
        }

    **A regex that will not compile is ignored rather than refused**, for the
    same reason a settings file that will not parse is: it is a convention, and
    failing closed on it blocks work while the person who can fix it is
    elsewhere.
    """
    block = settings.get("tagNameValidation")
    if not isinstance(block, dict):
        return (None, None)
    pattern = block.get("regex")
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_REGEX_LENGTH:
        return (None, None)
    message = block.get("errorMessage")
    try:
        return (re.compile(pattern), message if isinstance(message, str) else None)
    except re.error:
        return (None, None)


def check_name(name: str, settings: dict[str, Any]) -> None:
    """Refuse a name this repository's convention does not accept.

    **`fullmatch`, not `search`.** p.17's example regex is anchored with `^` and
    `$` and most people's will be; one that is not would otherwise accept
    `v1.4.0-wip-DO-NOT-USE` because `1.4.0` appears inside it, which is the
    opposite of what somebody writing a convention meant.
    """
    pattern, message = _compiled(settings)
    if pattern is None:
        return
    if pattern.fullmatch(name) is None:
        raise TagNameRefused(
            message
            or (
                f"{name!r} does not match this repository's tag name convention "
                f"({pattern.pattern}), set in {SETTINGS_FILE}"
            )
        )


async def create(
    conn: AsyncConnection,
    *,
    repo_id: UUID,
    name: str,
    commit_id: UUID,
    settings: dict[str, Any],
    message: str | None,
    created_by: UUID,
) -> dict[str, Any]:
    """Pin a name to a commit.

    The commit is resolved by the caller — p.17 allows "the current version of a
    branch, or any arbitrary commit", and *which branch a commit is on* is
    `repositories.resolve_ref`'s question, already answered there.
    """
    check_name(name, settings)

    existing = await fetch_one(
        conn,
        "SELECT commit_id FROM code_tags WHERE repo_id = :rid AND name = :name",
        {"rid": str(repo_id), "name": name},
    )
    if existing is not None:
        # **Named with what it already points at**, because the reader's next
        # question is always "the same commit, or a different one?" - and if it
        # is the same one they have nothing to do.
        raise ConflictError(
            f"{name!r} is already a tag in this repository, pinned to "
            f"{str(existing['commit_id'])[:8]}. A tag never moves, so a new "
            "version needs a new name."
        )

    row = await fetch_one(
        conn,
        """
        INSERT INTO code_tags (repo_id, name, commit_id, message, created_by)
        VALUES (:rid, :name, :cid, :message, :by)
        RETURNING id, repo_id, name, commit_id, message, created_at, created_by
        """,
        {"rid": str(repo_id), "name": name, "cid": str(commit_id),
         "message": message, "by": str(created_by)},
    )
    assert row is not None
    return dict(row)


async def listing(conn: AsyncConnection, *, repo_id: UUID) -> list[dict[str, Any]]:
    """This repository's tags, newest first.

    **Not sorted by name.** A version number sorts by neither of the orders
    people expect — `1.10.0` before `1.9.0` alphabetically — and a tags list is
    read to answer "what did we cut recently", which is what newest-first
    answers. Whoever wants `1.9.0` specifically is looking for a name, not
    scanning an order.
    """
    rows = await fetch_all(
        conn,
        """
        SELECT t.id, t.repo_id, t.name, t.commit_id, t.message, t.created_at,
               t.created_by, u.email AS created_by_email,
               c.message AS commit_message
          FROM code_tags t
          LEFT JOIN users u ON u.id = t.created_by
          JOIN code_commits c ON c.id = t.commit_id
         WHERE t.repo_id = :rid
         ORDER BY t.created_at DESC
        """,
        {"rid": str(repo_id)},
    )
    return [dict(r) for r in rows]


async def remove(conn: AsyncConnection, *, repo_id: UUID, tag_id: UUID) -> None:
    """Delete a tag.

    A mistyped name has to be removable. Deleting takes nothing with it: db 0072
    keeps `ON DELETE RESTRICT` on the *commit*, so the code a tag pointed at is
    exactly as safe after the tag goes as before — which is why Foundry's
    warning about deleting branches ("this can result in lost work for others")
    has no counterpart here.
    """
    row = await fetch_one(
        conn,
        "DELETE FROM code_tags WHERE id = :id AND repo_id = :rid RETURNING id",
        {"id": str(tag_id), "rid": str(repo_id)},
    )
    if row is None:
        raise NotFoundError("this tag")
