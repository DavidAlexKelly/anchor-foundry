"""The Ontology cleanup queue (§325; db 0080; `ontology-manager` p.68-74).

    "The Ontology cleanup tool is a safe way to delete object types… The tool
     aims to help Ontology editors determine the safety of deleting an object
     type and provides a deprecation option which informs object type users of
     its future removal." (p.68)

    "By default, the table is sorted by the highest priority among the flags
     that an object type triggers." (p.70)

    "The following list of flags is aimed at answering common issues, but is
     not exhaustive." (p.73)

**Nothing here is stored, and that is the design.** Every flag p.73-74 names is
computed from something the platform already records — the deprecation deadline
on `object_types`, the sync state on `object_type_sources` (§315's two issues),
the description column, the display name, and db 0077's thirty-day usage. A
materialised queue would be a second copy of all of it, wrong the moment
anything it summarised changed, and p.69's "the tool may take time to find
cleanup candidates" is a remark about scale rather than about storage.

The one thing that *is* stored is p.71's snooze, because it is a fact about a
person rather than about a type (db 0080).

**The flags say what is true; they do not say what to do.** p.68 is careful
about this — the tool "aims to help Ontology editors determine the safety of
deleting an object type" — and so is this module: a type with every flag lit is
still only a candidate, and the three actions on p.71 are all the editor's.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all, fetch_one

#: p.74's "Datasource not updated in [x] days". Foundry makes the number
#: configurable (p.73); this is the default, and it is 30 rather than 7 because
#: a weekly sync is an ordinary schedule here and a flag that fires on every
#: healthy weekly pipeline is a flag people learn to ignore.
STALE_SOURCE_DAYS = 30

#: db 0077's window, repeated rather than imported, because the two constants
#: answer different questions and `object_type_usage.WINDOW_DAYS` moving should
#: not silently move what "unused" means here. The API test pins them together.
UNUSED_DAYS = 30

#: How many candidates one read returns. p.69 is explicit that this is a list
#: with scale behind it — "the tool may take time to find cleanup candidates
#: based on the size of your Ontology" — and §256's rule is that a listing is a
#: *page*: a row is on screen because somebody asked for it, not because it
#: exists. Every flag is computed per row, so an unbounded answer is also an
#: unbounded amount of work before the first row can be drawn.
MAX_CANDIDATES = 200

#: How long p.71's snooze lasts when nobody says. "for a configurable amount of
#: time" — a fortnight is long enough that a queue cleared today is not back
#: tomorrow, and short enough that a type snoozed and forgotten comes back
#: while the reason for snoozing it is still true.
DEFAULT_SNOOZE_DAYS = 14

#: p.70's "highest priority among the flags that an object type triggers",
#: most serious first.
#:
#: **Ordered by what the flag says about deleting the type, not by how alarming
#: it sounds.** `past_deprecation` is first because somebody already decided
#: this type should go and announced a date that has passed — the decision is
#: made and the queue is only surfacing it. `unused` is second because thirty
#: days of nobody touching a type is the strongest evidence that deleting it
#: would be noticed by nobody, which is the question p.68 says the tool exists
#: to answer. `no_description` is last because it says something about the
#: documentation rather than about whether anyone would miss the type.
#:
#: p.72-73 makes this order configurable per user. That is ○ here and named in
#: `ontology.md`: the queue is worth having before the panel that tunes it.
FLAG_PRIORITY = (
    "past_deprecation",
    "unused",
    "no_source",
    "failing_source",
    "stale_source",
    "name_looks_temporary",
    "no_description",
)

#: p.74's default regex, and its own example: "The default value of
#: `\\[test|deprecated\\]` would match object types that have `[test]` or
#: `[deprecated]` in their display names."
#:
#: **Matched as two plain substrings rather than as a regex**, and that is a
#: deliberate narrowing of p.74. Foundry offers "ECMA (JavaScript) regex
#: syntax" as a per-user setting; running a pattern somebody typed against
#: every object type in a workspace is a query whose cost the person writing it
#: cannot see, and the configurable-flags panel that would let them type one is
#: ○ anyway. Two substrings answer p.74's own example exactly, and the day the
#: panel arrives is the day to decide how to bound a pattern.
TEMPORARY_MARKERS = ("[test]", "[deprecated]")


def priority_of(flags: list[str]) -> int:
    """Where an object type sits in p.70's ordering.

    Lower is more urgent. A type with no flags sorts last, which is where a
    type that is not a cleanup candidate belongs — it is in the answer at all
    only because a caller asked for everything.
    """
    for rank, flag in enumerate(FLAG_PRIORITY):
        if flag in flags:
            return rank
    return len(FLAG_PRIORITY)


async def candidates(
    conn: AsyncConnection,
    workspace_id: UUID,
    *,
    user_id: UUID,
    flag: str | None = None,
    include_snoozed: bool = False,
) -> list[dict[str, Any]]:
    """p.69's list of cleanup candidates, worst first.

    One statement, because every flag is a fact about a row that is already
    being read: asking seven questions separately would be seven scans of the
    same table to produce one list.

    `flag` narrows to types triggering that one — p.69's "the list can be
    filtered to specific flags". A flag nothing recognises returns nothing
    rather than everything, which is the safe direction for a screen whose
    buttons delete things.

    **Capped at `MAX_CANDIDATES`, and the cap is applied after the flags are
    known.** A `LIMIT` in the statement would cut the list before anything had
    been ranked, so the two hundred returned would be an arbitrary two hundred
    rather than p.70's worst two hundred — which is the difference between a
    page of a queue and a sample of one.
    """
    now = datetime.now(timezone.utc)
    rows = await fetch_all(
        conn,
        """
        WITH usage AS (
            SELECT object_type_id, sum(reads) + sum(writes) AS interactions
              FROM object_type_usage
             WHERE day >= CURRENT_DATE - CAST(:unused_days AS integer)
             GROUP BY 1
        )
        SELECT ot.id,
               ot.api_name,
               ot.display_name,
               ot.description,
               ot.status::text AS status,
               ot.deprecation,
               ot.created_at,
               COALESCE(u.interactions, 0) AS interactions,
               s.until AS snoozed_until,
               -- p.74: "Object type currently has the deprecated status and
               -- the deprecation date field is in the past." Both halves: a
               -- deadline on a type nobody deprecated is a plan, not a lapse.
               (ot.status::text = 'deprecated'
                AND ot.deprecation ->> 'deadline' IS NOT NULL
                AND (ot.deprecation ->> 'deadline')::date < CURRENT_DATE
               ) AS past_deprecation,
               -- p.74's "Trashed datasource", as near as this platform gets:
               -- there is no trash here, so a source is mapped or it is not.
               NOT EXISTS (SELECT 1 FROM object_type_sources src
                            WHERE src.object_type_id = ot.id) AS no_source,
               -- §315's other issue. p.74's "Phonograph deindexed" is the
               -- equivalent question for Object Storage v1 and is explicitly
               -- not offered for v2; this is ours under its own name.
               EXISTS (SELECT 1 FROM object_type_sources src
                        WHERE src.object_type_id = ot.id
                          AND src.sync_status = 'error') AS failing_source,
               -- p.74's "Datasource not updated in [x] days". Every source, so
               -- a type with one fresh mapping is not stale because another is.
               (EXISTS (SELECT 1 FROM object_type_sources src
                         WHERE src.object_type_id = ot.id)
                AND NOT EXISTS (
                    SELECT 1 FROM object_type_sources src
                     WHERE src.object_type_id = ot.id
                       AND src.last_synced_at IS NOT NULL
                       AND src.last_synced_at >= :stale_before)
               ) AS stale_source,
               -- p.74: "The object type has a blank description. Does not
               -- check for descriptions on all properties of the object type."
               (btrim(ot.description) = '') AS no_description,
               (position(:marker_test in lower(ot.display_name)) > 0
                OR position(:marker_dep in lower(ot.display_name)) > 0
               ) AS name_looks_temporary
          FROM object_types ot
          LEFT JOIN usage u ON u.object_type_id = ot.id
          -- **`s.user_id = :uid` is belt to db 0080's braces, and the sweep
          -- could not make it matter.** The row policy already restricts this
          -- table to `rls_current_user_id()`, so a join without the condition
          -- selects the same rows — a mutant removing it survived, correctly.
          -- Kept rather than deleted (unlike §323's redundant P95 filter,
          -- which was a no-op by the aggregate's own semantics): this one is
          -- redundant only because a *separate* mechanism gets there first,
          -- and the day somebody reads this table from an admin connection it
          -- is the difference between your queue and everybody's.
          LEFT JOIN object_type_snoozes s
                 ON s.object_type_id = ot.id AND s.user_id = :uid
         WHERE ot.workspace_id = :wid
        """,
        {
            "wid": str(workspace_id),
            "uid": str(user_id),
            "unused_days": UNUSED_DAYS,
            "stale_before": now - timedelta(days=STALE_SOURCE_DAYS),
            "marker_test": TEMPORARY_MARKERS[0],
            "marker_dep": TEMPORARY_MARKERS[1],
        },
    )

    out: list[dict[str, Any]] = []
    for row in rows:
        snoozed = row["snoozed_until"] is not None and row["snoozed_until"] > now
        if snoozed and not include_snoozed:
            # p.71: "Hide object types from your cleanup queue." Dropped rather
            # than returned with a flag, because a queue that still lists what
            # you silenced is a queue you silenced for nothing.
            continue
        flags = [name for name in FLAG_PRIORITY if row.get(name)]
        # **Unused is computed here rather than in SQL**, because it is the one
        # flag that is a statement about the *absence* of rows in another table
        # and reads far more clearly as arithmetic than as a NOT EXISTS over a
        # windowed aggregate.
        if int(row["interactions"]) == 0:
            flags.insert(0, "unused")
            flags = [name for name in FLAG_PRIORITY if name in flags]
        if not flags:
            continue
        if flag is not None and flag not in flags:
            continue
        out.append({
            "id": row["id"],
            "api_name": row["api_name"],
            "display_name": row["display_name"],
            "status": row["status"],
            "description": row["description"],
            "deprecation": _json(row["deprecation"]),
            "interactions": int(row["interactions"]),
            "flags": flags,
            "priority": priority_of(flags),
            "snoozed_until": row["snoozed_until"] if snoozed else None,
        })
    # p.70's ordering, then by name so two types with the same worst flag do
    # not swap places between reads.
    out.sort(key=lambda c: (c["priority"], str(c["display_name"]).lower()))
    return out[:MAX_CANDIDATES]


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def snooze(
    conn: AsyncConnection,
    object_type_id: UUID,
    *,
    user_id: UUID,
    days: int = DEFAULT_SNOOZE_DAYS,
    note: str | None = None,
) -> dict[str, Any]:
    """p.71's snooze: hide this type from **your** queue for a while.

    An upsert, because snoozing something already snoozed is somebody asking
    for longer rather than an error — and the second press moving the date is
    the behaviour a reader expects from a button that says "remind me later".
    """
    row = await fetch_one(
        conn,
        """
        INSERT INTO object_type_snoozes (object_type_id, user_id, until, note)
        VALUES (:tid, :uid, now() + make_interval(days => :days), :note)
        ON CONFLICT (object_type_id, user_id) DO UPDATE
            SET until = EXCLUDED.until, note = EXCLUDED.note
        RETURNING object_type_id, until, note
        """,
        {"tid": str(object_type_id), "uid": str(user_id),
         "days": days, "note": note},
    )
    assert row is not None
    return dict(row)


async def wake(
    conn: AsyncConnection, object_type_id: UUID, *, user_id: UUID
) -> bool:
    """Take a snooze back, so the type returns to your queue now.

    Returns whether there was one, so a caller can tell "un-snoozed" from
    "there was nothing to un-snooze" — the second is a 404 rather than a
    success that did nothing (§214).
    """
    row = await fetch_one(
        conn,
        """
        DELETE FROM object_type_snoozes
         WHERE object_type_id = :tid AND user_id = :uid
        RETURNING object_type_id
        """,
        {"tid": str(object_type_id), "uid": str(user_id)},
    )
    return row is not None
